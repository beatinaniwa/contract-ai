from __future__ import annotations

import os
from functools import lru_cache

from google import genai

from config_loader import ConfigNotFoundError, load_secret


class GeminiConfigError(RuntimeError):
    """Raised when Gemini configuration is missing or invalid."""


GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")


def _get_api_key() -> str:
    try:
        api_key = load_secret("gemini_api_key")
    except ConfigNotFoundError as exc:
        raise GeminiConfigError(str(exc)) from exc

    if not api_key:
        raise GeminiConfigError(".streamlit/secrets.toml に gemini_api_key を設定してください。")

    return api_key


@lru_cache(maxsize=1)
def get_client() -> genai.Client:
    """Return a cached Gemini client instance."""
    api_key = _get_api_key()
    return genai.Client(api_key=api_key)


__all__ = ["GeminiConfigError", "GEMINI_MODEL_NAME", "get_client"]

