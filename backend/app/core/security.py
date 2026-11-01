"""Password hashing, JWT handling, secret encryption and secret redaction."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

_ALGORITHM = "HS256"


# --- Passwords ---------------------------------------------------------------


def hash_password(password: str, *, iterations: int | None = None) -> str:
    iterations = iterations or get_settings().password_hash_iterations
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_s, salt_b64, digest_b64 = encoded.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    salt = base64.b64decode(salt_b64)
    expected = base64.b64decode(digest_b64)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations_s))
    return hmac.compare_digest(actual, expected)


# --- JWT -----------------------------------------------------------------------


def create_access_token(subject: str, *, expires_minutes: int | None = None, extra: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=expires_minutes or settings.access_token_expire_minutes)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT. Raises ``jwt.PyJWTError`` on failure."""
    return jwt.decode(token, get_settings().secret_key, algorithms=[_ALGORITHM])


# --- Symmetric encryption for secrets at rest (GitHub / LLM tokens) ------------


def _fernet() -> Fernet:
    settings = get_settings()
    if settings.encryption_key:
        return Fernet(settings.encryption_key.encode())
    derived = hashlib.sha256(("devflow-encryption:" + settings.secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:  # key rotated or data corrupted
        raise ValueError("Stored secret could not be decrypted; reconnect the integration.") from exc


# --- Secret detection / redaction ----------------------------------------------

# Patterns used both to redact content before it is sent to an LLM and by the
# review agent to block commits containing credentials.
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}\b")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("OpenAI API key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("Private key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    (
        "Hardcoded credential",
        re.compile(
            r"""(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)\b\s*[:=]\s*["'][^"'\s]{8,}["']"""
        ),
    ),
]

_PLACEHOLDER_HINTS = ("example", "changeme", "change-me", "placeholder", "your_", "your-", "xxx", "<", "${", "dummy", "test")


def find_secrets(text: str) -> list[tuple[str, str]]:
    """Return ``(kind, match)`` pairs for likely secrets in ``text``."""
    findings: list[tuple[str, str]] = []
    for kind, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(0)
            if kind == "Hardcoded credential" and any(h in value.lower() for h in _PLACEHOLDER_HINTS):
                continue
            findings.append((kind, value))
    return findings


def redact_secrets(text: str) -> str:
    """Replace anything that looks like a credential with a placeholder."""
    for kind, pattern in SECRET_PATTERNS:
        if kind == "Hardcoded credential":
            continue  # keep code readable; strong token patterns are enough for redaction
        text = pattern.sub(f"[REDACTED {kind.upper()}]", text)
    return text
