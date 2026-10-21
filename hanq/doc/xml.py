"""HWPX(OWPML) XML 이름과 글자·문단·표 칸을 다루는 작은 도우미들.

문단(hp:p) 안에는 글자 모양마다 run(hp:run)이 있고, run 안의 hp:t에 글자가 들어 있다.
한 줄의 글자를 바꿀 때는 set_para_text()로 줄 전체를 한 번에 바꾼다.
"""
import copy
import random
import re

from lxml import etree

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
HC = "http://www.hancom.co.kr/hwpml/2011/core"


def hp(name: str) -> str:
    return f"{{{HP}}}{name}"


def hh(name: str) -> str:
    return f"{{{HH}}}{name}"


P, RUN, T, TBL, TR, TC = (hp(n) for n in ("p", "run", "t", "tbl", "tr", "tc"))
SUBLIST, CELLADDR, CELLSPAN, CELLSZ, SZ = (hp(n) for n in ("subList", "cellAddr", "cellSpan", "cellSz", "sz"))
LINESEG, PIC, SECPR, DRAWTEXT = hp("linesegarray"), hp("pic"), hp("secPr"), hp("drawText")
TEXT_PATH = f"{RUN}/{T}"

HWPUNIT_PER_MM = 7200 / 25.4
ROMAN = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ"

# 양식의 빈칸 표시: ○○○○, {{이름}}, ___, ＯＯ, OOO
PLACEHOLDER = re.compile(r"[○◯]|\{\{[^}]*\}\}|_{3,}|ＯＯ|OOO")
NUMBER_ONLY = re.compile(r"^\s*\d+\s*$")
HEAD_NUM = re.compile(rf"^\s*(\d+|[{ROMAN}])\s*$")

# 본문 줄 앞의 기호 종류 → 그 종류의 줄 모양(문단)을 문서에서 찾아 복제한다
MARKERS = [
    ("num", re.compile(r"^\d+\.\s")), ("ga", re.compile(r"^[가-힣]\.\s")),
    ("paren_num", re.compile(r"^\(\d+\)")), ("paren_ga", re.compile(r"^\([가-힣]\)")),
    ("circle", re.compile(r"^[①-⑳]")), ("box", re.compile(r"^[□■]")),
    ("bullet", re.compile(r"^[❍◦●○]\s")), ("diamond", re.compile(r"^[◇◆]")),
    ("dash", re.compile(r"^[-–]\s")), ("star", re.compile(r"^\*")),
    ("note", re.compile(r"^※")), ("dot", re.compile(r"^[‣•·￭▪]")),
]

ALIGNS = {"left": "LEFT", "center": "CENTER", "right": "RIGHT", "justify": "JUSTIFY", "distribute": "DISTRIBUTE",
          "왼쪽": "LEFT", "가운데": "CENTER", "오른쪽": "RIGHT", "양쪽": "JUSTIFY", "배분": "DISTRIBUTE"}

COLOR_NAMES = {"빨강": "#FF0000", "빨간": "#FF0000", "red": "#FF0000", "파랑": "#0000FF", "파란": "#0000FF",
               "blue": "#0000FF", "검정": "#000000", "black": "#000000", "초록": "#008000", "green": "#008000",
               "노랑": "#FFFF00", "yellow": "#FFFF00", "주황": "#FF8C00", "orange": "#FF8C00",
               "보라": "#800080", "회색": "#808080", "gray": "#808080"}


def marker_of(text: str) -> str:
    s = text.strip()
    for name, rx in MARKERS:
        if rx.match(s):
            return name
    return "text"


def hex_color(c) -> str:
    c = str(c).strip()
    if c in COLOR_NAMES:
        return COLOR_NAMES[c]
    if re.fullmatch(r"#?[0-9a-fA-F]{6}", c):
        return "#" + c.lstrip("#").upper()
    return "#000000"


def new_id() -> str:
    return str(random.randint(1_800_000_000, 2_100_000_000))


def leading_ws(s: str) -> str:
    return s[: len(s) - len(s.lstrip())]


# ── 글자 (hp:t) ────────────────────────────────────────────────────────────

def t_text(t) -> str:
    return "".join(t.itertext())


def set_t(t, text: str):
    if t_text(t) == text and not len(t):
        return
    for c in list(t):
        t.remove(c)
    t.text = text
    run = t.getparent()
    if run is not None and run.getparent() is not None:
        mark_changed(run.getparent())


def mark_changed(p):
    """글자·모양이 바뀐 문단: 그 문단의 줄 배치 정보만 지워 한글·rhwp가 다시 계산하게 한다.
    (바뀌지 않은 문단의 줄 배치는 원본 그대로 둬야 도형·글상자 위치가 원본과 같게 나온다)"""
    if p is None or p.tag != P:
        return
    for ls in p.findall(LINESEG):
        p.remove(ls)


def ensure_t(p):
    """문단의 첫 글자 칸(hp:t). 없으면 만든다."""
    run = p.find(RUN)
    if run is None:
        run = etree.SubElement(p, RUN)
        run.set("charPrIDRef", "0")
    t = run.find(T)
    if t is None:
        t = etree.SubElement(run, T)
    return t


# ── 문단 (hp:p) ────────────────────────────────────────────────────────────

def para_text(p) -> str:
    """문단 바로 아래 run의 글자만 (표 칸·글상자 안의 글자는 빼고)."""
    return "".join(t_text(t) for t in p.iterfind(TEXT_PATH))


def has_objects(p) -> bool:
    """문단에 표·그림·글상자 같은 개체가 있는지."""
    for run in p.iterfind(RUN):
        for c in run:
            if c.tag != T:
                return True
    return False


def is_blank(p) -> bool:
    return not para_text(p).strip() and not has_objects(p)


def has_secpr(p) -> bool:
    """문서 설정(쪽 크기·여백)이 든 문단. 지우면 문서가 깨진다."""
    return p.find(f".//{SECPR}") is not None


def set_para_text(p, text: str):
    """줄 전체 글자를 text로 바꾼다.

    한 줄이 글자 모양별로 여러 조각(run)이면, 앞쪽 조각 중 새 글자의 앞부분과 똑같은 조각
    (예: 굵은 '□ ' 기호)은 모양째 그대로 두고, 나머지 글자는 그다음 조각에 넣고 남은 조각은 비운다.
    """
    ts = list(p.iterfind(TEXT_PATH))
    if not ts:
        set_t(ensure_t(p), text)
        return
    rest, i = text, 0
    while i < len(ts) - 1:
        cur = t_text(ts[i])
        if cur and rest.startswith(cur) and len(rest) > len(cur):
            rest = rest[len(cur):]
            i += 1
        else:
            break
    set_t(ts[i], rest)
    for t in ts[i + 1:]:
        set_t(t, "")


def clone_line(proto, text: str):
    """proto 줄의 모양을 복제해 text를 넣은 새 줄. 원래 줄의 앞쪽 들여쓰기 공백은 유지한다."""
    p = copy.deepcopy(proto)
    strip_lineseg(p)
    ts = p.findall(TEXT_PATH)
    indent = leading_ws(t_text(ts[0])) if ts else ""
    set_para_text(p, indent + text.strip())
    return p


def strip_lineseg(e):
    """줄 배치 정보(linesegarray)를 지운다. 한글이 열 때 다시 계산한다."""
    for ls in list(e.iter(LINESEG)):
        ls.getparent().remove(ls)


def top_para(e):
    """요소가 든 본문 문단(섹션 바로 아래 문단)."""
    top = None
    while e is not None:
        if e.tag == P:
            top = e
        if e.getparent() is None:
            break
        e = e.getparent()
    return top


def drop_if_empty(p):
    """글자도 개체도 없는 줄이면 지운다. 표 칸의 마지막 줄과 문서 설정 줄은 남긴다."""
    parent = p.getparent()
    if parent is None or has_objects(p) or para_text(p).strip():
        return
    if parent.tag == SUBLIST and len(parent.findall(P)) <= 1:
        return
    if has_secpr(p):
        return
    parent.remove(p)


# ── 표 칸 (hp:tc) ──────────────────────────────────────────────────────────

def cell_text(tc) -> str:
    sl = tc.find(SUBLIST)
    if sl is None:
        return ""
    return " ".join(para_text(p).strip() for p in sl.iterchildren(P)).strip()


def set_cell(tc, text: str):
    """칸의 글자를 text로 바꾼다. 여러 줄이면 첫 줄 모양을 복제해 이어 붙인다."""
    sl = tc.find(SUBLIST)
    ps = sl.findall(P)
    first = ps[0]
    for extra in ps[1:]:
        sl.remove(extra)
    lines = str(text).split("\n")
    set_para_text(first, lines[0])
    anchor = first
    for line in lines[1:]:
        np_ = copy.deepcopy(first)
        set_para_text(np_, line)
        anchor.addnext(np_)
        anchor = np_


def heading_parts(p):
    """장 제목 번호 상자(한 줄 표: 번호 | … | 제목)면 (표, 번호 칸, 제목 칸)을, 아니면 None."""
    if p is None or p.tag != P:
        return None
    tbl = p.find(f"{RUN}/{TBL}")
    if tbl is None:
        return None
    trs = tbl.findall(TR)
    if len(trs) != 1:
        return None
    cells = trs[0].findall(TC)
    if len(cells) < 2 or not HEAD_NUM.match(cell_text(cells[0])):
        return None
    title = next((c for c in reversed(cells[1:]) if cell_text(c)), None)
    if title is None:
        return None
    return tbl, cells[0], title


def renumber_table(tbl):
    """행 번호(rowAddr)·행 수·표 높이를 실제 행에 맞춘다."""
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


def is_simple_table_para(p) -> bool:
    """칸 합치기가 없고 2행 2열 이상인 표가 든 문단 (새 표의 본보기로 쓸 수 있는 표)."""
    tbl = p.find(f"{RUN}/{TBL}")
    if tbl is None or int(tbl.get("rowCnt", "0")) < 2 or int(tbl.get("colCnt", "0")) < 2:
        return False
    if heading_parts(p) is not None:
        return False
    for span in tbl.iter(CELLSPAN):
        if span.get("rowSpan") != "1" or span.get("colSpan") != "1":
            return False
    return tbl.find(f".//{TR}//{TBL}") is None


def build_table_paragraph(proto_p, columns: list, rows: list):
    """표가 든 문단(머리행 + 데이터 행)을 복제해 열·행 수가 다른 새 표 문단을 만든다."""
    n = len(columns)
    p = copy.deepcopy(proto_p)
    strip_lineseg(p)
    tbl = p.find(f"{RUN}/{TBL}")
    tbl.set("id", new_id())
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
            set_cell(tc, str(texts[j]) if j < len(texts) else "")
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
    renumber_table(tbl)
    return p
