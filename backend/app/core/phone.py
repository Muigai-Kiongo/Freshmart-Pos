from __future__ import annotations

import re

from app.core.errors import PhoneNormalizationError

_DEFAULT_PREFIXES = ("2547", "2541")
_NON_DIGIT_PLUS = re.compile(r"[^\d+]")


def national_from_e164(e164: str) -> str:
    """254712345678 -> 0712345678."""
    if e164.startswith("254") and len(e164) == 12:
        return "0" + e164[3:]
    return e164


def phone_variants(e164: str) -> set[str]:
    """Forms an attacker or owner might type; used to reject password==phone."""
    national = national_from_e164(e164)
    variants = {
        e164,
        f"+{e164}",
        national,
        e164.removeprefix("254"),
    }
    return {v for v in variants if v}


def normalize_ke_phone(
    raw: str | None,
    *,
    allowed_prefixes: tuple[str, ...] | list[str] | None = None,
) -> str:
    """
    Normalize a Kenyan mobile number to E.164 without '+', e.g. 254712345678.

    Accepts: 07XXXXXXXX, 01XXXXXXXX, 7XXXXXXXX, 1XXXXXXXX,
    +2547XXXXXXXX, 2547XXXXXXXX, and spaced/dashed variants.
    """
    if raw is None or not str(raw).strip():
        raise PhoneNormalizationError("Phone number is required")

    cleaned = _NON_DIGIT_PLUS.sub("", str(raw).strip())
    cleaned = cleaned.removeprefix("00")
    cleaned = cleaned.removeprefix("+")

    if not cleaned.isdigit():
        raise PhoneNormalizationError("Phone number must contain only digits")

    if cleaned.startswith("0") and len(cleaned) == 10:
        cleaned = "254" + cleaned[1:]
    elif len(cleaned) == 9 and cleaned[0] in {"7", "1"}:
        cleaned = "254" + cleaned

    prefixes = (
        tuple(allowed_prefixes) if allowed_prefixes is not None else _DEFAULT_PREFIXES
    )
    if not any(cleaned.startswith(prefix) for prefix in prefixes):
        raise PhoneNormalizationError(
            "Phone number is not in an allowed country/prefix range"
        )
    if len(cleaned) != 12:
        raise PhoneNormalizationError(
            "Phone number must be 12 digits in E.164 form (254XXXXXXXXX)"
        )

    return cleaned
