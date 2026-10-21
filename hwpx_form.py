"""
HWPX 양식 엔진.

- 양식의 빈칸(○○○○ 등)을 슬롯으로 추출하고, AI가 준 값으로 원본 XML의 글자만 바꿔 저장한다.
- 표의 반복 데이터 행은 행 단위로 받아 필요한 만큼 늘리거나 줄인다.
- PDF처럼 원본 서식이 없는 양식은 기본 양식의 문단·표를 복제해 새 문서를 조립한다.
"""
import copy
import random
import re
import zipfile

from lxml import etree

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
HEADER_NAME = "Contents/header.xml"
P, RUN, T, TBL, TR, TC = (f"{{{HP}}}{n}" for n in ("p", "run", "t", "tbl", "tr", "tc"))
SUBLIST, CELLADDR, CELLSPAN, CELLSZ, SZ = (f"{{{HP}}}{n}" for n in ("subList", "cellAddr", "cellSpan", "cellSz", "sz"))
LINESEG = f"{{{HP}}}linesegarray"

PLACEHOLDER = re.compile(r"[○◯]|\{\{[^}]*\}\}|_{3,}|ＯＯ|OOO")
NUMBER_ONLY = re.compile(r"^\s*\d+\s*$")
ROMAN = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ"
HEAD_NUM = re.compile(rf"^\s*(\d+|[{ROMAN}])\s*$")
ITEM_RE = re.compile(r"^\s*\d+\.\s")
SUB_RE = re.compile(r"^\s*[가-힣]\.\s")
# 본문 줄 앞의 기호 종류 → 그 종류의 줄 모양(문단)을 문서에서 찾아 복제한다
MARKERS = [
    ("num", re.compile(r"^\d+\.\s")), ("ga", re.compile(r"^[가-힣]\.\s")),
    ("paren_num", re.compile(r"^\(\d+\)")), ("paren_ga", re.compile(r"^\([가-힣]\)")),
    ("circle", re.compile(r"^[①-⑳]")), ("box", re.compile(r"^[□■]")),
    ("bullet", re.compile(r"^[❍◦●○]\s")), ("diamond", re.compile(r"^[◇◆]")),
    ("dash", re.compile(r"^[-–]\s")), ("star", re.compile(r"^\*")),
    ("note", re.compile(r"^※")), ("dot", re.compile(r"^[‣•·￭▪]")),
]


def marker_of(text: str) -> str:
    s = text.strip()
    for name, rx in MARKERS:
        if rx.match(s):
            return name
    return "text"
SECTION_RE = re.compile(r"^Contents/section\d+\.xml$")


def t_text(t) -> str:
    return "".join(t.itertext())


def set_t(t, text: str):
    for c in list(t):
        t.remove(c)
    t.text = text


def leading_ws(s: str) -> str:
    return s[: len(s) - len(s.lstrip())]


def _ensure_t(p):
    run = p.find(RUN)
    if run is None:
        run = etree.SubElement(p, RUN)
        run.set("charPrIDRef", "0")
    t = run.find(T)
    if t is None:
        t = etree.SubElement(run, T)
    return t


def _has_objects(p) -> bool:
    for run in p.iterfind(RUN):
        for c in run:
            if c.tag != T:
                return True
    return False


COLOR_NAMES = {"빨강": "#FF0000", "빨간": "#FF0000", "red": "#FF0000", "파랑": "#0000FF", "파란": "#0000FF",
               "blue": "#0000FF", "검정": "#000000", "black": "#000000", "초록": "#008000", "green": "#008000",
               "노랑": "#FFFF00", "yellow": "#FFFF00", "주황": "#FF8C00", "orange": "#FF8C00",
               "보라": "#800080", "회색": "#808080", "gray": "#808080"}


def _hex_color(c: str) -> str:
    c = str(c).strip()
    if c in COLOR_NAMES:
        return COLOR_NAMES[c]
    if re.fullmatch(r"#?[0-9a-fA-F]{6}", c):
        return "#" + c.lstrip("#").upper()
    return "#000000"


def _new_id() -> str:
    return str(random.randint(1_800_000_000, 2_100_000_000))


def _para_text(p) -> str:
    return "".join(t_text(t) for t in p.iterfind(f"{RUN}/{T}"))


def heading_parts(p):
    """장 제목 번호 상자(한 줄 표: 번호 | … | 제목)면 (표, 번호 칸, 제목 칸)을, 아니면 None."""
    tbl = p.find(f"{RUN}/{TBL}")
    if tbl is None:
        return None
    trs = tbl.findall(TR)
    if len(trs) != 1:
        return None
    cells = trs[0].findall(TC)
    if len(cells) < 2:
        return None
    if not HEAD_NUM.match(HwpxDoc._cell_text(cells[0])):
        return None
    title = next((c for c in reversed(cells[1:]) if HwpxDoc._cell_text(c)), None)
    if title is None:
        return None
    return tbl, cells[0], title


def _is_blank(p) -> bool:
    return not _para_text(p).strip() and not _has_objects(p)


def build_table_paragraph(proto_p, columns: list, rows: list):
    """표가 든 문단(머리행 + 데이터 행)을 복제해 열·행 수가 다른 새 표 문단을 만든다."""
    n = len(columns)
    p = copy.deepcopy(proto_p)
    tbl = p.find(f"{RUN}/{TBL}")
    tbl.set("id", _new_id())
    trs = tbl.findall(TR)
    hdr, first, last = trs[0], trs[1] if len(trs) > 1 else trs[0], trs[-1]
    mid = trs[2] if len(trs) > 3 else first
    hdr_cells = hdr.findall(TC)
    total_w = sum(int(tc.find(CELLSZ).get("width")) for tc in hdr_cells)
    lens = []
    for j in range(n):
        col = [str(columns[j])] + [str(r[j]) if isinstance(r, list) and j < len(r) else "" for r in rows]
        lens.append(min(max(len(c) for c in col), 30) + 4)
    widths = [int(total_w * L / sum(lens)) for L in lens]
    widths[-1] += total_w - sum(widths)
    row_h = hdr_cells[0].find(CELLSZ).get("height")

    def build(proto_tr, texts, r):
        cells = proto_tr.findall(TC)
        tr = copy.deepcopy(proto_tr)
        for tc in tr.findall(TC):
            tr.remove(tc)
        for j in range(n):
            src = cells[0] if j == 0 else cells[-1] if j == n - 1 else cells[min(1, len(cells) - 1)]
            tc = copy.deepcopy(src)
            tc.find(CELLADDR).set("colAddr", str(j))
            tc.find(CELLADDR).set("rowAddr", str(r))
            tc.find(CELLSPAN).set("colSpan", "1")
            tc.find(CELLSPAN).set("rowSpan", "1")
            tc.find(CELLSZ).set("width", str(widths[j]))
            tc.find(CELLSZ).set("height", row_h)
            HwpxDoc._set_cell(tc, str(texts[j]) if j < len(texts) else "")
            tr.append(tc)
        return tr

    for tr in trs:
        tbl.remove(tr)
    tbl.append(build(hdr, columns, 0))
    rows = rows or [[""] * n]
    for i, row in enumerate(rows):
        proto = last if i == len(rows) - 1 else first if i == 0 else mid
        tbl.append(build(proto, row if isinstance(row, list) else [row], i + 1))
    tbl.set("colCnt", str(n))
    _renumber_table(tbl)
    return p


def _is_simple_table_para(p) -> bool:
    tbl = p.find(f"{RUN}/{TBL}")
    if tbl is None or int(tbl.get("rowCnt", "0")) < 2 or int(tbl.get("colCnt", "0")) < 2:
        return False
    if heading_parts(p) is not None:
        return False
    for span in tbl.iter(CELLSPAN):
        if span.get("rowSpan") != "1" or span.get("colSpan") != "1":
            return False
    return tbl.find(f".//{TR}//{TBL}") is None


class TableGroup:
    def __init__(self, gid, tbl, trs, header):
        self.id = gid
        self.tbl = tbl
        self.trs = trs
        self.header = header
        self.ncols = len(trs[0].findall(TC))


class HwpxDoc:
    def __init__(self, path: str):
        self.path = path
        with zipfile.ZipFile(path) as z:
            self._items = [(i, z.read(i.filename)) for i in z.infolist()]
        parser = etree.XMLParser(remove_blank_text=False, huge_tree=True)
        self.sections = {
            i.filename: etree.fromstring(data, parser)
            for i, data in self._items if SECTION_RE.match(i.filename)
        }
        self.edit_mode = False
        self._page_map = None
        self._top_index = 0
        self._cur_page = None
        self._header = None
        self._charpr_cache: dict = {}
        self.headings: dict[str, object] = {}
        self.slots: dict[str, object] = {}
        self.tables: dict[str, TableGroup] = {}
        self._outline: list[str] = []

    # ── 저장 ────────────────────────────────────────────────────────────
    def save(self, out_path: str):
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
            for info, data in self._items:
                name = info.filename
                if name in self.sections:
                    root = self.sections[name]
                    for ls in list(root.iter(LINESEG)):
                        ls.getparent().remove(ls)
                    data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
                elif name == HEADER_NAME and self._header is not None:
                    data = etree.tostring(self._header, xml_declaration=True, encoding="UTF-8", standalone=True)
                elif name == "Preview/PrvText.txt":
                    data = self.plain_text()[:1000].encode("utf-8")
                ct = zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
                zi = zipfile.ZipInfo(name, date_time=info.date_time)
                zi.compress_type = ct
                z.writestr(zi, data)

    def snapshot(self) -> bytes:
        """본문 XML 전체. 수정 전후를 비교해 실제로 바뀐 게 있는지 본다."""
        return b"".join(etree.tostring(r) for r in self.ordered_sections())

    def plain_text(self) -> str:
        lines = []
        for root in self.sections.values():
            for p in root.iter(P):
                s = "".join(t_text(t) for t in p.iterfind(f"{RUN}/{T}"))
                if s.strip():
                    lines.append(s.rstrip())
        return "\n".join(lines)

    # ── 분석: 슬롯/표 추출 ───────────────────────────────────────────────
    def ordered_sections(self) -> list:
        """section0, section1, … 순서(숫자 기준)의 섹션 루트 목록."""
        return [self.sections[k] for k in sorted(self.sections, key=lambda n: int(re.search(r"\d+", n).group()))]

    def analyze(self, edit: bool = False, page_map: list | None = None, page_count: int | None = None) -> str:
        """양식 구조를 AI용 개요 문자열로 반환하고 self.slots / self.tables를 채운다.

        edit=True면 완성된 문서 수정용: 모든 줄이 슬롯이 되고, 표는 머리행 아래 행 전체를 T로 묶는다.
        """
        self.slots.clear()
        self.tables.clear()
        self.headings.clear()
        self._outline = []
        self.edit_mode = edit
        all_text = self.plain_text()
        self.has_placeholders = False if edit else bool(PLACEHOLDER.search(all_text))
        self._page_map = page_map
        self._top_index = 0
        self._cur_page = None
        for root in self.ordered_sections():
            self._walk(root, "")
        if page_map:
            total = page_count or max(page_map)
            notes = [f"(이 문서는 한글에서 총 {total}쪽입니다. '── N쪽 ──'은 그 쪽이 시작되는 곳)"]
            if total > max(page_map):
                notes.append(f"(주의: 마지막 줄은 {max(page_map)}쪽에서 시작하지만 문서는 {total}쪽까지 있음 "
                             f"→ 마지막 표나 내용이 {total}쪽으로 넘쳐 있음. 빈 줄만 지워서는 줄지 않음)")
            self._outline[0:0] = notes
        return "\n".join(self._outline)

    def _mark_page(self, p):
        """본문 줄마다: 쪽이 바뀌면 경계 표시, 표가 여러 쪽에 걸치면 그 사실을 표시."""
        pm = self._page_map
        i = self._top_index
        self._top_index += 1
        if not pm or i >= len(pm):
            return
        page = pm[i]
        if page != self._cur_page:
            self._outline.append(f"──── {page}쪽 ────")
            self._cur_page = page
        nxt = pm[i + 1] if i + 1 < len(pm) else max(pm)
        if p.find(f"{RUN}/{TBL}") is not None and nxt > page:
            self._outline.append(f"(아래 표는 {page}쪽에서 시작하고, 표 다음 줄은 {nxt}쪽에서 시작함 "
                                 f"— 표가 {page}쪽 끝까지 차 있거나 다음 쪽으로 넘어감)")

    def _is_slot(self, text: str) -> bool:
        if not text.strip():
            return False
        return bool(PLACEHOLDER.search(text)) if self.has_placeholders else True

    def _walk(self, container, prefix: str):
        top_level = container.getparent() is None
        # 빈 표 칸도 채울 수 있게 슬롯으로 내놓는다 (○ 빈칸이 없는 양식·수정 모드)
        if container.tag == SUBLIST and (self.edit_mode or not self.has_placeholders):
            ps = container.findall(P)
            if ps and not any(_para_text(p).strip() for p in ps) and not any(_has_objects(p) for p in ps):
                t = _ensure_t(ps[0])
                sid = f"S{len(self.slots) + 1}"
                self.slots[sid] = t
                self._outline.append(f"{prefix}[{sid}] (빈 칸)")
                return
        for p in container.iterchildren(P):
            if top_level:
                self._mark_page(p)
                # 수정 모드: 빈 줄도 지울 수 있게 내놓는다 (빈 줄이 다음 쪽으로 밀려 빈 쪽이 생기는 경우)
                if self.edit_mode and _is_blank(p) and p.find(f".//{{{HP}}}secPr") is None:
                    sid = f"S{len(self.slots) + 1}"
                    self.slots[sid] = _ensure_t(p)
                    self._outline.append(f"[{sid}] (빈 줄)")
                    continue
                hp = heading_parts(p)
                if hp is not None:
                    hid = f"H{len(self.headings) + 1}"
                    self.headings[hid] = p
                    self._outline.append(f"[{hid}] ===== 장 {HwpxDoc._cell_text(hp[1])}. "
                                         f"{HwpxDoc._cell_text(hp[2])} =====")
            for t in p.iterfind(f"{RUN}/{T}"):
                text = t_text(t)
                if not text.strip():
                    continue
                if self._is_slot(text):
                    sid = f"S{len(self.slots) + 1}"
                    self.slots[sid] = t
                    self._outline.append(f"{prefix}[{sid}] {text}")
                elif len(text.strip()) >= 10 and not prefix:
                    eid = f"E{len(self.slots) + 1}"
                    self.slots[eid] = t
                    self._outline.append(f"{prefix}[{eid}] (예시문) {text}")
                else:
                    self._outline.append(f"{prefix}(고정) {text}")
            for run in p.iterfind(RUN):
                for c in run:
                    if c.tag != T:
                        self._scan_obj(c, prefix)

    def _scan_obj(self, e, prefix):
        if e.tag == TBL:
            self._table(e, prefix)
        elif e.tag == SUBLIST:
            self._walk(e, prefix)
        else:
            for c in e:
                self._scan_obj(c, prefix)

    @staticmethod
    def _cell_text(tc) -> str:
        sl = tc.find(SUBLIST)
        if sl is None:
            return ""
        return " ".join(
            "".join(t_text(t) for t in p.iterfind(f"{RUN}/{T}")).strip()
            for p in sl.iterchildren(P)
        ).strip()

    def _is_data_row(self, tr, ncols) -> bool:
        if not self.has_placeholders and not self.edit_mode:
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
            if self.edit_mode:
                continue
            txt = self._cell_text(tc)
            if txt and not PLACEHOLDER.search(txt) and not NUMBER_ONLY.match(txt):
                return False
        return True

    def _table(self, tbl, prefix):
        trs = tbl.findall(TR)
        ncols = int(tbl.get("colCnt", "0") or 0)
        i = 0
        while i < len(trs):
            if i >= 1 and self._is_data_row(trs[i], ncols):
                j = i
                while j + 1 < len(trs) and self._is_data_row(trs[j + 1], ncols):
                    j += 1
                header = [self._cell_text(tc) for tc in trs[i - 1].findall(TC)]
                gid = f"T{len(self.tables) + 1}"
                group = TableGroup(gid, tbl, trs[i:j + 1], header)
                self.tables[gid] = group
                self._outline.append(
                    f"{prefix}[{gid}] 표 — 열 {group.ncols}개: " + " | ".join(header)
                )
                for tr in group.trs:
                    self._outline.append(
                        f"{prefix}    {'행' if self.edit_mode else '예시행'}: " + " | ".join(self._cell_text(tc) for tc in tr.findall(TC))
                    )
                i = j + 1
                continue
            for tc in trs[i].findall(TC):
                sl = tc.find(SUBLIST)
                if sl is not None:
                    self._walk(sl, prefix + "  │ ")
            i += 1

    # ── 채우기 ──────────────────────────────────────────────────────────
    def fill(self, slots: dict, tables: dict, new_sections: list | None = None,
             inserts: list | None = None, styles: list | None = None, deletes: list | None = None) -> dict:
        sequential = self._headings_sequential()
        self._fill_slots_tables(slots, tables)
        inserted = self.insert_lines(inserts or [])
        styled = self.apply_styles(styles or [])
        deleted = self.delete_blocks(deletes or [])
        added = self.insert_sections(new_sections or [])
        if (added or deleted) and sequential and self._all_headings():
            self._renumber_headings()
        return {"styled": styled, "inserted": inserted, "sections": added, "deleted": deleted}

    # ── 장·표 통째로 지우기 ─────────────────────────────────────────────
    @staticmethod
    def _is_ending(p) -> bool:
        s = _para_text(p).strip()
        return s.startswith("붙임") or s.endswith("끝.")

    def delete_blocks(self, refs: list) -> int:
        """H번호는 장 전체(제목 상자부터 다음 장 제목 앞까지, '붙임 … 끝.' 줄은 남김),
        T번호는 그 표 전체(머리행 포함)를 지운다. 지운 개수를 돌려준다."""
        heads = {id(p) for p in self.headings.values()}
        removed = 0
        for ref in refs:
            ref = str(ref).strip()
            if ref in self.headings:
                p = self.headings[ref]
                if p.getparent() is None:
                    continue
                victims, cur = [p], p.getnext()
                while cur is not None and id(cur) not in heads and not (cur.tag == P and self._is_ending(cur)):
                    victims.append(cur)
                    cur = cur.getnext()
                for v in victims:
                    # 문서 설정(secPr)이 든 줄은 지우면 문서가 깨지므로 남긴다
                    if v.find(f".//{{{HP}}}secPr") is None and v.getparent() is not None:
                        v.getparent().remove(v)
                removed += 1
            elif ref in self.tables:
                tbl = self.tables[ref].tbl
                run = tbl.getparent()
                p = run.getparent() if run is not None else None
                if p is None:
                    continue
                parent = p.getparent()
                alone = (not _para_text(p).strip() and sum(1 for r in p.iterfind(RUN) for c in r if c.tag != T) == 1)
                if alone and parent is not None and p.find(f".//{{{HP}}}secPr") is None and \
                        not (parent.tag == SUBLIST and len(parent.findall(P)) <= 1):
                    parent.remove(p)
                else:
                    run.remove(tbl)
                removed += 1
        return removed

    # ── 글자 모양(색·굵게 등) ────────────────────────────────────────────
    def _header_root(self):
        if self._header is None:
            data = next(d for i, d in self._items if i.filename == HEADER_NAME)
            self._header = etree.fromstring(data, etree.XMLParser(huge_tree=True))
        return self._header

    def _charpr_variant(self, base_id: str, style: dict) -> str:
        """기존 글자 모양(base_id)을 복제해 style만 바꾼 새 글자 모양을 만들고 그 id를 돌려준다."""
        key = (base_id, tuple(sorted((k, str(v)) for k, v in style.items())))
        if key in self._charpr_cache:
            return self._charpr_cache[key]
        hdr = self._header_root()
        props = hdr.find(f".//{{{HH}}}charProperties")
        items = props.findall(f"{{{HH}}}charPr")
        base = next((c for c in items if c.get("id") == base_id), items[0])
        cp = copy.deepcopy(base)
        new_id = str(max(int(c.get("id")) for c in items) + 1)
        cp.set("id", new_id)

        def flag(tag, on):
            el = cp.find(f"{{{HH}}}{tag}")
            if on and el is None:
                el = etree.Element(f"{{{HH}}}{tag}")
                anchor = cp.find(f"{{{HH}}}underline")
                if anchor is not None:
                    anchor.addprevious(el)
                else:
                    cp.append(el)
            elif not on and el is not None:
                cp.remove(el)

        if style.get("color"):
            cp.set("textColor", _hex_color(style["color"]))
        if style.get("background"):
            cp.set("shadeColor", _hex_color(style["background"]))
        if style.get("size"):
            cp.set("height", str(int(float(style["size"]) * 100)))
        if "bold" in style:
            flag("bold", bool(style["bold"]))
        if "italic" in style:
            flag("italic", bool(style["italic"]))
        if "underline" in style:
            ul = cp.find(f"{{{HH}}}underline")
            if ul is not None:
                ul.set("type", "BOTTOM" if style["underline"] else "NONE")
                if style.get("color"):
                    ul.set("color", _hex_color(style["color"]))
        props.append(cp)
        props.set("itemCnt", str(len(items) + 1))
        self._charpr_cache[key] = new_id
        return new_id

    def apply_style(self, t, style: dict, part: str | None = None) -> bool:
        """글자 덩어리(t) 전체, 또는 그 안의 일부 글자(part)에 글자 모양을 적용한다."""
        run = t.getparent()
        base = run.get("charPrIDRef", "0")
        new_id = self._charpr_variant(base, style)
        text = t_text(t)
        simple = len(run) == 1 and run[0] is t
        if part and part in text and part != text and simple:
            i = text.index(part)
            pieces = [(text[:i], base), (part, new_id), (text[i + len(part):], base)]
            anchor = run
            first = True
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
        for st in styles or []:
            if not isinstance(st, dict):
                continue
            target = str(st.get("target", ""))
            ts = []
            if target in self.slots:
                ts = [self.slots[target]]
            elif target in self.headings:
                hp = heading_parts(self.headings[target])
                ts = list(hp[2].iter(T)) if hp else []
            style = {k: st[k] for k in ("color", "background", "size", "bold", "italic", "underline") if k in st}
            if not style:
                continue
            for t in ts:
                if t.getparent() is not None and self.apply_style(t, style, st.get("part")):
                    n += 1
        return n

    # ── 줄 끼워 넣기 ────────────────────────────────────────────────────
    def _anchor_para(self, ref: str):
        if ref in self.headings:
            return self.headings[ref]
        t = self.slots.get(ref)
        if t is None or t.getparent() is None:
            return None
        p = t.getparent().getparent()
        # 표 칸 안의 줄이면, 그 표를 담은 본문 문단(섹션 바로 아래 문단)을 기준으로 삼는다
        while p.getparent() is not None and p.getparent().getparent() is not None:
            a = p.getparent()
            while a is not None and a.tag != P:
                a = a.getparent()
            if a is None:
                break
            p = a
        return p

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

    def _make_lines(self, anchor, lines: list, before: bool = False, protos: dict | None = None) -> list:
        protos = self._protos() if protos is None else protos
        fallback = next((protos[k] for k in ("num", "bullet", "box", "dash", "text") if k in protos), None)
        # 기호 없는 줄은 바로 옆 본문 줄의 모양·들여쓰기를 따른다
        neighbor = anchor if (before or heading_parts(anchor) is None) else anchor.getnext()
        if neighbor is not None and (neighbor.tag != P or _has_objects(neighbor)
                                     or not _para_text(neighbor).strip()):
            neighbor = None
        out = []
        for line in lines:
            line = str(line)
            kind = marker_of(line)
            proto = protos.get(kind) if kind != "text" else None
            if proto is None:
                proto = neighbor if neighbor is not None else protos.get("text", fallback)
            out.append(self._clone_line(proto, line) if proto is not None else self._plain_line(anchor, line))
        return out

    def insert_lines(self, inserts: list) -> int:
        n = 0
        protos = None
        for ins in inserts or []:
            if not isinstance(ins, dict) or not ins.get("lines"):
                continue
            before = ins.get("before")
            anchor = self._anchor_para(str(before or ins.get("after", "")))
            if anchor is None:
                continue
            if protos is None:
                protos = self._protos()
            new_ps = self._make_lines(anchor, ins["lines"], bool(before), protos)
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

    # ── 새 장 넣기 ──────────────────────────────────────────────────────
    def _all_headings(self):
        out = []
        for name in sorted(self.sections):
            for p in self.sections[name].iterchildren(P):
                hp = heading_parts(p)
                if hp is not None:
                    out.append((p, hp))
        return out

    def _headings_sequential(self) -> bool:
        nums = [HwpxDoc._cell_text(hp[1]).strip() for _, hp in self._all_headings()]
        if not nums:
            return False
        if all(n.isdigit() for n in nums):
            start = int(nums[0])
            return nums == [str(start + i) for i in range(len(nums))]
        if all(n in ROMAN for n in nums):
            start = ROMAN.index(nums[0])
            return nums == list(ROMAN[start:start + len(nums)])
        return False

    def _renumber_headings(self):
        hs = self._all_headings()
        first = HwpxDoc._cell_text(hs[0][1][1]).strip()
        for i, (_, (tbl, num_cell, _)) in enumerate(hs):
            if first.isdigit():
                label = str(int(first) + i)
            else:
                k = ROMAN.index(first) + i
                label = ROMAN[k] if k < len(ROMAN) else str(k + 1)
            HwpxDoc._set_cell(num_cell, label)

    def _protos(self):
        """본문(첫 장 제목 이후)에서 기호 종류별 줄 모양, 빈 줄, 표 모양을 찾는다.

        표지·목차의 '1.' 같은 줄을 잘못 가져오지 않도록 첫 장 제목 앞은 보지 않는다.
        """
        found = {}
        has_heading = any(heading_parts(p) is not None
                          for root in self.sections.values() for p in root.iterchildren(P))
        seen_heading = not has_heading  # 장 제목이 없는 양식이면 처음부터 본다
        tables = []
        for name in sorted(self.sections):
            top = list(self.sections[name].iterchildren(P))
            for i, p in enumerate(top):
                if heading_parts(p) is not None:
                    seen_heading = True
                    if i > 0 and _is_blank(top[i - 1]):
                        found.setdefault("blank", top[i - 1])
                    continue
                if not seen_heading:
                    continue
                if _has_objects(p):
                    if _is_simple_table_para(p):
                        tables.append(p)
                    continue
                s = _para_text(p)
                if s.strip():
                    found.setdefault(marker_of(s), p)
        if tables:
            # 열이 많은(머리행이 있는) 표를 우선
            found["table"] = max(tables, key=lambda p: (min(int(p.find(f"{RUN}/{TBL}").get("colCnt")), 4),
                                                       int(p.find(f"{RUN}/{TBL}").get("rowCnt"))))
        return found

    def body_markers(self) -> list[str]:
        """AI에게 알려줄, 이 문서 본문에서 쓰는 줄 기호 예시."""
        examples = []
        for kind, p in self._protos().items():
            if kind in ("blank", "table", "text"):
                continue
            examples.append(_para_text(p).strip()[:12])
        return examples

    @staticmethod
    def _clone_line(proto, text: str):
        p = copy.deepcopy(proto)
        ts = p.findall(f"{RUN}/{T}")
        t = ts[0] if ts else _ensure_t(p)
        for other in ts[1:]:
            set_t(other, "")
        set_t(t, leading_ws(t_text(t)) + text.strip())
        return p

    def insert_sections(self, new_sections: list) -> int:
        if not new_sections:
            return 0
        heads = self._all_headings()
        if not heads:
            return 0
        protos = self._protos()
        added = 0
        for sec in new_sections:
            if not isinstance(sec, dict) or not str(sec.get("title", "")).strip():
                continue
            after = self.headings.get(str(sec.get("after", "")))
            if after is None:
                after = heads[-1][0]
            root = after.getparent()
            top = list(root.iterchildren(P))
            i = top.index(after)
            nxt = next((k for k in range(i + 1, len(top)) if heading_parts(top[k]) is not None), None)

            new_ps = []
            head = copy.deepcopy(after)
            tbl, num_cell, title_cell = heading_parts(head)
            tbl.set("id", _new_id())
            ws = leading_ws("".join(t_text(t) for t in title_cell.iter(T)))
            HwpxDoc._set_cell(title_cell, ws + str(sec["title"]).strip())
            new_ps.append(head)
            fallback = next((protos[k] for k in ("num", "bullet", "box", "dash", "text") if k in protos), None)
            for line in sec.get("lines", []) or []:
                s = str(line)
                proto = protos.get(marker_of(s), fallback)
                if proto is not None:
                    new_ps.append(self._clone_line(proto, s))
            table = sec.get("table")
            if isinstance(table, dict) and table.get("columns") and protos.get("table") is not None:
                new_ps.append(build_table_paragraph(protos["table"], table["columns"], table.get("rows", [])))

            blank = protos.get("blank")
            if nxt is not None:
                seq = new_ps + ([copy.deepcopy(blank)] if blank is not None else [])
                anchor = top[nxt]
                for np_ in seq:
                    anchor.addprevious(np_)
            else:
                # 마지막 장 뒤: '붙임 … 끝.' 줄과 그 앞 빈 줄보다 앞에 넣는다
                k = next((k for k in range(i + 1, len(top))
                          if "붙임" in _para_text(top[k]) or _para_text(top[k]).strip().endswith("끝.")), len(top))
                while k - 1 > i and _is_blank(top[k - 1]):
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

    def _fill_slots_tables(self, slots: dict, tables: dict):
        touched = []
        for sid, value in (slots or {}).items():
            t = self.slots.get(sid)
            if t is None or value is None:
                continue
            lines = str(value).split("\n")
            set_t(t, lines[0])
            p = t.getparent().getparent()
            touched.append(p)
            if len(lines) > 1:
                if not _has_objects(p) and len(p.findall(f"{RUN}/{T}")) == 1:
                    new_ps = []
                    for line in lines[1:]:
                        np_ = copy.deepcopy(p)
                        set_t(np_.find(f"{RUN}/{T}"), line)
                        new_ps.append(np_)
                else:
                    # 표·문서 설정이 붙은 줄은 통째로 복제하면 안 되므로 새 줄을 만들어 뒤에 붙인다
                    new_ps = self._make_lines(p, lines[1:])
                anchor = p
                for np_ in new_ps:
                    anchor.addnext(np_)
                    anchor = np_
        for gid, rows in (tables or {}).items():
            g = self.tables.get(gid)
            if g is not None and isinstance(rows, list):
                self._fill_group(g, rows)
        for p in touched:
            self._drop_if_empty(p)

    @staticmethod
    def _drop_if_empty(p):
        parent = p.getparent()
        if parent is None or _has_objects(p):
            return
        if any(t_text(t).strip() for t in p.iterfind(f"{RUN}/{T}")):
            return
        if parent.tag == SUBLIST and len(parent.findall(P)) <= 1:
            return
        if p.find(f".//{{{HP}}}secPr") is not None:
            return
        parent.remove(p)

    @staticmethod
    def _set_cell(tc, text: str):
        sl = tc.find(SUBLIST)
        ps = sl.findall(P)
        first = ps[0]
        for extra in ps[1:]:
            sl.remove(extra)
        t = _ensure_t(first)
        for other in first.iterfind(f"{RUN}/{T}"):
            if other is not t:
                set_t(other, "")
        lines = str(text).split("\n")
        set_t(t, lines[0])
        anchor = first
        for line in lines[1:]:
            np_ = copy.deepcopy(first)
            set_t(np_.find(f"{RUN}/{T}"), line)
            anchor.addnext(np_)
            anchor = np_

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
            for j, tc in enumerate(tr.findall(TC)):
                self._set_cell(tc, row[j] if j < len(row) else "")
            new_trs.append(tr)
        for tr in g.trs:
            tbl.remove(tr)
        for k, tr in enumerate(new_trs):
            tbl.insert(anchor_idx + k, tr)
        g.trs = new_trs
        _renumber_table(tbl)


def _renumber_table(tbl):
    trs = tbl.findall(TR)
    height = 0
    for r, tr in enumerate(trs):
        row_h = 0
        for tc in tr.findall(TC):
            addr = tc.find(CELLADDR)
            if addr is not None:
                addr.set("rowAddr", str(r))
            sz = tc.find(CELLSZ)
            if sz is not None:
                row_h = max(row_h, int(sz.get("height", "0")))
        height += row_h
    tbl.set("rowCnt", str(len(trs)))
    sz = tbl.find(SZ)
    if sz is not None and height:
        sz.set("height", str(height))


# ── 기본 양식으로 새 문서 조립 (PDF 양식 / 자유 생성용) ─────────────────────

class DocumentBuilder:
    """기본 양식(번호 박스 제목 + 개조식 본문 + 표 구조)의 문단을 복제해 새 문서를 만든다."""

    def __init__(self, base_path: str):
        self.doc = HwpxDoc(base_path)
        name = sorted(self.doc.sections)[0]
        self.root = self.doc.sections[name]
        top = list(self.root.iterchildren(P))

        def text(p):
            return "".join(t_text(t) for t in p.iterfind(f"{RUN}/{T}"))

        def heading_tbl(p):
            tbl = p.find(f"{RUN}/{TBL}")
            if tbl is None or tbl.get("rowCnt") != "1" or tbl.get("colCnt") != "3":
                return None
            first = HwpxDoc._cell_text(tbl.find(TR).findall(TC)[0])
            return tbl if NUMBER_ONLY.match(first) else None

        first_heading = next(i for i, p in enumerate(top) if heading_tbl(p) is not None)
        body = top[first_heading:]

        def pick(pred):
            for p in body:
                if pred(p):
                    return copy.deepcopy(p)
            return None

        self.p_heading = copy.deepcopy(top[first_heading])
        self.p_item = pick(lambda p: re.match(r"^\s*\d+\.\s", text(p)) and not _has_objects(p))
        self.p_sub = pick(lambda p: re.match(r"^\s*[가-힣]\.\s", text(p)) and not _has_objects(p))
        if self.p_sub is None:
            self.p_sub = copy.deepcopy(self.p_item)
        self.p_note = pick(lambda p: "※" in text(p) and not _has_objects(p))
        if self.p_note is None:
            self.p_note = copy.deepcopy(self.p_item)
        self.p_blank = pick(lambda p: not text(p).strip() and not _has_objects(p))
        self.p_table = pick(lambda p: (lambda t: t is not None and int(t.get("rowCnt", "0")) >= 3
                                       and int(t.get("colCnt", "0")) >= 3)(p.find(f"{RUN}/{TBL}")))
        self.p_end = pick(lambda p: "붙임" in text(p) or "끝." in text(p))
        self.prefix = top[:first_heading]
        for p in body:
            self.root.remove(p)
        self._n_heading = 0

    # ── 표지/제목 채우기 ──
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

    def _append(self, p):
        self.root.append(p)

    @staticmethod
    def _set_para(p, text: str, proto_text_indent: str):
        t = p.find(f"{RUN}/{T}") if p.find(f"{RUN}/{T}") is not None else _ensure_t(p)
        set_t(t, proto_text_indent + text.strip())

    def _indent_of(self, p) -> str:
        t = p.find(f"{RUN}/{T}")
        return leading_ws(t_text(t)) if t is not None else ""

    def heading(self, text: str):
        self._n_heading += 1
        if self._n_heading > 1 and self.p_blank is not None:
            self._append(copy.deepcopy(self.p_blank))
        p = copy.deepcopy(self.p_heading)
        tbl = p.find(f"{RUN}/{TBL}")
        tbl.set("id", _new_id())
        cells = tbl.find(TR).findall(TC)
        HwpxDoc._set_cell(cells[0], str(self._n_heading))
        HwpxDoc._set_cell(cells[-1], "  " + text.strip())
        self._append(p)

    def item(self, text: str, kind: str = "item"):
        proto = {"item": self.p_item, "sub": self.p_sub, "note": self.p_note}.get(kind, self.p_item)
        p = copy.deepcopy(proto)
        indent = self._indent_of(proto)
        if kind == "note" and not text.strip().startswith("※"):
            text = "※ " + text.strip()
        self._set_para(p, text, indent)
        self._append(p)

    def blank(self):
        if self.p_blank is not None:
            self._append(copy.deepcopy(self.p_blank))

    def table(self, columns: list, rows: list):
        if self.p_table is None or not columns:
            return
        self._append(build_table_paragraph(self.p_table, columns, rows))

    def ending(self, text: str):
        if not text or self.p_end is None:
            return
        self.blank()
        p = copy.deepcopy(self.p_end)
        t = p.find(f"{RUN}/{T}")
        for other in p.iterfind(f"{RUN}/{T}"):
            if other is not t:
                set_t(other, "")
        set_t(t, text.strip())
        self._append(p)

    def build(self, spec: dict, out_path: str):
        self.set_cover(spec.get("title", ""), spec.get("department", ""), spec.get("date", ""))
        for b in spec.get("blocks", []):
            kind = b.get("type")
            if kind == "heading":
                self.heading(b.get("text", ""))
            elif kind in ("item", "sub", "note", "text"):
                self.item(b.get("text", ""), "item" if kind == "text" else kind)
            elif kind == "table":
                self.table(b.get("columns", []), b.get("rows", []))
            elif kind == "blank":
                self.blank()
        att = spec.get("attachment", "")
        if att:
            self.ending(f"붙임  {att.rstrip('.')}.  끝." if not att.startswith("붙임") else att)
        self.doc.save(out_path)


def read_preview_png(path: str) -> bytes | None:
    """hwpx 안에 저장된 미리보기 이미지(첫 쪽)."""
    try:
        with zipfile.ZipFile(path) as z:
            return z.read("Preview/PrvImage.png")
    except Exception:
        return None
