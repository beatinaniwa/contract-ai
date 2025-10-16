import base64
import hashlib
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services import basic_auth  # noqa: E402


def _configure_secrets(monkeypatch, secrets: dict[str, str]) -> None:
    basic_auth.reset_basic_auth_cache()
    monkeypatch.setattr(
        basic_auth,
        "load_secret",
        lambda key, default=None: secrets.get(key, default),
    )


def test_parse_basic_authorization_header_valid():
    header = "Basic " + base64.b64encode(b"user:pass").decode("ascii")
    assert basic_auth.parse_basic_authorization_header(header) == ("user", "pass")


def test_parse_basic_authorization_header_invalid_base64():
    assert basic_auth.parse_basic_authorization_header("Basic ???") is None


def test_get_basic_auth_config_with_plain_password(monkeypatch):
    _configure_secrets(
        monkeypatch,
        {
            "basic_auth_username": "alice",
            "basic_auth_password": "s3cret",
        },
    )

    config = basic_auth.get_basic_auth_config()
    assert config is not None
    assert config.username == "alice"
    assert config.password_hash == hashlib.sha256(b"s3cret").hexdigest()


def test_get_basic_auth_config_prefers_hash(monkeypatch):
    hashed = hashlib.sha256(b"ignored").hexdigest()
    _configure_secrets(
        monkeypatch,
        {
            "basic_auth_username": "bob",
            "basic_auth_password": "should-not-be-used",
            "basic_auth_password_hash": hashed,
        },
    )

    config = basic_auth.get_basic_auth_config()
    assert config is not None
    assert config.username == "bob"
    assert config.password_hash == hashed


def test_credentials_match(monkeypatch):
    _configure_secrets(
        monkeypatch,
        {
            "basic_auth_username": "carol",
            "basic_auth_password": "open-sesame",
        },
    )
    config = basic_auth.get_basic_auth_config()
    assert config is not None

    valid_header = "Basic " + base64.b64encode(b"carol:open-sesame").decode("ascii")
    creds = basic_auth.parse_basic_authorization_header(valid_header)
    assert basic_auth.credentials_match(creds, config) is True

    invalid_header = "Basic " + base64.b64encode(b"carol:wrong").decode("ascii")
    wrong_creds = basic_auth.parse_basic_authorization_header(invalid_header)
    assert basic_auth.credentials_match(wrong_creds, config) is False


def test_get_request_credentials_uses_headers(monkeypatch):
    header = "Basic " + base64.b64encode(b"dave:hunter2").decode("ascii")
    monkeypatch.setattr(
        basic_auth,
        "_get_headers",
        lambda: {"authorization": header},
    )

    creds = basic_auth.get_request_credentials()
    assert creds == ("dave", "hunter2")


class StopCalled(Exception):
    pass


class DummyPlaceholder:
    def __init__(self, sink):
        self.sink = sink

    def info(self, message):
        self.sink.append(("info", message))

    def error(self, message):
        self.sink.append(("error", message))

    def success(self, message):
        self.sink.append(("success", message))


class DummyForm:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class DummyStreamlit:
    def __init__(self):
        self.session_state: dict[str, object] = {}
        self._messages: list[tuple[str, str]] = []
        self.username_response = ""
        self.password_response = ""
        self.submit_response = False

    def empty(self):
        return DummyPlaceholder(self._messages)

    def form(self, key, clear_on_submit=False):
        return DummyForm()

    def text_input(self, label, key=None, type="text"):
        if "ユーザーID" in label:
            return self.username_response
        return self.password_response

    def form_submit_button(self, label):
        return self.submit_response

    def stop(self):
        raise StopCalled()

    def messages(self):
        return list(self._messages)


def test_render_login_form_success(monkeypatch):
    _configure_secrets(
        monkeypatch,
        {
            "basic_auth_username": "erin",
            "basic_auth_password": "letmein",
        },
    )
    config = basic_auth.get_basic_auth_config()
    assert config is not None

    stub = DummyStreamlit()
    stub.username_response = "erin"
    stub.password_response = "letmein"
    stub.submit_response = True

    monkeypatch.setattr(basic_auth, "st", stub)

    assert basic_auth.render_login_form(config) is True
    assert stub.session_state[basic_auth._SESSION_AUTH_FLAG] is True  # type: ignore[attr-defined]
    assert ("success", "認証に成功しました。") in stub.messages()


def test_render_login_form_failure(monkeypatch):
    _configure_secrets(
        monkeypatch,
        {
            "basic_auth_username": "frank",
            "basic_auth_password": "open-sesame",
        },
    )
    config = basic_auth.get_basic_auth_config()
    assert config is not None

    stub = DummyStreamlit()
    stub.username_response = "frank"
    stub.password_response = "wrong"
    stub.submit_response = True

    monkeypatch.setattr(basic_auth, "st", stub)

    assert basic_auth.render_login_form(config) is False
    assert basic_auth._SESSION_AUTH_FLAG not in stub.session_state  # type: ignore[attr-defined]
    assert stub.session_state[basic_auth._SESSION_ERROR_FLAG] == "ID またはパスワードが違います。"  # type: ignore[attr-defined]
    assert ("error", "ID またはパスワードが違います。") in stub.messages()


def test_require_basic_auth_accepts_header(monkeypatch):
    _configure_secrets(
        monkeypatch,
        {
            "basic_auth_username": "gina",
            "basic_auth_password": "hunter2",
        },
    )

    stub = DummyStreamlit()
    monkeypatch.setattr(basic_auth, "st", stub)
    monkeypatch.setattr(
        basic_auth,
        "get_request_credentials",
        lambda: ("gina", "hunter2"),
    )

    basic_auth.require_basic_auth()
    assert stub.session_state[basic_auth._SESSION_AUTH_FLAG] is True  # type: ignore[attr-defined]


def test_require_basic_auth_prompts_and_stops(monkeypatch):
    _configure_secrets(
        monkeypatch,
        {
            "basic_auth_username": "henry",
            "basic_auth_password": "secret",
        },
    )

    stub = DummyStreamlit()
    monkeypatch.setattr(basic_auth, "st", stub)
    monkeypatch.setattr(basic_auth, "get_request_credentials", lambda: None)

    with pytest.raises(StopCalled):
        basic_auth.require_basic_auth()

    assert ("info", "Basic 認証が必要です。ユーザーIDとパスワードを入力してください。") in stub.messages()
