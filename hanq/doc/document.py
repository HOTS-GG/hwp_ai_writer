"""HWPX 파일(zip)을 열고 저장한다. 본문 섹션과 header(글자·문단 모양 목록)를 lxml 트리로 들고 있다."""
import copy
import io
import re
import zipfile

from lxml import etree

from .xml import ALIGNS, P, RUN, SUBLIST, T, TBL, TC, TR, cell_text, hex_color, hh, para_text

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
                if ul is not None:
                    ul.set("type", "BOTTOM" if style["underline"] else "NONE")
                    if style.get("color"):
                        ul.set("color", hex_color(style["color"]))
        key = tuple(sorted((k, str(v)) for k, v in style.items()))
        return self._variant("charProperties", "charPr", base_id, key, change)

    def parapr_variant(self, base_id: str, para: dict) -> str:
        """문단 모양을 복제해 정렬(align)·줄 간격(line_spacing %)만 바꾼 id."""
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
        key = tuple(sorted((k, str(v)) for k, v in para.items()))
        return self._variant("paraProperties", "paraPr", base_id, key, change)

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

