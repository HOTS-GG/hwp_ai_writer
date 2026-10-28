"""완성 문서(작년 계획서 등)를 해마다 바뀌는 부분만 ○○○○로 바꾼 재사용 양식으로 만든다."""
from dataclasses import dataclass

from ..ai import AIConfig
from ..ai.prompts import TEMPLATIZE_SYSTEM
from ..doc import Editor, EditPlan, HwpxDocument, Outline
from ..doc.xml import PLACEHOLDER
from .job import Job
from .stream import LineStreamer, ask_json


@dataclass
class TemplatizeResult:
    reply: str
    changed: int          # 바뀐 줄·표 수
    blanks: int           # 만든 뒤 문서에 있는 ○ 빈칸 줄 수


def templatize(job: Job, path: str, out_path: str, ai: AIConfig) -> TemplatizeResult:
    doc = HwpxDocument(path)
    outline = Outline(doc, edit=True)
    editor = Editor(doc, outline)
    user = (f"## 완성 문서 구조\n{outline.text}\n\n"
            "해마다 바뀌는 정보만 ○로 바꾼 줄과 표를 JSON으로 출력하세요.")
    job.status("AI가 바뀌는 부분을 찾아 빈칸으로 바꾸는 중…")
    streamer = LineStreamer(editor, job)
    data = ask_json(ai, TEMPLATIZE_SYSTEM, user, job, on_text=streamer.on_text, label="양식으로 만드는 중")
    if not ai.streams:
        streamer.replay(data, seconds=2.0)
    plan = EditPlan.from_ai({"slots": data.get("slots") or {}, "tables": data.get("tables") or {}}, outline)
    report = editor.apply(plan) if not plan.is_empty() else None
    changed = report.changed if report else 0
    blanks = sum(1 for line in doc.plain_text().splitlines() if PLACEHOLDER.search(line))
    if changed:
        doc.save(out_path)
        job.frame(doc, force=True)
    return TemplatizeResult(str(data.get("reply", "")).strip(), changed, blanks)
