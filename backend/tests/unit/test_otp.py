from __future__ import annotations

import pytest

from app.core.otp import generate_otp, hash_otp, verify_otp


def test_generate_otp_is_six_digits() -> None:
    otp = generate_otp()
    assert len(otp) == 6
    assert otp.isdigit()


def test_otp_hash_roundtrip() -> None:
    otp = "482910"
    pepper = "otp-pepper"
    digest = hash_otp(otp, pepper)
    assert digest != otp
    assert verify_otp(otp, digest, pepper)
    assert not verify_otp("482911", digest, pepper)
    assert not verify_otp(otp, digest, "other-pepper")


def test_otp_codes_are_not_constant() -> None:
    samples = {generate_otp() for _ in range(25)}
    assert len(samples) > 1


@pytest.mark.parametrize("digits", [3, 11])
def test_otp_rejects_unsupported_digit_counts(digits: int) -> None:
    with pytest.raises(ValueError, match="between 4 and 10"):
        generate_otp(digits=digits)


def test_otp_supports_custom_digit_count() -> None:
    otp = generate_otp(digits=8)
    assert len(otp) == 8
    assert otp.isdigit()
