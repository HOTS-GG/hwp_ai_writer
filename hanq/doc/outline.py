"""문서를 AI가 가리킬 수 있는 번호와 개요 글로 정리한다.

  [S번호]  줄 하나 (한 줄 안에 글자 모양이 여러 개여도 번호는 하나), 또는 빈 표 칸
  [E번호]  양식의 예시 문장 (빈칸 양식에서만)
  [T번호]  표의 반복 데이터 행 묶음
  [H번호]  장 제목 번호 상자
  [B번호]  표 틀 (수정 모드)
  [I번호]  그림 (수정 모드)
"""
import re

from .document import HwpxDocument
from .xml import (HWPUNIT_PER_MM, NUMBER_ONLY, P, PIC, PLACEHOLDER, RUN, SUBLIST, SZ, T, TBL, TC, TR, CELLSPAN,
                  cell_text, ensure_t, has_objects, has_secpr, heading_parts, is_blank, para_text)

CELL_PREFIX = "  │ "
# 예시문은 본문 항목 줄만 (1. 가. ❍ □ ※ 붙임 …). 서명란·'○○학교장 귀하'·공문 끝의 기안자·시행 줄은 고정
_LIST_ITEM = re.compile(r"\s*(\d+[.)]|[가-하][.)]|[❍□○※*\-·▪■◦•]|붙임)")


class TableGroup:
    """표 안의 연속된 데이터 행 묶음 (머리행 바로 아래부터)."""

    def __init__(self, gid: str, tbl, trs: list, header: list[str]):
        self.id = gid
        self.tbl = tbl
        self.trs = trs
        self.header = header
        self.ncols = len(trs[0].findall(TC))


class Outline:
    def __init__(self, doc: HwpxDocument, edit: bool = False,
                 page_map: list | None = None, page_count: int | None = None):
        self.doc = doc
        self.edit = edit
        self.lines: dict[str, object] = {}      # S·E번호 → 줄(hp:p)
        self.empty_cells: set[str] = set()      # 빈 칸으로 내놓은 S번호
        self.tables: dict[str, TableGroup] = {}
        self.headings: dict[str, object] = {}
        self.boxes: dict[str, object] = {}
        self.images: dict[str, object] = {}
        self._out: list[str] = []
        # 장 제목 상자의 번호 칸: 번호는 프로그램이 매기므로 AI에게 고칠 줄로 내놓지 않는다
        # (AI가 번호 칸을 바꾸면 장 제목으로 알아보지 못해 새 장·장 번호 다시 매기기가 실패했다)
        self._heading_num_cells: set = set()
        self._page_map = page_map
        self._top_index = 0
        self._cur_page = None
        self.has_placeholders = False if edit else bool(PLACEHOLDER.search(doc.plain_text()))
        # 표지·머리 부분(첫 장 제목 앞)의 교훈·슬로건·주소는 학교 고정 문구라 '예시문'으로 내놓지 않는다
        self._in_body = not any(heading_parts(p) is not None
                                for root in doc.ordered_sections() for p in root.iterchildren(P))
        for root in doc.ordered_sections():
            self._walk(root, "")
        if page_map:
            total = page_count or max(page_map)
            notes = [f"(이 문서는 한글에서 총 {total}쪽입니다. '── N쪽 ──'은 그 쪽이 시작되는 곳)"]
            if total > max(page_map):
                notes.append(f"(주의: 마지막 줄은 {max(page_map)}쪽에서 시작하지만 문서는 {total}쪽까지 있음 "
                             f"→ 마지막 표나 내용이 {total}쪽으로 넘쳐 있음. 빈 줄만 지워서는 줄지 않음)")
            self._out[0:0] = notes
        self.text = "\n".join(self._out)

    # ── 조회 ────────────────────────────────────────────────────────────
    @property
    def fill_count(self) -> int:
        return sum(1 for k in self.lines if k.startswith("S"))

    def ref_kind(self, ref: str) -> str | None:
        ref = str(ref).strip()
        for kind, table in (("line", self.lines), ("table", self.tables), ("heading", self.headings),
                            ("box", self.boxes), ("image", self.images)):
            if ref in table:
                return kind
        return None

    def has(self, ref) -> bool:
        return self.ref_kind(ref) is not None

    # ── 만들기 ──────────────────────────────────────────────────────────
    def _add_line(self, p, label: str, prefix: str, kind: str = "S") -> str:
        lid = f"{kind}{len(self.lines) + 1}"
        self.lines[lid] = p
        self._out.append(f"{prefix}[{lid}] {label}")
        return lid

    def _mark_page(self, p):
        """본문 줄마다: 쪽이 바뀌면 경계 표시, 표가 여러 쪽에 걸치면 그 사실을 표시."""
        pm = self._page_map
        i = self._top_index
        self._top_index += 1
        if not pm or i >= len(pm):
            return
        page = pm[i]
        if page != self._cur_page:
            self._out.append(f"──── {page}쪽 ────")
            self._cur_page = page
        nxt = pm[i + 1] if i + 1 < len(pm) else max(pm)
        if p.find(f"{RUN}/{TBL}") is not None and nxt > page:
            self._out.append(f"(아래 표는 {page}쪽에서 시작하고, 표 다음 줄은 {nxt}쪽에서 시작함 "
                             f"— 표가 {page}쪽 끝까지 차 있거나 다음 쪽으로 넘어감)")

    def _walk(self, container, prefix: str):
        top_level = container.getparent() is None
        # 빈 표 칸도 채울 수 있게 내놓는다 (○ 빈칸이 없는 양식·수정 모드)
        if container.tag == SUBLIST and (self.edit or not self.has_placeholders):
            ps = container.findall(P)
            if ps and not any(para_text(p).strip() for p in ps) and not any(has_objects(p) for p in ps):
                ensure_t(ps[0])
                self.empty_cells.add(self._add_line(ps[0], "(빈 칸)", prefix))
                return
        for p in container.iterchildren(P):
            if top_level:
                self._mark_page(p)
                # 수정 모드: 빈 줄도 지울 수 있게 내놓는다 (빈 줄이 다음 쪽으로 밀려 빈 쪽이 생기는 경우)
                if self.edit and is_blank(p) and not has_secpr(p):
                    ensure_t(p)
                    self._add_line(p, "(빈 줄)", "")
                    continue
                hp_ = heading_parts(p)
                if hp_ is not None:
                    self._in_body = True
                    self._heading_num_cells.add(hp_[1])
                    hid = f"H{len(self.headings) + 1}"
                    self.headings[hid] = p
                    self._out.append(f"[{hid}] ===== 장 {cell_text(hp_[1])}. {cell_text(hp_[2])} =====")
            text = para_text(p)
            if text.strip():
                if not self.has_placeholders or PLACEHOLDER.search(text):
                    self._add_line(p, text, prefix)
                elif len(text.strip()) >= 10 and not prefix and self._in_body and _LIST_ITEM.match(text):
                    self._add_line(p, f"(예시문) {text}", prefix, kind="E")
                else:
                    self._out.append(f"{prefix}(고정) {text}")
            for run in p.iterfind(RUN):
                for c in run:
                    if c.tag == T:
                        continue
                    if self.edit and c.tag != TBL and (c.tag == PIC or c.find(f".//{PIC}") is not None):
                        self._add_image(c, prefix)
                    self._scan_obj(c, prefix)

    def _add_image(self, obj, prefix):
        iid = f"I{len(self.images) + 1}"
        self.images[iid] = obj
        sz = obj.find(SZ)
        w = int(sz.get("width", "0") or 0) if sz is not None else 0
        h = int(sz.get("height", "0") or 0) if sz is not None else 0
        size = f" 약 {w / HWPUNIT_PER_MM:.0f}×{h / HWPUNIT_PER_MM:.0f}mm" if w and h else ""
        self._out.append(f"{prefix}[{iid}] (그림{size})")

    def _scan_obj(self, e, prefix):
        if e.tag == TBL:
            self._table(e, prefix)
        elif e.tag == SUBLIST:
            self._walk(e, prefix)
        else:
            for c in e:
                self._scan_obj(c, prefix)

    def _is_data_row(self, tr, ncols) -> bool:
        if not self.has_placeholders and not self.edit:
            return False
        cells = tr.findall(TC)
        if len(cells) != ncols:
            return False
        for tc in cells:
            span = tc.find(CELLSPAN)
            if span is not None and (span.get("rowSpan") != "1" or span.get("colSpan") != "1"):
                return False
            if tc.find(f".//{TBL}") is not None:
                return False
            if self.edit:
                continue
            txt = cell_text(tc)
            if txt and not PLACEHOLDER.search(txt) and not NUMBER_ONLY.match(txt):
                return False
        return True

    def _table(self, tbl, prefix):
        trs = tbl.findall(TR)
        ncols = int(tbl.get("colCnt", "0") or 0)
        holder = tbl.getparent().getparent() if tbl.getparent() is not None else None
        hp_ = heading_parts(holder)
        if self.edit and not (hp_ and hp_[0] is tbl):
            # 수정 모드: 장 제목 상자를 뺀 모든 표를 B번호로 내놓아 표 지우기·틀 없애기·테두리에 쓴다
            bid = f"B{len(self.boxes) + 1}"
            self.boxes[bid] = tbl
            self._out.append(f"{prefix}[{bid}] 표 ({len(trs)}행 {ncols}열) ↓")
        i = 0
        while i < len(trs):
            if i >= 1 and self._is_data_row(trs[i], ncols):
                j = i
                while j + 1 < len(trs) and self._is_data_row(trs[j + 1], ncols):
                    j += 1
                header = [cell_text(tc) for tc in trs[i - 1].findall(TC)]
                gid = f"T{len(self.tables) + 1}"
                group = TableGroup(gid, tbl, trs[i:j + 1], header)
                self.tables[gid] = group
                self._out.append(f"{prefix}[{gid}] 표 — 열 {group.ncols}개: " + " | ".join(header))
                label = "행" if self.edit else "예시행"
                for tr in group.trs:
                    self._out.append(f"{prefix}    {label}: " + " | ".join(cell_text(tc) for tc in tr.findall(TC)))
                i = j + 1
                continue
            for tc in trs[i].findall(TC):
                if tc in self._heading_num_cells:
                    continue
                sl = tc.find(SUBLIST)
                if sl is not None:
                    self._walk(sl, prefix + CELL_PREFIX)
            i += 1
