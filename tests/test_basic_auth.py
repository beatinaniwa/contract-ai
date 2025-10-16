import base64
import hashlib
import sys
from pathlib import Path

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
