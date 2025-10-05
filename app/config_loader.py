from __future__ import annotations

import json
import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

APP_ROOT = Path(__file__).resolve().parent


def _default_secrets_path() -> Path:
    return APP_ROOT.parent / ".streamlit" / "secrets.toml"


def get_secrets_path() -> Path:
    override = os.getenv("STREAMLIT_SECRETS_PATH")
    if override:
        return Path(override).expanduser()
    return _default_secrets_path()


class ConfigNotFoundError(FileNotFoundError):
    """Raised when the expected secrets file is missing."""


@lru_cache(maxsize=1)
def load_secrets() -> Dict[str, Any]:
    secrets_path = get_secrets_path()

    if not secrets_path.exists():
        raise ConfigNotFoundError(
            f"Secrets ファイルが見つかりません: {secrets_path}. .streamlit/secrets.example.toml をコピーしてください。"
        )

    with secrets_path.open("rb") as f:
        data = tomllib.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Secrets ファイルの形式が正しくありません: {secrets_path}")

    return data


def load_secret(key: str, default: str | None = None) -> str | None:
    settings = load_secrets()
    value = settings.get(key)
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value)
