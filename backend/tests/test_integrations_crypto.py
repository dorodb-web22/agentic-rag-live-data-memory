"""Sprint 2 — Tests for token encryption/decryption (all offline, no DB needed)."""
from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet


# ── Helpers ──────────────────────────────────────────────────────────────────

def _set_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", key)
    return key


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_encrypt_decrypt_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_key(monkeypatch)
    # Must re-import AFTER env var is set so the module picks up the key.
    import importlib
    import app.integrations.crypto as crypto_mod
    importlib.reload(crypto_mod)

    payload = {"access_token": "tok_abc123", "refresh_token": "ref_xyz789", "expires_at": 9999999999}
    ciphertext = crypto_mod.encrypt_tokens(payload)
    recovered = crypto_mod.decrypt_tokens(ciphertext)
    assert recovered == payload


def test_version_prefix_present(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_key(monkeypatch)
    import importlib
    import app.integrations.crypto as crypto_mod
    importlib.reload(crypto_mod)

    ciphertext = crypto_mod.encrypt_tokens({"access_token": "t"})
    assert ciphertext.startswith("v1:"), f"Expected v1: prefix, got: {ciphertext[:10]}"


def test_decrypt_raises_on_tampered(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_key(monkeypatch)
    import importlib
    import app.integrations.crypto as crypto_mod
    importlib.reload(crypto_mod)

    ciphertext = crypto_mod.encrypt_tokens({"access_token": "t"})
    # Tamper: flip a byte in the base64 payload
    parts = ciphertext.split(":", 1)
    tampered = parts[0] + ":" + parts[1][:-4] + "XXXX"
    with pytest.raises((ValueError, Exception)):
        crypto_mod.decrypt_tokens(tampered)


def test_decrypt_raises_on_unknown_version(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_key(monkeypatch)
    import importlib
    import app.integrations.crypto as crypto_mod
    importlib.reload(crypto_mod)

    with pytest.raises(ValueError):
        crypto_mod.decrypt_tokens("v99:somegarbagedata")


def test_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    import importlib
    import app.integrations.crypto as crypto_mod
    importlib.reload(crypto_mod)

    with pytest.raises((EnvironmentError, ValueError, Exception)):
        crypto_mod.encrypt_tokens({"access_token": "t"})
