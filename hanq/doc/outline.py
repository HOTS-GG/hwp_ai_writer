"""문서를 AI가 가리킬 수 있는 번호와 개요 글로 정리한다.

  [S번호]  줄 하나 (한 줄 안에 글자 모양이 여러 개여도 번호는 하나), 또는 빈 표 칸
  [E번호]  양식의 예시 문장 (빈칸 양식에서만)
  [T번호]  표의 반복 데이터 행 묶음
  [H번호]  장 제목 번호 상자
  [B번호]  표 틀 (수정 모드)
  [I번호]  그림·글상자·도형 (수정 모드)
  [Q번호]  수식 (수정 모드)

수정 모드에서는 AI가 문서를 '읽을' 수 있게 용지·기본 글자 모양 요약, 줄마다 기본과 다른 모양(〔16pt 굵게 가운데〕),
머리말·꼬리말·각주·글상자 표시, 칸 위치도 함께 적는다.
"""
import collections
import re

from .document import HwpxDocument
from .xml import (CELLADDR, CELLSPAN, HWPUNIT_PER_MM, NUMBER_ONLY, P, PIC, PLACEHOLDER, RUN, SUBLIST, SZ, T, TBL, TC,
                  TR, cell_lines, cell_text, ensure_t, has_objects, has_secpr, heading_parts, hh, hp, is_blank,
                  para_text, t_text)

CELL_PREFIX = "  │ "
# 예시문은 본문 항목 줄만 (1. 가. ❍ □ ※ 붙임 …). 서명란·'○○학교장 귀하'·공문 끝의 기안자·시행 줄은 고정
_LIST_ITEM = re.compile(r"\s*(\d+[.)]|[가-하][.)]|[❍□○※*\-·▪■◦•]|붙임)")
EQUATION = hp("equation")
# 본문 밖의 글이 든 곳 → 줄 앞에 붙이는 표시
_PLACES = {hp("header"): "머리말", hp("footer"): "꼬리말", hp("footNote"): "각주", hp("endNote"): "미주",
           hp("drawText"): "글상자"}
_SHAPES = {"pic": "그림", "container": "묶음 개체", "rect": "사각형", "ellipse": "원", "line": "선", "connectLine": "선",
           "arc": "호", "polygon": "다각형", "curve": "곡선", "textart": "글맵시", "ole": "OLE 개체", "chart": "차트",
           "video": "동영상"}
_ALIGN = {"LEFT": "왼쪽", "CENTER": "가운데", "RIGHT": "오른쪽", "DISTRIBUTE": "배분", "DISTRIBUTE_SPACE": "나눔"}
# AI가 줄을 돌려줄 때 개요의 표시(모양·위치·장소)를 그대로 베껴 오는 경우가 있어 걷어 낸다
_ECHO = re.compile(r"^\s*(?:(?:〔[^〕]*〕|\(\d+행 \d+열[^)]*\)|\((?:머리말|꼬리말|각주|미주|글상자|빈 칸|빈 줄|예시문|고정)\))\s?)+")


def clean_value(value: str) -> str:
    """AI가 돌려준 줄에서 개요 표시(〔모양〕, (2행 1열), (각주) …)를 뗀다. 원래 글의 앞 공백은 지킨다."""
    m = _ECHO.match(value)
    return value[m.end():] if m else value


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
        self.equations: dict[str, object] = {}  # Q번호 → 수식(hp:equation)
        self._out: list[str] = []
        self._chars: dict[str, dict] = {}       # 글자 모양 id → 읽기 쉬운 값
        self._paras: dict[str, dict] = {}
        self._base = self._base_style() if edit else None
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
        if edit:
            self._out[0:0] = self._summary()
        self.text = "\n".join(self._out)

    # ── 조회 ────────────────────────────────────────────────────────────
    @property
    def fill_count(self) -> int:
        return sum(1 for k in self.lines if k.startswith("S"))

    def ref_kind(self, ref: str) -> str | None:
        ref = str(ref).strip()
        for kind, table in (("line", self.lines), ("table", self.tables), ("heading", self.headings),
                            ("box", self.boxes), ("image", self.images), ("equation", self.equations)):
            if ref in table:
                return kind
        return None

    def has(self, ref) -> bool:
        return self.ref_kind(ref) is not None

    # ── 만들기 ──────────────────────────────────────────────────────────
    def _add_line(self, p, label: str, prefix: str, kind: str = "S") -> str:
        lid = f"{kind}{len(self.lines) + 1}"
        self.lines[lid] = p
        self._out.append(f"{prefix}[{lid}] {self._hint(p)}{label}")
        return lid

    # ── 모양 읽기 (수정 모드) ────────────────────────────────────────────
    def _char(self, cid: str) -> dict:
        if cid not in self._chars:
            head = self.doc.header_root()
            cp = next((c for c in head.iter(hh("charPr")) if c.get("id") == cid), None)
            d = {}
            if cp is not None:
                ref, ul, so = cp.find(hh("fontRef")), cp.find(hh("underline")), cp.find(hh("strikeout"))
                face = ""
                if ref is not None:
                    ff = next((f for f in head.iter(hh("fontface")) if f.get("lang") == "HANGUL"), None)
                    font = next((f for f in ff if f.get("id") == ref.get("hangul")), None) if ff is not None else None
                    face = font.get("face", "") if font is not None else ""
                sp, ra = cp.find(hh("spacing")), cp.find(hh("ratio"))
                d = {"font": face, "size": int(cp.get("height", "1000")) / 100,
                     "bold": cp.find(hh("bold")) is not None, "italic": cp.find(hh("italic")) is not None,
                     "underline": ul is not None and ul.get("type", "NONE") != "NONE",
                     "strike": so is not None and so.get("shape", "NONE") not in ("NONE", ""),
                     "color": (cp.get("textColor") or "#000000").upper(),
                     "background": (cp.get("shadeColor") or "none").upper(),
                     "spacing": int(sp.get("hangul", "0")) if sp is not None else 0,
                     "ratio": int(ra.get("hangul", "100")) if ra is not None else 100,
                     "super": cp.find(hh("supscript")) is not None, "sub": cp.find(hh("subscript")) is not None}
            self._chars[cid] = d
        return self._chars[cid]

    def _para(self, pid: str) -> dict:
        if pid not in self._paras:
            pp = next((c for c in self.doc.header_root().iter(hh("paraPr")) if c.get("id") == pid), None)
            d = {}
            if pp is not None:
                al, ls = pp.find(hh("align")), next(pp.iter(hh("lineSpacing")), None)
                d = {"align": al.get("horizontal", "JUSTIFY") if al is not None else "JUSTIFY",
                     "line": int(ls.get("value", "160")) if ls is not None and ls.get("type") == "PERCENT" else 0}
            self._paras[pid] = d
        return self._paras[pid]

    def _base_style(self) -> dict:
        """본문에서 가장 많이 쓰인 글자·문단 모양 (이것과 다른 줄만 모양을 적는다)."""
        chars, paras = collections.Counter(), collections.Counter()
        for p in self.doc.top_paragraphs():
            n = len(para_text(p).strip())
            run = next((r for r in p.iterfind(RUN) if r.find(T) is not None), None)
            if n and run is not None:
                chars[run.get("charPrIDRef", "0")] += n
                paras[p.get("paraPrIDRef", "0")] += n
        c = self._char(chars.most_common(1)[0][0]) if chars else {}
        return {**c, **(self._para(paras.most_common(1)[0][0]) if paras else {})}

    @staticmethod
    def _char_diff(c: dict, base: dict) -> list[str]:
        out = []
        if c.get("font") and c.get("font") != base.get("font"):
            out.append(c["font"])
        if c.get("size") and c.get("size") != base.get("size"):
            out.append(f"{c['size']:g}pt")
        for key, word in (("bold", "굵게"), ("italic", "기울임"), ("underline", "밑줄"), ("strike", "취소선"),
                          ("super", "위 첨자"), ("sub", "아래 첨자")):
            if c.get(key) and not base.get(key):
                out.append(word)
            elif base.get(key) and not c.get(key) and key == "bold":
                out.append("굵지 않게")
        if c.get("color", "#000000") != base.get("color", "#000000"):
            out.append(f"글자색 {c['color']}")
        if c.get("background", "NONE") not in ("NONE", base.get("background", "NONE")):
            out.append(f"배경 {c['background']}")
        if abs(c.get("spacing", 0) - base.get("spacing", 0)) >= 10:
            out.append(f"자간 {c['spacing']}%")
        if abs(c.get("ratio", 100) - base.get("ratio", 100)) >= 10:
            out.append(f"장평 {c['ratio']}%")
        return out

    def _hint(self, p) -> str:
        """그 줄이 본문 기본 모양과 다른 점: 〔16pt 굵게 가운데, 일부 '안전' 글자색 #FF0000〕"""
        if not self.edit or not self._base:
            return ""
        runs = [(r.get("charPrIDRef", "0"), "".join(t_text(t) for t in r.iterfind(T))) for r in p.iterfind(RUN)]
        runs = [(cid, txt) for cid, txt in runs if txt.strip()]
        if not runs:
            return ""
        main = max(runs, key=lambda r: len(r[1]))[0]
        out = self._char_diff(self._char(main), self._base)
        pr = self._para(p.get("paraPrIDRef", "0"))
        if pr.get("align") and pr["align"] != self._base.get("align") and pr["align"] in _ALIGN:
            out.append(_ALIGN[pr["align"]])
        if pr.get("line") and self._base.get("line") and abs(pr["line"] - self._base["line"]) >= 20:
            out.append(f"줄 간격 {pr['line']}%")
        parts = []
        for cid, txt in runs:
            diff = self._char_diff(self._char(cid), self._char(main)) if cid != main else []
            if diff and len(parts) < 3:
                parts.append(f"일부 '{txt.strip()[:12]}' {' '.join(diff)}")
        text = ", ".join([" ".join(out)] * bool(out) + parts)
        return f"〔{text}〕 " if text else ""

    def _summary(self) -> list[str]:
        """문서 맨 위에 적는 용지·쪽 설정과 본문 기본 모양."""
        out = []
        first = self.doc.ordered_sections()[0]
        page = first.find(f".//{hp('pagePr')}")
        margin = page.find(hp("margin")) if page is not None else None
        if margin is not None:
            w, h = int(page.get("width", "0")), int(page.get("height", "0"))
            wide = page.get("landscape") == "NARROWLY" or w > h
            size = "A4" if {round(w / HWPUNIT_PER_MM), round(h / HWPUNIT_PER_MM)} == {210, 297} else (
                f"{w / HWPUNIT_PER_MM:.0f}×{h / HWPUNIT_PER_MM:.0f}mm")
            mm = {k: round(int(margin.get(k, "0")) / HWPUNIT_PER_MM) for k in ("top", "bottom", "left", "right")}
            col = next(first.iter(hp("colPr")), None)
            cols = int(col.get("colCount", "1")) if col is not None else 1
            num = next(first.iter(hp("pageNum")), None)
            bits = [f"용지 {size} {'가로' if wide else '세로'}",
                    f"여백 위 {mm['top']}·아래 {mm['bottom']}·왼쪽 {mm['left']}·오른쪽 {mm['right']}mm",
                    f"{cols}단" if cols > 1 else "한 단",
                    f"쪽 번호 {num.get('pos', '').lower()}" if num is not None else "쪽 번호 없음"]
            for tag, name in (("header", "머리말"), ("footer", "꼬리말")):
                if next(first.iter(hp(tag)), None) is not None:
                    bits.append(f"{name} 있음")
            notes = sum(1 for _ in first.iter(hp("footNote")))
            if notes:
                bits.append(f"각주 {notes}개")
            out.append("(문서 설정: " + ", ".join(bits) + ")")
        b = self._base or {}
        if b.get("size"):
            out.append(f"(본문 기본 모양: {b.get('font') or '글꼴 모름'} {b['size']:g}pt, "
                       f"{_ALIGN.get(b.get('align'), '양쪽')} 정렬, 줄 간격 {b.get('line') or '?'}%"
                       " — 줄 앞의 〔 〕는 이 기본과 다른 점)")
        return out

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

    def _walk(self, container, prefix: str, place: str = ""):
        """place: 본문 밖의 글(머리말·꼬리말·각주·미주·글상자)이면 그 이름 — 줄 앞에 표시한다."""
        top_level = container.getparent() is None
        mark = f"({place}) " if place else ""
        # 빈 표 칸도 채울 수 있게 내놓는다 (○ 빈칸이 없는 양식·수정 모드)
        if container.tag == SUBLIST and (self.edit or not self.has_placeholders):
            ps = container.findall(P)
            if ps and not any(para_text(p).strip() for p in ps) and not any(has_objects(p) for p in ps):
                ensure_t(ps[0])
                self.empty_cells.add(self._add_line(ps[0], f"{mark}(빈 칸)", prefix))
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
                    self._add_line(p, mark + text, prefix)
                elif (len(text.strip()) >= 10 and not prefix and not place and self._in_body
                      and _LIST_ITEM.match(text)):
                    self._add_line(p, f"(예시문) {text}", prefix, kind="E")
                else:
                    self._out.append(f"{prefix}(고정) {mark}{text}")
            for run in p.iterfind(RUN):
                for c in run:
                    if c.tag == T:
                        continue
                    if self.edit and c.tag == EQUATION:
                        qid = f"Q{len(self.equations) + 1}"
                        self.equations[qid] = c
                        self._out.append(f"{prefix}[{qid}] (수식) {(c.findtext(hp('script')) or '').strip()}")
                        continue
                    if self.edit and c.tag != TBL and c.find(SZ) is not None:
                        self._add_image(c, prefix)
                    if self.edit and c.tag == hp("ctrl"):
                        self._note_ctrl(c, prefix)
                    self._scan_obj(c, prefix)

    def _note_ctrl(self, ctrl, prefix: str):
        """글자 사이에 든 조판 부호 가운데 AI가 알아야 할 것: 하이퍼링크 주소."""
        for field in ctrl.iterfind(hp("fieldBegin")):
            if field.get("type") == "HYPERLINK":
                url = next((sp.text for sp in field.iter(hp("stringParam")) if sp.get("name") == "Path"), "") or ""
                self._out.append(f"{prefix}    (위 줄에 하이퍼링크: {url})")

    def _add_image(self, obj, prefix):
        """그림·글상자·도형 하나 (지우기·크기 바꾸기·앞뒤에 끼워 넣기의 기준이 된다)."""
        iid = f"I{len(self.images) + 1}"
        self.images[iid] = obj
        sz = obj.find(SZ)
        w = int(sz.get("width", "0") or 0) if sz is not None else 0
        h = int(sz.get("height", "0") or 0) if sz is not None else 0
        size = f" 약 {w / HWPUNIT_PER_MM:.0f}×{h / HWPUNIT_PER_MM:.0f}mm" if w and h else ""
        tag = obj.tag.rsplit("}", 1)[-1]
        kind = _SHAPES.get(tag, "개체")
        if obj.find(f".//{hp('drawText')}") is not None:
            kind = "글상자" if tag == "rect" else f"글이 든 {kind}"
        elif tag == "container" and obj.find(f".//{PIC}") is not None:
            kind = "그림 묶음"
        pos = obj.find(hp("pos"))
        floating = "" if pos is None or pos.get("treatAsChar") == "1" else ", 자리 고정"
        down = " ↓" if obj.find(f".//{SUBLIST}") is not None else ""
        self._out.append(f"{prefix}[{iid}] ({kind}{size}{floating}){down}")

    def _scan_obj(self, e, prefix, place: str = ""):
        if e.tag == TBL:
            self._table(e, prefix)
        elif e.tag == SUBLIST:
            self._walk(e, prefix + (CELL_PREFIX if place == "글상자" else ""), place)
        else:
            place = _PLACES.get(e.tag, place)
            for c in e:
                self._scan_obj(c, prefix, place)

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
            # 그림·수식·각주가 든 칸은 줄 단위([S])로 내놓는다 — 행을 통째로 다시 쓰면 그 개체가 사라진다
            if self.edit and any(has_objects(p) for p in tc.iter(P)):
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
                rows = f" ({i + 1}~{j + 1}행)" if self.edit else ""
                self._out.append(f"{prefix}[{gid}] 표 — 열 {group.ncols}개{rows}: " + " | ".join(header))
                label = "행" if self.edit else "예시행"
                read = cell_lines if self.edit else cell_text
                for tr in group.trs:
                    self._out.append(f"{prefix}    {label}: " + " | ".join(read(tc) for tc in tr.findall(TC)))
                i = j + 1
                continue
            for tc in trs[i].findall(TC):
                if tc in self._heading_num_cells:
                    continue
                sl = tc.find(SUBLIST)
                if sl is not None:
                    at = len(self._out)
                    self._walk(sl, prefix + CELL_PREFIX)
                    self._mark_cell(tc, at, prefix + CELL_PREFIX)
            i += 1

    def _mark_cell(self, tc, at: int, prefix: str):
        """수정 모드: 칸의 첫 줄에 (행,열)과 합쳐진 크기를 적는다 — 칸 합치기·나누기에서 칸을 가리킬 수 있게."""
        addr, span = tc.find(CELLADDR), tc.find(CELLSPAN)
        if not self.edit or addr is None or at >= len(self._out) or not self._out[at].startswith(prefix):
            return
        tag = f"({int(addr.get('rowAddr', '0')) + 1}행 {int(addr.get('colAddr', '0')) + 1}열"
        if span is not None and (span.get("rowSpan", "1") != "1" or span.get("colSpan", "1") != "1"):
            tag += f", {span.get('rowSpan', '1')}행×{span.get('colSpan', '1')}열 합침"
        bf = self._fill_of(tc.get("borderFillIDRef", ""))
        if bf:
            tag += f", 배경 {bf}"
        self._out[at] = f"{prefix}{tag}) {self._out[at][len(prefix):]}"

    def _fill_of(self, bf_id: str) -> str:
        """칸 배경색 (없으면 "")."""
        key = "bf" + bf_id
        if key not in self._chars:
            bf = next((b for b in self.doc.header_root().iter(hh("borderFill")) if b.get("id") == bf_id), None)
            wb = next(bf.iter("{http://www.hancom.co.kr/hwpml/2011/core}winBrush"), None) if bf is not None else None
            color = (wb.get("faceColor") or "none").upper() if wb is not None else "NONE"
            self._chars[key] = "" if color in ("NONE", "#FFFFFF") else color
        return self._chars[key]
