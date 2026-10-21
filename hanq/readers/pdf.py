"""PDF 글자 추출 (pypdf)."""


def read_pdf(path: str) -> str:
    """쪽 번호를 붙여 PDF 글자를 꺼낸다. 스캔 이미지 PDF면 오류."""
    try:
        import pypdf
    except ImportError:
        raise ImportError("pypdf 패키지가 필요합니다: pip install pypdf")
    reader = pypdf.PdfReader(path)
    pages = []
    for i, page in enumerate(reader.pages, 1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append(f"[{i}쪽]\n{text}")
    if not pages:
        raise RuntimeError("PDF에서 글자를 찾지 못했습니다. (스캔 이미지 PDF일 수 있습니다.)")
    return "\n\n".join(pages)
