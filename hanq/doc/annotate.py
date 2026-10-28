"""양식에서 AI가 읽고 채우는 곳을 형광펜처럼 칠한 사본을 만든다 (템플릿 탭의 'AI가 채울 곳 보기').

  노랑  AI가 채울 빈칸 줄 (○○○○ 등) — 빈칸이 없는 완성 문서면 모든 문장
  파랑  AI가 주제에 맞게 고칠 수 있는 예시 문장
  초록  AI가 행 수까지 맞춰 채우는 반복 표
  색 없음  그대로 남는 부분 (제목·항목명·로고 등)
"""
from dataclasses import dataclass

from .document import HwpxDocument
from .editor import Editor
from .outline import Outline
from .xml import T, TC, t_text

COLORS = {"fill": "#FFE58A", "example": "#CFE2FF", "table": "#C9F0D2"}


@dataclass
class FormSummary:
    fill_lines: int          # 채울 빈칸 줄
    empty_cells: int         # 그중 빈 표 칸
    examples: int            # 고칠 수 있는 예시문
    tables: int              # 반복 표
    headings: int            # 장 제목
    has_placeholders: bool   # ○ 빈칸 양식인지 (아니면 완성 문서 → 모든 문장을 다시 씀)

    def describe(self) -> str:
        if self.fill_lines == 0 and self.tables == 0:
            return ("AI가 채울 곳을 찾지 못했습니다.\n"
                    "한글에서 채울 자리에 ○○○○를 적어 저장한 뒤 다시 추가해 보세요.")
        if self.has_placeholders:
            lines = [f"• 빈칸 {self.fill_lines}곳을 채웁니다 (노랑)" + (f" — 빈 표 칸 {self.empty_cells}개 포함"
                                                               if self.empty_cells else "")]
            if self.examples:
                lines.append(f"• 예시 문장 {self.examples}줄은 주제에 맞게 고칠 수 있습니다 (파랑)")
        else:
            lines = [f"• ○ 빈칸이 없는 완성 문서입니다 — 문장 {self.fill_lines}줄을 요청 주제에 맞게 새로 씁니다 (노랑)"]
        if self.tables:
            lines.append(f"• 표 {self.tables}개는 내용에 맞게 행 수까지 맞춥니다 (초록)")
        lines.append("• 색이 없는 부분(장 제목·항목명·표지·로고)은 그대로 남습니다.")
        return "\n".join(lines)


def summarize(outline: Outline) -> FormSummary:
    return FormSummary(
        fill_lines=sum(1 for k in outline.lines if k.startswith("S")),
        empty_cells=len(outline.empty_cells),
        examples=sum(1 for k in outline.lines if k.startswith("E")),
        tables=len(outline.tables),
        headings=len(outline.headings),
        has_placeholders=outline.has_placeholders,
    )


def annotate(path: str) -> tuple[bytes, FormSummary]:
    """칠한 사본(hwpx 바이트)과 요약. 원본 파일은 건드리지 않는다."""
    doc = HwpxDocument(path)
    outline = Outline(doc)
    summary = summarize(outline)
    ed = Editor(doc, outline)
    for lid, p in outline.lines.items():
        color = COLORS["example"] if lid.startswith("E") else COLORS["fill"]
        for t in p.iter(T):
            if t_text(t).strip():
                ed.apply_style(t, {"background": color})
    for g in outline.tables.values():
        for tr in g.trs:
            for tc in tr.findall(TC):
                for t in tc.iter(T):
                    if t_text(t).strip():
                        ed.apply_style(t, {"background": COLORS["table"]})
    return doc.to_bytes(), summary
