import jwt
import pytest

from app.core.security import (
    create_access_token,
    decode_access_token,
    decrypt_secret,
    encrypt_secret,
    find_secrets,
    hash_password,
    redact_secrets,
    verify_password,
)


def test_password_hash_roundtrip():
    encoded = hash_password("s3cret-password", iterations=1000)
    assert encoded.startswith("pbkdf2_sha256$1000$")
    assert verify_password("s3cret-password", encoded)
    assert not verify_password("wrong", encoded)
    assert not verify_password("x", "garbage")


def test_jwt_roundtrip_and_tamper():
    token = create_access_token("user-1")
    assert decode_access_token(token)["sub"] == "user-1"
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(token + "x")


def test_encrypt_secret_roundtrip():
    cipher = encrypt_secret("ghp_example")
    assert "ghp_example" not in cipher
    assert decrypt_secret(cipher) == "ghp_example"
    with pytest.raises(ValueError):
        decrypt_secret("not-a-token")


def test_secret_detection_and_redaction():
    token = "ghp_" + "a" * 36
    text = f'GITHUB = "{token}"\npassword = "hunter2hunter2"\napi_key = "your_api_key_here"'
    kinds = [kind for kind, _ in find_secrets(text)]
    assert "GitHub token" in kinds
    assert "Hardcoded credential" in kinds
    assert sum(1 for k in kinds if k == "Hardcoded credential") == 1  # placeholder ignored
    redacted = redact_secrets(text)
    assert token not in redacted and "[REDACTED GITHUB TOKEN]" in redacted
