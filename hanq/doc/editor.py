"""Outline 번호를 기준으로 문서를 고친다: 줄·표 채우기, 줄 끼워 넣기, 장·표·그림·줄 지우기,
옮기기, 찾아 바꾸기, 표 틀 없애기·테두리, 글자·문단 모양, 새 장 추가.

AI 응답(JSON)은 EditPlan으로 정리한 뒤 apply()로 한 번에 반영한다.
실시간 화면에서는 fill_line()/fill_table()/type_line()을 받는 대로 하나씩 부른다.
"""
import copy
import io
import os
from dataclasses import dataclass, field

from lxml import etree

from .document import HwpxDocument
from .outline import Outline, TableGroup
from .xml import (CELLADDR, CELLSPAN, CELLSZ, HWPUNIT_PER_MM, P, ROMAN, RUN, SUBLIST, SZ, T, TBL, TC, TEXT_PATH, TR,
                  build_table_paragraph, cell_text, clone_line, drop_if_empty, has_objects, has_secpr, heading_parts,
                  hex_color, hp,
                  is_blank, is_simple_table_para, leading_ws, mark_changed, marker_of, new_id, para_text,
                  plain_table_paragraph, renumber_table, set_cell, set_para_text, set_t, strip_lineseg, t_text, top_para)


def as_lines(v) -> list[str]:
    """AI가 준 줄 목록. 목록 대신 글 하나로 주면 줄바꿈으로 나눈다 (글자마다 한 줄이 되지 않게)."""
    if isinstance(v, str):
        return [ln for ln in v.split("\n") if ln.strip()]
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v if x is not None and not isinstance(x, (dict, list))]
    return []


def _mm(v) -> int:
    """mm로 준 크기를 HWPUNIT으로 (숫자가 아니면 0)."""
    try:
        return int(float(v) * HWPUNIT_PER_MM) if v is not None and float(v) > 0 else 0
    except (TypeError, ValueError):
        return 0


def _span(tc) -> tuple[int, int, int, int]:
    """칸의 (행, 열, 행 수, 열 수) — 0부터."""
    addr, span = tc.find(CELLADDR), tc.find(CELLSPAN)
    return (int(addr.get("rowAddr", "0")), int(addr.get("colAddr", "0")),
            int(span.get("rowSpan", "1")) if span is not None else 1,
            int(span.get("colSpan", "1")) if span is not None else 1)


def _grid(tbl) -> dict:
    """(행, 열) → 그 자리를 차지한 칸 (합쳐진 칸은 여러 자리에 나온다)."""
    grid = {}
    for tr in tbl.iterfind(TR):
        for tc in tr.iterfind(TC):
            if tc.find(CELLADDR) is None:
                continue
            r, c, rs, cs = _span(tc)
            for i in range(rs):
                for j in range(cs):
                    grid[(r + i, c + j)] = tc
    return grid


def _table_spec(v) -> dict | None:
    """{columns, rows}가 제대로 든 표 요청만."""
    if not isinstance(v, dict) or not isinstance(v.get("columns"), list) or not v["columns"]:
        return None
    rows = v.get("rows") if isinstance(v.get("rows"), list) else []
    return {"columns": [str(c) for c in v["columns"]], "rows": [r if isinstance(r, list) else [r] for r in rows]}


INSERT_OBJECTS = ("table", "equation", "image", "textbox", "chart")   # inserts로 넣는 개체

STYLE_KEYS = ("color", "background", "size", "bold", "italic", "underline", "strike", "superscript", "subscript",
              "spacing", "ratio", "font")
PARA_KEYS = ("align", "line_spacing", "space_before", "space_after", "left_margin", "right_margin", "indent",
             "keep_with_next")


@dataclass
class EditPlan:
    """AI가 돌려준 변경 목록 (없는 번호는 걸러 내고 dropped에 모은다)."""
    lines: dict = field(default_factory=dict)        # S·E번호 → 줄 글자 ("" = 줄 지우기)
    tables: dict = field(default_factory=dict)       # T번호 → [[칸, …], …]
    inserts: list = field(default_factory=list)
    styles: list = field(default_factory=list)
    deletes: list = field(default_factory=list)
    moves: list = field(default_factory=list)
    replace_all: list = field(default_factory=list)
    unwraps: list = field(default_factory=list)
    new_sections: list = field(default_factory=list)
    page: dict = field(default_factory=dict)         # 용지 여백·방향·다단·쪽 번호·머리말·꼬리말
    merges: list = field(default_factory=list)       # 칸 합치기
    splits: list = field(default_factory=list)       # 합친 칸 나누기
    footnotes: list = field(default_factory=list)
    dropped: list = field(default_factory=list)      # 문서에 없는 번호

    @classmethod
    def from_ai(cls, data: dict, outline: Outline) -> "EditPlan":
        def as_list(k):
            v = data.get(k) or []
            return v if isinstance(v, list) else [v]

        def as_dict(k):
            v = data.get(k) or {}
            return v if isinstance(v, dict) else {}

        plan = cls()
        for k, v in as_dict("slots").items():
            (plan.lines.__setitem__(k, v) if k in outline.lines else plan.dropped.append(k))
        for k, v in as_dict("tables").items():
            (plan.tables.__setitem__(k, v) if k in outline.tables else plan.dropped.append(k))
        for d in as_list("deletes"):
            ref = str(d).strip()
            (plan.deletes.append(ref) if outline.has(ref) else plan.dropped.append(ref))
        for u in as_list("unwraps"):
            ref = str(u).strip()
            (plan.unwraps.append(ref) if ref in outline.boxes or ref in outline.tables else plan.dropped.append(ref))
        plan.inserts = [i for i in as_list("inserts") if isinstance(i, dict)]
        plan.styles = [s for s in as_list("styles") if isinstance(s, dict)]
        plan.moves = [m for m in as_list("moves") if isinstance(m, dict)]
        plan.replace_all = [r for r in as_list("replace_all") if isinstance(r, dict)]
        plan.new_sections = [s for s in as_list("new_sections") if isinstance(s, dict)]
        plan.page = as_dict("page")
        plan.merges = [m for m in as_list("merges") if isinstance(m, dict)]
        plan.splits = as_list("splits")
        plan.footnotes = [f for f in as_list("footnotes") if isinstance(f, dict)]
        return plan

    def is_empty(self) -> bool:
        return not any((self.lines, self.tables, self.inserts, self.styles, self.deletes, self.moves,
                        self.replace_all, self.unwraps, self.new_sections, self.page, self.merges, self.splits,
                        self.footnotes))


@dataclass
class ApplyReport:
    lines: int = 0
    tables: int = 0
    inserted: int = 0
    styled: int = 0
    deleted: int = 0
    moved: int = 0
    replaced: int = 0
    unwrapped: int = 0
    sections: int = 0
    page: int = 0
    merged: int = 0
    footnotes: int = 0
    missed: list = field(default_factory=list)       # 반영하지 못한 것 (사용자 안내용)

    @property
    def changed(self) -> int:
        return (self.lines + self.tables + self.inserted + self.styled + self.deleted + self.moved
                + self.replaced + self.unwrapped + self.sections + self.page + self.merged + self.footnotes)


class Editor:
    def __init__(self, doc: HwpxDocument, outline: Outline, images: dict | None = None):
        self.doc = doc
        self.outline = outline
        self.images = images or {}              # 사용자가 붙인 그림 파일: 이름 → 경로 (inserts의 image)
        self._applied: dict[str, object] = {}   # 이미 반영한 줄·표 (같은 값을 두 번 넣지 않게)
        self._extra: dict[str, list] = {}       # 줄 값의 줄바꿈으로 이어 붙인 줄들
        self._protos_cache = None

    # ── 줄·표 채우기 ────────────────────────────────────────────────────
    def type_line(self, lid: str, partial: str) -> list:
        """받는 중인 글자를 줄에 임시로 보여준다 (줄바꿈은 공백으로). 바뀐 줄 목록."""
        p = self.outline.lines.get(lid)
        if p is None or p.getparent() is None or lid in self._applied:
            return []
        set_para_text(p, str(partial).replace("\n", "  "))
        return [p]

    def fill_line(self, lid: str, value) -> list:
        """줄 글자를 value로 바꾼다. 여러 줄이면 같은 모양의 줄을 뒤에 이어 붙이고, ""면 줄을 지운다.
        새로 생기거나 바뀐 줄 목록을 돌려준다."""
        p = self.outline.lines.get(lid)
        if p is None or value is None or self._applied.get(lid) == value or p.getparent() is None:
            return []
        self._applied[lid] = value
        # 같은 줄을 다른 값으로 다시 넣는 경우(받는 중 값 → 최종 값): 앞서 이어 붙인 줄을 먼저 걷어낸다
        for old in self._extra.pop(lid, []):
            if old.getparent() is not None:
                old.getparent().remove(old)
        lines = str(value).split("\n")
        set_para_text(p, lines[0])
        touched = [p]
        if len(lines) > 1:
            if not has_objects(p):
                new_ps = []
                for line in lines[1:]:
                    np_ = copy.deepcopy(p)
                    strip_lineseg(np_)
                    set_para_text(np_, line)
                    new_ps.append(np_)
            else:
                # 표·문서 설정이 붙은 줄은 통째로 복제하면 안 되므로 새 줄을 만들어 뒤에 붙인다
                new_ps = self._make_lines(p, lines[1:])
            anchor = p
            for np_ in new_ps:
                anchor.addnext(np_)
                anchor = np_
            touched += new_ps
            self._extra[lid] = new_ps
        drop_if_empty(p)
        return [x for x in touched if x.getparent() is not None]

    def fill_table(self, tid: str, rows) -> list:
        g = self.outline.tables.get(tid)
        if g is None or not isinstance(rows, list) or self._applied.get(tid) == rows:
            return []
        self._applied[tid] = rows
        self._fill_group(g, rows)
        return list(g.trs)

    def _fill_group(self, g: TableGroup, rows: list):
        rows = [r if isinstance(r, list) else [r] for r in rows] or [[""] * g.ncols]
        m = len(g.trs)
        tbl = g.tbl
        anchor_idx = list(tbl).index(g.trs[0])
        new_trs = []
        for i, row in enumerate(rows):
            if i == len(rows) - 1:
                proto = g.trs[-1]
            elif i < m - 1:
                proto = g.trs[i]
            else:
                proto = g.trs[-2] if m >= 2 else g.trs[0]
            tr = copy.deepcopy(proto)
            strip_lineseg(tr)
            for j, tc in enumerate(tr.findall(TC)):
                set_cell(tc, row[j] if j < len(row) else "")
            new_trs.append(tr)
        for tr in g.trs:
            tbl.remove(tr)
        for k, tr in enumerate(new_trs):
            tbl.insert(anchor_idx + k, tr)
        g.trs = new_trs
        renumber_table(tbl)
        mark_changed(top_para(tbl))   # 표 높이가 바뀌었다

    # ── 한 번에 반영 ────────────────────────────────────────────────────
    def apply(self, plan: EditPlan) -> ApplyReport:
        rep = ApplyReport()
        if plan.dropped:
            rep.missed.append(f"없는 번호 {', '.join(map(str, plan.dropped[:5]))}")
        sequential = self._headings_sequential()
        hs = self._all_headings()
        start = cell_text(hs[0][1][1]).strip() if hs else None
        # 실시간 화면에서 이미 넣은 줄·표는 다시 넣지 않고 센다
        for lid, v in plan.lines.items():
            self.fill_line(lid, v)
            rep.lines += self._applied.get(lid) == v
        for tid, rows in plan.tables.items():
            self.fill_table(tid, rows)
            rep.tables += self._applied.get(tid) == rows
        if plan.page:   # 용지를 먼저 바꿔야 새로 넣는 표·그림이 바뀐 본문 폭에 맞는다
            old_width = self.doc.text_width()
            missed = self.doc.set_page(plan.page)
            rep.page = int(len(missed) < len(plan.page))
            rep.missed += missed
            self._refit(old_width, self.doc.text_width())
        rep.replaced = self.replace_everywhere(plan.replace_all)
        rep.inserted = self.insert_lines(plan.inserts)
        rep.styled = self.apply_styles(plan.styles)
        rep.moved = self.move_blocks(plan.moves)
        rep.unwrapped = self.unwrap_tables(plan.unwraps)
        rep.deleted = self.delete_blocks(plan.deletes)
        rep.sections = self.insert_sections(plan.new_sections)
        rep.footnotes = self.add_footnotes(plan.footnotes)
        rep.merged = self.merge_cells(plan.merges) + self.split_cells(plan.splits)
        if (rep.sections or rep.deleted or rep.moved) and sequential and self._all_headings():
            self._renumber_headings(start)

        want_lines = sum(len(as_lines(i.get("lines"))) + sum(i.get(k) is not None for k in INSERT_OBJECTS)
                         for i in plan.inserts)
        for have, want, what in ((rep.inserted, want_lines, "끼워 넣을 줄"), (rep.styled, len(plan.styles), "모양 바꾸기"),
                                 (rep.sections, len(plan.new_sections), "새 장"), (rep.moved, len(plan.moves), "옮기기"),
                                 (rep.deleted, len(plan.deletes), "지우기"), (rep.unwrapped, len(plan.unwraps), "표 틀 없애기"),
                                 (rep.footnotes, len(plan.footnotes), "각주"),
                                 (rep.merged, len(plan.merges) + len(plan.splits), "칸 합치기·나누기")):
            if have < want:
                rep.missed.append(f"{what} {want - have}건")
        if plan.replace_all and not rep.replaced:
            rep.missed.append("찾아 바꿀 글자")
        return rep

    def _refit(self, old: int, new: int):
        """본문 폭이 바뀌면(용지 방향·여백·다단) 본문의 표·그림·글상자 폭을 같은 비율로 맞춘다.
        표지처럼 자리를 따로 정해 둔(글자처럼 취급하지 않는) 개체는 건드리지 않는다."""
        if not old or not new or abs(new - old) < 300:
            return
        from .objects import resize_picture
        ratio = new / old
        for p in self.doc.top_paragraphs():
            for obj in [c for run in p.iterfind(RUN) for c in run if c.tag != T and c.find(SZ) is not None]:
                pos = obj.find(hp("pos"))
                width = int(obj.find(SZ).get("width", "0") or 0)
                if pos is None or pos.get("treatAsChar") != "1" or not width:
                    continue
                if obj.tag == TBL:
                    for tbl in obj.iter(TBL):   # 표 안의 표도 같은 비율로
                        for el in [tbl.find(SZ), *(tc.find(CELLSZ) for tr in tbl.iterfind(TR) for tc in tr.iterfind(TC))]:
                            if el is not None:
                                el.set("width", str(int(int(el.get("width", "0") or 0) * ratio)))
                    strip_lineseg(obj)
                elif ratio < 1 and width > new:   # 그림·글상자는 넘칠 때만 줄인다
                    # 글상자는 폭만, 그림은 가로세로 비율을 지켜 줄인다
                    is_box = obj.find(f".//{SUBLIST}") is not None
                    resize_picture(obj, new, int(obj.find(SZ).get("height", "0") or 0) if is_box else None)
                else:
                    continue
                mark_changed(p)

    # ── 표 틀만 없애기 / 테두리 ─────────────────────────────────────────
    def _table_of(self, ref: str):
        ref = str(ref).strip()
        if ref in self.outline.boxes:
            return self.outline.boxes[ref]
        return self.outline.tables[ref].tbl if ref in self.outline.tables else None

    def unwrap_tables(self, refs: list) -> int:
        """표 틀을 없애고 칸 안의 글(문단)은 표가 있던 자리에 차례로 남긴다."""
        n = 0
        for ref in refs:
            tbl = self._table_of(ref)
            run = tbl.getparent() if tbl is not None else None
            p = run.getparent() if run is not None else None
            if p is None or p.getparent() is None:
                continue
            paras = []
            for tr in tbl.iterfind(TR):
                cells = []
                for tc in tr.iterfind(TC):
                    sl = tc.find(SUBLIST)
                    cells.append([cp for cp in (sl.iterfind(P) if sl is not None else [])
                                  if para_text(cp).strip() or has_objects(cp)])
                filled = [c for c in cells if c]
                if len(filled) >= 2 and all(len(c) == 1 and not has_objects(c[0]) for c in filled):
                    # 한 줄짜리 칸들은 한 줄로: 2칸이면 "항목: 내용", 그 이상이면 " / "로 잇는다
                    texts = [para_text(c[0]).strip() for c in filled]
                    line = f"{texts[0]}: {texts[1]}" if len(texts) == 2 else " / ".join(texts)
                    np_ = copy.deepcopy(filled[-1][0])
                    set_para_text(np_, line)
                    paras.append(np_)
                    continue
                for c in filled:
                    paras.extend(copy.deepcopy(cp) for cp in c)
            anchor = p
            for np_ in paras:
                strip_lineseg(np_)
                np_.set("id", "0")
                anchor.addnext(np_)
                anchor = np_
            run.remove(tbl)
            drop_if_empty(p)
            n += 1
        return n

    def set_table_border(self, ref: str, on: bool) -> bool:
        tbl = self._table_of(ref)
        if tbl is None:
            return False
        if tbl.get("borderFillIDRef"):
            tbl.set("borderFillIDRef", self.doc.borderfill_variant(tbl.get("borderFillIDRef"), on))
        for tr in tbl.iterfind(TR):
            for tc in tr.iterfind(TC):
                tc.set("borderFillIDRef", self.doc.borderfill_variant(tc.get("borderFillIDRef", "1"), on))
        return True

    def _cells_of(self, ref: str) -> list:
        """S번호 → 그 줄이 든 칸 하나, T번호 → 그 행들의 칸, B번호 → 표의 모든 칸."""
        o = self.outline
        if ref in o.lines:
            sl = o.lines[ref].getparent()
            tc = sl.getparent() if sl is not None and sl.tag == SUBLIST else None
            return [tc] if tc is not None and tc.tag == TC else []   # 글상자 안의 줄은 표 칸이 아니다
        if ref in o.tables:
            return [tc for tr in o.tables[ref].trs for tc in tr.iterfind(TC)]
        if ref in o.boxes:
            return [tc for tr in o.boxes[ref].iterfind(TR) for tc in tr.iterfind(TC)]
        return []

    def set_cell_background(self, ref: str, color) -> bool:
        cells = self._cells_of(ref)
        for tc in cells:
            tc.set("borderFillIDRef", self.doc.cellfill_variant(tc.get("borderFillIDRef", "1"), color))
        return bool(cells)

    def set_col_widths(self, ref: str, widths) -> bool:
        """표의 열 너비를 비율(예: [20, 50, 30])대로 다시 나눈다. 표 전체 폭은 그대로."""
        tbl = self._table_of(ref)
        try:
            ws = [float(w) for w in widths]
        except (TypeError, ValueError):
            return False
        if tbl is None or not ws or min(ws) <= 0 or len(ws) != int(tbl.get("colCnt", "0") or 0):
            return False
        sz = tbl.find(SZ)
        total = int(sz.get("width")) if sz is not None else 0
        if not total:   # 표 폭이 없으면 칸 합치기가 없는 첫 행의 폭을 더한다
            total = sum(int(tc.find(CELLSZ).get("width")) for tc in tbl.find(TR).iterfind(TC))
        cols = [int(total * w / sum(ws)) for w in ws]
        cols[-1] += total - sum(cols)
        for tr in tbl.iterfind(TR):
            for tc in tr.iterfind(TC):
                addr, span, csz = tc.find(CELLADDR), tc.find(CELLSPAN), tc.find(CELLSZ)
                if addr is None or csz is None:
                    continue
                c = int(addr.get("colAddr", "0"))
                n = int(span.get("colSpan", "1")) if span is not None else 1
                csz.set("width", str(sum(cols[c:c + n])))
        strip_lineseg(tbl)
        mark_changed(top_para(tbl))
        return True

    def set_row_height(self, ref: str, mm) -> bool:
        """칸 높이(mm): S번호면 그 칸이 든 행, T번호면 그 행들, B번호면 표의 모든 행."""
        try:
            h = int(float(mm) * HWPUNIT_PER_MM)
        except (TypeError, ValueError):
            return False
        cells = self._cells_of(ref)
        if not cells or not 0 < h < 80000:
            return False
        for tr in {tc.getparent() for tc in cells}:
            for tc in tr.iterfind(TC):
                span, csz = tc.find(CELLSPAN), tc.find(CELLSZ)
                if csz is not None and (span is None or span.get("rowSpan", "1") == "1"):
                    csz.set("height", str(h))
        mark_changed(top_para(cells[0]))
        return True

    # ── 문서 전체 찾아 바꾸기 ────────────────────────────────────────────
    def replace_everywhere(self, pairs: list) -> int:
        """같은 글자를 문서 전체에서 바꾼다. 글자 모양 조각에 걸쳐 있어도 줄 단위로 찾는다."""
        n = 0
        for pr in pairs:
            find, repl = str(pr.get("find", "")), str(pr.get("replace", ""))
            if not find:
                continue
            for root in self.doc.ordered_sections():
                for p in root.iter(P):
                    ts = list(p.iterfind(TEXT_PATH))
                    if any(find in t_text(t) for t in ts):
                        for t in ts:
                            s = t_text(t)
                            if find in s:
                                set_t(t, s.replace(find, repl))
                                n += 1
                    elif find in para_text(p):
                        set_para_text(p, para_text(p).replace(find, repl))
                        n += 1
        return n

    # ── 장·표·그림·줄 통째로 지우기 / 옮기기 ─────────────────────────────
    @staticmethod
    def _is_ending(p) -> bool:
        s = para_text(p).strip()
        return s.startswith("붙임") or s.endswith("끝.")

    def _section_block(self, head_p) -> list:
        """장 제목 문단부터 다음 장 제목 앞까지('붙임 … 끝.' 줄은 뺌)."""
        heads = set(self.outline.headings.values())
        block, cur = [head_p], head_p.getnext()
        while cur is not None and cur not in heads and not (cur.tag == P and self._is_ending(cur)):
            block.append(cur)
            cur = cur.getnext()
        return block

    def _block(self, ref: str) -> list:
        """옮길 덩어리: H는 장 전체, S·T·I·B는 그것이 든 본문 문단 하나."""
        ref = str(ref).strip()
        o = self.outline
        if ref in o.headings:
            return self._section_block(o.headings[ref])
        # lxml 요소는 자식이 없으면 거짓이므로 'a or b'로 고르지 않는다
        el = next((m[ref] for m in (o.lines, o.images, o.boxes) if ref in m), None)
        if ref in o.tables:
            el = o.tables[ref].tbl
        p = top_para(el) if el is not None else None
        return [p] if p is not None and p.getparent() is not None else []

    def move_blocks(self, moves: list) -> int:
        """{"block": "H3", "after": "H5"} / {"block": "S12", "before": "S4"} 처럼 장이나 줄을 옮긴다."""
        n = 0
        for mv in moves:
            blk = [e for e in self._block(mv.get("block", "")) if not has_secpr(e)]
            after = "after" in mv
            ref = mv.get("after") if after else mv.get("before")
            if not blk or not ref:
                continue
            ref_blk = self._block(ref)
            if not ref_blk or any(e is r for e in blk for r in ref_blk):
                continue
            for e in blk:
                e.getparent().remove(e)
            tgt = self._block(ref)
            if not tgt:
                continue
            if after:
                anchor = tgt[-1]
                for e in blk:
                    anchor.addnext(e)
                    anchor = e
            else:
                for e in blk:
                    tgt[0].addprevious(e)
            n += 1
        return n

    def delete_blocks(self, refs: list) -> int:
        """H는 장 전체('붙임 … 끝.' 줄은 남김), T·B는 표 전체, I는 그림, S·E는 그 줄을 지운다."""
        removed = 0
        o = self.outline
        for ref in refs:
            ref = str(ref).strip()
            if ref in o.headings:
                p = o.headings[ref]
                if p.getparent() is None:
                    continue
                for v in self._section_block(p):
                    if not has_secpr(v) and v.getparent() is not None:
                        v.getparent().remove(v)
                removed += 1
            elif ref in o.tables or ref in o.images or ref in o.boxes:
                obj = (o.tables[ref].tbl if ref in o.tables else
                       o.images[ref] if ref in o.images else o.boxes[ref])
                run = obj.getparent()
                if run is None:
                    continue
                run.remove(obj)
                p = run.getparent()
                if p is not None:
                    drop_if_empty(p)
                removed += 1
            elif ref in o.lines:
                p = o.lines[ref]
                if p.getparent() is None:
                    continue
                set_para_text(p, "")
                # 표·설정이 붙은 줄은 글자만 지우고, 표 칸의 마지막 줄은 칸이 깨지지 않게 남긴다
                drop_if_empty(p)
                removed += 1
        return removed

    # ── 글자·문단 모양 ──────────────────────────────────────────────────
    def apply_style(self, t, style: dict, part: str | None = None) -> bool:
        """글자 조각(t) 전체, 또는 그 안의 일부 글자(part)에 글자 모양을 적용한다."""
        run = t.getparent()
        mark_changed(run.getparent())    # 글자 크기 등이 바뀌면 줄 배치가 달라진다
        base = run.get("charPrIDRef", "0")
        new_id = self.doc.charpr_variant(base, style)
        text = t_text(t)
        simple = len(run) == 1 and run[0] is t
        if part and part in text and part != text and simple:
            i = text.index(part)
            pieces = [(text[:i], base), (part, new_id), (text[i + len(part):], base)]
            anchor, first = run, True
            for s, cid in pieces:
                if not s:
                    continue
                if first:
                    run.set("charPrIDRef", cid)
                    set_t(t, s)
                    first = False
                    continue
                nr = copy.deepcopy(run)
                nr.set("charPrIDRef", cid)
                set_t(nr.find(T), s)
                anchor.addnext(nr)
                anchor = nr
            return True
        run.set("charPrIDRef", new_id)
        return True

    def apply_styles(self, styles: list) -> int:
        n = 0
        o = self.outline
        for st in styles:
            target = str(st.get("target", "")).strip()
            if "border" in st and self._table_of(target) is not None:
                n += self.set_table_border(target, bool(st["border"]))
                continue
            done = False
            if target in o.images and ("width" in st or "height" in st):   # 그림 크기 (mm)
                from .objects import resize_picture
                pic = o.images[target]   # 그림 하나(hp:pic) 또는 여러 개를 묶은 틀(hp:container)
                if resize_picture(pic, _mm(st.get("width")), _mm(st.get("height"))):
                    mark_changed(top_para(pic))
                    done = True
            if "cell_background" in st:
                done = self.set_cell_background(target, st["cell_background"]) or done
            if "col_widths" in st:
                done = self.set_col_widths(target, st["col_widths"]) or done
            if "row_height" in st:
                done = self.set_row_height(target, st["row_height"]) or done
            ts, ps = [], []
            if target in o.lines:
                p = o.lines[target]
                ps = [p]
                ts = [t for t in p.iterfind(TEXT_PATH) if t_text(t)]
                part = st.get("part")
                if part:
                    # 일부 글자만: 그 글자가 든 조각만
                    ts = [t for t in ts if part in t_text(t)] or ts
            elif target in o.headings:
                hp_ = heading_parts(o.headings[target])
                ts = list(hp_[2].iter(T)) if hp_ else []
                ps = [o.headings[target]]
            elif target.lower() in ("all", "전체"):
                # 문서 전체 (표 칸 안의 줄 포함): 글꼴·줄 간격을 한꺼번에 바꿀 때
                ps = [p for root in self.doc.ordered_sections() for p in root.iter(P)]
            elif target in o.tables or target in o.boxes:
                # 표: 그 표(T는 그 행들) 칸 안의 모든 줄
                ps = [p for tc in self._cells_of(target) for p in tc.iter(P)]
            if not ts:
                ts = [t for p in ps for t in p.iterfind(TEXT_PATH) if t_text(t)]
            style = {k: st[k] for k in STYLE_KEYS if k in st}
            para = {k: st[k] for k in PARA_KEYS if k in st}
            if style:
                for t in ts:
                    if t.getparent() is not None and self.apply_style(t, style, st.get("part")):
                        done = True
            for p in ps:
                if para and p.getparent() is not None:
                    mark_changed(p)
                    p.set("paraPrIDRef", self.doc.parapr_variant(p.get("paraPrIDRef", "0"), para))
                    done = True
                if "page_break" in st:
                    top = top_para(p)
                    if top is not None:
                        top.set("pageBreak", "1" if st["page_break"] else "0")
                        done = True
            n += int(done)
        return n

    # ── 줄 끼워 넣기 ────────────────────────────────────────────────────
    def _anchor_para(self, ref: str, in_cell: bool = False):
        o = self.outline
        if ref in o.headings:
            return o.headings[ref]
        # 표(T·B)나 그림(I)을 기준으로 삼으면 그 표·그림이 든 문단의 앞·뒤
        obj = o.tables[ref].tbl if ref in o.tables else o.boxes.get(ref, o.images.get(ref))
        if obj is not None:
            holder = obj.getparent().getparent() if obj.getparent() is not None else None
            if holder is None or holder.getparent() is None:
                return None
            return holder if in_cell and holder.getparent().tag == SUBLIST else top_para(holder)
        p = o.lines.get(ref)
        if p is None or p.getparent() is None:
            return None
        if in_cell and p.getparent().tag == SUBLIST:
            return p   # 표 칸 안의 줄: 그 칸 안에 넣는다
        # 그 밖에는 그 표를 담은 본문 문단(섹션 바로 아래 문단)을 기준으로 삼는다
        return top_para(p)

    def _table_proto(self, like=None):
        """새 표의 본보기: 본문의 단순한 표 → 문서 어디든(표 안 포함) 단순한 표 → 장 제목이 아닌 아무 표
        → 표가 하나도 없는 문서(공문 등)는 실선 테두리의 기본 표 (글자 모양은 like 줄을 따름)."""
        proto = self._protos().get("table")
        if proto is not None:
            return proto
        simple, other = None, None
        for tbl in (t for root in self.doc.ordered_sections() for t in root.iter(TBL)):
            p = tbl.getparent().getparent() if tbl.getparent() is not None else None
            if p is None or p.tag != P or heading_parts(p) is not None:
                continue
            if simple is None and is_simple_table_para(p):
                simple = p
            if other is None and tbl.find(f".//{TR}//{TBL}") is None:
                other = p
        if simple is not None or other is not None:
            return simple if simple is not None else other
        run = like.find(RUN) if like is not None else None
        return plain_table_paragraph(self.doc.borderfill_variant("", True), self.doc.text_width(),
                                     run.get("charPrIDRef", "0") if run is not None else "0")

    def _new_table(self, spec, anchor):
        """inserts의 table({columns, rows})로 새 표 문단을 만든다. 칸 안이면 그 칸 폭에 맞춘다."""
        spec = _table_spec(spec)
        if spec is None:
            return None
        cols = spec["columns"]
        proto = self._table_proto(anchor)
        width = None
        sl = anchor.getparent()
        if sl is not None and sl.tag == SUBLIST:
            sz = sl.getparent().find(CELLSZ)
            if sz is not None:
                width = max(int(sz.get("width", "0")) - 1200, 2000)   # 칸 안쪽 여백만큼 줄임
        return build_table_paragraph(proto, cols, spec["rows"], width)

    @staticmethod
    def _plain_line(base, text: str):
        """복제할 줄 모양이 없을 때: 기준 문단에서 표·설정 정보를 뺀 '바탕글' 줄을 만든다."""
        p = copy.deepcopy(base)
        runs = p.findall(RUN)
        for r in runs[1:]:
            p.remove(r)
        for c in list(p):
            if c.tag != RUN:
                p.remove(c)
        run = runs[0] if runs else etree.SubElement(p, RUN)
        for c in list(run):
            run.remove(c)
        run.set("charPrIDRef", "0")
        p.set("paraPrIDRef", "0")
        p.set("styleIDRef", "0")
        for attr in ("pageBreak", "columnBreak"):
            if p.get(attr) is not None:
                p.set(attr, "0")
        t = etree.SubElement(run, T)
        t.text = text.strip()
        return p

    def _make_lines(self, anchor, lines: list, before: bool = False) -> list:
        protos = self._protos()
        fallback = next((protos[k] for k in ("num", "bullet", "box", "dash", "text") if k in protos), None)
        # 기호 없는 줄은 바로 옆 본문 줄의 모양·들여쓰기를 따른다
        neighbor = anchor if (before or heading_parts(anchor) is None) else anchor.getnext()
        if neighbor is not None and (neighbor.tag != P or has_objects(neighbor) or not para_text(neighbor).strip()):
            neighbor = None
        # 표 칸 안: 본문 줄 모양(폭·들여쓰기)을 가져오면 칸을 벗어나므로 그 칸의 줄 모양을 따른다
        in_cell = anchor.getparent() is not None and anchor.getparent().tag == SUBLIST
        out = []
        for line in lines:
            line = str(line)
            kind = marker_of(line)
            proto = protos.get(kind) if kind != "text" and not in_cell else None
            if proto is None:
                proto = neighbor if neighbor is not None else protos.get("text", fallback)
            out.append(clone_line(proto, line) if proto is not None else self._plain_line(anchor, line))
        return out

    def insert_lines(self, inserts: list) -> int:
        n = 0
        for ins in inserts:
            lines = as_lines(ins.get("lines"))
            if not lines and not any(ins.get(k) is not None for k in INSERT_OBJECTS):
                continue
            before = ins.get("before")
            anchor = self._anchor_para(str(before or ins.get("after", "")).strip(), in_cell=True)
            if anchor is None:
                continue
            new_ps = self._make_lines(anchor, lines, bool(before))
            for kind in INSERT_OBJECTS:
                if ins.get(kind) is not None:
                    try:
                        obj = self._new_object(kind, ins, anchor)
                    except Exception:
                        obj = None   # 그림 파일을 못 읽는 등: '반영하지 못함'으로 알린다
                    if obj is not None:
                        new_ps.append(obj)
            if before:
                for np_ in new_ps:
                    anchor.addprevious(np_)
            else:
                cur = anchor
                for np_ in new_ps:
                    cur.addnext(np_)
                    cur = np_
            n += len(new_ps)
        return n

    def _width_at(self, anchor) -> int:
        """anchor 자리에 넣을 개체가 쓸 수 있는 폭: 표 칸 안이면 칸 폭, 아니면 본문 폭."""
        sl = anchor.getparent()
        if sl is not None and sl.tag == SUBLIST and sl.getparent().find(CELLSZ) is not None:
            return max(int(sl.getparent().find(CELLSZ).get("width", "0")) - 1200, 2000)
        return self.doc.text_width()

    def _new_object(self, kind: str, ins: dict, anchor):
        """inserts의 table·equation·image·textbox·chart 하나를 문단으로 만든다. 못 만들면 None."""
        from . import objects as ob
        spec = ins[kind]
        if kind == "table":
            return self._new_table(spec, anchor)
        room = self._width_at(anchor)
        run = anchor.find(RUN)
        char_id = run.get("charPrIDRef", "0") if run is not None else "0"
        if kind == "equation":
            return ob.equation_paragraph(spec, char_id=char_id) if str(spec).strip() else None
        if kind == "textbox":
            box = spec if isinstance(spec, dict) else {"lines": spec}
            lines = as_lines(box.get("lines"))
            if not lines:
                return None
            return ob.textbox_paragraph(lines, min(_mm(box.get("width")) or room, room), char_id=char_id,
                                        fill=hex_color(box["background"]) if box.get("background") else "#FFFFFF",
                                        border=box.get("border", True) is not False)
        if kind == "chart":
            from .chart import parse_chart, render_chart
            chart = parse_chart(spec)
            if chart is None:
                return None
            data, ext, size, name = render_chart(chart), "png", (1200, 720), chart["title"] or "차트"
        else:   # image: 사용자가 붙인 그림 파일만 (이름으로 찾는다)
            path = self._find_image(spec.get("file") if isinstance(spec, dict) else spec)
            if path is None:
                return None
            from PIL import Image
            with open(path, "rb") as f:
                data = f.read()
            with Image.open(io.BytesIO(data)) as im:
                size = im.size
            ext, name = os.path.splitext(path)[1], os.path.basename(path)
        want = _mm(ins.get("width")) or (_mm(spec.get("width")) if isinstance(spec, dict) else 0)
        # 크기를 말하지 않으면: 차트는 본문 폭의 60%, 그림은 원래 크기(1픽셀 = 75, 96dpi) — 본문 폭을 넘지 않게
        w = min(want or (int(room * 0.6) if kind == "chart" else size[0] * 75), room)
        return ob.picture_paragraph(self.doc.add_image(data, ext), w, int(w * size[1] / size[0]), name=name)

    def _find_image(self, name) -> str | None:
        name = os.path.splitext(str(name or "").strip().lower())[0]
        for key, path in self.images.items():
            if name and os.path.splitext(key.lower())[0] == name:
                return path
        return next(iter(self.images.values())) if len(self.images) == 1 else None

    # ── 각주 ────────────────────────────────────────────────────────────
    def add_footnotes(self, notes: list) -> int:
        """{"target": "S12", "text": "각주 글", "part": "이 글자 뒤(없으면 줄 끝)"}"""
        from . import objects as ob
        n = 0
        for note in notes:
            p = self.outline.lines.get(str(note.get("target", "")).strip())
            text = str(note.get("text", "")).strip()
            if p is None or p.getparent() is None or not text:
                continue
            ts = [t for t in p.iterfind(TEXT_PATH) if t_text(t)]
            part = str(note.get("part") or "")
            t = next((t for t in ts if part and part in t_text(t)), ts[-1] if ts else None)
            if t is None:
                continue
            ctrl = ob.footnote_ctrl(text, self.doc.style_ids("각주"))
            whole = t_text(t)
            cut = whole.index(part) + len(part) if part and part in whole else len(whole)
            set_t(t, whole[:cut])
            t.addnext(ctrl)
            if whole[cut:]:   # 각주 뒤에 남은 글자
                rest = etree.Element(T)
                rest.text = whole[cut:]
                ctrl.addnext(rest)
            mark_changed(top_para(p))
            n += 1
        if n:
            ob.renumber_footnotes(self.doc.ordered_sections())
        return n

    # ── 칸 합치기 / 나누기 ───────────────────────────────────────────────
    def _cell_at(self, ref):
        """칸을 가리키는 말 → (표, 칸). S번호(그 줄이 든 칸) 또는 {"table": "B3", "cell": [행, 열]} (1부터)."""
        if isinstance(ref, dict):
            tbl = self._table_of(ref.get("table", ""))
            pos = ref.get("cell")
            if tbl is None or not isinstance(pos, (list, tuple)) or len(pos) != 2:
                return None, None
            try:
                r, c = int(pos[0]) - 1, int(pos[1]) - 1
            except (TypeError, ValueError):
                return None, None
            return tbl, _grid(tbl).get((r, c))
        cells = self._cells_of(str(ref).strip()) if str(ref).strip() in self.outline.lines else []
        return (cells[0].getparent().getparent(), cells[0]) if cells else (None, None)

    def merge_cells(self, merges: list) -> int:
        """{"from": "S12", "to": "S15"} 또는 {"table": "B3", "from": [1, 1], "to": [2, 3]} — 두 칸을 모서리로 하는
        네모 범위를 한 칸으로 합친다. 글은 왼쪽 위 칸에 차례로 모은다."""
        n = 0
        for m in merges:
            def ref(v):
                return {"table": m.get("table"), "cell": v} if isinstance(v, (list, tuple)) else v
            tbl, a = self._cell_at(ref(m.get("from")))
            tbl2, b = self._cell_at(ref(m.get("to")))
            if a is None or b is None or tbl is not tbl2 or a is b:
                continue
            (r1, c1, rs1, cs1), (r2, c2, rs2, cs2) = _span(a), _span(b)
            top, left = min(r1, r2), min(c1, c2)
            bottom, right = max(r1 + rs1, r2 + rs2), max(c1 + cs1, c2 + cs2)
            grid = _grid(tbl)
            cells = {id(tc): tc for (r, c), tc in grid.items() if top <= r < bottom and left <= c < right}
            spans = {k: _span(tc) for k, tc in cells.items()}
            # 범위 밖으로 걸친 칸이 있거나, 한 행이 통째로 사라지면 합치지 않는다
            if any(r < top or c < left or r + rs > bottom or c + cs > right for r, c, rs, cs in spans.values()):
                continue
            if right - left == int(tbl.get("colCnt", "0") or 0) and bottom - top > 1:
                continue
            first = grid[(top, left)]
            width = sum(int(tc.find(CELLSZ).get("width")) for k, tc in cells.items() if spans[k][0] == top)
            height = sum(int(tc.find(CELLSZ).get("height")) for k, tc in cells.items() if spans[k][1] == left)
            sl = first.find(SUBLIST)
            for k, tc in sorted(cells.items(), key=lambda kv: spans[kv[0]][:2]):
                if tc is first:
                    continue
                for p in list(tc.find(SUBLIST).iterfind(P)) if tc.find(SUBLIST) is not None else []:
                    if para_text(p).strip() or has_objects(p):
                        if len(sl.findall(P)) == 1 and is_blank(sl.find(P)):
                            sl.remove(sl.find(P))
                        sl.append(p)
                tc.getparent().remove(tc)
            first.find(CELLSPAN).set("rowSpan", str(bottom - top))
            first.find(CELLSPAN).set("colSpan", str(right - left))
            first.find(CELLSZ).set("width", str(width))
            first.find(CELLSZ).set("height", str(height))
            strip_lineseg(tbl)
            mark_changed(top_para(tbl))
            n += 1
        return n

    def split_cells(self, splits: list) -> int:
        """합쳐진 칸을 원래 격자대로 다시 나눈다. "S12" 또는 {"table": "B3", "cell": [1, 1]}"""
        n = 0
        for ref in splits:
            tbl, tc = self._cell_at(ref)
            if tc is None:
                continue
            r0, c0, rs, cs = _span(tc)
            if rs == 1 and cs == 1:
                continue
            grid = _grid(tbl)
            trs = tbl.findall(TR)

            def size(index, axis):
                """그 열의 폭(axis 0)·그 행의 높이(axis 1): 합쳐지지 않은 다른 칸에서 찾고, 없으면 고르게 나눈다."""
                for (r, c), other in grid.items():
                    sp = _span(other)
                    if other is not tc and axis == 0 and (c, sp[3]) == (index, 1):
                        return int(other.find(CELLSZ).get("width"))
                    if other is not tc and axis == 1 and (r, sp[2]) == (index, 1):
                        return int(other.find(CELLSZ).get("height"))
                whole = int(tc.find(CELLSZ).get("width" if axis == 0 else "height"))
                return whole // (cs if axis == 0 else rs)
            widths = [size(c0 + j, 0) for j in range(cs)]
            heights = [size(r0 + i, 1) for i in range(rs)]
            for i in range(rs):
                for j in range(cs):
                    if i == 0 and j == 0:
                        cell = tc
                    else:
                        cell = copy.deepcopy(tc)
                        strip_lineseg(cell)
                        sl = cell.find(SUBLIST)
                        for p in sl.findall(P)[1:]:
                            sl.remove(p)
                        set_cell(cell, "")
                        row = trs[r0 + i]
                        before = [t for t in row.findall(TC) if int(t.find(CELLADDR).get("colAddr")) < c0 + j]
                        before[-1].addnext(cell) if before else row.insert(0, cell)
                    cell.find(CELLADDR).set("rowAddr", str(r0 + i))
                    cell.find(CELLADDR).set("colAddr", str(c0 + j))
                    cell.find(CELLSPAN).set("rowSpan", "1")
                    cell.find(CELLSPAN).set("colSpan", "1")
                    cell.find(CELLSZ).set("width", str(widths[j]))
                    cell.find(CELLSZ).set("height", str(heights[i]))
            strip_lineseg(tbl)
            mark_changed(top_para(tbl))
            n += 1
        return n

    # ── 장 번호 ─────────────────────────────────────────────────────────
    def _all_headings(self):
        return [(p, hp_) for p in self.doc.top_paragraphs() if (hp_ := heading_parts(p)) is not None]

    def _headings_sequential(self) -> bool:
        nums = [cell_text(hp_[1]).strip() for _, hp_ in self._all_headings()]
        if not nums:
            return False
        if all(n.isdigit() for n in nums):
            start = int(nums[0])
            return nums == [str(start + i) for i in range(len(nums))]
        if all(n in ROMAN for n in nums):
            start = ROMAN.index(nums[0])
            return nums == list(ROMAN[start:start + len(nums)])
        return False

    def _renumber_headings(self, start: str | None = None):
        """장 번호를 처음 번호(start, 없으면 지금 첫 장의 번호)부터 차례로 다시 매긴다."""
        hs = self._all_headings()
        first = start or cell_text(hs[0][1][1]).strip()
        for i, (_, (tbl, num_cell, _)) in enumerate(hs):
            if first.isdigit():
                label = str(int(first) + i)
            else:
                k = ROMAN.index(first) + i
                label = ROMAN[k] if k < len(ROMAN) else str(k + 1)
            set_cell(num_cell, label)

    # ── 줄 모양 본보기 ──────────────────────────────────────────────────
    def _protos(self) -> dict:
        """본문(첫 장 제목 이후)에서 기호 종류별 줄 모양, 빈 줄, 표 모양을 찾는다.
        표지·목차의 '1.' 같은 줄을 잘못 가져오지 않도록 첫 장 제목 앞은 보지 않는다."""
        if self._protos_cache is not None:
            return self._protos_cache
        found = {}
        top = list(self.doc.top_paragraphs())
        seen_heading = not any(heading_parts(p) is not None for p in top)  # 장 제목이 없으면 처음부터
        tables = []
        for i, p in enumerate(top):
            if heading_parts(p) is not None:
                seen_heading = True
                if i > 0 and is_blank(top[i - 1]):
                    found.setdefault("blank", copy.deepcopy(top[i - 1]))
                continue
            if not seen_heading:
                continue
            if has_objects(p):
                if is_simple_table_para(p):
                    tables.append(p)
                continue
            s = para_text(p)
            if s.strip():
                found.setdefault(marker_of(s), copy.deepcopy(p))
        if tables:
            # 열이 많은(머리행이 있는) 표를 우선
            best = max(tables, key=lambda p: (min(int(p.find(f"{RUN}/{TBL}").get("colCnt")), 4),
                                              int(p.find(f"{RUN}/{TBL}").get("rowCnt"))))
            found["table"] = copy.deepcopy(best)
        self._protos_cache = found
        return found

    def body_markers(self) -> list[str]:
        """AI에게 알려줄, 이 문서 본문에서 쓰는 줄 기호 예시."""
        return [para_text(p).strip()[:12] for kind, p in self._protos().items()
                if kind not in ("blank", "table", "text")]

    # ── 새 장 넣기 ──────────────────────────────────────────────────────
    def insert_sections(self, new_sections: list) -> int:
        heads = self._all_headings()
        if not new_sections or not heads:
            return 0
        protos = self._protos()
        fallback = next((protos[k] for k in ("num", "bullet", "box", "dash", "text") if k in protos), None)
        added = 0
        for sec in new_sections:
            title = str(sec.get("title", "")).strip()
            if not title:
                continue
            after = self.outline.headings.get(str(sec.get("after", "")).strip())
            if after is None or after.getparent() is None:
                after = self._all_headings()[-1][0]
            root = after.getparent()
            top = list(root.iterchildren(P))
            i = top.index(after)
            nxt = next((k for k in range(i + 1, len(top)) if heading_parts(top[k]) is not None), None)

            head = copy.deepcopy(after)
            strip_lineseg(head)
            tbl, _, title_cell = heading_parts(head)
            tbl.set("id", new_id())
            ws = leading_ws("".join(t_text(t) for t in title_cell.iter(T)))
            set_cell(title_cell, ws + title)
            new_ps = [head]
            for line in as_lines(sec.get("lines")):
                proto = protos.get(marker_of(line), fallback)
                if proto is not None:
                    new_ps.append(clone_line(proto, line))
            table = _table_spec(sec.get("table"))
            if table is not None:
                new_ps.append(build_table_paragraph(self._table_proto(fallback), table["columns"], table["rows"]))

            blank = protos.get("blank")
            if nxt is not None:
                seq = new_ps + ([copy.deepcopy(blank)] if blank is not None else [])
                for np_ in seq:
                    top[nxt].addprevious(np_)
            else:
                # 마지막 장 뒤: '붙임 … 끝.' 줄과 그 앞 빈 줄보다 앞에 넣는다
                k = next((k for k in range(i + 1, len(top)) if self._is_ending(top[k])), len(top))
                while k - 1 > i and is_blank(top[k - 1]):
                    k -= 1
                seq = ([copy.deepcopy(blank)] if blank is not None else []) + new_ps
                if k < len(top):
                    for np_ in seq:
                        top[k].addprevious(np_)
                else:
                    for np_ in seq:
                        root.append(np_)
            added += 1
        return added
