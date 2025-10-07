"""Utilities to load plain text from uploaded files."""

from __future__ import annotations

import io
from pathlib import Path

from pypdf import PdfReader

_TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}


def load_text_from_bytes(data: bytes, filename: str) -> str:
    """Extract text content from raw file bytes.

    Args:
        data: Raw file content.
        filename: Original file name used for extension detection.

    Returns:
        Extracted text stripped of leading/trailing whitespace.

    Raises:
        ValueError: If the file type is unsupported or text cannot be extracted.
    """

    if not data:
        raise ValueError("ファイルの内容が空です。")

    suffix = Path(filename or "uploaded").suffix.lower()

    if suffix in _TEXT_EXTENSIONS:
        return _decode_text_file(data)

    if suffix == ".pdf":
        return _extract_pdf_text(data)

    raise ValueError(f"サポートされていないファイル形式です: {suffix or '不明'}")
def _decode_text_file(data: bytes) -> str:
    text = data.decode("utf-8", errors="ignore").strip()
    if not text:
        raise ValueError("テキストファイルから内容を取得できませんでした。")
    return text


def _extract_pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    extracted_parts = []
    for page in reader.pages:
        page_text = page.extract_text() or ""
        if page_text:
            extracted_parts.append(page_text.strip())
    combined = "\n\n".join(part for part in extracted_parts if part)
    combined = combined.strip()
    if not combined:
        raise ValueError("PDFからテキストを抽出できませんでした。")
    return combined
