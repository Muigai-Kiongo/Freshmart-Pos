from __future__ import annotations

from datetime import datetime, timedelta

import jwt as pyjwt
import pytest

from app.core.clock import FakeClock
from app.core.config import Settings
from app.core.jwt import JwtError, JwtKeys, JwtService, jwt_service_from_settings


def test_staff_roundtrip(jwt_service: JwtService) -> None:
    token = jwt_service.encode(
        subject="staff-1",
        audience="staff",
        ttl=timedelta(minutes=15),
        extra={
            "business_id": "b1",
            "outlet_id": "o1",
            "role": "cashier",
            "device_id": "d1",
        },
    )
    payload = jwt_service.decode(token, audience="staff")
    assert payload["sub"] == "staff-1"
    assert payload["aud"] == "staff"
    assert payload["iss"] == "dazu-pos-test"
    assert payload["role"] == "cashier"
    assert "jti" in payload
    assert payload["exp"] > payload["iat"]


def test_staff_token_rejected_as_admin(jwt_service: JwtService) -> None:
    token = jwt_service.encode(
        subject="staff-1", audience="staff", ttl=timedelta(minutes=15)
    )
    with pytest.raises(JwtError):
        jwt_service.decode(token, audience="admin")


def test_expired_token(jwt_service: JwtService, clock) -> None:
    token = jwt_service.encode(
        subject="s",
        audience="signup",
        ttl=timedelta(minutes=15),
        extra={"purpose": "signup"},
    )
    clock.advance(minutes=16)
    with pytest.raises(JwtError) as exc:
        jwt_service.decode(token, audience="signup")
    assert exc.value.code == "INVALID_CREDENTIALS"


def test_secret_rotation_reads_old_kid(jwt_service: JwtService) -> None:
    old = JwtService(
        issuer=jwt_service.issuer,
        staff=type(jwt_service.staff_keys)(
            current_kid="v1", secrets=jwt_service.staff_keys.secrets
        ),
        admin=jwt_service.admin_keys,
        signup=jwt_service.signup_keys,
        reset=jwt_service.reset_keys,
        clock=jwt_service.clock,
    )
    token = old.encode(subject="staff-1", audience="staff", ttl=timedelta(minutes=15))
    payload = jwt_service.decode(token, audience="staff")
    assert payload["sub"] == "staff-1"


def test_unknown_kid_rejected(jwt_service: JwtService) -> None:
    token = pyjwt.encode(
        {"sub": "x", "aud": "staff"},
        "not-a-registered-signing-secret!!",
        algorithm="HS256",
        headers={"kid": "v9"},
    )
    with pytest.raises(JwtError):
        jwt_service.decode(token, audience="staff")


def test_secret_rotation_settings_and_missing_kid_fallback() -> None:
    keys = JwtKeys.from_settings(
        kid="v2",
        secret="current-secret-xxxxxxxxxxxxxxxx",
        extra="v1:previous-secret-xxxxxxxxxxxx, , v3:next-secret-xxxxxxxxxxxx",
    )
    assert keys.secrets == {
        "v1": "previous-secret-xxxxxxxxxxxx",
        "v2": "current-secret-xxxxxxxxxxxxxxxx",
        "v3": "next-secret-xxxxxxxxxxxx",
    }
    assert keys.secret_for_kid(None) == "current-secret-xxxxxxxxxxxxxxxx"

    with pytest.raises(JwtError) as exc:
        JwtKeys.from_settings(kid="v1", secret="current", extra="invalid-entry")
    assert exc.value.code == "VALIDATION_ERROR"


def test_jwt_service_loads_independent_keys_from_settings() -> None:
    settings = Settings(
        jwt_kid="v2",
        jwt_staff_secret="staff-secret-xxxxxxxxxxxxxxxx",
        jwt_staff_secrets="v1:old-staff-secret-xxxxxxxxxxxx",
        jwt_admin_secret="admin-secret-xxxxxxxxxxxxxxxx",
        jwt_signup_secret="signup-secret-xxxxxxxxxxxxxxx",
        jwt_reset_secret="reset-secret-xxxxxxxxxxxxxxxx",
    )
    service = jwt_service_from_settings(settings)
    assert service.staff_keys.current_kid == "v2"
    assert service.staff_keys.secret_for_kid("v1") == "old-staff-secret-xxxxxxxxxxxx"
    assert service.admin_keys.signing_secret() == (
        "v2",
        "admin-secret-xxxxxxxxxxxxxxxx",
    )
    assert service.signup_keys.signing_secret() == (
        "v2",
        "signup-secret-xxxxxxxxxxxxxxx",
    )
    assert service.reset_keys.signing_secret() == (
        "v2",
        "reset-secret-xxxxxxxxxxxxxxxx",
    )


def test_malformed_and_bad_signature_tokens_are_rejected(
    jwt_service: JwtService,
) -> None:
    with pytest.raises(JwtError) as malformed:
        jwt_service.decode("not-a-jwt", audience="staff")
    assert malformed.value.code == "INVALID_CREDENTIALS"

    token = pyjwt.encode(
        {
            "sub": "staff-1",
            "iss": jwt_service.issuer,
            "aud": "staff",
            "iat": 1_794_225_600,
            "nbf": 1_794_225_600,
            "exp": 1_794_226_500,
            "jti": "token-id",
        },
        "wrong-signing-secret-xxxxxxxxxxxx",
        algorithm="HS256",
        headers={"kid": "v2"},
    )
    with pytest.raises(JwtError) as invalid:
        jwt_service.decode(token, audience="staff")
    assert invalid.value.code == "INVALID_CREDENTIALS"


def test_missing_kid_uses_current_secret_and_future_nbf_is_rejected(
    jwt_service: JwtService, clock: FakeClock
) -> None:
    now = int(clock.now().timestamp())
    claims = {
        "sub": "staff-1",
        "iss": jwt_service.issuer,
        "aud": "staff",
        "iat": now,
        "nbf": now,
        "exp": now + 900,
        "jti": "without-kid",
    }
    token_without_kid = pyjwt.encode(
        claims,
        jwt_service.staff_keys.secrets[jwt_service.staff_keys.current_kid],
        algorithm="HS256",
    )
    assert jwt_service.decode(token_without_kid, audience="staff")["sub"] == "staff-1"

    future_claims = {**claims, "nbf": now + 60, "jti": "future-token"}
    future_token = pyjwt.encode(
        future_claims,
        jwt_service.staff_keys.secrets[jwt_service.staff_keys.current_kid],
        algorithm="HS256",
        headers={"kid": jwt_service.staff_keys.current_kid},
    )
    with pytest.raises(JwtError) as exc:
        jwt_service.decode(future_token, audience="staff")
    assert exc.value.code == "INVALID_CREDENTIALS"
    assert "not yet valid" in exc.value.message


def test_naive_clock_is_treated_as_utc(jwt_service: JwtService) -> None:
    naive_clock = FakeClock(datetime(2026, 11, 9, 12, 0))
    service = JwtService(
        issuer=jwt_service.issuer,
        staff=jwt_service.staff_keys,
        admin=jwt_service.admin_keys,
        signup=jwt_service.signup_keys,
        reset=jwt_service.reset_keys,
        clock=naive_clock,
    )
    token = service.encode(
        subject="staff-1", audience="staff", ttl=timedelta(minutes=15)
    )
    assert service.decode(token, audience="staff")["sub"] == "staff-1"
