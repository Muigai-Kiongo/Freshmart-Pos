from __future__ import annotations

import pytest

from app.core.errors import PhoneNormalizationError
from app.core.phone import national_from_e164, normalize_ke_phone, phone_variants


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0712345678", "254712345678"),
        ("0112345678", "254112345678"),
        ("+254712345678", "254712345678"),
        ("254712345678", "254712345678"),
        ("712345678", "254712345678"),
        ("112345678", "254112345678"),
        ("+254 712 345 678", "254712345678"),
        ("07-123-45678", "254712345678"),
        ("(0712) 345 678", "254712345678"),
        ("00712345678", "254712345678"),
        ("00254712345678", "254712345678"),
        ("0790112233", "254790112233"),
        ("0101234567", "254101234567"),
    ],
)
def test_normalize_kenyan_numbers(raw: str, expected: str) -> None:
    assert normalize_ke_phone(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "123",
        "+14155550123",
        "254812345678",
        "25471234567",
        "2547123456789",
        "abcdefghij",
        "072123456",
    ],
)
def test_reject_invalid_or_foreign_numbers(raw: str | None) -> None:
    with pytest.raises(PhoneNormalizationError) as exc:
        normalize_ke_phone(raw)
    assert exc.value.code == "VALIDATION_ERROR"


def test_non_kenyan_allowed_when_prefix_configured() -> None:
    assert (
        normalize_ke_phone("+255712345678", allowed_prefixes=("2557",))
        == "255712345678"
    )


def test_national_and_variants() -> None:
    e164 = "254712345678"
    assert national_from_e164(e164) == "0712345678"
    variants = phone_variants(e164)
    assert "0712345678" in variants
    assert "+254712345678" in variants
    assert "712345678" in variants


def test_non_e164_phone_is_returned_unchanged_by_national_helper() -> None:
    assert national_from_e164("123456789") == "123456789"
