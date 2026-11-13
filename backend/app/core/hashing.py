from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


class Argon2Params:
    def __init__(
        self,
        *,
        time_cost: int = 3,
        memory_cost: int = 65536,
        parallelism: int = 2,
        hash_len: int = 32,
        salt_len: int = 16,
    ) -> None:
        self.time_cost = time_cost
        self.memory_cost = memory_cost
        self.parallelism = parallelism
        self.hash_len = hash_len
        self.salt_len = salt_len


TEST_ARGON2_PARAMS = Argon2Params(time_cost=1, memory_cost=8, parallelism=1)


class SecretHasher:
    """argon2id for passwords/PINs, plus HMAC-SHA256 for OTPs/tokens."""

    def __init__(
        self, params: Argon2Params | None = None, *, pin_pepper: str = "dev-pepper"
    ) -> None:
        p = params or Argon2Params()
        self._ph = PasswordHasher(
            time_cost=p.time_cost,
            memory_cost=p.memory_cost,
            parallelism=p.parallelism,
            hash_len=p.hash_len,
            salt_len=p.salt_len,
            type=Type.ID,
        )
        self.pin_pepper = pin_pepper
        self._dummy_hash = self._ph.hash("__dazu_dummy_password__")

    def hash_password(self, password: str) -> str:
        return self._ph.hash(password)

    def verify_password(self, password: str, password_hash: str) -> bool:
        try:
            return bool(self._ph.verify(password_hash, password))
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def verify_password_dummy_if_missing(
        self, password: str, password_hash: str | None
    ) -> bool:
        """Always run a verify so missing users take a similar amount of time."""
        if not password_hash:
            self.verify_password(password, self._dummy_hash)
            return False
        return self.verify_password(password, password_hash)

    def _pin_material(self, pin: str) -> str:
        return hmac.new(
            self.pin_pepper.encode("utf-8"), pin.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def hash_pin(self, pin: str) -> str:
        return self._ph.hash(self._pin_material(pin))

    def verify_pin(self, pin: str, pin_hash: str) -> bool:
        return self.verify_password(self._pin_material(pin), pin_hash)

    def verify_pin_dummy_if_missing(self, pin: str, pin_hash: str | None) -> bool:
        if not pin_hash:
            self.verify_pin(pin, self._dummy_hash)
            return False
        return self.verify_pin(pin, pin_hash)


def hash_token(value: str) -> str:
    """SHA-256 hex digest for refresh tokens, device tokens, pairing codes."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def generate_urlsafe_token(*, nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def generate_device_token() -> tuple[str, str]:
    plain = generate_urlsafe_token(nbytes=32)
    return plain, hash_token(plain)
