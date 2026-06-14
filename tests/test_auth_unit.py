import bcrypt
import pytest
from itsdangerous import BadData

from app.auth import (
    hash_password,
    sign_token,
    verify_password,
    verify_token,
)


def test_hash_and_verify_password_roundtrip():
    hashed = hash_password("s3cret")
    assert hashed != "s3cret"
    assert verify_password("s3cret", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_sign_and_verify_token_roundtrip():
    secret = "test-secret-value"
    token = sign_token(secret, {"scope": "main"})
    assert isinstance(token, str)
    assert verify_token(secret, token) == {"scope": "main"}


def test_verify_token_rejects_tampered_token():
    secret = "test-secret-value"
    token = sign_token(secret, {"scope": "main"})
    tampered = token + "x"
    assert verify_token(secret, tampered) is None


def test_verify_token_rejects_wrong_secret():
    token = sign_token("secret-a", {"scope": "main"})
    assert verify_token("secret-b", token) is None


def test_verify_token_handles_garbage():
    assert verify_token("secret", "not-a-real-token") is None
    assert verify_token("secret", "") is None


def test_verify_token_handles_baddata_from_serializer(monkeypatch):
    def raise_bad_data(self, token):
        raise BadData("bad payload")

    monkeypatch.setattr("app.auth.URLSafeSerializer.loads", raise_bad_data)
    assert verify_token("secret", "token") is None


def test_hash_password_raises_controlled_error_when_bcrypt_backend_missing(monkeypatch):
    def raise_missing_backend(*args, **kwargs):
        raise RuntimeError("bcrypt backend missing")

    monkeypatch.setattr(bcrypt, "hashpw", raise_missing_backend)

    with pytest.raises(RuntimeError, match="bcrypt backend unavailable"):
        hash_password("s3cret")
