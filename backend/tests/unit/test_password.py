from __future__ import annotations

import pytest

from app.core.errors import WeakPasswordError
from app.core.password import validate_password


def test_accepts_strong_password() -> None:
    assert validate_password("correct-horse-battery") == "correct-horse-battery"


def test_rejects_short_password() -> None:
    with pytest.raises(WeakPasswordError) as exc:
        validate_password("short")
    assert exc.value.code == "WEAK_PASSWORD"


def test_rejects_common_password() -> None:
    with pytest.raises(WeakPasswordError):
        validate_password("password123")


def test_rejects_password_equal_to_phone() -> None:
    phone = "254712345678"
    with pytest.raises(WeakPasswordError):
        validate_password("0712345678", phone_e164=phone)
    with pytest.raises(WeakPasswordError):
        validate_password("254712345678", phone_e164=phone)
    with pytest.raises(WeakPasswordError):
        validate_password("+254712345678", phone_e164=phone)


def test_unrelated_password_ok_with_phone() -> None:
    validate_password("market-stall-92", phone_e164="254712345678")


def test_missing_common_password_file_is_handled(monkeypatch, tmp_path) -> None:
    import app.core.password as password_module

    password_module.load_common_passwords.cache_clear()
    monkeypatch.setattr(
        password_module, "_DATA_FILE", tmp_path / "missing-passwords.txt"
    )
    try:
        assert password_module.validate_password("market-stall-92") == "market-stall-92"
    finally:
        password_module.load_common_passwords.cache_clear()


def test_non_string_password_is_rejected() -> None:
    with pytest.raises(WeakPasswordError, match="Password is required"):
        validate_password(None)  # type: ignore[arg-type]
