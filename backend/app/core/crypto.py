from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class SecretBox:
    """Encrypt MFA TOTP secrets at rest. Key must be a Fernet urlsafe-base64 key."""

    def __init__(self, key: str | bytes) -> None:
        if isinstance(key, str):
            key_bytes = key.encode("utf-8")
        else:
            key_bytes = key
        self._fernet = Fernet(key_bytes)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Unable to decrypt secret") from exc


def generate_fernet_key() -> str:
    return Fernet.generate_key().decode("utf-8")
