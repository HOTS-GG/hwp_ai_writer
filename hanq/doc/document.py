"""HWPX 파일(zip)을 열고 저장한다. 본문 섹션과 header(글자·문단 모양 목록)를 lxml 트리로 들고 있다."""
import copy
import io
import re
import zipfile

from lxml import etree

from .xml import (ALIGNS, HWPUNIT_PER_MM, P, RUN, SUBLIST, T, TBL, TC, TR, cell_text, hc, hex_color, hh, hp,
                  para_text)


def _num(v) -> float | None:
    """AI가 준 숫자 ('12', '12pt', 12.5). 숫자가 아니면 None."""
    if isinstance(v, bool) or v is None:
        return None
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)", str(v))
    return float(m.group(1)) if m else None


HEADER_NAME = "Contents/header.xml"
SECTION_RE = re.compile(r"^Contents/section\d+\.xml$")
_PARSER = etree.XMLParser(remove_blank_text=False, huge_tree=True)


class HwpxDocument:
    def __init__(self, path: str | None = None, data: bytes | None = None):
        self.path = path
        src = io.BytesIO(data) if data is not None else path
        with zipfile.ZipFile(src) as z:
            self._items = [(i, z.read(i.filename)) for i in z.infolist()]
        self.sections = {i.filename: etree.fromstring(d, _PARSER)
                         for i, d in self._items if SECTION_RE.match(i.filename)}
        if not self.sections:
            raise ValueError("HWPX 본문(Contents/section0.xml)이 없습니다.")
        self._header = None
        self._variant_cache: dict = {}

    @classmethod
    def from_bytes(cls, data: bytes) -> "HwpxDocument":
        return cls(data=data)

    # ── 저장 ────────────────────────────────────────────────────────────
    def to_bytes(self) -> bytes:
        buf = io.BytesIO()
        self._write(buf)
        return buf.getvalue()

    def save(self, out_path: str):
        with open(out_path, "wb") as f:
            self._write(f)

    def _write(self, fp):
        with zipfile.ZipFile(fp, "w", zipfile.ZIP_DEFLATED) as z:
            for info, data in self._items:
                name = info.filename
                if name in self.sections:
                    # 줄 배치 정보는 바뀐 문단에서만 지운다 (xml.mark_changed) — 나머지는 원본 그대로
                    root = self.sections[name]
                    data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
                elif name == HEADER_NAME and self._header is not None:
                    data = etree.tostring(self._header, xml_declaration=True, encoding="UTF-8", standalone=True)
                elif name == "Preview/PrvText.txt":
                    data = self.plain_text()[:1000].encode("utf-8")
                zi = zipfile.ZipInfo(name, date_time=info.date_time)
                zi.compress_type = zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
                z.writestr(zi, data)

    def snapshot(self) -> bytes:
        """본문 XML 전체. 수정 전후를 비교해 실제로 바뀐 게 있는지 본다."""
        return b"".join(etree.tostring(r) for r in self.ordered_sections())

    def read_item(self, name: str) -> bytes | None:
        return next((d for i, d in self._items if i.filename == name), None)

    # ── 본문 ────────────────────────────────────────────────────────────
    def ordered_sections(self) -> list:
        """section0, section1, … 순서(숫자 기준)의 섹션 루트 목록."""
        return [self.sections[k] for k in sorted(self.sections, key=lambda n: int(re.search(r"\d+", n).group()))]

    def top_paragraphs(self):
        """섹션 바로 아래의 본문 문단을 차례로."""
        for root in self.ordered_sections():
            yield from root.iterchildren(P)

    def plain_text(self) -> str:
        lines = []
        for root in self.ordered_sections():
            for p in root.iter(P):
                s = para_text(p)
                if s.strip():
                    lines.append(s.rstrip())
        return "\n".join(lines)

    def structured_text(self) -> str:
        """참고 자료용 글: 본문 줄은 그대로, 표는 행마다 '| 칸 | 칸 |' 한 줄로 (구조 보존)."""
        out: list[str] = []

        def para(p, depth):
            s = para_text(p).rstrip()
            if s.strip():
                out.append(s)
            for run in p.iterfind(RUN):
                for obj in run:
                    if obj.tag == TBL:
                        table(obj, depth)
                    elif obj.tag != T:
                        for sp in obj.iter(P):  # 글상자 안의 글
                            s2 = para_text(sp).strip()
                            if s2:
                                out.append(s2)

        def table(tbl, depth):
            if depth > 3:
                return
            for tr in tbl.iterfind(TR):
                cells = [cell_text(tc) for tc in tr.iterfind(TC)]
                if any(c.strip() for c in cells):
                    out.append("| " + " | ".join(cells) + " |")
                # 칸 안에 든 표는 그 행 아래에 이어서
                for tc in tr.iterfind(TC):
                    for nested in tc.iterfind(f"{SUBLIST}/{P}/{RUN}/{TBL}"):
                        table(nested, depth + 1)

        for p in self.top_paragraphs():
            para(p, 0)
        return "\n".join(out)

    # ── header: 글자·문단·테두리 모양 복제 ────────────────────────────────
    def header_root(self):
        if self._header is None:
            self._header = etree.fromstring(self.read_item(HEADER_NAME), _PARSER)
        return self._header

    def _variant(self, list_tag: str, item_tag: str, base_id: str, key, change) -> str:
        """header 목록(list_tag)에서 base_id 항목을 복제해 change(복제본)로 고친 새 항목의 id."""
        cache_key = (item_tag, base_id, key)
        if cache_key in self._variant_cache:
            return self._variant_cache[cache_key]
        props = self.header_root().find(f".//{hh(list_tag)}")
        items = props.findall(hh(item_tag))
        base = next((c for c in items if c.get("id") == base_id), items[0])
        new = copy.deepcopy(base)
        new_id = str(max(int(c.get("id")) for c in items) + 1)
        new.set("id", new_id)
        change(new)
        props.append(new)
        props.set("itemCnt", str(len(items) + 1))
        self._variant_cache[cache_key] = new_id
        return new_id

    def charpr_variant(self, base_id: str, style: dict) -> str:
        """글자 모양(base_id)을 복제해 style(color, background, size, bold, italic, underline)만 바꾼 id."""
        def change(cp):
            def flag(tag, on):
                el = cp.find(hh(tag))
                if on and el is None:
                    el = etree.Element(hh(tag))
                    anchor = cp.find(hh("underline"))
                    if anchor is not None:
                        anchor.addprevious(el)
                    else:
                        cp.append(el)
                elif not on and el is not None:
                    cp.remove(el)
            if style.get("color"):
                cp.set("textColor", hex_color(style["color"]))
            if style.get("background"):
                cp.set("shadeColor", hex_color(style["background"]))
            if style.get("size"):
                cp.set("height", str(int(float(style["size"]) * 100)))
            if "bold" in style:
                flag("bold", bool(style["bold"]))
            if "italic" in style:
                flag("italic", bool(style["italic"]))
            if "underline" in style:
                ul = cp.find(hh("underline"))
                if ul is None and style["underline"]:
                    ul = etree.Element(hh("underline"), shape="SOLID", color="#000000")
                    anchor = cp.find(hh("strikeout"))
                    anchor.addprevious(ul) if anchor is not None else cp.append(ul)
                if ul is not None:
                    ul.set("type", "BOTTOM" if style["underline"] else "NONE")
                    if style.get("color"):
                        ul.set("color", hex_color(style["color"]))
            if "strike" in style:   # 취소선
                so = cp.find(hh("strikeout"))
                if so is None:
                    so = etree.Element(hh("strikeout"), color="#000000")
                    anchor = cp.find(hh("outline"))
                    anchor.addprevious(so) if anchor is not None else cp.append(so)
                so.set("shape", "SOLID" if style["strike"] else "NONE")
            for key_, tag in (("superscript", "supscript"), ("subscript", "subscript")):   # 위 첨자·아래 첨자
                if key_ in style:
                    for other in ("supscript", "subscript"):   # 둘은 함께 쓸 수 없다
                        el = cp.find(hh(other))
                        if el is not None:
                            cp.remove(el)
                    if style[key_]:
                        cp.append(etree.Element(hh(tag)))
            # 자간(spacing, -50~50%)·장평(ratio, 50~200%): 한글·영문 등 모든 글자 종류에 같이 적용
            for key_, tag, lo, hi in (("spacing", "spacing", -50, 50), ("ratio", "ratio", 50, 200)):
                v = _num(style.get(key_))
                el = cp.find(hh(tag))
                if v is not None and el is not None:
                    for lang in el.attrib:
                        el.set(lang, str(int(max(lo, min(hi, v)))))
            if style.get("font"):
                ref = cp.find(hh("fontRef"))
                if ref is not None:
                    for lang in list(ref.attrib):
                        ref.set(lang, self.font_id(lang, str(style["font"]).strip()))
        key = tuple(sorted((k, str(v)) for k, v in style.items()))
        return self._variant("charProperties", "charPr", base_id, key, change)

    def font_id(self, lang: str, face: str) -> str:
        """글꼴 이름의 id (글자 종류 lang: hangul·latin …). 문서 글꼴 목록에 없으면 목록에 더한다."""
        ff = next((f for f in self.header_root().iter(hh("fontface")) if f.get("lang", "").lower() == lang.lower()),
                  None)
        if ff is None:
            return "0"
        fonts = ff.findall(hh("font"))
        for f in fonts:
            if f.get("face") == face:
                return f.get("id")
        new = etree.SubElement(ff, hh("font"), id=str(max((int(f.get("id")) for f in fonts), default=-1) + 1),
                               face=face, type="TTF", isEmbedded="0")
        ff.set("fontCnt", str(len(fonts) + 1))
        return new.get("id")

    def parapr_variant(self, base_id: str, para: dict) -> str:
        """문단 모양을 복제해 정렬(align), 줄 간격(line_spacing %), 문단 위·아래 간격(space_before/after pt),
        왼쪽·오른쪽 여백(left_margin/right_margin pt), 첫 줄 들여쓰기(indent pt, 음수면 내어쓰기)만 바꾼 id."""
        def change(pp):
            align = str(para.get("align", "")).strip().lower()
            if align in ALIGNS:
                al = pp.find(hh("align"))
                if al is None:
                    al = etree.Element(hh("align"))
                    pp.insert(0, al)
                al.set("horizontal", ALIGNS[align])
            if para.get("line_spacing"):
                for ls in pp.iter(hh("lineSpacing")):
                    ls.set("type", "PERCENT")
                    ls.set("value", str(int(float(para["line_spacing"]))))
            for key_, tag in (("space_before", "prev"), ("space_after", "next"), ("left_margin", "left"),
                              ("right_margin", "right"), ("indent", "intent")):
                v = _num(para.get(key_))
                if v is None:
                    continue
                for m in pp.iter(hh("margin")):
                    el = m.find(hc(tag))
                    if el is None:
                        el = etree.SubElement(m, hc(tag), unit="HWPUNIT")
                    # 새 형식(hp:case) 안의 값은 1pt=100, 그 밖(예전 형식과 호환용 hp:default)은 1pt=200
                    scale = 100 if m.getparent().tag == hp("case") else 200
                    el.set("value", str(int(v * scale)))
            if "keep_with_next" in para:
                for bs in pp.iter(hh("breakSetting")):
                    bs.set("keepWithNext", "1" if para["keep_with_next"] else "0")
        key = tuple(sorted((k, str(v)) for k, v in para.items()))
        return self._variant("paraProperties", "paraPr", base_id, key, change)

    def cellfill_variant(self, base_id: str, color) -> str:
        """테두리 모양을 복제해 칸 배경색만 바꾼 id (color가 비거나 'none'이면 배경색 없앰)."""
        face = "none" if not color or str(color).strip().lower() in ("none", "없음") else hex_color(color)

        def change(bf):
            fb = bf.find(hc("fillBrush"))
            if fb is None:
                fb = etree.SubElement(bf, hc("fillBrush"))
            wb = fb.find(hc("winBrush"))
            if wb is None:
                for c in list(fb):
                    fb.remove(c)
                wb = etree.SubElement(fb, hc("winBrush"), hatchColor="#999999", alpha="0")
            wb.set("faceColor", face)
        return self._variant("borderFills", "borderFill", base_id, ("fill", face), change)

    def set_page(self, page: dict) -> list[str]:
        """용지·쪽 설정을 바꾸고, 반영하지 못한 항목 이름을 돌려준다.
        여백(mm) margin_top/bottom/left/right/header/footer, 방향 orientation(landscape|portrait),
        다단 columns(1~4)·column_gap(mm), 쪽 번호 page_number(위치|none), 머리말 header·꼬리말 footer(글, ""면 지움)."""
        from . import objects as ob
        missed = []
        for root in self.ordered_sections():
            for margin in root.iter(hp("margin")):
                if margin.getparent().tag != hp("pagePr"):
                    continue
                for side in ("top", "bottom", "left", "right", "header", "footer"):
                    v = _num(page.get(f"margin_{side}"))
                    if v is not None and 0 <= v <= 100:
                        margin.set(side, str(int(v * HWPUNIT_PER_MM)))
        first = self.ordered_sections()[0]
        sec_run = next((r for r in first.iter(RUN) if r.find(hp("secPr")) is not None), None)

        orient = str(page.get("orientation", "")).strip().lower()
        if orient:
            # 한글은 종이 크기를 그대로 두고 방향만 적는다: NARROWLY = 가로(넓게), WIDELY = 세로
            want = {"landscape": "NARROWLY", "가로": "NARROWLY", "portrait": "WIDELY", "세로": "WIDELY"}.get(orient)
            pages = [pp for root in self.ordered_sections() for pp in root.iter(hp("pagePr"))]
            if want and pages:
                for pp in pages:
                    w, h = int(pp.get("width", "0")), int(pp.get("height", "0"))
                    if w > h:   # 크기를 바꿔 가로로 만든 문서도 같은 규칙으로 맞춘다
                        pp.set("width", str(h))
                        pp.set("height", str(w))
                    pp.set("landscape", want)
            else:
                missed.append("용지 방향")

        cols = _num(page.get("columns"))
        if cols is not None:
            col = next(first.iter(hp("colPr")), None)
            if col is not None and 1 <= cols <= 4:
                col.set("colCount", str(int(cols)))
                gap = _num(page.get("column_gap"))
                col.set("sameGap", str(int((gap if gap is not None else 8) * HWPUNIT_PER_MM) if cols > 1 else 0))
            else:
                missed.append("다단")

        if "page_number" in page:
            pos = str(page.get("page_number") or "none").strip().lower()
            old = [c for c in first.iter(hp("ctrl")) if c.find(hp("pageNum")) is not None]
            if pos in ("none", "없음", "false"):
                for c in old:
                    c.getparent().remove(c)
            elif pos in ob.PAGE_NUM_POS and (old or sec_run is not None):
                if old:
                    old[0].find(hp("pageNum")).set("pos", ob.PAGE_NUM_POS[pos])
                else:
                    sec_run.append(ob.page_num_ctrl(ob.PAGE_NUM_POS[pos]))
            else:
                missed.append("쪽 번호")

        for kind, style in (("header", "머리말"), ("footer", "머리말")):
            if kind not in page:
                continue
            for c in [c for root in self.ordered_sections() for c in root.iter(hp("ctrl"))
                      if c.find(hp(kind)) is not None]:
                c.getparent().remove(c)
            text = str(page.get(kind) or "").strip()
            if text and sec_run is not None:
                sec_run.append(ob.header_ctrl(kind, text, self.text_width(), self.style_ids(style)))
            elif text:
                missed.append("머리말" if kind == "header" else "꼬리말")
        return missed

    def style_ids(self, name: str) -> tuple[str, str, str]:
        """스타일 이름(머리말·각주 …)의 (문단 모양, 글자 모양, 스타일) id. 없으면 바탕글."""
        for st in self.header_root().iter(hh("style")):
            if st.get("name") == name:
                return st.get("paraPrIDRef", "0"), st.get("charPrIDRef", "0"), st.get("id", "0")
        return "0", "0", "0"

    def add_image(self, data: bytes, ext: str) -> str:
        """그림 파일을 문서 안에 넣고(BinData) 그 이름(image7 …)을 돌려준다."""
        ext = ext.lower().lstrip(".")
        ext = "jpg" if ext == "jpeg" else ext
        hpf_i = next(k for k, (i, _) in enumerate(self._items) if i.filename == "Contents/content.hpf")
        hpf = etree.fromstring(self._items[hpf_i][1], _PARSER)
        manifest = next(e for e in hpf.iter() if etree.QName(e).localname == "manifest")
        used = {e.get("id") for e in manifest}
        n = 1
        while f"image{n}" in used:
            n += 1
        name = f"image{n}"
        item = etree.SubElement(manifest, manifest[0].tag, id=name, href=f"BinData/{name}.{ext}")
        item.set("media-type", {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif",
                                "bmp": "image/bmp"}.get(ext, "image/unknown"))
        item.set("isEmbeded", "1")
        self._items[hpf_i] = (self._items[hpf_i][0],
                              etree.tostring(hpf, xml_declaration=True, encoding="UTF-8", standalone=True))
        self._items.append((zipfile.ZipInfo(f"BinData/{name}.{ext}", date_time=self._items[hpf_i][0].date_time), data))
        return name

    def text_width(self) -> int:
        """본문 폭(HWPUNIT) = 종이 폭 - 왼쪽·오른쪽 여백 (가로 용지면 긴 쪽이 폭). 알 수 없으면 A4 기본(150mm)."""
        for root in self.ordered_sections():
            page = root.find(f".//{hp('pagePr')}")
            margin = page.find(hp("margin")) if page is not None else None
            if margin is not None:
                try:
                    paper = int(page.get("height" if page.get("landscape") == "NARROWLY" else "width"))
                    w = paper - int(margin.get("left")) - int(margin.get("right"))
                    cols = next(root.iter(hp("colPr")), None)
                    n = int(cols.get("colCount", "1")) if cols is not None else 1
                    if n > 1:
                        w = (w - int(cols.get("sameGap", "0")) * (n - 1)) // n
                except (TypeError, ValueError):
                    break
                if w > 5000:
                    return w
        return 42520

    def borderfill_variant(self, base_id: str, on: bool) -> str:
        """테두리 모양을 복제해 네 변을 실선(on) 또는 없음으로 바꾼 id. 칸 배경색은 그대로."""
        def change(bf):
            for side in ("leftBorder", "rightBorder", "topBorder", "bottomBorder"):
                e = bf.find(hh(side))
                if e is None:
                    continue
                e.set("type", "SOLID" if on else "NONE")
                if on and e.get("width", "").startswith("0.1 "):
                    e.set("width", "0.12 mm")
        return self._variant("borderFills", "borderFill", base_id, ("border", on), change)


def read_preview_png(path: str) -> bytes | None:
    """hwpx 안에 저장된 미리보기 이미지(첫 쪽)."""
    try:
        with zipfile.ZipFile(path) as z:
            return z.read("Preview/PrvImage.png")
    except Exception:
        return None

