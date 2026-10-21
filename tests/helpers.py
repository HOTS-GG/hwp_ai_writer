"""테스트 공용: 기본 양식 경로, 섞인 글자 모양 줄이 있는 작은 HWPX 만들기."""
import copy
from pathlib import Path

from hanq.doc import HwpxDocument
from hanq.doc.xml import RUN, T, P, para_text

ROOT = Path(__file__).resolve().parent.parent
FORMS = sorted((ROOT / "forms").glob("*.hwpx"))
PLAN_FORM = str(FORMS[0])          # 01_행사·사업 운영 계획서 (○ 빈칸 + 장 제목 + 표)
REPORT_FORM = str(FORMS[2])        # 03_결과 보고서


def split_runs(doc: HwpxDocument, text_start: str, cut: int):
    """text_start로 시작하는 본문 줄을 글자 모양 조각 둘로 나눈다 (실제 공문서의 '□ ' + '제목' 같은 줄 흉내)."""
    for p in doc.top_paragraphs():
        s = para_text(p)
        if s.strip().startswith(text_start):
            run = p.find(RUN)
            t = run.find(T)
            first, rest = s[:cut], s[cut:]
            t.text = first
            for c in list(t):
                t.remove(c)
            run2 = copy.deepcopy(run)
            run2.find(T).text = rest
            run.addnext(run2)
            return p
    raise AssertionError(f"'{text_start}'로 시작하는 줄이 없음")


def find_line(outline, needle: str) -> str:
    for lid, p in outline.lines.items():
        if needle in para_text(p):
            return lid
    raise AssertionError(f"'{needle}'이(가) 든 줄이 없음")


def body_lines(doc) -> list[str]:
    return [para_text(p) for p in doc.top_paragraphs()]


__all__ = ["ROOT", "FORMS", "PLAN_FORM", "REPORT_FORM", "split_runs", "find_line", "body_lines", "P"]
