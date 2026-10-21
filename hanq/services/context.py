"""AI에게 보낼 입력 앞부분: 작성 요청, 기본 정보, 참고 자료."""
import datetime
from pathlib import Path

from ..readers import read_reference


def today_text() -> str:
    d = datetime.date.today()
    return f"{d.year}. {d.month}. {d.day}.({'월화수목금토일'[d.weekday()]})"


def read_references(refs: list[str], max_chars: int) -> list[tuple[str, str]]:
    """참고 자료를 읽어 (파일 이름, 글) 목록으로. 글자 수 한도는 자료마다 고르게 나눈다
    (짧은 자료가 남긴 몫은 뒤 자료가 쓴다)."""
    texts = []
    for path in refs:
        try:
            txt = read_reference(path).strip() or "(글자가 없습니다)"
        except Exception as e:
            txt = f"(읽기 실패: {e})"
        texts.append((Path(path).name, txt))
    out = []
    budget = max_chars
    for i, (name, txt) in enumerate(texts):
        share = budget // max(len(texts) - i, 1)
        used = min(len(txt), share)
        if len(txt) > share:
            txt = txt[:share] + f"\n…(이하 {len(txt) - share:,}자 생략)"
        budget -= used
        out.append((name, txt))
    return out


def build_context(request: str, refs: list[str], info: dict, max_chars: int) -> str:
    parts = [
        "## 작성 요청",
        request.strip() or "(요청 없음 — 양식과 참고 자료를 바탕으로 작성)",
        "",
        "## 기본 정보",
        f"- 학교(기관)명: {info.get('school_name') or '-'}",
        f"- 작성 부서: {info.get('department') or '-'}",
        f"- 작성자: {info.get('author') or '-'}",
        f"- 오늘 날짜: {today_text()}",
    ]
    for name, txt in read_references(refs, max_chars):
        parts += ["", f"## 참고 자료: {name}", txt]
    return "\n".join(parts)
