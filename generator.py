"""양식 채우기 / PDF 양식 변환 / 자유 생성 — AI 프롬프트와 실행 흐름."""
import datetime
from pathlib import Path

import llm
from hwpx_form import DocumentBuilder, HwpxDoc

STYLE_RULES = """문체 규칙(학교·공공기관 공문 개조식):
- 문장은 '~함', '~임', '~음', '~기름'처럼 명사형으로 끝내고 짧고 명확하게 씀
- 날짜는 '2025. 3. 14.(금)', 시간은 '09:00~10:00', 금액은 '120,000' 형식
- 요청과 참고 자료에 있는 사실을 우선 사용하고, 없는 정보는 현실적인 값으로 채우되 과장하지 않음
- 사람 이름처럼 알 수 없는 개인 정보는 '○○○'로 남김
- JSON 값 안에서 인용할 때는 큰따옴표(") 대신 「 」나 ‘ ’를 씀"""

NEW_SECTION_RULE = """새 장 추가:
- [H번호]는 번호 상자가 달린 장 제목. 양식에 없는 큰 주제가 필요하면 새 장을 만들 수 있음
- "new_sections": [{"after": "H3", "title": "홍보 계획", "lines": ["1. 학교 누리집 게시", "가. 세부 내용"], "table": {"columns": ["구분", "내용"], "rows": [["…", "…"]]}}]
- after: 이 장 뒤에 넣음. title에는 번호를 쓰지 않음(번호 상자와 뒤 장 번호는 자동으로 고쳐짐)
- lines는 '이 문서의 줄 기호'에 나온 기호 체계를 그대로 따름(예: '1.'→'가.' 또는 '□'→'❍'→'-'). 앞쪽 공백은 넣지 않음
- table은 필요할 때만
- 기존 장에 줄 몇 개를 더하는 것으로 충분하면 새 장을 만들지 않음"""

FIX_SYSTEM = """당신은 JSON 교정기입니다. 주어진 텍스트를 내용은 그대로 두고 문법만 고쳐
올바른 JSON 객체 하나로만 출력합니다. 설명이나 코드 블록 없이 JSON만 출력하세요.
문자열 안의 큰따옴표는 \\" 로 이스케이프하고, 잘린 부분이 있으면 자연스럽게 닫으세요."""


def _ask_json(ai: dict, system: str, user: str, status, images: list | None = None) -> dict:
    raw = llm.complete(ai["provider"], ai["api_key"], ai["model"], system, user,
                       max_tokens=ai["max_tokens"], temperature=ai["temperature"],
                       timeout=ai["timeout"],
                       on_progress=lambda n: status(_progress("AI 작성 중", n)),
                       images=images)
    _dump(raw, "last_response.txt")
    try:
        return llm.parse_json(raw)
    except llm.LLMError as e:
        first_err = str(e)
        status("응답 형식 오류 — AI에게 교정 요청 중…")
    fixed = llm.complete(ai["provider"], ai["api_key"], ai["model"], FIX_SYSTEM,
                         f"오류: {first_err}\n\n교정할 텍스트:\n{raw}",
                         max_tokens=ai["max_tokens"], temperature=0.0, timeout=ai["timeout"],
                         on_progress=lambda n: status(_progress("JSON 교정 중", n)))
    _dump(fixed, "last_response_fixed.txt")
    try:
        return llm.parse_json(fixed)
    except llm.LLMError as e:
        from settings import CACHE_DIR
        hint = ("응답이 중간에 잘렸을 수 있습니다. 설정에서 '최대 출력 토큰'을 늘려주세요."
                if not raw.rstrip().endswith("}") else "다른 모델로 다시 시도해 보세요.")
        raise llm.LLMError(f"{e}\n\n{hint}\n원본 응답: {CACHE_DIR / 'last_response.txt'}")


def _progress(label: str, n: int) -> str:
    # 음수는 CLI(Claude Code/Codex)의 경과 초, 양수는 받은 글자 수
    return f"{label}… {-n}초 경과" if n < 0 else f"{label}… {n:,}자 받음"


def _dump(text: str, name: str):
    from settings import CACHE_DIR
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / name).write_text(text, encoding="utf-8")
    except OSError:
        pass

FILL_SYSTEM = f"""당신은 한국 학교·공공기관 문서 작성 전문가입니다.
HWPX 양식의 빈칸을 채워 바로 결재에 올릴 수 있는 문서를 완성합니다.

입력으로 양식 구조가 주어집니다.
- [S번호] : 채워야 할 빈칸이 있는 줄. 줄 전체를 대체할 텍스트를 돌려줌
- [E번호] (예시문) : 양식에 들어 있는 예시 문장. 주제에 맞지 않을 때만 고쳐서 돌려주고, 맞으면 생략
- [T번호] 표 : 반복 데이터 행. 열 순서대로 행 배열을 돌려줌. 행 수는 내용에 맞게 늘리거나 줄여도 됨
- (고정) : 바꾸지 않는 제목·항목명. 맥락 파악용
- '│'로 시작하는 줄은 표 칸 안의 내용

출력 규칙:
- JSON 객체 하나만 출력: {{"slots": {{"S1": "...", "E7": "..."}}, "tables": {{"T1": [["칸1", "칸2"], ...]}}}}
- 각 슬롯은 원래 줄의 앞쪽 공백, 번호(1. / 가. / ❍ / - / ◇ 등), 고정 문구(예: '행사명: ')를 그대로 유지하고 ○ 부분만 실제 내용으로 바꾼 줄 전체
- 같은 항목에 줄을 더 넣고 싶으면 값 안에 \\n을 넣고, 다음 줄도 같은 번호 체계(2. 3. / 나. 다.)와 같은 들여쓰기로 씀
- 필요 없는 줄은 빈 문자열 ""로 지움 (예: 내용이 없는 '3. ○○○○')
- 모든 S와 T를 빠짐없이 채움. 문서 안에 ○가 남지 않게 함(알 수 없는 사람 이름 제외)
- 요청에 양식에 없는 큰 주제가 있으면 "new_sections"로 새 장을 추가할 수 있음

{NEW_SECTION_RULE}

{STYLE_RULES}"""

BUILD_SYSTEM = f"""당신은 한국 학교·공공기관 문서 작성 전문가입니다.
요청에 맞는 문서 내용을 구조화된 JSON으로 작성합니다. 이 JSON은 학교 공문 서식(번호 박스 제목, 개조식 본문, 표)으로 조판됩니다.

출력: JSON 객체 하나만.
{{
  "title": "문서 제목 (예: 2025년 과학 탐구 축전 운영 계획)",
  "department": "작성 부서 (예: 과학정보부)",
  "date": "2025. 3.",
  "blocks": [
    {{"type": "heading", "text": "추진 목적"}},
    {{"type": "item", "text": "1. ~을 통해 ~ 역량을 기름"}},
    {{"type": "sub", "text": "가. 세부 내용"}},
    {{"type": "table", "columns": ["시간", "내용", "장소", "비고"], "rows": [["09:00~10:00", "개회식", "강당", ""]]}},
    {{"type": "note", "text": "※ 세부 일정은 변경될 수 있음"}}
  ],
  "attachment": "참가 동의서 1부"
}}
- heading은 큰 장 제목(번호는 자동으로 붙음, 텍스트에 번호 쓰지 않음)
- item은 '1. 2. 3.', sub는 '가. 나. 다.' 번호를 텍스트 앞에 직접 씀
- 일정·역할·예산·명단처럼 항목이 반복되는 정보는 table로 작성
- attachment는 붙임 문서가 없으면 빈 문자열

{STYLE_RULES}"""


def read_reference(path: str) -> str:
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".pdf":
        from pdf_reader import extract_pdf_text
        return extract_pdf_text(str(p))
    if ext == ".hwpx":
        return HwpxDoc(str(p)).plain_text()
    if ext == ".hwp":
        from hwp_controller import HwpFileReader
        return HwpFileReader(str(p)).read_all_text()
    for enc in ("utf-8", "cp949"):
        try:
            return p.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return p.read_text(encoding="utf-8", errors="replace")


def _context(request: str, refs: list[str], info: dict, max_chars: int) -> str:
    today = datetime.date.today()
    wd = "월화수목금토일"[today.weekday()]
    parts = [
        "## 작성 요청",
        request.strip() or "(요청 없음 — 양식과 참고 자료를 바탕으로 작성)",
        "",
        "## 기본 정보",
        f"- 학교(기관)명: {info.get('school_name') or '-'}",
        f"- 작성 부서: {info.get('department') or '-'}",
        f"- 작성자: {info.get('author') or '-'}",
        f"- 오늘 날짜: {today.year}. {today.month}. {today.day}.({wd})",
    ]
    budget = max_chars
    for path in refs:
        try:
            txt = read_reference(path)
        except Exception as e:
            txt = f"(읽기 실패: {e})"
        txt = txt[:budget]
        budget -= len(txt)
        parts += ["", f"## 참고 자료: {Path(path).name}", txt]
        if budget <= 0:
            break
    return "\n".join(parts)


def fill_form(form_path: str, out_path: str, request: str, refs: list[str], info: dict,
              ai: dict, on_status=None) -> dict:
    status = on_status or (lambda m: None)
    doc = HwpxDoc(form_path)
    outline = doc.analyze()
    note = "" if doc.has_placeholders else (
        "\n※ 이 양식에는 ○ 빈칸이 없는 완성된 예시 문서입니다. 모든 [S] 줄을 요청 주제에 맞게 다시 쓰되, "
        "항목명·제목처럼 그대로 두어야 할 줄은 원문 그대로 돌려주세요.\n")
    user = (_context(request, refs, info, ai["ref_max_chars"])
            + f"\n\n## 양식 구조 ({Path(form_path).stem})\n{note}{outline}\n\n"
              f"## 이 문서의 줄 기호 (새 장을 만들 때 이 체계를 따름)\n{' / '.join(doc.body_markers())}\n\n"
              "위 양식의 [S]와 [T]를 모두 채운 JSON만 출력하세요.")
    status(f"AI 작성 중… (빈칸 {len(doc.slots)}개, 표 {len(doc.tables)}개)")
    data = _ask_json(ai, FILL_SYSTEM, user, status)
    status("문서에 내용 채우는 중…")
    doc.fill(data.get("slots", {}), data.get("tables", {}), data.get("new_sections"))
    doc.save(out_path)
    return {"title": _guess_title(data.get("slots", {}), doc)}


def build_document(base_style_path: str, out_path: str, request: str, refs: list[str],
                   info: dict, ai: dict, pdf_form: str | None = None, on_status=None) -> dict:
    status = on_status or (lambda m: None)
    user = _context(request, refs, info, ai["ref_max_chars"])
    if pdf_form:
        from pdf_reader import extract_pdf_text
        form_text = extract_pdf_text(pdf_form)[: ai["ref_max_chars"]]
        user += ("\n\n## 따라야 할 양식 (PDF에서 추출한 텍스트)\n"
                 "아래 양식의 장 제목, 항목 순서, 표 구성을 그대로 따르고 ○○ 같은 빈칸과 예시 문장을 "
                 "요청 내용으로 채우세요.\n\n" + form_text)
    user += "\n\n위 내용으로 문서 JSON만 출력하세요."
    status("AI 작성 중…")
    spec = _ask_json(ai, BUILD_SYSTEM, user, status)
    status("문서 조판 중…")
    DocumentBuilder(base_style_path).build(spec, out_path)
    return {"title": spec.get("title", "")}


EDIT_SYSTEM = f"""당신은 한국 학교·공공기관 문서 편집 도우미입니다.
이미 작성된 HWPX 문서를 사용자의 요청대로 고칩니다. 서식은 프로그램이 유지하므로 글자만 바꿉니다.

입력 문서 구조:
- [S번호] : 문서의 한 줄(또는 한 칸). 고치려면 줄 전체를 새 텍스트로 돌려줌
- [T번호] 표 : 머리행 아래의 행들. 표를 고칠 때는 그 표의 '전체 행'을 열 순서대로 돌려줌(행 추가·삭제 가능)
- '│'로 시작하는 줄은 표 칸 안의 내용

출력: JSON 객체 하나만.
{{"reply": "무엇을 바꿨는지 한두 문장으로", "slots": {{"S12": "고친 줄"}}, "tables": {{"T2": [["칸", "칸"]]}},
  "inserts": [], "styles": [], "new_sections": []}}
- 바꾼 것만 넣음. 쓰지 않는 항목은 빼도 됨
- 원래 줄의 앞쪽 공백과 번호 체계(1. / 가. / ❍ / - 등)를 유지
- 줄을 뒤에 추가하려면 해당 줄 값에 \\n으로 이어 쓰고, 번호를 이어감 (예: "  2. 기존 내용\\n  3. 새 내용")
- 줄을 지우려면 ""
- 요청이 모호하거나 문서에 해당 부분이 없으면 slots와 tables를 비우고 reply에 무엇이 필요한지 물음
- 장 제목 번호 박스(숫자 1, 2, 3…)는 바꾸지 않음
- "○○ 장을 추가해줘"처럼 새 장이 필요하면 new_sections를 씀
- '1장', '첫 장', '2번째 장'이 종이 쪽(페이지)을 뜻할 수 있음. 문서 구조의 '── N쪽 ──' 표시와 첨부 화면으로 판단
- 쪽 수를 줄여 달라는 요청이면: 다음 쪽으로 밀려난 (빈 줄) 지우기, 문장 짧게 줄이기, 덜 중요한 줄 지우기 순서로 해결.
  (빈 줄)은 ""로 지움. 무엇 때문에 쪽이 넘쳤는지 reply에 설명
- 양식의 항목 구성(표의 항목명 칸, 장 제목)은 합치거나 지우지 않음. 사용자가 직접 요청할 때만 바꿈

줄 끼워 넣기 (장 제목 바로 아래, 또는 어떤 줄의 앞·뒤):
- "inserts": [{{"after": "H2", "lines": ["  운영 개요 설명 문장"]}}, {{"before": "S7", "lines": ["1. 새 첫 줄"]}}]
- after에 H번호를 쓰면 그 장 제목 바로 아래(첫 줄 앞)에 들어감. S번호를 쓰면 그 줄 바로 뒤
- before에 S번호를 쓰면 그 줄 바로 앞
- lines는 이 문서의 줄 기호 체계를 따르고 앞쪽 공백은 넣지 않음. 기호 없는 설명 문장도 가능

글자 모양 (색, 굵게, 기울임, 밑줄, 크기, 배경색):
- "styles": [{{"target": "S12", "color": "#FF0000"}}, {{"target": "S15", "part": "강조할 글자", "bold": true, "underline": true}}]
- target은 S번호 또는 H번호(장 제목). part를 쓰면 그 줄 안의 그 글자만, 없으면 줄 전체
- color·background는 #RRGGBB, size는 포인트(예: 12), bold/italic/underline은 true/false
- 글자 모양만 바꿀 때는 slots에 그 줄을 넣지 않음

{NEW_SECTION_RULE}

{STYLE_RULES}"""


def edit_document(path: str, out_path: str, instruction: str, history: list[tuple[str, str]],
                  ai: dict, on_status=None, page_info: tuple | None = None) -> dict:
    status = on_status or (lambda m: None)
    pages, pinfo = page_info or ([], None)
    pinfo = pinfo or {}
    doc = HwpxDoc(path)
    outline = doc.analyze(edit=True, page_map=pinfo.get("paras"), page_count=pinfo.get("pages"))
    images = pages[: ai.get("max_images", 6)] if ai.get("send_images", True) else []
    hist = "\n".join(f"{'사용자' if who == 'user' else 'AI'}: {msg}" for who, msg in history[-8:])
    user = (f"## 현재 문서 구조\n{outline}\n\n"
            f"## 이 문서의 줄 기호 (새 장을 만들 때 이 체계를 따름)\n{' / '.join(doc.body_markers())}\n\n"
            + (f"## 지금까지의 대화\n{hist}\n\n" if hist else "")
            + f"## 이번 수정 요청\n{instruction}\n\n바뀐 부분만 담은 JSON을 출력하세요.")
    status("AI가 수정 중…" + (f" (화면 {len(images)}쪽 첨부)" if images else ""))
    data = _ask_json(ai, EDIT_SYSTEM, user, status, images)
    slots = {k: v for k, v in (data.get("slots") or {}).items() if k in doc.slots}
    tables = {k: v for k, v in (data.get("tables") or {}).items() if k in doc.tables}
    new_sections = data.get("new_sections") or []
    inserts = data.get("inserts") or []
    styles = data.get("styles") or []
    changed = 0
    missed = []
    dropped = [k for k in (data.get("slots") or {}) if k not in doc.slots]
    if dropped:
        missed.append(f"없는 줄 번호 {', '.join(dropped[:5])}")
    if slots or tables or new_sections or inserts or styles:
        status("문서에 반영 중…")
        r = doc.fill(slots, tables, new_sections, inserts, styles)
        changed = len(slots) + len(tables) + r["sections"] + r["inserted"] + r["styled"]
        want_lines = sum(len(i.get("lines") or []) for i in inserts if isinstance(i, dict))
        if r["inserted"] < want_lines:
            missed.append(f"끼워 넣을 줄 {want_lines - r['inserted']}개")
        if r["styled"] < len(styles):
            missed.append(f"글자 모양 {len(styles) - r['styled']}곳")
        if r["sections"] < len(new_sections):
            missed.append(f"새 장 {len(new_sections) - r['sections']}개")
        if changed:
            doc.save(out_path)
    warning = ("AI가 요청한 것 중 " + ", ".join(missed) + "을(를) 문서에 반영하지 못했습니다. "
               "위치를 더 구체적으로 말씀해 주세요.") if missed else ""
    return {"reply": str(data.get("reply", "")).strip(), "changed": changed, "warning": warning}


def _guess_title(slots: dict, doc: HwpxDoc) -> str:
    for v in slots.values():
        s = str(v).strip()
        if s and ("계획" in s or "보고" in s) and len(s) < 60:
            return s
    return ""
