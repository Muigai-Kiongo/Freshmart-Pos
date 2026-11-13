from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_redis, get_secret_hasher, get_sms_provider
from app.api.schemas.signup import SignupCompleteRequest, SignupStartRequest
from app.core.clock import FakeClock
from app.core.config import Settings, get_settings
from app.core.errors import AuthError
from app.core.jwt import jwt_service_from_settings
from app.db.session import get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.business import Business, BusinessSettings, ProductCategory
from app.models.consumed_token import ConsumedToken
from app.models.device import Device
from app.models.enums import StaffRole
from app.models.idempotency import IdempotencyKey
from app.models.otp_challenge import OtpChallenge
from app.models.outlet import Outlet
from app.models.refresh_token import RefreshToken
from app.models.staff import Staff
from app.services.signup import (
    SignupService,
    _decrypt_response,
    _idempotency_box,
    _preferred_language,
)


class RecordingSmsProvider:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def send(self, phone: str, message: str) -> None:
        self.messages.append((phone, message))


@pytest.fixture
async def signup_api(db_session: AsyncSession, redis, hasher):
    settings = Settings(
        _env_file=None,
        environment="test",
        dev_otp_code="000000",
        otp_phone_hourly_limit=10,
        otp_ip_hourly_limit=20,
        otp_global_daily_limit=100,
    )
    sms = RecordingSmsProvider()
    original_overrides = app.dependency_overrides.copy()

    async def override_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_redis] = lambda: redis
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_secret_hasher] = lambda: hasher
    app.dependency_overrides[get_sms_provider] = lambda: sms

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client, sms, settings
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)


async def _start_and_verify(client: AsyncClient, phone: str = "0712345678") -> str:
    started = await client.post("/api/v1/auth/signup/start", json={"phone": phone})
    assert started.status_code == 200
    verified = await client.post(
        "/api/v1/auth/signup/verify-otp",
        json={"challenge_id": started.json()["challenge_id"], "otp": "000000"},
    )
    assert verified.status_code == 200
    return verified.json()["signup_token"]


def _signup_body(*, device: bool = True) -> dict:
    return {
        "owner_name": "Amina Wanjiku",
        "business_name": "Amina's Duka",
        "mode": "simple",
        "county": "Nairobi",
        "email": "AMINA@example.com" if device else None,
        "password": "market-stall-92",
        "pin": "2580",
        "accept_terms": True,
        "terms_version": "2026-01",
        "device": (
            {
                "name": "Amina's Android",
                "platform": "android",
                "fingerprint": "test-device-fingerprint",
                "app_version": "1.0.0",
            }
            if device
            else None
        ),
    }


async def test_signup_flow_creates_business_owner_defaults_and_device(
    signup_api, db_session
) -> None:
    client, sms, settings = signup_api
    token = await _start_and_verify(client)
    assert sms.messages[0][0] == "254712345678"
    assert "000000" in sms.messages[0][1]

    completed = await client.post(
        "/api/v1/auth/signup/complete",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "signup-test-0001",
        },
        json=_signup_body(),
    )
    assert completed.status_code == 201, completed.text
    result = completed.json()
    assert result["business"]["status"] == "trial"
    assert result["business"]["mode"] == "simple"
    assert result["outlet"]["name"] == "Main"
    assert result["staff"]["role"] == "owner"
    assert result["device_token"]
    assert result["access_token"]
    assert result["refresh_token"]
    assert result["refresh_expires_in"] == settings.staff_refresh_days * 86400

    business = await db_session.get(Business, UUID(result["business"]["id"]))
    owner = await db_session.get(Staff, UUID(result["staff"]["id"]))
    device = await db_session.scalar(
        select(Device).where(Device.business_id == business.id)
    )
    refresh = await db_session.scalar(
        select(RefreshToken).where(RefreshToken.subject_id == owner.id)
    )
    categories = await db_session.scalars(
        select(ProductCategory)
        .where(ProductCategory.business_id == business.id)
        .order_by(ProductCategory.sort_order)
    )
    settings_row = await db_session.get(BusinessSettings, business.id)
    assert business.trial_ends_at is not None
    assert owner.phone == "254712345678"
    assert owner.phone_verified_at is not None
    assert owner.email == "amina@example.com"
    assert owner.pin_hash != "2580"
    assert device.device_token_hash != result["device_token"]
    assert refresh.token_hash
    assert [category.name for category in categories] == [
        "General",
        "Produce",
        "Drinks",
        "Household",
    ]
    assert settings_row.vat_enabled is False
    assert await db_session.scalar(select(func.count()).select_from(AuditLog)) >= 3


async def test_signup_complete_replay_returns_identical_response_and_does_not_duplicate(
    signup_api, db_session
) -> None:
    client, _, _ = signup_api
    token = await _start_and_verify(client)
    headers = {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": "signup-test-0002",
    }
    body = _signup_body()

    first = await client.post(
        "/api/v1/auth/signup/complete", headers=headers, json=body
    )
    replay = await client.post(
        "/api/v1/auth/signup/complete", headers=headers, json=body
    )

    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert await db_session.scalar(select(func.count()).select_from(Business)) == 1
    record = await db_session.scalar(select(IdempotencyKey))
    assert "encrypted" in record.response_body
    assert first.json()["refresh_token"] not in str(record.response_body)


async def test_service_complete_directly_returns_session_tokens(
    signup_api, db_session, redis, hasher
) -> None:
    _, sms, settings = signup_api
    service = SignupService(
        session=db_session,
        redis=redis,
        settings=settings,
        jwt_service=jwt_service_from_settings(settings),
        hasher=hasher,
        sms_provider=sms,
    )
    started = await service.start(
        SignupStartRequest(phone="0712345678"),
        ip="127.0.0.1",
        user_agent=None,
        accept_language="sw-KE,en;q=0.8",
    )
    verified = await service.verify_otp(
        UUID(started["challenge_id"]), "000000", ip="127.0.0.1"
    )

    result = await service.complete(
        SignupCompleteRequest.model_validate(_signup_body()),
        signup_token=verified["signup_token"],
        idempotency_key="signup-direct-01",
        ip="127.0.0.1",
        user_agent=None,
    )

    assert result["access_token"]
    assert result["refresh_token"]
    with pytest.raises(AuthError) as used_token:
        await service.complete(
            SignupCompleteRequest.model_validate(_signup_body()),
            signup_token=verified["signup_token"],
            idempotency_key="signup-direct-reuse",
            ip="127.0.0.1",
            user_agent=None,
        )
    assert used_token.value.code == "INVALID_CREDENTIALS"

    wrong_purpose_token = service.jwt_service.encode(
        subject="254712345678",
        audience="signup",
        ttl=timedelta(minutes=15),
        extra={"purpose": "password_reset", "phone": "254712345678"},
    )
    with pytest.raises(AuthError) as wrong_purpose:
        await service.complete(
            SignupCompleteRequest.model_validate(_signup_body()),
            signup_token=wrong_purpose_token,
            idempotency_key="signup-direct-purpose",
            ip="127.0.0.1",
            user_agent=None,
        )
    assert wrong_purpose.value.code == "INVALID_CREDENTIALS"


async def test_signup_rejects_reuse_with_different_idempotency_key(signup_api) -> None:
    client, _, _ = signup_api
    token = await _start_and_verify(client)
    headers = {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": "signup-test-0003",
    }
    first = await client.post(
        "/api/v1/auth/signup/complete", headers=headers, json=_signup_body()
    )
    assert first.status_code == 201

    reused = await client.post(
        "/api/v1/auth/signup/complete",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "signup-test-0004",
        },
        json=_signup_body(),
    )
    assert reused.status_code == 401
    assert reused.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_idempotency_key_rejects_a_different_body(signup_api) -> None:
    client, _, _ = signup_api
    token = await _start_and_verify(client)
    headers = {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": "signup-test-0005",
    }
    first = await client.post(
        "/api/v1/auth/signup/complete", headers=headers, json=_signup_body()
    )
    assert first.status_code == 201

    changed = _signup_body()
    changed["business_name"] = "Different Duka"
    replay = await client.post(
        "/api/v1/auth/signup/complete", headers=headers, json=changed
    )
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_complete_rejects_invalid_authorization_and_weak_credentials(
    signup_api,
) -> None:
    client, _, _ = signup_api
    invalid_auth = await client.post(
        "/api/v1/auth/signup/complete",
        headers={
            "Authorization": "Bearer invalid",
            "Idempotency-Key": "signup-test-invalid",
        },
        json=_signup_body(),
    )
    assert invalid_auth.status_code == 401
    assert invalid_auth.json()["error"]["code"] == "INVALID_CREDENTIALS"

    token = await _start_and_verify(client)
    body = _signup_body()
    body["password"] = "password123"
    weak_password = await client.post(
        "/api/v1/auth/signup/complete",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "signup-test-weak-01",
        },
        json=body,
    )
    assert weak_password.status_code == 422
    assert weak_password.json()["error"]["code"] == "WEAK_PASSWORD"

    body = _signup_body()
    body["pin"] = "1234"
    weak_pin = await client.post(
        "/api/v1/auth/signup/complete",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "signup-test-weak-02",
        },
        json=body,
    )
    assert weak_pin.status_code == 422
    assert weak_pin.json()["error"]["code"] == "WEAK_PIN"

    body = _signup_body()
    body["accept_terms"] = False
    missing_terms = await client.post(
        "/api/v1/auth/signup/complete",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "signup-test-weak-03",
            "Accept-Language": "sw-KE,en;q=0.8",
        },
        json=body,
    )
    assert missing_terms.status_code == 422
    assert missing_terms.json()["error"]["code"] == "VALIDATION_ERROR"
    assert missing_terms.json()["error"]["message"] == "Taarifa ulizotuma si sahihi."


async def test_pro_signup_without_device_enables_vat_and_omits_session_tokens(
    signup_api, db_session
) -> None:
    client, _, _ = signup_api
    token = await _start_and_verify(client, "0711111111")
    body = _signup_body(device=False)
    body["mode"] = "pro"

    completed = await client.post(
        "/api/v1/auth/signup/complete",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "signup-test-pro-01",
        },
        json=body,
    )
    assert completed.status_code == 201
    result = completed.json()
    assert result["device_token"] is None
    assert result["access_token"] is None
    assert result["refresh_token"] is None
    settings_row = await db_session.get(
        BusinessSettings, UUID(result["business"]["id"])
    )
    assert settings_row.vat_enabled is True


async def test_signup_failure_rolls_back_all_rows(
    signup_api, db_session, redis, hasher
) -> None:
    client, sms, settings = signup_api
    token = await _start_and_verify(client, "0711111111")

    class PinHashFailure:
        def hash_password(self, password: str) -> str:
            return hasher.hash_password(password)

        def hash_pin(self, pin: str) -> str:
            raise RuntimeError("simulated PIN hasher failure")

    service = SignupService(
        session=db_session,
        redis=redis,
        settings=settings,
        jwt_service=jwt_service_from_settings(settings),
        hasher=PinHashFailure(),
        sms_provider=sms,
    )
    with pytest.raises(RuntimeError, match="simulated PIN hasher failure"):
        await service.complete(
            SignupCompleteRequest.model_validate(_signup_body()),
            signup_token=token,
            idempotency_key="signup-rollback-01",
            ip="127.0.0.1",
            user_agent=None,
        )

    assert await db_session.scalar(select(func.count()).select_from(Business)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Outlet)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Staff)) == 0
    assert (
        await db_session.scalar(select(func.count()).select_from(IdempotencyKey)) == 0
    )
    assert await db_session.scalar(select(func.count()).select_from(ConsumedToken)) == 0


async def test_signup_start_response_shape_does_not_disclose_existing_owner(
    signup_api, db_session
) -> None:
    client, sms, _ = signup_api
    db_session.add(
        Staff(name="Existing Owner", role=StaffRole.OWNER, phone="254712345678")
    )
    await db_session.commit()

    existing = await client.post(
        "/api/v1/auth/signup/start", json={"phone": "0712345678"}
    )
    new = await client.post("/api/v1/auth/signup/start", json={"phone": "0711111111"})

    assert existing.status_code == new.status_code == 200
    assert (
        set(existing.json())
        == set(new.json())
        == {"challenge_id", "resend_after_seconds"}
    )
    assert existing.json()["resend_after_seconds"] == new.json()["resend_after_seconds"]
    assert "already registered" in sms.messages[0][1]
    assert "000000" in sms.messages[1][1]


async def test_five_wrong_otp_attempts_consume_challenge(signup_api) -> None:
    client, _, _ = signup_api
    started = await client.post(
        "/api/v1/auth/signup/start", json={"phone": "0712345678"}
    )
    challenge_id = started.json()["challenge_id"]

    for attempt in range(5):
        response = await client.post(
            "/api/v1/auth/signup/verify-otp",
            json={"challenge_id": challenge_id, "otp": "123456"},
        )
        assert response.json()["error"]["code"] == (
            "OTP_TOO_MANY_ATTEMPTS" if attempt == 4 else "OTP_INVALID"
        )

    replay = await client.post(
        "/api/v1/auth/signup/verify-otp",
        json={"challenge_id": challenge_id, "otp": "000000"},
    )
    assert replay.status_code == 429
    assert replay.json()["error"]["code"] == "OTP_TOO_MANY_ATTEMPTS"


async def test_resend_cooldown_and_expiry_are_enforced(
    db_session, redis, hasher
) -> None:
    now = datetime.now(UTC)
    clock = FakeClock(now)
    settings = Settings(
        _env_file=None,
        environment="test",
        otp_resend_cooldown_seconds=60,
        otp_phone_hourly_limit=10,
        otp_ip_hourly_limit=20,
        otp_global_daily_limit=100,
    )
    sms = RecordingSmsProvider()
    service = SignupService(
        session=db_session,
        redis=redis,
        settings=settings,
        jwt_service=jwt_service_from_settings(settings, clock),
        hasher=hasher,
        sms_provider=sms,
        clock=clock,
    )
    started = await service.start(
        SignupStartRequest(phone="0712345678"),
        ip="127.0.0.1",
        user_agent=None,
        accept_language="sw,en;q=0.8",
    )
    challenge_id = UUID(started["challenge_id"])

    with pytest.raises(AuthError) as cooldown:
        await service.resend(
            challenge_id, ip="127.0.0.1", user_agent=None, accept_language="sw"
        )
    assert getattr(cooldown.value, "code", None) == "RATE_LIMITED"
    assert len(sms.messages) == 1

    clock.advance(seconds=61)
    for _ in range(settings.otp_max_resends):
        resent = await service.resend(
            challenge_id, ip="127.0.0.1", user_agent=None, accept_language="sw"
        )
        assert resent["challenge_id"] == started["challenge_id"]
        assert "Nambari yako" in sms.messages[-1][1]
        clock.advance(seconds=61)

    with pytest.raises(AuthError) as max_resends:
        await service.resend(
            challenge_id, ip="127.0.0.1", user_agent=None, accept_language="sw"
        )
    assert max_resends.value.code == "RATE_LIMITED"

    clock.advance(seconds=settings.otp_ttl_seconds + 1)
    with pytest.raises(AuthError) as expired:
        await service.verify_otp(challenge_id, "000000", ip="127.0.0.1")
    assert getattr(expired.value, "code", None) == "OTP_EXPIRED"
    challenge = await db_session.get(OtpChallenge, challenge_id)
    assert challenge.consumed_at is not None


async def test_signup_rate_limits_and_captcha_gate(
    db_session, redis, hasher, monkeypatch
) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        otp_phone_hourly_limit=1,
        otp_ip_hourly_limit=10,
        otp_global_daily_limit=10,
    )
    sms = RecordingSmsProvider()
    service = SignupService(
        session=db_session,
        redis=redis,
        settings=settings,
        jwt_service=jwt_service_from_settings(settings),
        hasher=hasher,
        sms_provider=sms,
    )
    with pytest.raises(AuthError) as invalid_phone:
        await service.start(
            SignupStartRequest(phone="+14155550123"),
            ip="127.0.0.1",
            user_agent=None,
            accept_language=None,
        )
    assert invalid_phone.value.code == "VALIDATION_ERROR"

    await service.start(
        SignupStartRequest(phone="0712345678"),
        ip="127.0.0.1",
        user_agent=None,
        accept_language=None,
    )
    with pytest.raises(AuthError) as limited:
        await service.start(
            SignupStartRequest(phone="0712345678"),
            ip="127.0.0.1",
            user_agent=None,
            accept_language=None,
        )
    assert limited.value.code == "RATE_LIMITED"
    assert limited.value.details["retry_after_seconds"] == 3600

    captcha_settings = settings.model_copy(
        update={
            "otp_phone_hourly_limit": 10,
            "turnstile_secret": "test-secret",
            "signup_captcha_threshold": 0,
        }
    )
    captcha_service = SignupService(
        session=db_session,
        redis=redis,
        settings=captcha_settings,
        jwt_service=jwt_service_from_settings(captcha_settings),
        hasher=hasher,
        sms_provider=sms,
    )
    with pytest.raises(AuthError) as required:
        await captcha_service.start(
            SignupStartRequest(phone="0711111111"),
            ip="127.0.0.2",
            user_agent=None,
            accept_language=None,
        )
    assert required.value.message == "CAPTCHA is required to continue."

    verify_captcha = AsyncMock()
    monkeypatch.setattr(captcha_service, "_verify_captcha", verify_captcha)
    await captcha_service.start(
        SignupStartRequest(phone="0711111111", captcha_token="valid-test-token"),
        ip="127.0.0.2",
        user_agent=None,
        accept_language=None,
    )
    verify_captcha.assert_awaited_once_with("valid-test-token", "127.0.0.2")


async def test_resend_sms_failure_preserves_previous_challenge(
    db_session, redis, hasher
) -> None:
    clock = FakeClock(datetime.now(UTC))
    settings = Settings(
        _env_file=None,
        environment="test",
        otp_resend_cooldown_seconds=60,
        otp_phone_hourly_limit=10,
        otp_ip_hourly_limit=20,
        otp_global_daily_limit=100,
    )
    sms = RecordingSmsProvider()
    service = SignupService(
        session=db_session,
        redis=redis,
        settings=settings,
        jwt_service=jwt_service_from_settings(settings, clock),
        hasher=hasher,
        sms_provider=sms,
        clock=clock,
    )
    started = await service.start(
        SignupStartRequest(phone="0712345678"),
        ip="127.0.0.1",
        user_agent=None,
        accept_language=None,
    )
    challenge_id = UUID(started["challenge_id"])
    challenge = await db_session.get(OtpChallenge, challenge_id)
    old_hash = challenge.code_hash
    await db_session.rollback()

    class FailedSms:
        async def send(self, phone: str, message: str) -> None:
            from app.integrations.sms import SmsDeliveryError

            raise SmsDeliveryError("provider unavailable")

    service.sms_provider = FailedSms()
    clock.advance(seconds=61)
    with pytest.raises(AuthError) as failure:
        await service.resend(
            challenge_id, ip="127.0.0.1", user_agent=None, accept_language=None
        )

    assert failure.value.code == "SERVICE_UNAVAILABLE"
    await db_session.refresh(challenge)
    assert challenge.code_hash == old_hash
    assert challenge.resend_count == 0


async def test_start_sms_failure_removes_unusable_challenge(
    db_session, redis, hasher
) -> None:
    settings = Settings(_env_file=None, environment="test")

    class FailedSms:
        async def send(self, phone: str, message: str) -> None:
            from app.integrations.sms import SmsDeliveryError

            raise SmsDeliveryError("provider unavailable")

    service = SignupService(
        session=db_session,
        redis=redis,
        settings=settings,
        jwt_service=jwt_service_from_settings(settings),
        hasher=hasher,
        sms_provider=FailedSms(),
    )
    with pytest.raises(AuthError) as failure:
        await service.start(
            SignupStartRequest(phone="0712345678"),
            ip="127.0.0.1",
            user_agent=None,
            accept_language=None,
        )
    assert failure.value.code == "SERVICE_UNAVAILABLE"
    assert await db_session.scalar(select(func.count()).select_from(OtpChallenge)) == 0


async def test_resend_rejects_unknown_consumed_and_expired_challenges(
    db_session, redis, hasher
) -> None:
    clock = FakeClock(datetime.now(UTC))
    settings = Settings(_env_file=None, environment="test")
    service = SignupService(
        session=db_session,
        redis=redis,
        settings=settings,
        jwt_service=jwt_service_from_settings(settings, clock),
        hasher=hasher,
        sms_provider=RecordingSmsProvider(),
        clock=clock,
    )
    with pytest.raises(AuthError) as unknown:
        await service.resend(
            UUID(int=1), ip="127.0.0.1", user_agent=None, accept_language=None
        )
    assert unknown.value.code == "OTP_INVALID"

    started = await service.start(
        SignupStartRequest(phone="0712345678"),
        ip="127.0.0.1",
        user_agent=None,
        accept_language=None,
    )
    challenge = await db_session.get(OtpChallenge, UUID(started["challenge_id"]))
    challenge.consumed_at = clock.now()
    await db_session.commit()
    with pytest.raises(AuthError) as consumed:
        await service.resend(
            challenge.id, ip="127.0.0.1", user_agent=None, accept_language=None
        )
    assert consumed.value.code == "OTP_INVALID"

    started = await service.start(
        SignupStartRequest(phone="0711111111"),
        ip="127.0.0.2",
        user_agent=None,
        accept_language=None,
    )
    expired = await db_session.get(OtpChallenge, UUID(started["challenge_id"]))
    expired.expires_at = clock.now()
    await db_session.commit()
    with pytest.raises(AuthError) as expiry:
        await service.resend(
            expired.id, ip="127.0.0.2", user_agent=None, accept_language=None
        )
    assert expiry.value.code == "OTP_EXPIRED"


async def test_verify_rejects_unknown_expired_and_reused_challenges(
    db_session, redis, hasher
) -> None:
    clock = FakeClock(datetime.now(UTC))
    settings = Settings(_env_file=None, environment="test")
    service = SignupService(
        session=db_session,
        redis=redis,
        settings=settings,
        jwt_service=jwt_service_from_settings(settings, clock),
        hasher=hasher,
        sms_provider=RecordingSmsProvider(),
        clock=clock,
    )
    with pytest.raises(AuthError) as unknown:
        await service.verify_otp(UUID(int=2), "000000", ip="127.0.0.1")
    assert unknown.value.code == "OTP_INVALID"

    started = await service.start(
        SignupStartRequest(phone="0712345678"),
        ip="127.0.0.1",
        user_agent=None,
        accept_language=None,
    )
    challenge_id = UUID(started["challenge_id"])
    with pytest.raises(AuthError) as wrong:
        await service.verify_otp(challenge_id, "123456", ip="127.0.0.1")
    assert wrong.value.code == "OTP_INVALID"
    verified = await service.verify_otp(challenge_id, "000000", ip="127.0.0.1")
    assert verified["signup_token"]
    with pytest.raises(AuthError) as reused:
        await service.verify_otp(challenge_id, "000000", ip="127.0.0.1")
    assert reused.value.code == "OTP_INVALID"

    started = await service.start(
        SignupStartRequest(phone="0711122233"),
        ip="127.0.0.3",
        user_agent=None,
        accept_language=None,
    )
    max_attempts_id = UUID(started["challenge_id"])
    for attempt in range(settings.otp_max_attempts):
        with pytest.raises(AuthError) as wrong:
            await service.verify_otp(max_attempts_id, "123456", ip="127.0.0.3")
        expected = (
            "OTP_TOO_MANY_ATTEMPTS"
            if attempt == settings.otp_max_attempts - 1
            else "OTP_INVALID"
        )
        assert wrong.value.code == expected

    started = await service.start(
        SignupStartRequest(phone="0711111111"),
        ip="127.0.0.2",
        user_agent=None,
        accept_language=None,
    )
    expired_id = UUID(started["challenge_id"])
    clock.advance(seconds=settings.otp_ttl_seconds + 1)
    with pytest.raises(AuthError) as expired:
        await service.verify_otp(expired_id, "000000", ip="127.0.0.2")
    assert expired.value.code == "OTP_EXPIRED"


async def test_signup_rate_limiter_reports_redis_unavailability(
    db_session, redis, hasher, monkeypatch
) -> None:
    settings = Settings(_env_file=None, environment="test")
    service = SignupService(
        session=db_session,
        redis=redis,
        settings=settings,
        jwt_service=jwt_service_from_settings(settings),
        hasher=hasher,
        sms_provider=RecordingSmsProvider(),
    )
    monkeypatch.setattr(
        service.limiter,
        "hit",
        AsyncMock(side_effect=RedisConnectionError("redis offline")),
    )
    with pytest.raises(AuthError) as unavailable:
        await service._check_rate_limits("254712345678", "127.0.0.1")
    assert unavailable.value.code == "SERVICE_UNAVAILABLE"


async def test_turnstile_requires_configured_secret(db_session, redis, hasher) -> None:
    settings = Settings(_env_file=None, environment="test", turnstile_secret=None)
    service = SignupService(
        session=db_session,
        redis=redis,
        settings=settings,
        jwt_service=jwt_service_from_settings(settings),
        hasher=hasher,
        sms_provider=RecordingSmsProvider(),
    )
    with pytest.raises(AuthError) as missing:
        await service._verify_captcha("token", "127.0.0.1")
    assert missing.value.code == "VALIDATION_ERROR"
    assert missing.value.status_code == 503


async def test_turnstile_verification_handles_success_rejection_and_provider_error(
    db_session, redis, hasher, monkeypatch
) -> None:
    settings = Settings(
        _env_file=None, environment="test", turnstile_secret="turnstile-secret"
    )
    service = SignupService(
        session=db_session,
        redis=redis,
        settings=settings,
        jwt_service=jwt_service_from_settings(settings),
        hasher=hasher,
        sms_provider=RecordingSmsProvider(),
    )

    class MockResponse:
        def __init__(self, success: object) -> None:
            self.success = success

        def raise_for_status(self) -> None:
            return None

        def json(self) -> object:
            return self.success

    class MockClient:
        def __init__(
            self, response: MockResponse | None = None, error: Exception | None = None
        ) -> None:
            self.response = response
            self.error = error

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, *_args, **_kwargs) -> MockResponse:
            if self.error:
                raise self.error
            return self.response

    monkeypatch.setattr(
        "app.services.signup.httpx.AsyncClient",
        lambda **_: MockClient(MockResponse({"success": True})),
    )
    await service._verify_captcha("valid-token", "127.0.0.1")

    monkeypatch.setattr(
        "app.services.signup.httpx.AsyncClient",
        lambda **_: MockClient(MockResponse({"success": False})),
    )
    with pytest.raises(AuthError) as rejected:
        await service._verify_captcha("bad-token", "127.0.0.1")
    assert rejected.value.code == "VALIDATION_ERROR"

    monkeypatch.setattr(
        "app.services.signup.httpx.AsyncClient",
        lambda **_: MockClient(MockResponse([])),
    )
    with pytest.raises(AuthError) as invalid_response:
        await service._verify_captcha("bad-response", "127.0.0.1")
    assert invalid_response.value.code == "SERVICE_UNAVAILABLE"

    request = httpx.Request("POST", "https://challenges.cloudflare.com")
    monkeypatch.setattr(
        "app.services.signup.httpx.AsyncClient",
        lambda **_: MockClient(
            error=httpx.ConnectError("provider offline", request=request)
        ),
    )
    with pytest.raises(AuthError) as unavailable:
        await service._verify_captcha("valid-token", "127.0.0.1")
    assert unavailable.value.code == "SERVICE_UNAVAILABLE"


def test_signup_language_and_idempotency_cache_validation() -> None:
    from app.api.schemas.signup import Language

    assert _preferred_language(None, Language.SW) is Language.SW
    assert _preferred_language("fr-CA, sw-KE;q=0.9, en;q=0.8", None) is Language.SW
    assert _preferred_language("fr-CA", None) is Language.EN
    assert _preferred_language("sw;q=0, en;q=0.8", None) is Language.EN

    with pytest.raises(AuthError) as corrupt:
        _decrypt_response({"unexpected": "value"}, "test-signup-secret")
    assert corrupt.value.status_code == 503

    invalid_payload = (
        _idempotency_box("test-signup-secret").encrypt(b"[]").decode("ascii")
    )
    with pytest.raises(AuthError) as invalid_shape:
        _decrypt_response({"encrypted": invalid_payload}, "test-signup-secret")
    assert invalid_shape.value.status_code == 503
