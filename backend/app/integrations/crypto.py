"""Token encryption — versioned AES-128-CBC/HMAC-SHA256 via Fernet.

The version prefix ("v1:") means key rotation in Sprint 3 is a one-liner:
  - Add "v2:" branch in decrypt_tokens()
  - Set TOKEN_ENCRYPTION_KEY_V2 and TOKEN_ENCRYPTION_KEY_V1 (old)
  - Migrate background job re-encrypts rows from v1 → v2

Environment variable:
  TOKEN_ENCRYPTION_KEY — Fernet key (32-byte URL-safe base64).
  Generate with:
    python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from __future__ import annotations

import base64
import json
import os

from cryptography.fernet import Fernet, InvalidToken

_VERSION = "v1"


def _fernet() -> Fernet:
    raw = os.environ.get("TOKEN_ENCRYPTION_KEY", "").strip()
    if not raw:
        raise EnvironmentError(
            "TOKEN_ENCRYPTION_KEY is not set. "
            "Generate one with: python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    # Accept both a bare Fernet key (44 chars base64url) and a 64-char hex string
    if len(raw) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw):
        # hex → 32 bytes → base64url → Fernet key
        key = base64.urlsafe_b64encode(bytes.fromhex(raw))
    else:
        key = raw.encode()
    return Fernet(key)


def encrypt_tokens(data: dict) -> str:
    """Encrypt a token dict and return a versioned string safe for DB storage."""
    plaintext = json.dumps(data, separators=(",", ":")).encode()
    ciphertext = _fernet().encrypt(plaintext).decode()
    return f"{_VERSION}:{ciphertext}"


def decrypt_tokens(stored: str | None) -> dict:
    """Decrypt a versioned string back to a token dict.

    Raises ValueError on unknown version or tampered ciphertext.
    """
    if not stored:
        return {}
    if ":" not in stored:
        raise ValueError("Ciphertext is missing version prefix.")
    version, payload = stored.split(":", 1)
    if version == "v1":
        try:
            plaintext = _fernet().decrypt(payload.encode())
            return json.loads(plaintext)
        except InvalidToken as exc:
            raise ValueError("Token decryption failed — key mismatch or tampered data.") from exc
    raise ValueError(f"Unknown token version: {version!r}")
