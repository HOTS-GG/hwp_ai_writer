"""대화로 문서 고치기. 고친 줄은 받는 대로 화면에 보이고, 끝나면 실제로 바뀐 게 있는지 확인한다."""
from dataclasses import dataclass, field

from ..ai import AIConfig
from ..ai.prompts import EDIT_SYSTEM
from ..doc import Editor, EditPlan, HwpxDocument, Outline
from ..doc.editor import ApplyReport
from .context import read_references
from .job import Job
from .stream import LineStreamer, ask_json, sources_of


@dataclass
class EditResult:
    reply: str
    changed: int
    report: ApplyReport = field(default_factory=ApplyReport)
    warning: str = ""
    pages: tuple | None = None    # (고치기 전 쪽 수, 고친 뒤 쪽 수) — 한글로 확인했을 때만
    sources: list = field(default_factory=list)   # 웹 검색 출처 [(제목, 주소)]


def edit_document(job: Job, path: str, out_path: str, instruction: str, history: list[tuple[str, str]],
                  ai: AIConfig, page_info: tuple | None = None, refs: list[str] | None = None) -> EditResult:
    pages, pinfo = page_info or ([], None)
    pinfo = pinfo or {}
    doc = HwpxDocument(path)
    outline = Outline(doc, edit=True, page_map=pinfo.get("paras"), page_count=pinfo.get("pages"))
    editor = Editor(doc, outline)
    before = doc.snapshot()
    images = pages[: ai.max_images] if ai.send_images else []
    hist = "\n".join(f"{'사용자' if who == 'user' else 'AI'}: {msg}" for who, msg in history[-8:])
    ref_text = "".join(f"## 참고 자료: {name}\n{txt}\n\n" for name, txt in read_references(refs or [], ai.ref_max_chars))
    user = (f"## 현재 문서 구조\n{outline.text}\n\n"
            f"## 이 문서의 줄 기호 (새 장을 만들 때 이 체계를 따름)\n{' / '.join(editor.body_markers())}\n\n"
            + ref_text
            + (f"## 지금까지의 대화\n{hist}\n\n" if hist else "")
            + f"## 이번 수정 요청\n{instruction}\n\n바뀐 부분만 담은 JSON을 출력하세요.")
    job.status("AI가 수정 중…" + (f" (화면 {len(images)}쪽 첨부)" if images else ""))
    streamer = LineStreamer(editor, job)
    data = ask_json(ai, EDIT_SYSTEM, user, job, images=images, on_text=streamer.on_text, label="AI가 수정 중")
    if not ai.streams:
        streamer.replay(data, seconds=2.0)

    plan = EditPlan.from_ai(data, outline)
    report = ApplyReport()
    if not plan.is_empty() or plan.dropped:
        job.status("문서에 반영 중…")
        report = editor.apply(plan)
    changed = report.changed
    warning = ""
    if report.missed:
        warning = ("AI가 요청한 것 중 문서에 반영하지 못한 것이 있습니다: " + ", ".join(report.missed) + ". "
                   "위치를 더 구체적으로 말씀해 주세요.")
    # AI가 같은 글자를 그대로 돌려준 경우: 고쳤다고 답해도 실제로는 바뀐 게 없다
    if changed and doc.snapshot() == before:
        changed = 0
        warning = ("AI가 고쳤다고 답했지만 실제 문서는 바뀌지 않았습니다. "
                   "고칠 곳을 더 구체적으로 말씀해 주세요. (예: '5장 소요 예산을 통째로 지워줘')")
    if changed:
        doc.save(out_path)
        job.frame(doc, force=True)
    return EditResult(str(data.get("reply", "")).strip(), changed, report, warning, sources=sources_of(data))
