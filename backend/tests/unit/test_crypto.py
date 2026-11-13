from __future__ import annotations

import pytest

from app.core.crypto import SecretBox


def test_encrypt_roundtrip(fernet_key: str) -> None:
    box = SecretBox(fernet_key)
    token = box.encrypt("JBSWY3DPEHPK3PXP")
    assert token != "JBSWY3DPEHPK3PXP"
    assert box.decrypt(token) == "JBSWY3DPEHPK3PXP"


def test_wrong_key_fails(fernet_key: str) -> None:
    from app.core.crypto import generate_fernet_key

    box = SecretBox(fernet_key)
    token = box.encrypt("secret")
    other = SecretBox(generate_fernet_key())
    with pytest.raises(ValueError):
        other.decrypt(token)


def test_invalid_fernet_key_is_rejected() -> None:
    with pytest.raises(ValueError):
        SecretBox("not-a-fernet-key")
