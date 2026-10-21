"""참고 자료 읽기: 어떤 형식이든 read_reference(path) 하나로 글을 꺼낸다.

표는 행마다 '| 칸 | 칸 |' 한 줄로 남겨, AI가 일정표·예산표 같은 구조를 그대로 알아보게 한다.
확장자보다 파일 앞부분(매직 바이트)을 먼저 보고 형식을 정한다 (.hwp로 저장된 HWPX 등).
"""
import zipfile
from pathlib import Path

SUPPORTED = (".hwp", ".hwpx", ".pdf", ".docx", ".txt", ".md", ".csv")
FILE_TYPES = [("문서", " ".join(f"*{e}" for e in SUPPORTED)), ("모든 파일", "*.*")]


class ReadError(Exception):
    pass


def _kind(path: Path) -> str:
    with open(path, "rb") as f:
        head = f.read(8)
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "hwp"
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK"):
        try:
            with zipfile.ZipFile(path) as z:
                names = set(z.namelist())
        except zipfile.BadZipFile:
            return "text"
        if "Contents/section0.xml" in names or "Contents/header.xml" in names:
            return "hwpx"
        if "word/document.xml" in names:
            return "docx"
        raise ReadError("알 수 없는 압축 문서입니다.")
    return "text"


def read_reference(path: str) -> str:
    p = Path(path)
    kind = _kind(p)
    if kind == "hwp":
        from .hwp import read_hwp
        return read_hwp(str(p))
    if kind == "hwpx":
        from ..doc import HwpxDocument
        return HwpxDocument(str(p)).structured_text()
    if kind == "pdf":
        from .pdf import read_pdf
        return read_pdf(str(p))
    if kind == "docx":
        from .docx import read_docx
        return read_docx(str(p))
    data = p.read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")
