"""AI에게 JSON을 받으면서 받는 대로 문서에 반영한다.

  ask_json()        AI 호출 + JSON 해석 (실패하면 AI에게 한 번 교정을 맡김)
  LineStreamer      slots/tables 응답(양식 채우기·수정)을 받는 대로 Editor에 반영하고 화면을 보낸다
"""
import re
import time

from ..ai import AIConfig, LLMError, complete, parse_json
from ..ai.jsonstream import scan
from ..ai.jsonutil import JSONError
from ..ai.prompts import FIX_SYSTEM
from ..config import CACHE_DIR
from ..doc import Editor


def _progress(label: str, n: int) -> str:
    # 음수는 CLI(Claude Code/Codex)의 경과 초, 양수는 받은 글자 수
    return f"{label}… {-n}초 경과" if n < 0 else f"{label}… {n:,}자 받음"


def dump(text: str, name: str):
    """마지막 AI 응답을 임시 폴더에 남긴다 (문제 확인용)."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / name).write_text(text, encoding="utf-8")
    except OSError:
        pass


def ask_json(ai: AIConfig, system: str, user: str, job, images=None, on_text=None, label="AI 작성 중") -> dict:
    raw = complete(ai, system, user, images=images, on_text=on_text, stop=job.stop,
                   on_progress=lambda n: job.status(_progress(label, n)),
                   on_note=lambda msg: job.status(f"{label}… {msg}…"))
    dump(raw, "last_response.txt")
    try:
        return parse_json(raw)
    except JSONError as e:
        first_err = str(e)
    job.status("응답 형식 오류 — AI에게 교정 요청 중…")
    fix_cfg = AIConfig(**{**ai.__dict__, "temperature": 0.0, "web_search": False})
    fixed = complete(fix_cfg, FIX_SYSTEM, f"오류: {first_err}\n\n교정할 텍스트:\n{raw}", stop=job.stop,
                     on_progress=lambda n: job.status(_progress("JSON 교정 중", n)))
    dump(fixed, "last_response_fixed.txt")
    try:
        return parse_json(fixed)
    except JSONError as e:
        hint = ("응답이 중간에 잘렸을 수 있습니다. 설정에서 '최대 출력 토큰'을 늘려주세요."
                if not raw.rstrip().endswith("}") else "다른 모델로 다시 시도해 보세요.")
        raise LLMError(f"{e}\n\n{hint}\n원본 응답: {CACHE_DIR / 'last_response.txt'}")


def sources_of(data: dict) -> list[tuple[str, str]]:
    """AI가 웹 검색으로 쓴 출처·찾은 자료 링크 [(제목, 주소)]. http(s) 주소만, 같은 주소는 한 번."""
    out, seen = [], set()
    for s in data.get("sources") or []:
        if isinstance(s, str):
            title, url = "", s
        elif isinstance(s, dict):
            title, url = str(s.get("title", "")).strip(), str(s.get("url", "")).strip()
        else:
            continue
        if url.startswith(("http://", "https://")) and url not in seen:
            seen.add(url)
            out.append((title or url, url))
    return out[:8]


class LineStreamer:
    """받는 중인 응답의 slots·tables를 Editor에 반영하고 Job으로 화면을 보낸다.

    - 완성된 줄·표는 그대로 넣는다 (fill_line/fill_table)
    - 쓰는 중인 줄은 받은 글자까지 임시로 보여준다 (type_line)
    """

    SCAN_INTERVAL = 0.12

    def __init__(self, editor: Editor, job):
        self.editor = editor
        self.job = job
        self._done: set[str] = set()
        self._last_scan = 0.0

    def on_text(self, text: str):
        """화면은 보조 기능이라, 여기서 무엇이 잘못돼도 받기(문서 생성)는 멈추지 않는다."""
        if not self.job.live:
            return
        try:
            self._update(text)
        except Exception:
            pass

    def _update(self, text: str):
        now = time.monotonic()
        if now - self._last_scan < self.SCAN_INTERVAL:
            return
        self._last_scan = now
        part = scan(text)
        focus = []
        for lid, value in part.entries.get("slots", {}).items():
            if lid not in self._done:
                self._done.add(lid)
                focus = self.editor.fill_line(lid, value) or focus
        for tid, rows in part.entries.get("tables", {}).items():
            if tid not in self._done:
                self._done.add(tid)
                focus = self.editor.fill_table(tid, rows) or focus
        if part.typing and part.typing[0] == "slots":
            focus = self.editor.type_line(part.typing[1], part.typing[2]) or focus
        if focus:
            self.job.frame(self.editor.doc, _cells(focus))

    def replay(self, data: dict, seconds: float = 4.0):
        """스트리밍이 안 되는 경우(Codex): 다 받은 답을 위에서부터 한 줄씩 채워 보여준다."""
        if not self.job.visible:   # 화면이 없으면 기다릴 이유가 없다 (끝에 한 번에 반영)
            return
        slots = [(k, v) for k, v in (data.get("slots") or {}).items() if k not in self._done]
        tables = [(k, v) for k, v in (data.get("tables") or {}).items() if k not in self._done]
        order = _doc_order(self.editor.outline.text)
        todo = sorted(slots + tables, key=lambda kv: order.get(kv[0], 1 << 30))
        if not todo:
            return
        delay = min(0.12, seconds / len(todo))
        for ref, value in todo:
            self.job.check()
            self._done.add(ref)
            if ref.startswith("T"):
                focus = self.editor.fill_table(ref, value) if isinstance(value, list) else []
            else:
                focus = self.editor.fill_line(ref, value)
            if focus:
                self.job.frame(self.editor.doc, _cells(focus), force=True)
                time.sleep(delay)


def _doc_order(outline_text: str) -> dict:
    """개요 글에서 각 번호([S3], [T1] …)가 처음 나오는 위치 = 문서 위에서 아래 순서."""
    order = {}
    for m in re.finditer(r"\[([SETHBI]\d+)\]", outline_text):
        order.setdefault(m.group(1), m.start())
    return order


def _cells(focus: list) -> list:
    """표 행(hp:tr)이면 그 행의 칸 줄들을 강조 대상으로 바꾼다."""
    out = []
    for e in focus:
        if e.tag.endswith("}tr"):
            out += [p for p in e.iter() if p.tag.endswith("}p")]
        else:
            out.append(e)
    return out
