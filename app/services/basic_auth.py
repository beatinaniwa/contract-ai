from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from functools import lru_cache
from typing import Mapping

from config_loader import load_secret

try:  # pragma: no cover - streamlit may not be importable in some contexts
    import streamlit as st
except Exception:  # pragma: no cover - keep optional dependency soft
    st = None

try:
    from streamlit.web.server.websocket_headers import _get_websocket_headers
except Exception:  # pragma: no cover - streamlit fallback when not running in app context
    _get_websocket_headers = None


@dataclass(frozen=True)
class BasicAuthConfig:
    """Expected credentials for basic authentication."""

    username: str
    password_hash: str


def _hash_password(raw_password: str) -> str:
    return hashlib.sha256(raw_password.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def get_basic_auth_config() -> BasicAuthConfig | None:
    """Read basic auth settings from secrets.

    Returns None when no credentials are configured.
    """
    username = load_secret("basic_auth_username")
    password = load_secret("basic_auth_password")
    password_hash = load_secret("basic_auth_password_hash")

    if password_hash:
        resolved_hash = password_hash.strip().lower()
    elif password:
        resolved_hash = _hash_password(password.strip())
    else:
        return None

    if not username or not username.strip():
        raise ValueError(
            "Basic 認証を有効化する場合は basic_auth_username を設定してください。"
        )

    return BasicAuthConfig(username=username.strip(), password_hash=resolved_hash)


def reset_basic_auth_cache() -> None:
    """Testing helper to clear cached configuration."""
    get_basic_auth_config.cache_clear()


def parse_basic_authorization_header(
    header_value: str | None,
) -> tuple[str, str] | None:
    """Decode a Basic Authorization header into credentials."""
    if not header_value:
        return None
    if not header_value.startswith("Basic "):
        return None

    token = header_value.split(" ", 1)[1]
    try:
        decoded = base64.b64decode(token, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None

    if ":" not in decoded:
        return None
    username, password = decoded.split(":", 1)
    return username, password


def _get_headers() -> Mapping[str, str] | None:
    """Fetch headers from the running Streamlit context."""
    if st is not None:
        try:
            headers = getattr(st.context, "headers", None)
            if headers:  # Streamlit 1.28+
                return headers
        except Exception:  # pragma: no cover - context access may fail in tests
            pass

    if _get_websocket_headers is not None:
        try:
            return _get_websocket_headers()
        except Exception:  # pragma: no cover - legacy fallback
            return None

    return None


def get_request_credentials() -> tuple[str, str] | None:
    """Fetch credentials supplied via the websocket handshake headers."""
    headers = _get_headers()
    if not headers:
        return None

    auth_header = headers.get("Authorization") or headers.get("authorization")
    return parse_basic_authorization_header(auth_header)


def credentials_match(
    credentials: tuple[str, str] | None, config: BasicAuthConfig
) -> bool:
    """Compare provided credentials against the configured baseline."""
    if not credentials:
        return False

    username, password = credentials
    if username != config.username:
        return False

    hashed = _hash_password(password)
    return hmac.compare_digest(hashed, config.password_hash)


__all__ = [
    "BasicAuthConfig",
    "credentials_match",
    "get_basic_auth_config",
    "get_request_credentials",
    "parse_basic_authorization_header",
    "reset_basic_auth_cache",
]
