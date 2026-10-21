"""한글 없이 HWPX 쪽 이미지를 그리는 간이 미리보기.

맥이나 한글이 없는 PC에서는 한글 COM으로 쪽 이미지를 만들 수 없다. hwpx 안의 미리보기 그림
(Preview/PrvImage.png)은 처음 양식의 그림이라 내용을 고쳐도 바뀌지 않으므로, 문서 내용
(글자, 표, 그림, 정렬·들여쓰기, 쪽 나누기)을 직접 그려 실제 내용이 보이게 한다.
글꼴·줄 나눔은 한글과 조금 다를 수 있다.
"""
import io
import os
import sys
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from hwpx_form import (CELLADDR, CELLSPAN, CELLSZ, HH, HP, P, PIC, RUN, SUBLIST, SZ, T, TBL, TC, TR,
                       HwpxDoc, t_text)

HC = "http://www.hancom.co.kr/hwpml/2011/core"
DRAWTEXT = f"{{{HP}}}drawText"
SHAPES = {f"{{{HP}}}{n}" for n in ("pic", "rect", "ellipse", "container", "polygon", "curve", "arc")}
UNIT_PER_INCH = 7200

FONT_CANDIDATES = [
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "malgun.ttf"),
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]
_font_path = next((f for f in FONT_CANDIDATES if os.path.exists(f)), None)
_fonts: dict = {}


def _font(px: int):
    px = max(6, int(px))
    if px not in _fonts:
        _fonts[px] = ImageFont.truetype(_font_path, px) if _font_path else ImageFont.load_default()
    return _fonts[px]


class _Styles:
    """header.xml의 글자 모양·문단 모양 중 미리보기에 필요한 값."""

    def __init__(self, header):
        self.chars, self.paras, self.fills = {}, {}, {}
        for bf in header.iter(f"{{{HH}}}borderFill"):
            wb = bf.find(f".//{{{HC}}}winBrush")
            color = wb.get("faceColor") if wb is not None else None
            if color and color.startswith("#") and color.upper() != "#FFFFFF":
                self.fills[bf.get("id")] = color
        for c in header.iter(f"{{{HH}}}charPr"):
            self.chars[c.get("id")] = (int(c.get("height", "1000")) / 100,
                                       c.find(f"{{{HH}}}bold") is not None,
                                       c.get("textColor", "#000000"))
        for pp in header.iter(f"{{{HH}}}paraPr"):
            al = pp.find(f"{{{HH}}}align")
            box = pp.find(f".//{{{HP}}}default/{{{HH}}}margin")
            if box is None:
                box = pp.find(f".//{{{HH}}}margin")

            def val(tag):
                e = box.find(f"{{{HC}}}{tag}") if box is not None else None
                return int(e.get("value", "0")) if e is not None else 0
            ls = pp.find(f".//{{{HP}}}default/{{{HH}}}lineSpacing")
            if ls is None:
                ls = pp.find(f".//{{{HH}}}lineSpacing")
            spacing = int(ls.get("value", "160")) if ls is not None and ls.get("type") == "PERCENT" else 160
            self.paras[pp.get("id")] = {
                "align": al.get("horizontal", "JUSTIFY") if al is not None else "JUSTIFY",
                "left": val("left"), "indent": val("intent"), "prev": val("prev"), "next": val("next"),
                "spacing": spacing,
            }

    def char(self, cid):
        return self.chars.get(cid, (10.0, False, "#000000"))

    def para(self, pid):
        return self.paras.get(pid, {"align": "JUSTIFY", "left": 0, "indent": 0, "prev": 0, "next": 0, "spacing": 160})


class _Renderer:
    def __init__(self, path: str, dpi: int):
        self.doc = HwpxDoc(path)
        self.zip = zipfile.ZipFile(path)
        self.styles = _Styles(self.doc._header_root())
        self.scale = dpi / UNIT_PER_INCH
        self.pages: list[Image.Image] = []
        self._images: dict = {}
        self._new_page_size()

    def px(self, unit) -> int:
        return int(round(int(unit) * self.scale))

    # ── 쪽 ──────────────────────────────────────────────────────────────
    def _new_page_size(self):
        pp = next((e for r in self.doc.ordered_sections() for e in r.iter(f"{{{HP}}}pagePr")), None)
        w, h = (int(pp.get("width", 59528)), int(pp.get("height", 84188))) if pp is not None else (59528, 84188)
        m = pp.find(f"{{{HP}}}margin") if pp is not None else None
        g = (lambda k, d: int(m.get(k, d))) if m is not None else (lambda k, d: d)
        self.page_w, self.page_h = self.px(w), self.px(h)
        self.left = self.px(g("left", 5669))
        self.right = self.page_w - self.px(g("right", 5669))
        self.top = self.px(g("top", 4251) + g("header", 0))
        self.bottom = self.page_h - self.px(g("bottom", 4252) + g("footer", 0))

    def _page(self):
        img = Image.new("RGB", (self.page_w, self.page_h), "white")
        self.pages.append(img)
        self.draw = ImageDraw.Draw(img)
        self.y = self.top

    def _need(self, h):
        if not self.pages or (self.y + h > self.bottom and self.y > self.top):
            self._page()

    # ── 글자 줄 배치 ────────────────────────────────────────────────────
    def _runs(self, p):
        """문단의 (글자, 크기px, 굵게, 색) 조각."""
        out = []
        for run in p.iterfind(RUN):
            size, bold, color = self.styles.char(run.get("charPrIDRef", "0"))
            for t in run.iterfind(T):
                s = t_text(t)
                if s:
                    out.append((s, self.px(size * 100), bold, color))
        return out

    def _layout(self, p, width: int) -> tuple[list, int]:
        """문단을 width 안에서 줄로 나눈다. ([(x, y, 조각들)], 높이)."""
        ps = self.styles.para(p.get("paraPrIDRef", "0"))
        runs = self._runs(p)
        left = self.px(ps["left"])
        indent = self.px(ps["indent"])
        size = max((r[1] for r in runs), default=self.px(1000))
        line_h = int(size * max(ps["spacing"], 100) / 100)
        lines, cur, cur_w = [], [], 0
        first_x = left + max(indent, 0)
        rest_x = left + (-indent if indent < 0 else 0)
        avail = lambda: width - (first_x if not lines else rest_x)  # noqa: E731
        for text, sz, bold, color in runs:
            f = _font(sz)
            buf = ""
            for ch in text:
                w = f.getlength(buf + ch)
                if cur_w + w > avail() and (buf or cur):
                    if buf:
                        cur.append((buf, sz, bold, color))
                    lines.append(cur)
                    cur, cur_w, buf = [], 0, ch.lstrip() if ch == " " else ch
                else:
                    buf += ch
            if buf:
                cur.append((buf, sz, bold, color))
                cur_w += f.getlength(buf)
        if cur or not lines:
            lines.append(cur)
        placed = []
        for i, ln in enumerate(lines):
            x0 = first_x if i == 0 else rest_x
            lw = sum(_font(s).getlength(t) for t, s, _, _ in ln)
            if ps["align"] == "CENTER":
                x0 = max(x0, (width - lw) / 2)
            elif ps["align"] == "RIGHT":
                x0 = max(x0, width - lw)
            placed.append((x0, i * line_h, ln))
        return placed, len(lines) * line_h + self.px(ps["prev"] + ps["next"])

    def _draw_lines(self, placed, ox, oy):
        for x, y, ln in placed:
            for text, sz, bold, color in ln:
                f = _font(sz)
                self.draw.text((ox + x, oy + y), text, font=f, fill=color if color.startswith("#") else "#000",
                               stroke_width=1 if bold else 0, stroke_fill=color if color.startswith("#") else "#000")
                x += f.getlength(text)

    # ── 그림 ────────────────────────────────────────────────────────────
    def _image(self, pic):
        img = pic.find(f".//{{{HC}}}img")
        ref = img.get("binaryItemIDRef") if img is not None else None
        if not ref:
            return None
        if ref not in self._images:
            name = next((n for n in self.zip.namelist() if n.startswith(f"BinData/{ref}.")), None)
            try:
                self._images[ref] = Image.open(io.BytesIO(self.zip.read(name))).convert("RGBA") if name else None
            except Exception:
                self._images[ref] = None
        return self._images[ref]

    def _obj_size(self, obj):
        sz = obj.find(SZ)
        if sz is None or not int(sz.get("width", 0) or 0):
            sz = self._unit_size(obj)
            return self.px(sz[0]), self.px(sz[1])
        return self.px(sz.get("width", 0)), self.px(sz.get("height", 0))

    @staticmethod
    def _unit_size(obj) -> tuple[int, int]:
        """묶음 안 개체의 크기(HWPUNIT): 현재 크기, 없으면 원래 크기."""
        for tag in ("curSz", "orgSz", "sz"):
            e = obj.find(f"{{{HP}}}{tag}")
            if e is not None and int(e.get("width", 0) or 0):
                return int(e.get("width", 0)), int(e.get("height", 0))
        return 0, 0

    @staticmethod
    def is_drawable(o) -> bool:
        return o.tag == PIC or o.find(f".//{PIC}") is not None or o.find(f".//{DRAWTEXT}") is not None

    def _draw_object(self, obj, x, y, w, h):
        """그림·글상자·묶음 개체를 (x, y, w, h) 상자 안에 그린다. 묶음은 안의 개체를 제 위치(offset)에."""
        if obj.tag == PIC:
            self._paste(obj, x, y, w, h)
            return
        dt = obj.find(DRAWTEXT)
        if dt is not None:
            self._text_box(dt, x, y, w, h)
        kids = [c for c in obj if c.tag in SHAPES]
        if not kids:
            return
        ow, oh = self._unit_size(obj) if obj.find(f"{{{HP}}}orgSz") is None else \
            (int(obj.find(f"{{{HP}}}orgSz").get("width", 0)), int(obj.find(f"{{{HP}}}orgSz").get("height", 0)))
        sx = w / ow if ow else self.scale
        sy = h / oh if oh else self.scale
        for c in kids:
            off = c.find(f"{{{HP}}}offset")
            cx = x + (int(off.get("x", 0)) * sx if off is not None else 0)
            cy = y + (int(off.get("y", 0)) * sy if off is not None else 0)
            cw, ch = self._unit_size(c)
            self._draw_object(c, cx, cy, int(cw * sx), int(ch * sy))

    def _text_box(self, dt, x, y, w, h):
        sl = dt.find(SUBLIST)
        if sl is None or w <= 0:
            return
        layouts, total = [], 0
        for p in sl.iterfind(P):
            placed, ph = self._layout(p, int(w))
            layouts.append((placed, total))
            total += ph
        off = {"CENTER": (h - total) / 2, "BOTTOM": h - total}.get(sl.get("vertAlign", "TOP"), 0)
        for placed, dy in layouts:
            self._draw_lines(placed, x, y + max(off, 0) + dy)

    def _paste(self, pic, x, y, w, h):
        im = self._image(pic)
        if w <= 0 or h <= 0:
            return
        if im is None:
            self.draw.rectangle([x, y, x + w, y + h], outline="#bbbbbb")
            return
        im = im.copy()
        im.thumbnail((w, h))
        self.pages[-1].paste(im, (int(x), int(y)), im)

    # ── 표 ──────────────────────────────────────────────────────────────
    def _table(self, tbl, x0, width, draw=True) -> int:
        """표를 그리고(draw) 높이를 돌려준다. 열 너비는 표 안의 칸 너비 비율대로."""
        cells = []
        for tr in tbl.iterfind(TR):
            for tc in tr.iterfind(TC):
                a, sp, sz = tc.find(CELLADDR), tc.find(CELLSPAN), tc.find(CELLSZ)
                cells.append({
                    "tc": tc, "col": int(a.get("colAddr", 0)), "row": int(a.get("rowAddr", 0)),
                    "cs": int(sp.get("colSpan", 1)) if sp is not None else 1,
                    "rs": int(sp.get("rowSpan", 1)) if sp is not None else 1,
                    "w": int(sz.get("width", 0)) if sz is not None else 0,
                    "h": int(sz.get("height", 0)) if sz is not None else 0,
                })
        if not cells:
            return 0
        ncol = max(c["col"] + c["cs"] for c in cells)
        nrow = max(c["row"] + c["rs"] for c in cells)
        colw = [0] * ncol
        for c in cells:
            if c["cs"] == 1:
                colw[c["col"]] = max(colw[c["col"]], c["w"])
        known = sum(colw)
        for c in sorted(cells, key=lambda c: c["cs"]):
            miss = [i for i in range(c["col"], c["col"] + c["cs"]) if not colw[i]]
            if miss:
                share = max(c["w"] - sum(colw[c["col"]:c["col"] + c["cs"]]), 0) // len(miss)
                for i in miss:
                    colw[i] = share or 1
        known = sum(colw) or 1
        tbl_w = min(width, self.px(known))
        xs = [x0]
        for w in colw:
            xs.append(xs[-1] + w * tbl_w / known)
        pad = self.px(510)
        rowh = [0] * nrow
        for c in cells:
            c["x"], c["x2"] = xs[c["col"]], xs[c["col"] + c["cs"]]
            c["layouts"] = []
            text_h = 0
            sl = c["tc"].find(SUBLIST)
            for p in (sl.iterfind(P) if sl is not None else []):
                placed, h = self._layout(p, int(c["x2"] - c["x"] - 2 * pad))
                c["layouts"].append((placed, text_h))
                text_h += h
                for run in p.iterfind(RUN):
                    for o in run:
                        if o.tag == TBL:
                            text_h += self._table(o, 0, int(c["x2"] - c["x"] - 2 * pad), draw=False)
                        elif o.tag != T:
                            text_h += self._obj_size(o)[1] if self.is_drawable(o) else 0
            c["text_h"] = text_h + 2 * pad
            if c["rs"] == 1:
                rowh[c["row"]] = max(rowh[c["row"]], c["text_h"], self.px(c["h"]))
        for c in cells:
            if c["rs"] > 1:
                have = sum(rowh[c["row"]:c["row"] + c["rs"]])
                if c["text_h"] > have:
                    rowh[c["row"] + c["rs"] - 1] += c["text_h"] - have
        total = sum(rowh)
        if not draw:
            return total
        ys = [self.y]
        for h in rowh:
            ys.append(ys[-1] + h)
        for c in cells:
            top, bot = ys[c["row"]], ys[c["row"] + c["rs"]]
            fill = self.styles.fills.get(c["tc"].get("borderFillIDRef"))
            self.draw.rectangle([c["x"], top, c["x2"], bot], outline="#000000", fill=fill)
            sl = c["tc"].find(SUBLIST)
            valign = sl.get("vertAlign", "TOP") if sl is not None else "TOP"
            off = {"CENTER": (bot - top - c["text_h"]) / 2, "BOTTOM": bot - top - c["text_h"]}.get(valign, 0)
            cy = top + pad + max(off, 0)
            for placed, dy in c["layouts"]:
                self._draw_lines(placed, c["x"] + pad, cy + dy)
            # 칸 안의 그림
            for p in (sl.iterfind(P) if sl is not None else []):
                for run in p.iterfind(RUN):
                    for o in run:
                        if o.tag not in (T, TBL) and self.is_drawable(o):
                            w, h = self._obj_size(o)
                            self._draw_object(o, c["x"] + (c["x2"] - c["x"] - w) / 2, cy, w, h)
        return total

    # ── 본문 ────────────────────────────────────────────────────────────
    def render(self) -> list[Image.Image]:
        width = self.right - self.left
        for root in self.doc.ordered_sections():
            for p in root.iterchildren(P):
                if p.get("pageBreak") == "1" and self.pages and self.y > self.top:
                    self._page()
                placed, h = self._layout(p, width)
                if any(ln for _, _, ln in placed):
                    self._need(h)
                    self._draw_lines(placed, self.left, self.y)
                    self.y += h
                objs = [o for run in p.iterfind(RUN) for o in run if o.tag != T]
                for o in objs:
                    if o.tag == TBL:
                        th = self._table(o, self.left, width, draw=False)
                        self._need(th)
                        self._table(o, self.left, width)
                        self.y += th
                    elif self.is_drawable(o):
                        w, oh = self._obj_size(o)
                        w, oh = min(w, width), oh * (min(w, width) / w if w else 1)
                        self._need(oh)
                        ps = self.styles.para(p.get("paraPrIDRef", "0"))
                        x = self.left + {"CENTER": (width - w) / 2, "RIGHT": width - w}.get(ps["align"], 0)
                        self._draw_object(o, x, self.y, int(w), int(oh))
                        self.y += int(oh)
                if not objs and not any(ln for _, _, ln in placed):
                    self._need(h)
                    self.y += h  # 빈 줄
        if not self.pages:
            self._page()
        return self.pages


def render_pages(path: str, dpi: int, out_dir: Path) -> list[str]:
    """path(hwpx)의 쪽 이미지를 out_dir에 page_000.png… 로 저장하고 경로 목록을 돌려준다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = _Renderer(path, dpi).render()
    paths = []
    for i, im in enumerate(pages):
        p = out_dir / f"page_{i:03d}.png"
        im.save(p)
        paths.append(str(p))
    return paths


if __name__ == "__main__":
    for i, p in enumerate(render_pages(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 96, Path(sys.argv[3]))):
        print(p)
