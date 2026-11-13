from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.core.errors import WeakPasswordError
from app.core.phone import phone_variants

_MIN_LENGTH = 10
_DATA_FILE = Path(__file__).parent / "data" / "common_passwords.txt"


@lru_cache(maxsize=1)
def load_common_passwords() -> frozenset[str]:
    if not _DATA_FILE.exists():
        return frozenset()
    lines = _DATA_FILE.read_text(encoding="utf-8").splitlines()
    return frozenset(
        line.strip().lower()
        for line in lines
        if line.strip() and not line.startswith("#")
    )


def validate_password(password: str, *, phone_e164: str | None = None) -> str:
    if not isinstance(password, str):
        raise WeakPasswordError("Password is required")
    if len(password) < _MIN_LENGTH:
        raise WeakPasswordError(
            f"Password must be at least {_MIN_LENGTH} characters",
            details={"min_length": _MIN_LENGTH},
        )
    if password.lower() in load_common_passwords():
        raise WeakPasswordError("Password is too common")
    if phone_e164:
        variants = {v.lower() for v in phone_variants(phone_e164)}
        if password.lower() in variants or "".join(
            ch for ch in password if ch.isdigit()
        ) in {
            phone_e164,
            phone_e164.removeprefix("254"),
        }:
            raise WeakPasswordError("Password must not be the same as the phone number")
    return password
