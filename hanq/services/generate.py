"""문서 만들기: 양식 빈칸 채우기(fill_form) / 기본 서식으로 새 문서 조립(build_document).

둘 다 AI 응답을 받는 대로 문서에 반영해 Job.frame()으로 화면에 보낸다.
"""
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..ai import AIConfig
from ..ai.jsonstream import scan
from ..ai.prompts import BUILD_SYSTEM, FILL_NO_PLACEHOLDER_NOTE, FILL_SYSTEM, PDF_FORM_NOTE
from ..doc import DocumentBuilder, Editor, EditPlan, HwpxDocument, Outline
from ..doc.editor import ApplyReport
from .context import build_context
from .job import Job
from .stream import LineStreamer, ask_json


@dataclass
class Result:
    path: str
    title: str = ""
    report: ApplyReport = field(default_factory=ApplyReport)
    warning: str = ""


def describe_form(path: str) -> str:
    """양식 안내 한 줄 (양식을 고를 때 보여줌)."""
    o = Outline(HwpxDocument(path))
    if o.has_placeholders:
        return f"빈칸 {o.fill_count}개 · 반복 표 {len(o.tables)}개를 채웁니다. 서식은 원본 그대로 유지됩니다."
    return f"○ 빈칸이 없는 완성 문서입니다. 문장 {o.fill_count}개를 요청 주제에 맞게 다시 씁니다."


def fill_form(job: Job, form_path: str, out_path: str, request: str, refs: list[str], info: dict,
              ai: AIConfig) -> Result:
    doc = HwpxDocument(form_path)
    outline = Outline(doc)
    editor = Editor(doc, outline)
    job.frame(doc, force=True)

    note = "" if outline.has_placeholders else f"\n{FILL_NO_PLACEHOLDER_NOTE}\n"
    job.status("참고 자료 읽는 중…" if refs else "AI에게 보낼 내용 준비 중…")
    user = (build_context(request, refs, info, ai.ref_max_chars)
            + f"\n\n## 양식 구조 ({Path(form_path).stem})\n{note}{outline.text}\n\n"
              f"## 이 문서의 줄 기호 (새 장을 만들 때 이 체계를 따름)\n{' / '.join(editor.body_markers())}\n\n"
              "위 양식의 [S]와 [T]를 채운 JSON만 출력하세요.")
    job.status(f"AI 작성 중… (빈칸 {outline.fill_count}개, 표 {len(outline.tables)}개)")
    streamer = LineStreamer(editor, job)
    data = ask_json(ai, FILL_SYSTEM, user, job, on_text=streamer.on_text)
    if not ai.streams:
        streamer.replay(data)

    job.status("문서에 내용 채우는 중…")
    plan = EditPlan.from_ai(data, outline)
    report = editor.apply(plan)
    job.frame(doc, force=True)
    doc.save(out_path)
    return Result(out_path, _guess_title(plan.lines), report)


def build_document(job: Job, base_style_path: str, out_path: str, request: str, refs: list[str], info: dict,
                   ai: AIConfig, pdf_form: str | None = None) -> Result:
    base = Path(base_style_path).read_bytes()
    job.status("참고 자료 읽는 중…" if refs else "AI에게 보낼 내용 준비 중…")
    user = build_context(request, refs, info, ai.ref_max_chars)
    if pdf_form:
        from ..readers.pdf import read_pdf
        user += f"\n\n## 따라야 할 양식 (PDF에서 추출한 텍스트)\n{PDF_FORM_NOTE}\n\n" + read_pdf(pdf_form)[: ai.ref_max_chars]
    user += "\n\n위 내용으로 문서 JSON만 출력하세요."

    live = _LiveBuilder(base, job)
    job.frame(live.builder.doc, force=True)
    job.status("AI 작성 중…")
    spec = ask_json(ai, BUILD_SYSTEM, user, job, on_text=live.on_text)
    if not ai.streams:
        live.replay(spec)

    job.status("문서 조판 중…")
    builder = DocumentBuilder(base)
    doc = builder.build(spec, out_path)
    job.frame(doc, force=True)
    return Result(out_path, str(spec.get("title", "")))


class _LiveBuilder:
    """받는 중인 blocks를 하나씩 붙여 가며 보여준다 (blocks는 뒤에 붙기만 하므로 이어서 만든다)."""

    SCAN_INTERVAL = 0.15

    def __init__(self, base: bytes, job: Job):
        self.builder = DocumentBuilder(base)
        self.job = job
        self.n = 0
        self._covered = False
        self._last = 0.0

    def _cover(self, scalars: dict):
        if not self._covered and scalars.get("title"):
            self.builder.set_cover(str(scalars.get("title", "")), str(scalars.get("department", "")),
                                   str(scalars.get("date", "")))
            self._covered = True

    def _add(self, blocks: list, scalars: dict, force=False):
        self._cover(scalars)
        focus = []
        for b in blocks[self.n:]:
            if isinstance(b, dict):
                p = self.builder.block(b)
                if p is not None:
                    focus = [p]
        self.n = max(self.n, len(blocks))
        if focus:
            self.job.frame(self.builder.doc, focus, force=force)

    def on_text(self, text: str):
        if not self.job.live:
            return
        try:
            self._update(text)
        except Exception:
            pass   # 화면 오류로 생성이 멈추지 않게

    def _update(self, text: str):
        now = time.monotonic()
        if now - self._last < self.SCAN_INTERVAL:
            return
        self._last = now
        part = scan(text, objects=(), arrays=("blocks",))
        self._add(part.items.get("blocks", []), part.scalars)

    def replay(self, spec: dict, seconds: float = 4.0):
        if not self.job.live:
            return
        blocks = [b for b in (spec.get("blocks") or [])]
        delay = min(0.12, seconds / max(len(blocks) - self.n, 1))
        for i in range(self.n, len(blocks)):
            self.job.check()
            self._add(blocks[: i + 1], spec, force=True)
            time.sleep(delay)


def _guess_title(lines: dict) -> str:
    for v in lines.values():
        s = str(v).strip()
        if s and ("계획" in s or "보고" in s) and len(s) < 60:
            return s
    return ""
