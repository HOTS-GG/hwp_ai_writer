"""기본 양식(번호 상자 장 제목 + 개조식 본문 + 표)의 문단을 복제해 새 문서를 조립한다.
PDF 양식이나 양식 없는 자유 작성에 쓴다."""
import copy
import re

from .document import HwpxDocument
from .xml import (NUMBER_ONLY, PLACEHOLDER, P, RUN, T, TBL, TC, TR, build_table_paragraph, cell_text, ensure_t,
                  has_objects, leading_ws, new_id, para_text, set_cell, set_t, strip_lineseg, t_text)


class DocumentBuilder:
    def __init__(self, base: str | bytes):
        self.doc = HwpxDocument(data=base) if isinstance(base, (bytes, bytearray)) else HwpxDocument(base)
        name = sorted(self.doc.sections)[0]
        self.root = self.doc.sections[name]
        top = list(self.root.iterchildren(P))

        def heading_tbl(p):
            tbl = p.find(f"{RUN}/{TBL}")
            if tbl is None or tbl.get("rowCnt") != "1" or tbl.get("colCnt") != "3":
                return None
            return tbl if NUMBER_ONLY.match(cell_text(tbl.find(TR).findall(TC)[0])) else None

        first_heading = next((i for i, p in enumerate(top) if heading_tbl(p) is not None), None)
        if first_heading is None:
            raise ValueError("기본 서식 양식에서 번호 상자 장 제목을 찾지 못했습니다.")
        body = top[first_heading:]

        def pick(pred):
            for p in body:
                if pred(p):
                    found = copy.deepcopy(p)
                    strip_lineseg(found)
                    return found
            return None

        def plain(rx):
            return lambda p: re.match(rx, para_text(p)) and not has_objects(p)

        def pick_or(pred, fallback):
            # lxml 요소는 진릿값으로 고르지 않는다 (자식 수로 판단돼 틀릴 수 있음)
            found = pick(pred)
            return found if found is not None else copy.deepcopy(fallback)

        self.p_heading = pick(lambda p: heading_tbl(p) is not None)
        self.p_item = pick(plain(r"^\s*\d+\.\s"))
        self.p_sub = pick_or(plain(r"^\s*[가-힣]\.\s"), self.p_item)
        self.p_note = pick_or(lambda p: "※" in para_text(p) and not has_objects(p), self.p_item)
        self.p_blank = pick(lambda p: not para_text(p).strip() and not has_objects(p))
        self.p_table = pick(lambda p: (lambda t: t is not None and int(t.get("rowCnt", "0")) >= 3
                                       and int(t.get("colCnt", "0")) >= 3)(p.find(f"{RUN}/{TBL}")))
        self.p_end = pick(lambda p: "붙임" in para_text(p) or "끝." in para_text(p))
        self.prefix = top[:first_heading]
        for p in body:
            self.root.remove(p)
        self._n_heading = 0

    # ── 표지/제목 ──
    def set_cover(self, title: str, department: str, date: str):
        for p in self.prefix:
            for t in p.iter(T):
                s = t_text(t)
                if not PLACEHOLDER.search(s):
                    continue
                stripped = s.strip()
                if re.fullmatch(r"-?.*부-?", stripped) or stripped.startswith("-"):
                    set_t(t, f"-{department}-" if department else "")
                elif re.fullmatch(r"[\d○\.\s]+", stripped):
                    set_t(t, leading_ws(s) + date)
                else:
                    set_t(t, leading_ws(s) + title)

    # ── 본문 ──
    def _append(self, p):
        self.root.append(p)
        return p

    def heading(self, text: str):
        self._n_heading += 1
        if self._n_heading > 1:
            self.blank()
        p = copy.deepcopy(self.p_heading)
        tbl = p.find(f"{RUN}/{TBL}")
        tbl.set("id", new_id())
        cells = tbl.find(TR).findall(TC)
        set_cell(cells[0], str(self._n_heading))
        set_cell(cells[-1], "  " + text.strip())
        return self._append(p)

    def item(self, text: str, kind: str = "item"):
        proto = {"item": self.p_item, "sub": self.p_sub, "note": self.p_note}.get(kind, self.p_item)
        p = copy.deepcopy(proto)
        if kind == "note" and not text.strip().startswith("※"):
            text = "※ " + text.strip()
        t = p.find(f"{RUN}/{T}")
        if t is None:
            t = ensure_t(p)
        indent = leading_ws(t_text(t))
        for other in p.iterfind(f"{RUN}/{T}"):
            if other is not t:
                set_t(other, "")
        set_t(t, indent + text.strip())
        return self._append(p)

    def blank(self):
        if self.p_blank is not None:
            return self._append(copy.deepcopy(self.p_blank))
        return None

    def table(self, columns: list, rows: list):
        if self.p_table is None or not columns:
            return None
        return self._append(build_table_paragraph(self.p_table, columns, rows))

    def ending(self, text: str):
        if not text or self.p_end is None:
            return None
        self.blank()
        p = copy.deepcopy(self.p_end)
        t = p.find(f"{RUN}/{T}")
        for other in p.iterfind(f"{RUN}/{T}"):
            if other is not t:
                set_t(other, "")
        set_t(t, text.strip())
        return self._append(p)

    def block(self, b: dict):
        """blocks 항목 하나를 붙이고, 붙인 문단을 돌려준다."""
        kind = b.get("type")
        if kind == "heading":
            return self.heading(str(b.get("text", "")))
        if kind in ("item", "sub", "note", "text"):
            return self.item(str(b.get("text", "")), "item" if kind == "text" else kind)
        if kind == "table":
            return self.table(b.get("columns") or [], b.get("rows") or [])
        if kind == "blank":
            return self.blank()
        return None

    def finish(self, spec: dict) -> HwpxDocument:
        self.set_cover(str(spec.get("title", "")), str(spec.get("department", "")), str(spec.get("date", "")))
        att = str(spec.get("attachment", "") or "")
        if att:
            self.ending(att if att.startswith("붙임") else f"붙임  {att.rstrip('.')}.  끝.")
        return self.doc

    def build(self, spec: dict, out_path: str | None = None) -> HwpxDocument:
        for b in spec.get("blocks") or []:
            if isinstance(b, dict):
                self.block(b)
        doc = self.finish(spec)
        if out_path:
            doc.save(out_path)
        return doc
