from __future__ import annotations

import hmac
import secrets
from hashlib import sha256


def generate_otp(*, digits: int = 6) -> str:
    if digits < 4 or digits > 10:
        raise ValueError("OTP digits must be between 4 and 10")
    modulus = 10**digits
    return f"{secrets.randbelow(modulus):0{digits}d}"


def hash_otp(otp: str, pepper: str) -> str:
    return hmac.new(pepper.encode("utf-8"), otp.encode("utf-8"), sha256).hexdigest()


def verify_otp(otp: str, code_hash: str, pepper: str) -> bool:
    candidate = hash_otp(otp, pepper)
    return hmac.compare_digest(candidate, code_hash)
