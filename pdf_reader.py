# -*- coding: utf-8 -*-
"""PDF 텍스트 추출 유틸리티."""
from pathlib import Path


def extract_pdf_text(path: str) -> str:
    """PDF 파일에서 텍스트를 추출합니다. 페이지 번호 포함."""
    try:
        import pypdf
    except ImportError:
        raise ImportError("pypdf 패키지가 필요합니다: pip install pypdf")

    reader = pypdf.PdfReader(path)
    pages = []
    for i, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        text = text.strip()
        if text:
            pages.append(f"[페이지 {i}]\n{text}")

    if not pages:
        raise RuntimeError("PDF에서 텍스트를 추출할 수 없습니다. (스캔 이미지 PDF일 수 있습니다.)")

    return "\n\n".join(pages)


def get_pdf_summary(path: str, max_chars: int = 3000) -> str:
    """AI 프롬프트 주입용 PDF 텍스트 요약 (길이 제한)."""
    text = extract_pdf_text(path)
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n... (총 {len(text)}자 중 {max_chars}자 표시)"
    return text
