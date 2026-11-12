"""차트(막대·꺾은선·원)를 그림(PNG)으로 그린다. 문서에는 그림으로 들어간다.

숫자는 AI가 문서·참고 자료에서 옮긴 것만 쓴다 (그림을 지어내는 것이 아니라 표의 숫자를 그래프로 그리는 것).
"""
import io
import math

from ..system import IS_MAC

COLORS = ["#4472C4", "#ED7D31", "#A5A5A5", "#FFC000", "#5B9BD5", "#70AD47", "#264478", "#9E480E"]
_FONTS = (["AppleSDGothicNeo.ttc", "AppleGothic.ttf"] if IS_MAC else ["malgun.ttf", "gulim.ttc", "batang.ttc"])


def _font(size: int):
    from PIL import ImageFont
    for name in _FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _numbers(values) -> list[float]:
    out = []
    for v in values if isinstance(values, (list, tuple)) else []:
        try:
            out.append(float(str(v).replace(",", "").replace("%", "").strip()))
        except ValueError:
            out.append(0.0)
    return out


def _fmt(v: float) -> str:
    return f"{v:,.0f}" if abs(v - round(v)) < 1e-9 else f"{v:,.1f}"


def _nice_max(v: float) -> float:
    if v <= 0:
        return 1.0
    exp = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * exp:
            return m * exp
    return 10 * exp


def parse_chart(spec) -> dict | None:
    """AI가 준 차트 요청을 다듬는다. 그릴 숫자가 없으면 None."""
    if not isinstance(spec, dict):
        return None
    labels = [str(x) for x in spec.get("labels") or []]
    series = []
    for s in spec.get("series") or []:
        if isinstance(s, dict):
            vals = _numbers(s.get("values"))
            if vals:
                series.append((str(s.get("name", "")), vals))
    if not series and spec.get("values"):
        series.append(("", _numbers(spec.get("values"))))
    if not labels or not series:
        return None
    n = len(labels)
    series = [(name, (vals + [0.0] * n)[:n]) for name, vals in series]
    kind = str(spec.get("type", "bar")).lower()
    kind = {"막대": "bar", "column": "bar", "꺾은선": "line", "선": "line", "원": "pie", "파이": "pie"}.get(kind, kind)
    return {"type": kind if kind in ("bar", "line", "pie") else "bar", "title": str(spec.get("title", "")),
            "labels": labels, "series": series}


def render_chart(chart: dict, width: int = 1200, height: int = 720) -> bytes:
    """parse_chart() 결과를 PNG로."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    f_title, f = _font(46), _font(30)
    top = 30
    if chart["title"]:
        tw = d.textlength(chart["title"], font=f_title)
        d.text(((width - tw) / 2, top), chart["title"], fill="#222222", font=f_title)
        top += 80
    labels, series = chart["labels"], chart["series"]
    named = [name for name, _ in series if name]

    def legend(items, y):
        x = 80
        for i, name in enumerate(items):
            d.rectangle([x, y + 4, x + 22, y + 26], fill=COLORS[i % len(COLORS)])
            d.text((x + 30, y), name, fill="#333333", font=f)
            x += 30 + d.textlength(name, font=f) + 36
            if x > width - 200:
                x, y = 80, y + 36
        return y + 44

    if chart["type"] == "pie":
        vals = [max(v, 0.0) for v in series[0][1]]
        total = sum(vals) or 1.0
        top = legend([f"{lb} {_fmt(v)} ({v / total:.0%})" for lb, v in zip(labels, vals)], top)
        size = min(width - 160, height - top - 40)
        box = [(width - size) / 2, top, (width + size) / 2, top + size]
        start = -90.0
        for i, v in enumerate(vals):
            end = start + 360.0 * v / total
            if v > 0:
                d.pieslice(box, start, end, fill=COLORS[i % len(COLORS)], outline="white", width=3)
            start = end
    else:
        if len(named) > 1:
            top = legend(named, top)
        left, right, bottom = 120, width - 50, height - 80
        peak = _nice_max(max(max(vals) for _, vals in series))
        for k in range(6):   # 눈금선과 숫자
            y = bottom - (bottom - top - 20) * k / 5
            d.line([left, y, right, y], fill="#DDDDDD" if k else "#666666", width=2)
            t = _fmt(peak * k / 5)
            d.text((left - 14 - d.textlength(t, font=f), y - 14), t, fill="#555555", font=f)
        slot = (right - left) / len(labels)
        scale = (bottom - top - 20) / peak
        for i, lb in enumerate(labels):
            lb = lb if len(lb) <= 9 else lb[:8] + "…"
            d.text((left + slot * (i + 0.5) - d.textlength(lb, font=f) / 2, bottom + 12), lb, fill="#333333", font=f)
        if chart["type"] == "line":
            for s, (_, vals) in enumerate(series):
                pts = [(left + slot * (i + 0.5), bottom - max(v, 0) * scale) for i, v in enumerate(vals)]
                d.line(pts, fill=COLORS[s % len(COLORS)], width=5, joint="curve")
                for (x, y), v in zip(pts, vals):
                    d.ellipse([x - 8, y - 8, x + 8, y + 8], fill=COLORS[s % len(COLORS)])
                    if len(series) == 1:
                        t = _fmt(v)
                        d.text((x - d.textlength(t, font=f) / 2, y - 52), t, fill="#333333", font=f)
        else:
            bar = slot * 0.7 / len(series)
            for s, (_, vals) in enumerate(series):
                for i, v in enumerate(vals):
                    x = left + slot * (i + 0.15) + bar * s
                    y = bottom - max(v, 0) * scale
                    d.rectangle([x, y, x + bar - 4, bottom], fill=COLORS[s % len(COLORS)])
                    if len(series) == 1 and len(labels) <= 12:
                        t = _fmt(v)
                        d.text((x + (bar - 4) / 2 - d.textlength(t, font=f) / 2, y - 42), t, fill="#333333", font=f)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
