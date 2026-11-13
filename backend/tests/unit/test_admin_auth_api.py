from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import UUID

import pyotp
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_redis, get_secret_hasher, get_sms_provider
from app.core.clock import FakeClock
from app.core.config import Settings, get_settings
from app.core.crypto import SecretBox, generate_fernet_key
from app.core.errors import AuthError
from app.core.hashing import generate_urlsafe_token, hash_token
from app.core.jwt import jwt_service_from_settings
from app.core.otp import hash_otp
from app.db.session import get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.business import Business
from app.models.device import Device
from app.models.enums import (
    BusinessStatus,
    DevicePlatform,
    DeviceStatus,
    OtpPurpose,
    StaffRole,
    SubjectType,
)
from app.models.offline_unlock import OfflineUnlock
from app.models.otp_challenge import OtpChallenge
from app.models.outlet import Outlet
from app.models.refresh_token import RefreshToken
from app.models.staff import Staff
from app.services.admin_auth import AdminAuthService


class RecordingSmsProvider:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def send(self, phone: str, message: str) -> None:
        self.messages.append((phone, message))


def _service(
    values, *, secret_box: SecretBox | None = None, clock: FakeClock | None = None
) -> AdminAuthService:
    return AdminAuthService(
        session=values["db"],
        redis=values["redis"],
        settings=values["settings"],
        jwt_service=jwt_service_from_settings(values["settings"], clock=clock),
        hasher=values["hasher"],
        sms_provider=values["sms"],
        secret_box=secret_box or SecretBox(values["settings"].mfa_encryption_key),
        clock=clock,
    )


@pytest.fixture
async def admin_auth_api(db_session: AsyncSession, redis, hasher):
    settings = Settings(
        _env_file=None,
        environment="test",
        mfa_encryption_key=generate_fernet_key(),
        admin_login_ip_limit=100,
        password_reset_phone_hourly_limit=10,
        password_reset_ip_hourly_limit=100,
        password_reset_global_daily_limit=100,
    )
    business = Business(name="Admin test shop", status=BusinessStatus.TRIAL)
    db_session.add(business)
    await db_session.flush()
    outlet = Outlet(business_id=business.id, name="Main", is_default=True)
    db_session.add(outlet)
    await db_session.flush()
    owner = Staff(
        business_id=business.id,
        outlet_id=outlet.id,
        name="Amina Owner",
        role=StaffRole.OWNER,
        phone="254712345678",
        email="amina@example.com",
        password_hash=hasher.hash_password("correct-horse-market-42"),
        pin_hash=hasher.hash_pin("2580"),
    )
    device = Device(
        business_id=business.id,
        outlet_id=outlet.id,
        name="Admin test device",
        platform=DevicePlatform.ANDROID,
        device_token_hash=hash_token("admin-test-device-token"),
        status=DeviceStatus.ACTIVE,
    )
    platform_admin = Staff(
        business_id=None,
        name="Platform Admin",
        role=StaffRole.PLATFORM_ADMIN,
        phone="254701234567",
        email="admin@example.com",
        password_hash=hasher.hash_password("platform-password-42"),
    )
    db_session.add_all([owner, platform_admin, device])
    await db_session.commit()
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
            yield (
                client,
                {
                    "owner": owner,
                    "platform_admin": platform_admin,
                    "business": business,
                    "outlet": outlet,
                    "device": device,
                    "settings": settings,
                    "sms": sms,
                    "redis": redis,
                    "hasher": hasher,
                    "db": db_session,
                },
            )
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)


async def _login(
    client: AsyncClient,
    identifier: str = "amina@example.com",
    password: str = "correct-horse-market-42",
    totp_code: str | None = None,
):
    return await client.post(
        "/api/v1/admin/auth/login",
        json={"identifier": identifier, "password": password, "totp_code": totp_code},
    )


async def test_admin_login_by_email_or_phone_and_generic_invalid_credentials(
    admin_auth_api,
) -> None:
    client, _ = admin_auth_api
    email_login = await _login(client)
    assert email_login.status_code == 200
    assert email_login.json()["access_token"]
    assert email_login.json()["refresh_token"]
    assert email_login.json()["expires_in"] == 600
    assert email_login.json()["refresh_expires_in"] == 7 * 86400

    phone_login = await _login(client, identifier="0712345678")
    assert phone_login.status_code == 200
    assert phone_login.json()["access_token"]

    bad_password = await _login(client, password="wrong-password")
    unknown = await _login(client, identifier="nobody@example.com")
    assert bad_password.status_code == unknown.status_code == 401
    assert (
        bad_password.json()["error"]["code"]
        == unknown.json()["error"]["code"]
        == "INVALID_CREDENTIALS"
    )
    assert bad_password.json()["error"]["message"] == unknown.json()["error"]["message"]


async def test_admin_login_lockout_and_rate_limit(admin_auth_api, db_session) -> None:
    client, values = admin_auth_api
    for _ in range(4):
        response = await _login(client, password="wrong-password")
        assert response.status_code == 401
    locked = await _login(client, password="wrong-password")
    assert locked.status_code == 423
    assert locked.json()["error"]["code"] == "ACCOUNT_LOCKED"
    audit_types = list(await db_session.scalars(select(AuditLog.event_type)))
    assert "lockout" in audit_types

    values["settings"].admin_login_ip_limit = 1
    limited_client, limited_values = admin_auth_api
    limited_values["settings"].admin_login_ip_limit = 1
    await values["redis"].flushall()
    first = await _login(limited_client, password="wrong-password")
    second = await _login(limited_client, password="wrong-password")
    assert first.status_code == 401
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "RATE_LIMITED"


async def test_admin_auth_service_login_and_refresh_core_paths(admin_auth_api) -> None:
    _, values = admin_auth_api
    service = _service(values)
    owner = values["owner"]
    login_args = {
        "identifier": owner.email,
        "ip": "192.0.2.21",
        "user_agent": "unit-test",
    }

    with pytest.raises(AuthError) as invalid:
        await service.login(password="incorrect-password", totp_code=None, **login_args)
    assert invalid.value.code == "INVALID_CREDENTIALS"

    owner.is_active = False
    await values["db"].commit()
    with pytest.raises(AuthError) as inactive:
        await service.login(
            password="correct-horse-market-42", totp_code=None, **login_args
        )
    assert inactive.value.code == "INVALID_CREDENTIALS"
    owner.is_active = True
    await values["db"].commit()

    values["business"].status = BusinessStatus.SUSPENDED
    await values["db"].commit()
    with pytest.raises(AuthError) as suspended:
        await service.login(
            password="correct-horse-market-42", totp_code=None, **login_args
        )
    assert suspended.value.code == "BUSINESS_SUSPENDED"
    values["business"].status = BusinessStatus.TRIAL
    await values["db"].commit()

    mfa = await service.setup_totp(staff=owner)
    owner.mfa_enabled = True
    await values["db"].commit()
    required = await service.login(
        password="correct-horse-market-42", totp_code=None, **login_args
    )
    assert required["mfa_required"] is True
    with pytest.raises(AuthError) as bad_code:
        await service.login(
            password="correct-horse-market-42", totp_code="000000", **login_args
        )
    assert bad_code.value.code == "INVALID_CREDENTIALS"
    logged_in = await service.login(
        password="correct-horse-market-42",
        totp_code=pyotp.TOTP(mfa["secret"]).now(),
        **login_args,
    )
    assert logged_in["access_token"]

    rotated = await service.refresh(
        raw_refresh_token=logged_in["refresh_token"],
        ip=login_args["ip"],
        user_agent=login_args["user_agent"],
    )
    assert rotated["access_token"]
    with pytest.raises(AuthError) as reused:
        await service.refresh(
            raw_refresh_token=logged_in["refresh_token"],
            ip=login_args["ip"],
            user_agent=login_args["user_agent"],
        )
    assert reused.value.code == "TOKEN_REUSED"


async def test_admin_auth_service_platform_owner_suspension_and_logout_paths(
    admin_auth_api,
) -> None:
    _, values = admin_auth_api
    service = _service(values)
    owner = values["owner"]
    admin = values["platform_admin"]

    with pytest.raises(AuthError) as mfa_required:
        await service.login(
            identifier=admin.email,
            password="platform-password-42",
            totp_code=None,
            ip="192.0.2.41",
            user_agent=None,
        )
    assert mfa_required.value.code == "MFA_REQUIRED"

    owner.business_id = None
    with pytest.raises(AuthError) as orphan:
        await service.login(
            identifier=owner.email,
            password="correct-horse-market-42",
            totp_code=None,
            ip="192.0.2.42",
            user_agent=None,
        )
    assert orphan.value.code == "INVALID_CREDENTIALS"
    owner.business_id = values["business"].id
    await values["db"].commit()

    _, refresh_token_id = await service._issue_session(
        staff=owner,
        ip="192.0.2.43",
        user_agent=None,
        now=service._now(),
        mfa=False,
    )
    await values["db"].commit()
    token = await values["db"].get(RefreshToken, refresh_token_id)
    assert token is not None
    raw_refresh = generate_urlsafe_token()
    token.token_hash = hash_token(raw_refresh)
    values["business"].status = BusinessStatus.SUSPENDED
    await values["db"].commit()
    with pytest.raises(AuthError) as suspended:
        await service.refresh(
            raw_refresh_token=raw_refresh, ip="192.0.2.43", user_agent=None
        )
    assert suspended.value.code == "BUSINESS_SUSPENDED"
    values["business"].status = BusinessStatus.TRIAL
    await values["db"].commit()

    await service.logout(raw_refresh_token=raw_refresh, staff_id=owner.id)
    assert token.revoked_at is not None
    assert (
        await service.logout_all(staff_id=owner.id, ip="192.0.2.44", user_agent=None)
        == 0
    )
    assert service._normalize_identifier("invalid phone") == "invalid phone"


async def test_admin_auth_service_rejects_malformed_tokens_and_unreadable_mfa_secrets(
    admin_auth_api,
) -> None:
    _, values = admin_auth_api
    service = _service(values)
    owner = values["owner"]
    malformed = service.jwt_service.encode(
        subject=str(owner.id),
        audience="admin",
        ttl=timedelta(minutes=5),
        extra={"role": StaffRole.OWNER.value, "mfa": "false"},
    )
    with pytest.raises(AuthError) as invalid_access:
        await service.authenticate_access_token(malformed)
    assert invalid_access.value.code == "INVALID_CREDENTIALS"

    with pytest.raises(AuthError) as missing_refresh:
        await service.refresh(
            raw_refresh_token=generate_urlsafe_token(),
            ip="192.0.2.51",
            user_agent=None,
        )
    assert missing_refresh.value.code == "INVALID_CREDENTIALS"

    expired_raw = generate_urlsafe_token()
    values["db"].add(
        RefreshToken(
            family_id=UUID("d1f6c47b-f3e7-432e-8ec6-faa88b28f850"),
            subject_type=SubjectType.ADMIN,
            subject_id=owner.id,
            token_hash=hash_token(expired_raw),
            expires_at=service._now() - timedelta(seconds=1),
        )
    )
    await values["db"].commit()
    with pytest.raises(AuthError) as expired_refresh:
        await service.refresh(
            raw_refresh_token=expired_raw,
            ip="192.0.2.52",
            user_agent=None,
        )
    assert expired_refresh.value.code == "INVALID_CREDENTIALS"

    owner.mfa_secret = "not-an-encrypted-secret"
    with pytest.raises(AuthError) as unreadable_setup_secret:
        service._decrypt_totp_secret(owner)
    assert unreadable_setup_secret.value.code == "SERVICE_UNAVAILABLE"
    with pytest.raises(AuthError) as unreadable_login_secret:
        service._verify_totp(owner.mfa_secret, "123456")
    assert unreadable_login_secret.value.code == "SERVICE_UNAVAILABLE"

    owner.mfa_secret = SecretBox(values["settings"].mfa_encryption_key).encrypt(
        "JBSWY3DPEHPK3PXP"
    )
    owner.mfa_enabled = True
    await service.disable_totp(
        staff=owner,
        password="correct-horse-market-42",
        totp_code=pyotp.TOTP("JBSWY3DPEHPK3PXP").now(),
    )
    assert owner.mfa_enabled is False


async def test_mfa_setup_enables_totp_and_requires_code_at_login(
    admin_auth_api, db_session
) -> None:
    client, values = admin_auth_api
    initial = await _login(client)
    auth_headers = {"Authorization": f"Bearer {initial.json()['access_token']}"}

    setup = await client.post("/api/v1/admin/auth/2fa/setup", headers=auth_headers)
    assert setup.status_code == 200, setup.text
    setup_data = setup.json()
    assert setup_data["secret"]
    assert setup_data["otpauth_uri"].startswith("otpauth://totp/")
    assert base64.b64decode(setup_data["qr_png_base64"]).startswith(b"\x89PNG")
    assert values["owner"].mfa_secret != setup_data["secret"]

    invalid = await client.post(
        "/api/v1/admin/auth/2fa/enable",
        headers=auth_headers,
        json={"totp_code": "000000"},
    )
    assert invalid.status_code == 401

    code = pyotp.TOTP(setup_data["secret"]).now()
    enabled = await client.post(
        "/api/v1/admin/auth/2fa/enable",
        headers=auth_headers,
        json={"totp_code": code},
    )
    assert enabled.status_code == 204
    assert values["owner"].mfa_enabled is True
    assert next(
        await db_session.scalars(
            select(RefreshToken).where(RefreshToken.subject_id == values["owner"].id)
        )
    ).revoked_at

    required = await _login(client)
    assert required.status_code == 200
    assert required.json()["mfa_required"] is True
    assert required.json()["access_token"] is None

    wrong_code = await _login(client, totp_code="000000")
    assert wrong_code.status_code == 401
    valid_code = await _login(client, totp_code=pyotp.TOTP(setup_data["secret"]).now())
    assert valid_code.status_code == 200
    claims = AdminAuthService(
        session=db_session,
        redis=values["redis"],
        settings=values["settings"],
        jwt_service=jwt_service_from_settings(values["settings"]),
        hasher=values["hasher"],
        sms_provider=values["sms"],
        secret_box=SecretBox(values["settings"].mfa_encryption_key),
    )
    staff = await claims.authenticate_access_token(valid_code.json()["access_token"])
    assert staff.id == values["owner"].id


async def test_mfa_disable_requires_password_and_totp_and_is_forbidden_for_platform_admin(
    admin_auth_api,
) -> None:
    client, values = admin_auth_api
    login = await _login(client)
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    setup = (await client.post("/api/v1/admin/auth/2fa/setup", headers=headers)).json()
    code = pyotp.TOTP(setup["secret"]).now()
    enabled = await client.post(
        "/api/v1/admin/auth/2fa/enable", headers=headers, json={"totp_code": code}
    )
    assert enabled.status_code == 204

    mfa_login = await _login(client, totp_code=pyotp.TOTP(setup["secret"]).now())
    mfa_headers = {"Authorization": f"Bearer {mfa_login.json()['access_token']}"}
    wrong = await client.post(
        "/api/v1/admin/auth/2fa/disable",
        headers=mfa_headers,
        json={
            "password": "wrong-password",
            "totp_code": pyotp.TOTP(setup["secret"]).now(),
        },
    )
    assert wrong.status_code == 401
    disabled = await client.post(
        "/api/v1/admin/auth/2fa/disable",
        headers=mfa_headers,
        json={
            "password": "correct-horse-market-42",
            "totp_code": pyotp.TOTP(setup["secret"]).now(),
        },
    )
    assert disabled.status_code == 204
    assert values["owner"].mfa_enabled is False

    admin = values["platform_admin"]
    admin.mfa_enabled = True
    admin.mfa_secret = SecretBox(values["settings"].mfa_encryption_key).encrypt(
        "JBSWY3DPEHPK3PXP"
    )
    await values["db"].commit()
    platform_login = await _login(
        client,
        identifier="admin@example.com",
        password="platform-password-42",
        totp_code=pyotp.TOTP("JBSWY3DPEHPK3PXP").now(),
    )
    platform_headers = {
        "Authorization": f"Bearer {platform_login.json()['access_token']}"
    }
    cannot_disable = await client.post(
        "/api/v1/admin/auth/2fa/disable",
        headers=platform_headers,
        json={
            "password": "platform-password-42",
            "totp_code": pyotp.TOTP("JBSWY3DPEHPK3PXP").now(),
        },
    )
    assert cannot_disable.status_code == 403
    assert cannot_disable.json()["error"]["code"] == "MFA_REQUIRED"


async def test_admin_refresh_rotation_reuse_and_logout(
    admin_auth_api, db_session
) -> None:
    client, values = admin_auth_api
    login = await _login(client)
    first = login.json()["refresh_token"]
    rotated = await client.post(
        "/api/v1/admin/auth/refresh", json={"refresh_token": first}
    )
    assert rotated.status_code == 200, rotated.text
    second = rotated.json()["refresh_token"]
    assert second != first
    reuse = await client.post(
        "/api/v1/admin/auth/refresh", json={"refresh_token": first}
    )
    assert reuse.status_code == 401
    assert reuse.json()["error"]["code"] == "TOKEN_REUSED"
    records = list(
        await db_session.scalars(
            select(RefreshToken).where(RefreshToken.subject_id == values["owner"].id)
        )
    )
    assert len(records) == 2
    assert all(record.revoked_at is not None for record in records)

    fresh_login = await _login(client)
    token = fresh_login.json()
    headers = {"Authorization": f"Bearer {token['access_token']}"}
    logout = await client.post(
        "/api/v1/admin/auth/logout",
        headers=headers,
        json={"refresh_token": token["refresh_token"]},
    )
    assert logout.status_code == 204
    invalid_refresh = await client.post(
        "/api/v1/admin/auth/refresh", json={"refresh_token": token["refresh_token"]}
    )
    assert invalid_refresh.status_code == 401


async def test_change_password_validates_and_revokes_admin_sessions(
    admin_auth_api,
) -> None:
    client, values = admin_auth_api
    login = await _login(client)
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    wrong = await client.post(
        "/api/v1/admin/auth/change-password",
        headers=headers,
        json={
            "current_password": "wrong-password",
            "new_password": "new-strong-password-92",
        },
    )
    assert wrong.status_code == 401
    weak = await client.post(
        "/api/v1/admin/auth/change-password",
        headers=headers,
        json={
            "current_password": "correct-horse-market-42",
            "new_password": "1234567890",
        },
    )
    assert weak.status_code == 422
    assert weak.json()["error"]["code"] == "WEAK_PASSWORD"

    changed = await client.post(
        "/api/v1/admin/auth/change-password",
        headers=headers,
        json={
            "current_password": "correct-horse-market-42",
            "new_password": "new-market-password-2026",
        },
    )
    assert changed.status_code == 204
    assert values["owner"].password_changed_at is not None
    assert values["owner"].must_change_password is False
    assert all(
        token.revoked_at is not None
        for token in await values["db"].scalars(
            select(RefreshToken).where(RefreshToken.subject_id == values["owner"].id)
        )
    )
    old_password = await _login(client)
    new_password = await _login(client, password="new-market-password-2026")
    assert old_password.status_code == 401
    assert new_password.status_code == 200


async def test_password_reset_flow_antienumeration_single_use_and_session_revocation(
    admin_auth_api, db_session
) -> None:
    client, values = admin_auth_api
    existing = await client.post(
        "/api/v1/admin/auth/password-reset/start", json={"phone": "0712345678"}
    )
    nonexistent = await client.post(
        "/api/v1/admin/auth/password-reset/start", json={"phone": "0799999999"}
    )
    assert existing.status_code == nonexistent.status_code == 200
    assert existing.json().keys() == nonexistent.json().keys()
    assert existing.json()["message"] == nonexistent.json()["message"]
    assert len(values["sms"].messages) == 1

    owner_login = await _login(client)
    challenge = UUID(existing.json()["challenge_id"])
    wrong = await client.post(
        "/api/v1/admin/auth/password-reset/verify-otp",
        json={"challenge_id": str(challenge), "otp": "999999"},
    )
    assert wrong.status_code == 400
    otp = values["sms"].messages[0][1].split("code is ")[1].split(".")[0]
    verified = await client.post(
        "/api/v1/admin/auth/password-reset/verify-otp",
        json={"challenge_id": str(challenge), "otp": otp},
    )
    assert verified.status_code == 200, verified.text
    complete = await client.post(
        "/api/v1/admin/auth/password-reset/complete",
        json={
            "reset_token": verified.json()["reset_token"],
            "new_password": "reset-market-password-2026",
        },
    )
    assert complete.status_code == 204
    replay = await client.post(
        "/api/v1/admin/auth/password-reset/complete",
        json={
            "reset_token": verified.json()["reset_token"],
            "new_password": "reset-market-password-2026",
        },
    )
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert (await _login(client)).status_code == 401
    assert (
        await _login(client, password="reset-market-password-2026")
    ).status_code == 200
    refresh_after_reset = await client.post(
        "/api/v1/admin/auth/refresh",
        json={"refresh_token": owner_login.json()["refresh_token"]},
    )
    assert refresh_after_reset.status_code == 401
    challenge_row = await db_session.get(OtpChallenge, challenge)
    assert challenge_row.purpose == OtpPurpose.PASSWORD_RESET


async def test_admin_auth_service_completes_reset_and_password_pin_changes(
    admin_auth_api,
) -> None:
    _, values = admin_auth_api
    service = _service(values)
    owner = values["owner"]
    started = await service.password_reset_start(
        phone_value="0712345678",
        ip="192.0.2.31",
        user_agent="unit-test",
        accept_language="en",
    )
    otp = values["sms"].messages[-1][1].split("code is ")[1].split(".")[0]
    verified = await service.password_reset_verify(
        challenge_id=UUID(started["challenge_id"]),
        otp=otp,
        ip="192.0.2.31",
    )
    await service.password_reset_complete(
        reset_token=verified["reset_token"],
        new_password="fresh-reset-password-58",
        ip="192.0.2.31",
        user_agent="unit-test",
    )
    assert values["hasher"].verify_password(
        "fresh-reset-password-58", owner.password_hash
    )

    await service.change_password(
        staff=owner,
        current_password="fresh-reset-password-58",
        new_password="changed-password-68",
    )
    assert values["hasher"].verify_password("changed-password-68", owner.password_hash)

    await service.reset_own_pin(
        staff=owner,
        password="changed-password-68",
        new_pin="5826",
    )
    assert values["hasher"].verify_pin("5826", owner.pin_hash)


async def test_password_reset_wrong_attempt_limit_expiry_and_missing_account(
    admin_auth_api, db_session
) -> None:
    client, values = admin_auth_api
    values["settings"].otp_max_attempts = 2
    start = await client.post(
        "/api/v1/admin/auth/password-reset/start", json={"phone": "0712345678"}
    )
    challenge_id = UUID(start.json()["challenge_id"])
    for expected in ("OTP_INVALID", "OTP_TOO_MANY_ATTEMPTS"):
        result = await client.post(
            "/api/v1/admin/auth/password-reset/verify-otp",
            json={"challenge_id": str(challenge_id), "otp": "123456"},
        )
        assert result.json()["error"]["code"] == expected

    missing_start = await client.post(
        "/api/v1/admin/auth/password-reset/start", json={"phone": "0799999999"}
    )
    missing_id = UUID(missing_start.json()["challenge_id"])
    missing_challenge = await db_session.get(OtpChallenge, missing_id)
    missing_challenge.code_hash = hash_otp("000000", values["settings"].otp_pepper)
    await db_session.commit()
    no_account = await client.post(
        "/api/v1/admin/auth/password-reset/verify-otp",
        json={"challenge_id": str(missing_id), "otp": "000000"},
    )
    assert no_account.status_code == 400
    assert no_account.json()["error"]["code"] == "OTP_INVALID"

    expired_start = await client.post(
        "/api/v1/admin/auth/password-reset/start", json={"phone": "0712345678"}
    )
    expired_id = UUID(expired_start.json()["challenge_id"])
    expired_challenge = await db_session.get(OtpChallenge, expired_id)
    expired_challenge.expires_at = expired_challenge.created_at - timedelta(seconds=1)
    await db_session.commit()
    expired = await client.post(
        "/api/v1/admin/auth/password-reset/verify-otp",
        json={"challenge_id": str(expired_id), "otp": "000000"},
    )
    assert expired.status_code == 400
    assert expired.json()["error"]["code"] == "OTP_EXPIRED"


async def test_reset_own_pin_revokes_offline_unlocks_and_staff_sessions(
    admin_auth_api, db_session, hasher
) -> None:
    client, values = admin_auth_api
    login = await _login(client)
    db_session.add(
        OfflineUnlock(
            staff_id=values["owner"].id,
            device_id=values["device"].id,
            salt="only-a-salt",
            expires_at=values["owner"].created_at,
        )
    )
    await db_session.commit()
    response = await client.post(
        "/api/v1/admin/auth/reset-own-pin",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json={"password": "correct-horse-market-42", "new_pin": "8642"},
    )
    assert response.status_code == 204
    assert hasher.verify_pin("8642", values["owner"].pin_hash)
    unlock = await db_session.scalar(
        select(OfflineUnlock).where(OfflineUnlock.staff_id == values["owner"].id)
    )
    assert unlock.revoked_at is not None
    assert (
        await db_session.scalar(
            select(RefreshToken.id).where(
                RefreshToken.subject_id == values["owner"].id,
                RefreshToken.subject_type == SubjectType.ADMIN,
                RefreshToken.revoked_at.is_(None),
            )
        )
        is None
    )


async def test_platform_admin_requires_mfa_before_login(admin_auth_api) -> None:
    client, _ = admin_auth_api
    response = await _login(
        client,
        identifier="admin@example.com",
        password="platform-password-42",
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "MFA_REQUIRED"


async def test_admin_refresh_rejects_invalid_expired_and_unrotated_revoked_tokens(
    admin_auth_api, db_session
) -> None:
    client, _ = admin_auth_api
    unknown = await client.post(
        "/api/v1/admin/auth/refresh",
        json={"refresh_token": "unknown-refresh-token-that-is-long-enough"},
    )
    assert unknown.status_code == 401

    login = await _login(client)
    token = login.json()["refresh_token"]
    row = await db_session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(token))
    )
    row.revoked_at = row.created_at
    await db_session.commit()
    revoked = await client.post(
        "/api/v1/admin/auth/refresh", json={"refresh_token": token}
    )
    assert revoked.status_code == 401
    assert revoked.json()["error"]["code"] == "INVALID_CREDENTIALS"

    second_login = await _login(client)
    expired_token = second_login.json()["refresh_token"]
    row = await db_session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(expired_token))
    )
    row.expires_at = row.created_at
    await db_session.commit()
    expired = await client.post(
        "/api/v1/admin/auth/refresh", json={"refresh_token": expired_token}
    )
    assert expired.status_code == 401


async def test_admin_refresh_rejects_non_admin_token_and_deactivated_admin(
    admin_auth_api, db_session
) -> None:
    client, values = admin_auth_api
    row = RefreshToken(
        family_id=UUID("00000000-0000-0000-0000-000000000001"),
        subject_type=SubjectType.STAFF,
        subject_id=values["owner"].id,
        token_hash=hash_token("staff-refresh-token-for-admin-test"),
        device_id=values["device"].id,
        expires_at=values["owner"].created_at.replace(
            year=values["owner"].created_at.year + 1
        ),
    )
    db_session.add(row)
    await db_session.commit()
    wrong_type = await client.post(
        "/api/v1/admin/auth/refresh",
        json={"refresh_token": "staff-refresh-token-for-admin-test"},
    )
    assert wrong_type.status_code == 401

    login = await _login(client)
    refresh = login.json()["refresh_token"]
    values["owner"].is_active = False
    await db_session.commit()
    inactive = await client.post(
        "/api/v1/admin/auth/refresh", json={"refresh_token": refresh}
    )
    assert inactive.status_code == 401


async def test_admin_logout_all_revokes_sessions_and_audits(
    admin_auth_api, db_session
) -> None:
    client, values = admin_auth_api
    first = await _login(client)
    await _login(client)
    response = await client.post(
        "/api/v1/admin/auth/logout-all",
        headers={"Authorization": f"Bearer {first.json()['access_token']}"},
    )
    assert response.status_code == 200
    assert response.json()["revoked_sessions"] == 2
    active = await db_session.scalar(
        select(RefreshToken.id).where(
            RefreshToken.subject_id == values["owner"].id,
            RefreshToken.subject_type == SubjectType.ADMIN,
            RefreshToken.revoked_at.is_(None),
        )
    )
    assert active is None


async def test_admin_access_token_rejects_malformed_role_and_mfa_claims(
    admin_auth_api,
) -> None:
    _, values = admin_auth_api
    service = _service(values)
    from app.core.errors import AuthError

    for token in ("not-a-jwt",):
        with pytest.raises(AuthError):
            await service.authenticate_access_token(token)

    wrong_role = service.jwt_service.encode(
        subject=str(values["owner"].id),
        audience="staff",
        ttl=timedelta(minutes=1),
    )
    with pytest.raises(AuthError):
        await service.authenticate_access_token(wrong_role)

    missing_mfa = service.jwt_service.encode(
        subject=str(values["owner"].id),
        audience="admin",
        ttl=timedelta(minutes=1),
    )
    with pytest.raises(AuthError):
        await service.authenticate_access_token(missing_mfa)

    values["owner"].mfa_enabled = True
    await values["db"].commit()
    no_mfa_proof = service.jwt_service.encode(
        subject=str(values["owner"].id),
        audience="admin",
        ttl=timedelta(minutes=1),
        extra={"mfa": False},
    )
    with pytest.raises(AuthError):
        await service.authenticate_access_token(no_mfa_proof)


async def test_totp_setup_configuration_and_pending_state_errors(
    admin_auth_api,
) -> None:
    _, values = admin_auth_api
    service = _service(values, secret_box=None)
    service.secret_box = None
    with pytest.raises(Exception) as missing_key:
        await service.setup_totp(staff=values["owner"])
    assert "not configured" in str(missing_key.value)

    service.secret_box = SecretBox(values["settings"].mfa_encryption_key)
    with pytest.raises(Exception) as incomplete:
        await service.enable_totp(staff=values["owner"], totp_code="123456")
    assert "incomplete" in str(incomplete.value)

    values["owner"].mfa_enabled = True
    await values["db"].commit()
    with pytest.raises(Exception) as already_enabled:
        await service.setup_totp(staff=values["owner"])
    assert "already enabled" in str(already_enabled.value)


async def test_totp_disable_rejects_invalid_code(admin_auth_api) -> None:
    client, _ = admin_auth_api
    login = await _login(client)
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    setup = (await client.post("/api/v1/admin/auth/2fa/setup", headers=headers)).json()
    code = pyotp.TOTP(setup["secret"]).now()
    assert (
        await client.post(
            "/api/v1/admin/auth/2fa/enable", headers=headers, json={"totp_code": code}
        )
    ).status_code == 204
    login_mfa = await _login(client, totp_code=pyotp.TOTP(setup["secret"]).now())
    invalid = await client.post(
        "/api/v1/admin/auth/2fa/disable",
        headers={"Authorization": f"Bearer {login_mfa.json()['access_token']}"},
        json={"password": "correct-horse-market-42", "totp_code": "000000"},
    )
    assert invalid.status_code == 401


async def test_password_reset_verify_rejects_invalid_consumed_and_wrong_purpose_challenges(
    admin_auth_api, db_session
) -> None:
    client, values = admin_auth_api
    invalid = await client.post(
        "/api/v1/admin/auth/password-reset/verify-otp",
        json={"challenge_id": "00000000-0000-0000-0000-000000000001", "otp": "000000"},
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "OTP_INVALID"

    signup_challenge = OtpChallenge(
        purpose=OtpPurpose.SIGNUP,
        phone=values["owner"].phone,
        code_hash=hash_otp("123456", values["settings"].otp_pepper),
        expires_at=values["owner"].created_at.replace(
            year=values["owner"].created_at.year + 1
        ),
    )
    db_session.add(signup_challenge)
    await db_session.commit()
    wrong_purpose = await client.post(
        "/api/v1/admin/auth/password-reset/verify-otp",
        json={"challenge_id": str(signup_challenge.id), "otp": "123456"},
    )
    assert wrong_purpose.status_code == 400

    start = await client.post(
        "/api/v1/admin/auth/password-reset/start", json={"phone": "0712345678"}
    )
    challenge = await db_session.get(OtpChallenge, UUID(start.json()["challenge_id"]))
    challenge.verified_at = challenge.created_at
    challenge.consumed_at = challenge.created_at
    await db_session.commit()
    reused = await client.post(
        "/api/v1/admin/auth/password-reset/verify-otp",
        json={"challenge_id": str(challenge.id), "otp": "123456"},
    )
    assert reused.status_code == 400
    assert reused.json()["error"]["code"] == "OTP_INVALID"


async def test_password_reset_rejects_repeated_verified_challenge_and_enforces_rate_limits(
    admin_auth_api, db_session
) -> None:
    client, values = admin_auth_api
    values["settings"].password_reset_global_daily_limit = 1
    first = await client.post(
        "/api/v1/admin/auth/password-reset/start",
        headers={"Accept-Language": "sw-KE"},
        json={"phone": "0712345678"},
    )
    assert first.status_code == 200
    assert "Nambari" in values["sms"].messages[0][1]
    limited = await client.post(
        "/api/v1/admin/auth/password-reset/start",
        json={"phone": "0799999999"},
    )
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"

    otp = values["sms"].messages[0][1].split("ni ")[1].split(".")[0]
    challenge_id = first.json()["challenge_id"]
    verified = await client.post(
        "/api/v1/admin/auth/password-reset/verify-otp",
        json={"challenge_id": challenge_id, "otp": otp},
    )
    assert verified.status_code == 200
    reused = await client.post(
        "/api/v1/admin/auth/password-reset/verify-otp",
        json={"challenge_id": challenge_id, "otp": otp},
    )
    assert reused.status_code == 400
    assert reused.json()["error"]["code"] == "OTP_INVALID"


async def test_password_reset_sms_failure_cleans_up_challenge(
    admin_auth_api, db_session
) -> None:
    _, values = admin_auth_api

    class FailingSmsProvider:
        async def send(self, phone: str, message: str) -> None:
            from app.integrations.sms import SmsDeliveryError

            raise SmsDeliveryError("test delivery failure")

    service = _service(values)
    service.sms_provider = FailingSmsProvider()
    before = len(list(await db_session.scalars(select(OtpChallenge))))
    with pytest.raises(AuthError) as failed:
        await service.password_reset_start(
            phone_value="0712345678",
            ip="192.0.2.10",
            user_agent=None,
            accept_language="en",
        )
    assert failed.value.code == "SERVICE_UNAVAILABLE"
    after = len(list(await db_session.scalars(select(OtpChallenge))))
    assert after == before


async def test_password_reset_normalization_and_reset_rate_limit_scopes(
    admin_auth_api,
) -> None:
    _, values = admin_auth_api
    service = _service(values)
    with pytest.raises(AuthError) as invalid_phone:
        await service.password_reset_start(
            phone_value="not-a-phone",
            ip="192.0.2.11",
            user_agent=None,
            accept_language=None,
        )
    assert invalid_phone.value.code == "VALIDATION_ERROR"

    values["settings"].password_reset_ip_hourly_limit = 1
    await service.password_reset_start(
        phone_value="0712345678",
        ip="192.0.2.12",
        user_agent=None,
        accept_language=None,
    )
    with pytest.raises(AuthError) as limited:
        await service.password_reset_start(
            phone_value="0799999999",
            ip="192.0.2.12",
            user_agent=None,
            accept_language=None,
        )
    assert limited.value.code == "RATE_LIMITED"


async def test_password_reset_complete_rejects_wrong_purpose_weak_and_expired_tokens(
    admin_auth_api,
) -> None:
    _, values = admin_auth_api
    service = _service(values)
    phone = values["owner"].phone
    from app.core.errors import AuthError

    with pytest.raises(AuthError):
        await service.password_reset_complete(
            reset_token="invalid",
            new_password="a-strong-reset-password",
            ip="192.0.2.1",
            user_agent=None,
        )
    wrong_purpose = service.jwt_service.encode(
        subject=phone,
        audience="reset",
        ttl=timedelta(minutes=5),
        extra={"purpose": "other", "phone": phone},
    )
    with pytest.raises(AuthError):
        await service.password_reset_complete(
            reset_token=wrong_purpose,
            new_password="a-strong-reset-password",
            ip="192.0.2.1",
            user_agent=None,
        )
    weak_token = service.jwt_service.encode(
        subject=phone,
        audience="reset",
        ttl=timedelta(minutes=5),
        extra={"purpose": "password_reset", "phone": phone},
    )
    with pytest.raises(AuthError) as weak:
        await service.password_reset_complete(
            reset_token=weak_token,
            new_password="1234567890",
            ip="192.0.2.1",
            user_agent=None,
        )
    assert weak.value.code == "WEAK_PASSWORD"

    expired = service.jwt_service.encode(
        subject=phone,
        audience="reset",
        ttl=timedelta(seconds=-1),
        extra={"purpose": "password_reset", "phone": phone},
    )
    with pytest.raises(AuthError):
        await service.password_reset_complete(
            reset_token=expired,
            new_password="a-strong-reset-password",
            ip="192.0.2.1",
            user_agent=None,
        )


async def test_reset_own_pin_rejects_non_owner_wrong_password_and_weak_pin(
    admin_auth_api,
) -> None:
    client, values = admin_auth_api
    login = await _login(client)
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    not_owner_login = await _login(
        client,
        identifier="admin@example.com",
        password="platform-password-42",
    )
    values["platform_admin"].mfa_enabled = True
    values["platform_admin"].mfa_secret = SecretBox(
        values["settings"].mfa_encryption_key
    ).encrypt("JBSWY3DPEHPK3PXP")
    await values["db"].commit()
    not_owner_login = await _login(
        client,
        identifier="admin@example.com",
        password="platform-password-42",
        totp_code=pyotp.TOTP("JBSWY3DPEHPK3PXP").now(),
    )
    platform_headers = {
        "Authorization": f"Bearer {not_owner_login.json()['access_token']}"
    }
    for payload, expected in (
        ({"password": "platform-password-42", "new_pin": "8642"}, 403),
        ({"password": "incorrect-password", "new_pin": "8642"}, 401),
        ({"password": "correct-horse-market-42", "new_pin": "1234"}, 422),
    ):
        response = await client.post(
            "/api/v1/admin/auth/reset-own-pin",
            headers=platform_headers if expected == 403 else headers,
            json=payload,
        )
        assert response.status_code == expected
