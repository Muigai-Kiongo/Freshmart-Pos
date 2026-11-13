from __future__ import annotations

from app.core.hashing import (
    TEST_ARGON2_PARAMS,
    SecretHasher,
    generate_device_token,
    hash_token,
)


def test_password_hash_and_verify(hasher: SecretHasher) -> None:
    digest = hasher.hash_password("correct-horse-battery")
    assert digest.startswith("$argon2id$")
    assert hasher.verify_password("correct-horse-battery", digest)
    assert not hasher.verify_password("wrong-password-xx", digest)


def test_dummy_verify_when_user_missing(hasher: SecretHasher) -> None:
    assert hasher.verify_password_dummy_if_missing("anything-long", None) is False
    digest = hasher.hash_password("correct-horse-battery")
    assert (
        hasher.verify_password_dummy_if_missing("correct-horse-battery", digest) is True
    )


def test_pin_uses_pepper(hasher: SecretHasher) -> None:
    digest = hasher.hash_pin("2580")
    assert hasher.verify_pin("2580", digest)
    other = SecretHasher(TEST_ARGON2_PARAMS, pin_pepper="different-pepper")
    assert not other.verify_pin("2580", digest)


def test_device_token_is_hashed() -> None:
    plain, digest = generate_device_token()
    assert digest == hash_token(plain)
    assert digest != plain
    assert len(digest) == 64
