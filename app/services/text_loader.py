"""Utilities to load plain text from uploaded files."""

from __future__ import annotations

import io
import logging
from pathlib import Path

from google.genai import types
from pypdf import PdfReader

from .gemini_client import GEMINI_MODEL_NAME, GeminiConfigError, get_client as _get_gemini_client

logger = logging.getLogger(__name__)

_TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}
_PPTX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

PPTX_EXTRACTION_PROMPT = (
    "アップロードされたPowerPointファイルから各スライドのタイトルと本文に含まれるテキストを順番に抽出してください。"
    "スライドごとに「[Slide X]」の見出しを付け、その下に箇条書きで主要なテキストをまとめてください。"
    "出力はプレーンテキストのみとし、余分な解説やマークダウンは含めないでください。"
)


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

    if suffix == ".pptx":
        return _extract_pptx_text(data)

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


def _extract_pptx_text(data: bytes) -> str:
    try:
        client = _get_gemini_client()
    except GeminiConfigError as exc:
        raise ValueError(f"Geminiの設定に問題があります: {exc}") from exc

    parts = [
        types.Part.from_bytes(data=data, mime_type=_PPTX_MIME_TYPE),
        types.Part.from_text(PPTX_EXTRACTION_PROMPT),
    ]

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL_NAME,
            contents=[types.Content(role="user", parts=parts)],
        )
    except Exception as exc:  # pragma: no cover - external API variations
        logger.exception("Gemini PPTX extraction failed")
        raise ValueError("GeminiによるPPTXの読み取りに失敗しました。") from exc

    feedback = getattr(response, "prompt_feedback", None)
    if feedback and getattr(feedback, "block_reason", None):
        raise ValueError(f"Geminiの安全フィルタによりブロックされました: {feedback.block_reason}")

    content = getattr(response, "text", None)
    if not content:
        raise ValueError("Geminiの応答が空でした。")

    return content.strip()
