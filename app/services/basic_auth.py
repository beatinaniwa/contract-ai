from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Mapping

from config_loader import load_secret

st: Any
try:  # pragma: no cover - streamlit may not be importable in some contexts
    import streamlit as st
except Exception:  # pragma: no cover - keep optional dependency soft
    st = None

_get_websocket_headers: Callable[[], Mapping[str, str] | None] | None
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


_SESSION_AUTH_FLAG = "basic_auth_authenticated"
_SESSION_ERROR_FLAG = "basic_auth_error"
_FORM_KEY = "basic_auth_form"
_USERNAME_INPUT_KEY = "basic_auth_username_input"
_PASSWORD_INPUT_KEY = "basic_auth_password_input"


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


def _mark_session_authenticated() -> None:
    if st is None:
        return
    st.session_state[_SESSION_AUTH_FLAG] = True


def _is_session_authenticated() -> bool:
    if st is None:
        return False
    return bool(st.session_state.get(_SESSION_AUTH_FLAG))


def _trigger_rerun() -> None:
    if st is None:
        return
    try:
        if hasattr(st, "rerun"):
            st.rerun()
        elif hasattr(st, "experimental_rerun"):
            st.experimental_rerun()
    except Exception:
        # Ignore rerun errors; the existing run will finish and proceed.
        pass


def render_login_form(config: BasicAuthConfig) -> bool:
    """Show a simple login form when running without an Authorization header."""
    if st is None:
        return False

    message_box = st.empty()
    previous_error = None
    if _SESSION_ERROR_FLAG in st.session_state:
        previous_error = st.session_state.pop(_SESSION_ERROR_FLAG, None)

    if previous_error:
        message_box.error(previous_error)
    else:
        message_box.info("Basic 認証が必要です。ユーザーIDとパスワードを入力してください。")

    with st.form(key=_FORM_KEY, clear_on_submit=False):
        username = st.text_input("ユーザーID", key=_USERNAME_INPUT_KEY)
        password = st.text_input(
            "パスワード", type="password", key=_PASSWORD_INPUT_KEY
        )
        submitted = st.form_submit_button("ログイン")

    if not submitted:
        return False

    if credentials_match((username, password), config):
        _mark_session_authenticated()
        st.session_state.pop(_SESSION_ERROR_FLAG, None)
        message_box.success("認証に成功しました。")
        _trigger_rerun()
        return True

    error_message = "ID またはパスワードが違います。"
    st.session_state[_SESSION_ERROR_FLAG] = error_message
    message_box.error(error_message)
    return False


def require_basic_auth() -> None:
    """Ensure the current request is authenticated before proceeding."""
    config = get_basic_auth_config()
    if not config:
        return

    if _is_session_authenticated():
        return

    provided_credentials = get_request_credentials()
    if credentials_match(provided_credentials, config):
        _mark_session_authenticated()
        return

    if st is None:
        raise PermissionError("Basic authentication required but Streamlit is unavailable.")

    if render_login_form(config):
        return

    st.stop()


__all__ = [
    "BasicAuthConfig",
    "credentials_match",
    "get_basic_auth_config",
    "get_request_credentials",
    "parse_basic_authorization_header",
    "render_login_form",
    "require_basic_auth",
    "reset_basic_auth_cache",
]
