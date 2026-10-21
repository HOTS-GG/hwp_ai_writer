"""Word(.docx) 글자 추출. 본문 문단은 줄로, 표는 행마다 '| 칸 | 칸 |'로."""
import zipfile

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _w(name: str) -> str:
    return f"{{{W}}}{name}"


def _para(p) -> str:
    return "".join(t.text or "" for t in p.iter(_w("t")))


def read_docx(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    body = root.find(_w("body"))
    out: list[str] = []

    def table(tbl):
        for tr in tbl.iterfind(_w("tr")):
            cells = [" ".join(_para(p) for p in tc.iterfind(_w("p"))).strip() for tc in tr.iterfind(_w("tc"))]
            if any(cells):
                out.append("| " + " | ".join(cells) + " |")
            for tc in tr.iterfind(_w("tc")):
                for nested in tc.iterfind(_w("tbl")):
                    table(nested)

    for el in (body if body is not None else []):
        if el.tag == _w("p"):
            s = _para(el)
            if s.strip():
                out.append(s)
        elif el.tag == _w("tbl"):
            table(el)
    return "\n".join(out)
