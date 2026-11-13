from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_redis, get_secret_hasher
from app.api.schemas.staff_auth import OfflineSessionItem
from app.core.config import Settings, get_settings
from app.core.errors import AuthError
from app.core.hashing import hash_token
from app.core.jwt import jwt_service_from_settings
from app.db.session import get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.business import Business
from app.models.device import Device
from app.models.enums import BusinessStatus, DevicePlatform, DeviceStatus, StaffRole
from app.models.offline_unlock import OfflineUnlock
from app.models.outlet import Outlet
from app.models.refresh_token import RefreshToken
from app.models.staff import Staff
from app.services.staff_auth import StaffAuthService


@pytest.fixture
async def staff_auth_api(db_session: AsyncSession, redis, hasher):
    settings = Settings(
        _env_file=None,
        environment="test",
        lockout_failures=5,
        lockout_base_seconds=900,
        pin_login_ip_limit=100,
        pin_login_device_limit=100,
    )
    business = Business(name="Test shop", status=BusinessStatus.TRIAL)
    await db_session.flush()
    db_session.add(business)
    await db_session.flush()
    outlet = Outlet(business_id=business.id, name="Main", is_default=True)
    db_session.add(outlet)
    await db_session.flush()
    staff = Staff(
        business_id=business.id,
        outlet_id=outlet.id,
        name="Amina Owner",
        role=StaffRole.OWNER,
        pin_hash=hasher.hash_pin("2580"),
    )
    cashier = Staff(
        business_id=business.id,
        outlet_id=outlet.id,
        name="Brian Cashier",
        role=StaffRole.CASHIER,
        pin_hash=hasher.hash_pin("3690"),
    )
    raw_device_token = "registered-device-token-for-tests-123456"
    device = Device(
        business_id=business.id,
        outlet_id=outlet.id,
        name="Test Android",
        platform=DevicePlatform.ANDROID,
        device_token_hash=hash_token(raw_device_token),
        status=DeviceStatus.ACTIVE,
        fingerprint="fingerprint",
    )
    db_session.add_all([staff, cashier, device])
    await db_session.commit()
    values = {
        "business": business,
        "outlet": outlet,
        "staff": staff,
        "cashier": cashier,
        "device": device,
        "device_token": raw_device_token,
        "settings": settings,
    }

    original_overrides = app.dependency_overrides.copy()

    async def override_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_redis] = lambda: redis
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_secret_hasher] = lambda: hasher

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client, values
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)


async def _login(
    client: AsyncClient, values: dict, staff_id: UUID | None = None, pin: str = "2580"
):
    return await client.post(
        "/api/v1/auth/pin-login",
        headers={"X-Device-Token": values["device_token"]},
        json={"staff_id": str(staff_id or values["staff"].id), "pin": pin},
    )


async def test_staff_list_is_device_and_outlet_scoped(staff_auth_api) -> None:
    client, values = staff_auth_api
    response = await client.get(
        "/api/v1/auth/staff-list",
        params={"outlet_id": str(values["outlet"].id)},
        headers={"X-Device-Token": values["device_token"]},
    )
    assert response.status_code == 200
    assert {item["name"] for item in response.json()} == {
        "Amina Owner",
        "Brian Cashier",
    }

    mismatch = await client.get(
        "/api/v1/auth/staff-list",
        params={"outlet_id": "00000000-0000-0000-0000-000000000001"},
        headers={"X-Device-Token": values["device_token"]},
    )
    assert mismatch.status_code == 403

    values["cashier"].is_active = False
    filtered = await client.get(
        "/api/v1/auth/staff-list",
        params={"outlet_id": str(values["outlet"].id)},
        headers={"X-Device-Token": values["device_token"]},
    )
    assert [item["name"] for item in filtered.json()] == ["Amina Owner"]


async def test_pin_login_requires_registered_device_and_returns_bound_session(
    staff_auth_api,
) -> None:
    client, values = staff_auth_api
    missing = await client.post(
        "/api/v1/auth/pin-login",
        json={"staff_id": str(values["staff"].id), "pin": "2580"},
    )
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "DEVICE_NOT_REGISTERED"

    response = await _login(client, values)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["access_token"]
    assert result["refresh_token"]
    assert result["expires_in"] == 900
    assert result["refresh_expires_in"] == 30 * 86400
    assert result["must_change_pin"] is False
    claims = jwt_service_from_settings(values["settings"]).decode(
        result["access_token"], audience="staff"
    )
    assert claims["sub"] == str(values["staff"].id)
    assert claims["business_id"] == str(values["business"].id)
    assert claims["outlet_id"] == str(values["outlet"].id)
    assert claims["device_id"] == str(values["device"].id)


async def test_pin_login_generic_failure_then_lockout(
    staff_auth_api, db_session
) -> None:
    client, values = staff_auth_api
    for _ in range(4):
        response = await _login(client, values, pin="0000")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    locked = await _login(client, values, pin="0000")
    assert locked.status_code == 423
    assert locked.json()["error"]["code"] == "ACCOUNT_LOCKED"
    assert locked.json()["error"]["details"]["retry_after"] > 0
    events = await db_session.scalars(select(AuditLog.event_type))
    assert list(events).count("lockout") == 1


async def test_pin_login_enforces_device_rate_limit(staff_auth_api) -> None:
    client, values = staff_auth_api
    values["settings"].pin_login_device_limit = 1
    first = await _login(client, values, pin="0000")
    assert first.status_code == 401
    limited = await _login(client, values, pin="0000")
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"


async def test_pin_login_rejects_revoked_device(staff_auth_api, db_session) -> None:
    client, values = staff_auth_api
    values["device"].status = DeviceStatus.REVOKED
    await db_session.commit()
    response = await _login(client, values)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "DEVICE_REVOKED"


async def test_pin_login_blocks_suspended_business_and_mismatched_staff(
    staff_auth_api, db_session
) -> None:
    client, values = staff_auth_api
    mismatch = await _login(client, values, staff_id=values["cashier"].id, pin="2580")
    assert mismatch.status_code == 401
    assert mismatch.json()["error"]["code"] == "INVALID_CREDENTIALS"

    business = values["business"]
    business.status = BusinessStatus.SUSPENDED
    await db_session.commit()
    suspended = await _login(client, values)
    assert suspended.status_code == 403
    assert suspended.json()["error"]["code"] == "BUSINESS_SUSPENDED"


async def test_refresh_rotates_and_reuse_revokes_the_whole_family(
    staff_auth_api, db_session
) -> None:
    client, values = staff_auth_api
    login = await _login(client, values)
    initial = login.json()["refresh_token"]
    headers = {"X-Device-Token": values["device_token"]}

    rotated = await client.post(
        "/api/v1/auth/refresh", headers=headers, json={"refresh_token": initial}
    )
    assert rotated.status_code == 200, rotated.text
    new_token = rotated.json()["refresh_token"]
    assert new_token != initial

    reused = await client.post(
        "/api/v1/auth/refresh", headers=headers, json={"refresh_token": initial}
    )
    assert reused.status_code == 401
    assert reused.json()["error"]["code"] == "TOKEN_REUSED"
    records = await db_session.scalars(select(RefreshToken))
    family = list(records)
    assert len(family) == 2
    assert all(record.revoked_at is not None for record in family)


async def test_refresh_rejects_unknown_expired_and_unrotated_revoked_tokens(
    staff_auth_api, db_session
) -> None:
    client, values = staff_auth_api
    headers = {"X-Device-Token": values["device_token"]}
    unknown = await client.post(
        "/api/v1/auth/refresh",
        headers=headers,
        json={"refresh_token": "unknown-refresh-token-that-is-long-enough"},
    )
    assert unknown.status_code == 401
    assert unknown.json()["error"]["code"] == "INVALID_CREDENTIALS"

    login = await _login(client, values)
    raw_token = login.json()["refresh_token"]
    record = await db_session.scalar(select(RefreshToken))
    record.revoked_at = record.created_at
    await db_session.commit()
    revoked = await client.post(
        "/api/v1/auth/refresh", headers=headers, json={"refresh_token": raw_token}
    )
    assert revoked.status_code == 401
    assert revoked.json()["error"]["code"] == "INVALID_CREDENTIALS"

    second_login = await _login(client, values)
    second_raw = second_login.json()["refresh_token"]
    record = await db_session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(second_raw))
    )
    record.expires_at = record.created_at
    await db_session.commit()
    expired = await client.post(
        "/api/v1/auth/refresh", headers=headers, json={"refresh_token": second_raw}
    )
    assert expired.status_code == 401
    assert expired.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_refresh_is_bound_to_device_and_active_staff(
    staff_auth_api, db_session
) -> None:
    client, values = staff_auth_api
    login = await _login(client, values)
    token = login.json()["refresh_token"]
    second_raw_device = "another-registered-device-token-for-tests"
    second_device = Device(
        business_id=values["business"].id,
        outlet_id=values["outlet"].id,
        name="Second device",
        platform=DevicePlatform.WEB,
        device_token_hash=hash_token(second_raw_device),
        status=DeviceStatus.ACTIVE,
    )
    db_session.add(second_device)
    await db_session.commit()

    mismatch = await client.post(
        "/api/v1/auth/refresh",
        headers={"X-Device-Token": second_raw_device},
        json={"refresh_token": token},
    )
    assert mismatch.status_code == 401
    assert mismatch.json()["error"]["code"] == "DEVICE_REVOKED"

    values["staff"].is_active = False
    await db_session.commit()
    inactive = await client.post(
        "/api/v1/auth/refresh",
        headers={"X-Device-Token": values["device_token"]},
        json={"refresh_token": token},
    )
    assert inactive.status_code == 401
    assert inactive.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_refresh_rejects_suspended_business(staff_auth_api, db_session) -> None:
    client, values = staff_auth_api
    login = await _login(client, values)
    values["business"].status = BusinessStatus.SUSPENDED
    await db_session.commit()
    response = await client.post(
        "/api/v1/auth/refresh",
        headers={"X-Device-Token": values["device_token"]},
        json={"refresh_token": login.json()["refresh_token"]},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "BUSINESS_SUSPENDED"


async def test_authenticated_me_sessions_and_logout_all(staff_auth_api) -> None:
    client, values = staff_auth_api
    login = await _login(client, values)
    tokens = login.json()
    headers = {
        "Authorization": f"Bearer {tokens['access_token']}",
        "X-Device-Token": values["device_token"],
    }

    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["id"] == str(values["staff"].id)
    assert me.json()["business"]["name"] == "Test shop"

    sessions = await client.get("/api/v1/auth/sessions", headers=headers)
    assert sessions.status_code == 200
    assert len(sessions.json()) == 1
    session_id = sessions.json()[0]["id"]

    revoked = await client.delete(
        f"/api/v1/auth/sessions/{session_id}", headers=headers
    )
    assert revoked.status_code == 204
    assert (await client.get("/api/v1/auth/sessions", headers=headers)).json() == []


async def test_logout_and_logout_all_revoke_refresh_tokens(
    staff_auth_api, db_session
) -> None:
    client, values = staff_auth_api
    login = await _login(client, values)
    tokens = login.json()
    headers = {
        "Authorization": f"Bearer {tokens['access_token']}",
        "X-Device-Token": values["device_token"],
    }
    logged_out = await client.post(
        "/api/v1/auth/logout",
        headers=headers,
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert logged_out.status_code == 204
    logged_out_refresh = await client.post(
        "/api/v1/auth/refresh",
        headers={"X-Device-Token": values["device_token"]},
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert logged_out_refresh.status_code == 401

    second_login = await _login(client, values)
    second_tokens = second_login.json()
    second_headers = {
        "Authorization": f"Bearer {second_tokens['access_token']}",
        "X-Device-Token": values["device_token"],
    }
    logout_all = await client.post("/api/v1/auth/logout-all", headers=second_headers)
    assert logout_all.status_code == 200
    assert logout_all.json()["revoked_sessions"] >= 1
    refresh = await client.post(
        "/api/v1/auth/refresh",
        headers={"X-Device-Token": values["device_token"]},
        json={"refresh_token": second_tokens["refresh_token"]},
    )
    assert refresh.status_code == 401


async def test_access_token_requires_matching_device(staff_auth_api) -> None:
    client, values = staff_auth_api
    login = await _login(client, values)
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "DEVICE_NOT_REGISTERED"


async def test_access_token_rejects_other_valid_device_and_invalid_tokens(
    staff_auth_api, db_session
) -> None:
    client, values = staff_auth_api
    login = await _login(client, values)
    access_token = login.json()["access_token"]
    second_raw_device = "another-active-device-token-for-me-tests"
    db_session.add(
        Device(
            business_id=values["business"].id,
            outlet_id=values["outlet"].id,
            name="Second device",
            platform=DevicePlatform.WEB,
            device_token_hash=hash_token(second_raw_device),
            status=DeviceStatus.ACTIVE,
        )
    )
    await db_session.commit()
    mismatch = await client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-Device-Token": second_raw_device,
        },
    )
    assert mismatch.status_code == 401
    assert mismatch.json()["error"]["code"] == "INVALID_CREDENTIALS"

    invalid = await client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": "Bearer not-a-jwt",
            "X-Device-Token": values["device_token"],
        },
    )
    assert invalid.status_code == 401
    assert invalid.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_session_revoke_is_user_scoped_and_logout_ignores_other_refresh_tokens(
    staff_auth_api,
) -> None:
    client, values = staff_auth_api
    login = await _login(client, values)
    tokens = login.json()
    headers = {
        "Authorization": f"Bearer {tokens['access_token']}",
        "X-Device-Token": values["device_token"],
    }

    other_staff_login = await _login(
        client, values, staff_id=values["cashier"].id, pin="3690"
    )
    other_refresh = other_staff_login.json()["refresh_token"]
    logout = await client.post(
        "/api/v1/auth/logout",
        headers=headers,
        json={"refresh_token": other_refresh},
    )
    assert logout.status_code == 204
    not_found = await client.delete(
        "/api/v1/auth/sessions/00000000-0000-0000-0000-000000000001",
        headers=headers,
    )
    assert not_found.status_code == 204


async def test_staff_auth_service_edge_cases(
    staff_auth_api, db_session, redis, hasher
) -> None:
    _, values = staff_auth_api
    service = StaffAuthService(
        session=db_session,
        redis=redis,
        settings=values["settings"],
        jwt_service=jwt_service_from_settings(values["settings"]),
        hasher=hasher,
    )

    with pytest.raises(AuthError, match="not registered"):
        await service.require_device("unknown-device-token")
    with pytest.raises(AuthError) as wrong_outlet:
        await service.staff_list(
            outlet_id=UUID("00000000-0000-0000-0000-000000000001"),
            device_token=values["device_token"],
        )
    assert wrong_outlet.value.code == "DEVICE_NOT_REGISTERED"
    staff_list = await service.staff_list(
        outlet_id=values["outlet"].id,
        device_token=values["device_token"],
    )
    assert len(staff_list) == 2

    with pytest.raises(AuthError) as unknown_staff:
        await service.pin_login(
            staff_id=UUID("00000000-0000-0000-0000-000000000001"),
            pin="2580",
            device_token=values["device_token"],
            ip="192.0.2.1",
            user_agent=None,
        )
    assert unknown_staff.value.code == "INVALID_CREDENTIALS"

    for _ in range(values["settings"].lockout_failures):
        with pytest.raises(AuthError):
            await service.pin_login(
                staff_id=values["staff"].id,
                pin="0000",
                device_token=values["device_token"],
                ip="192.0.2.2",
                user_agent=None,
            )
    with pytest.raises(AuthError) as already_locked:
        await service.pin_login(
            staff_id=values["staff"].id,
            pin="2580",
            device_token=values["device_token"],
            ip="192.0.2.2",
            user_agent=None,
        )
    assert already_locked.value.code == "ACCOUNT_LOCKED"

    login = await service.pin_login(
        staff_id=values["cashier"].id,
        pin="3690",
        device_token=values["device_token"],
        ip="192.0.2.3",
        user_agent="unit-test",
    )
    assert login["refresh_token"]
    rotated = await service.refresh(
        raw_refresh_token=login["refresh_token"],
        device_token=values["device_token"],
        ip="192.0.2.3",
        user_agent="unit-test",
    )
    assert rotated["refresh_token"] != login["refresh_token"]
    with pytest.raises(AuthError) as reused:
        await service.refresh(
            raw_refresh_token=login["refresh_token"],
            device_token=values["device_token"],
            ip="192.0.2.3",
            user_agent="unit-test",
        )
    assert reused.value.code == "TOKEN_REUSED"

    second_device_token = "third-device-token-for-refresh-tests-123456"
    second_device = Device(
        business_id=values["business"].id,
        outlet_id=values["outlet"].id,
        name="Refresh test device",
        platform=DevicePlatform.WEB,
        device_token_hash=hash_token(second_device_token),
        status=DeviceStatus.ACTIVE,
    )
    db_session.add(second_device)
    await db_session.commit()
    bound_login = await service.pin_login(
        staff_id=values["cashier"].id,
        pin="3690",
        device_token=values["device_token"],
        ip="192.0.2.4",
        user_agent=None,
    )
    with pytest.raises(AuthError) as wrong_device:
        await service.refresh(
            raw_refresh_token=bound_login["refresh_token"],
            device_token=second_device_token,
            ip="192.0.2.4",
            user_agent=None,
        )
    assert wrong_device.value.code == "DEVICE_REVOKED"

    bound_record = await db_session.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_token(bound_login["refresh_token"])
        )
    )
    values["cashier"].outlet_id = None
    await db_session.commit()
    with pytest.raises(AuthError) as inactive_staff:
        await service.refresh(
            raw_refresh_token=bound_login["refresh_token"],
            device_token=values["device_token"],
            ip="192.0.2.4",
            user_agent=None,
        )
    assert inactive_staff.value.code == "INVALID_CREDENTIALS"
    values["cashier"].outlet_id = values["outlet"].id
    bound_record.expires_at = bound_record.created_at
    await db_session.commit()
    with pytest.raises(AuthError) as expired:
        await service.refresh(
            raw_refresh_token=bound_login["refresh_token"],
            device_token=values["device_token"],
            ip="192.0.2.4",
            user_agent=None,
        )
    assert expired.value.code == "INVALID_CREDENTIALS"

    logout_login = await service.pin_login(
        staff_id=values["cashier"].id,
        pin="3690",
        device_token=values["device_token"],
        ip="192.0.2.5",
        user_agent=None,
    )
    await service.logout(
        raw_refresh_token=logout_login["refresh_token"], staff_id=values["cashier"].id
    )
    with pytest.raises(AuthError) as revoked_token:
        await service.refresh(
            raw_refresh_token=logout_login["refresh_token"],
            device_token=values["device_token"],
            ip="192.0.2.5",
            user_agent=None,
        )
    assert revoked_token.value.code == "INVALID_CREDENTIALS"

    session_login = await service.pin_login(
        staff_id=values["cashier"].id,
        pin="3690",
        device_token=values["device_token"],
        ip="192.0.2.6",
        user_agent=None,
    )
    assert session_login["refresh_token"]
    active_sessions = await service.sessions(staff_id=values["cashier"].id)
    assert active_sessions
    await service.revoke_session(
        staff_id=values["cashier"].id,
        session_id=active_sessions[0]["id"],
    )
    assert await service.sessions(staff_id=values["cashier"].id) == []

    with pytest.raises(AuthError):
        await service.refresh(
            raw_refresh_token="unknown-refresh-token-that-is-long-enough",
            device_token=values["device_token"],
            ip="192.0.2.1",
            user_agent=None,
        )
    await service.logout(
        raw_refresh_token="unknown-refresh-token-that-is-long-enough",
        staff_id=values["staff"].id,
    )
    assert await service.sessions(staff_id=values["staff"].id) == []
    await service.revoke_session(
        staff_id=values["staff"].id,
        session_id=UUID("00000000-0000-0000-0000-000000000001"),
    )
    await service.logout_all(
        staff_id=values["staff"].id, ip="192.0.2.1", user_agent=None
    )

    values["device"].status = DeviceStatus.REVOKED
    with pytest.raises(AuthError) as revoked:
        await service.require_device(values["device_token"])
    assert revoked.value.code == "DEVICE_REVOKED"

    with pytest.raises(AuthError):
        await service.authenticate_access_token(
            token="not-a-jwt", device_token=values["device_token"]
        )
    incomplete = service.jwt_service.encode(
        subject=str(values["staff"].id),
        audience="staff",
        ttl=timedelta(minutes=1),
    )
    with pytest.raises(AuthError) as missing_claim:
        await service.authenticate_access_token(
            token=incomplete, device_token=values["device_token"]
        )
    assert missing_claim.value.code == "INVALID_CREDENTIALS"

    profile_with_business = await service.me(staff=values["staff"])
    assert profile_with_business["business"]["name"] == "Test shop"

    values["staff"].business_id = None
    values["staff"].outlet_id = None
    profile = await service.me(staff=values["staff"])
    assert profile["business"] is None
    assert profile["outlet"] is None


async def test_offline_unlock_issue_verifies_pin_and_stores_only_salt(
    staff_auth_api, db_session
) -> None:
    client, values = staff_auth_api
    login = await _login(client, values)
    auth_headers = {
        "Authorization": f"Bearer {login.json()['access_token']}",
        "X-Device-Token": values["device_token"],
    }

    wrong_pin = await client.post(
        "/api/v1/auth/offline-unlock/issue",
        headers=auth_headers,
        json={"pin": "0000"},
    )
    assert wrong_pin.status_code == 401
    assert wrong_pin.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert await db_session.scalar(select(OfflineUnlock)) is None

    before = datetime.now(UTC)
    issued = await client.post(
        "/api/v1/auth/offline-unlock/issue",
        headers=auth_headers,
        json={"pin": "2580"},
    )
    after = datetime.now(UTC)
    assert issued.status_code == 200, issued.text
    payload = issued.json()
    expires_at = datetime.fromisoformat(payload["expires_at"])
    assert payload["salt"]
    assert before + timedelta(days=6, hours=23) < expires_at
    assert expires_at <= after + timedelta(days=7, seconds=2)

    stored = await db_session.scalar(select(OfflineUnlock))
    assert stored.salt == payload["salt"]
    assert stored.staff_id == values["staff"].id
    assert stored.device_id == values["device"].id
    assert stored.revoked_at is None
    assert not hasattr(stored, "pin_hash")
    assert not hasattr(stored, "verifier")


async def test_offline_unlock_reissue_and_explicit_revoke(
    staff_auth_api, db_session
) -> None:
    client, values = staff_auth_api
    login = await _login(client, values)
    auth_headers = {
        "Authorization": f"Bearer {login.json()['access_token']}",
        "X-Device-Token": values["device_token"],
    }
    first = await client.post(
        "/api/v1/auth/offline-unlock/issue", headers=auth_headers, json={"pin": "2580"}
    )
    second = await client.post(
        "/api/v1/auth/offline-unlock/issue", headers=auth_headers, json={"pin": "2580"}
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["salt"] != second.json()["salt"]

    rows = list(
        await db_session.scalars(
            select(OfflineUnlock).order_by(OfflineUnlock.issued_at)
        )
    )
    assert len(rows) == 2
    assert rows[0].revoked_at is not None
    assert rows[1].revoked_at is None

    revoked = await client.post(
        "/api/v1/auth/offline-unlock/revoke", headers=auth_headers
    )
    assert revoked.status_code == 200
    assert revoked.json()["revoked_unlocks"] == 1
    assert rows[1].revoked_at is not None


async def test_offline_unlock_expiry_is_capped_at_seven_days(staff_auth_api) -> None:
    client, values = staff_auth_api
    values["settings"].offline_unlock_max_days = 30
    login = await _login(client, values)
    response = await client.post(
        "/api/v1/auth/offline-unlock/issue",
        headers={
            "Authorization": f"Bearer {login.json()['access_token']}",
            "X-Device-Token": values["device_token"],
        },
        json={"pin": "2580"},
    )
    expires_at = datetime.fromisoformat(response.json()["expires_at"])
    assert response.status_code == 200
    assert expires_at <= datetime.now(UTC) + timedelta(days=7, seconds=2)


async def test_offline_unlock_configuration_must_be_positive(
    staff_auth_api, db_session, redis, hasher
) -> None:
    _, values = staff_auth_api
    settings = values["settings"]
    service = StaffAuthService(
        session=db_session,
        redis=redis,
        settings=settings,
        jwt_service=jwt_service_from_settings(settings),
        hasher=hasher,
    )
    issued = await service.issue_offline_unlock(
        staff=values["staff"],
        pin="2580",
        device_token=values["device_token"],
    )
    assert issued["salt"]

    settings.offline_unlock_max_days = 0
    with pytest.raises(AuthError) as disabled:
        await service.issue_offline_unlock(
            staff=values["staff"],
            pin="2580",
            device_token=values["device_token"],
        )
    assert disabled.value.code == "SERVICE_UNAVAILABLE"


async def test_pin_change_revokes_offline_unlocks(
    staff_auth_api, db_session, hasher
) -> None:
    client, values = staff_auth_api
    login = await _login(client, values)
    auth_headers = {
        "Authorization": f"Bearer {login.json()['access_token']}",
        "X-Device-Token": values["device_token"],
    }
    issued = await client.post(
        "/api/v1/auth/offline-unlock/issue", headers=auth_headers, json={"pin": "2580"}
    )
    unlock = await db_session.scalar(select(OfflineUnlock))
    assert issued.status_code == 200

    wrong = await client.post(
        "/api/v1/auth/change-pin",
        headers=auth_headers,
        json={"current_pin": "0000", "new_pin": "8642"},
    )
    assert wrong.status_code == 401
    weak = await client.post(
        "/api/v1/auth/change-pin",
        headers=auth_headers,
        json={"current_pin": "2580", "new_pin": "1234"},
    )
    assert weak.status_code == 422
    assert weak.json()["error"]["code"] == "WEAK_PIN"

    changed = await client.post(
        "/api/v1/auth/change-pin",
        headers=auth_headers,
        json={"current_pin": "2580", "new_pin": "8642"},
    )
    assert changed.status_code == 204
    assert hasher.verify_pin("8642", values["staff"].pin_hash)
    assert unlock.revoked_at is not None
    assert values["staff"].must_change_pin is False

    old_pin = await _login(client, values, pin="2580")
    new_pin = await _login(client, values, pin="8642")
    assert old_pin.status_code == 401
    assert new_pin.status_code == 200


async def test_offline_unlocks_revoke_on_device_revoke_and_staff_deactivation(
    staff_auth_api, db_session
) -> None:
    client, values = staff_auth_api
    login = await _login(client, values)
    auth_headers = {
        "Authorization": f"Bearer {login.json()['access_token']}",
        "X-Device-Token": values["device_token"],
    }
    issued = await client.post(
        "/api/v1/auth/offline-unlock/issue", headers=auth_headers, json={"pin": "2580"}
    )
    unlock = await db_session.scalar(select(OfflineUnlock))
    assert issued.status_code == 200

    values["device"].status = DeviceStatus.REVOKED
    await db_session.commit()
    denied = await client.post(
        "/api/v1/auth/offline-unlock/revoke", headers=auth_headers
    )
    assert denied.status_code == 401
    assert unlock.revoked_at is not None

    values["device"].status = DeviceStatus.ACTIVE
    values["staff"].is_active = True
    await db_session.commit()
    next_login = await _login(client, values)
    next_headers = {
        "Authorization": f"Bearer {next_login.json()['access_token']}",
        "X-Device-Token": values["device_token"],
    }
    next_issue = await client.post(
        "/api/v1/auth/offline-unlock/issue", headers=next_headers, json={"pin": "2580"}
    )
    assert next_issue.status_code == 200
    second_unlock = await db_session.scalar(
        select(OfflineUnlock).where(OfflineUnlock.revoked_at.is_(None))
    )

    values["staff"].is_active = False
    await db_session.commit()
    inactive = await client.get("/api/v1/auth/me", headers=next_headers)
    assert inactive.status_code == 401
    assert second_unlock.revoked_at is not None


async def test_offline_sessions_sync_records_audit_events(
    staff_auth_api, db_session, redis, hasher
) -> None:
    client, values = staff_auth_api
    login = await _login(client, values)
    now = datetime.now(UTC)
    body = {
        "sessions": [
            {
                "staff_id": str(values["staff"].id),
                "device_id": str(values["device"].id),
                "unlocked_at": (now - timedelta(hours=2)).isoformat(),
                "locked_at": (now - timedelta(hours=1)).isoformat(),
            },
            {
                "staff_id": str(values["cashier"].id),
                "device_id": str(values["device"].id),
                "unlocked_at": (now - timedelta(minutes=30)).isoformat(),
                "locked_at": None,
            },
        ]
    }
    response = await client.post(
        "/api/v1/auth/offline-sessions/sync",
        headers={
            "Authorization": f"Bearer {login.json()['access_token']}",
            "X-Device-Token": values["device_token"],
        },
        json=body,
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"recorded_sessions": 2}
    events = await db_session.scalars(
        select(AuditLog).where(AuditLog.details["method"].as_string() == "offline")
    )
    audits = list(events)
    assert len(audits) == 2
    assert {event.actor_id for event in audits} == {
        values["staff"].id,
        values["cashier"].id,
    }

    service = StaffAuthService(
        session=db_session,
        redis=redis,
        settings=values["settings"],
        jwt_service=jwt_service_from_settings(values["settings"]),
        hasher=hasher,
    )
    records = await service.sync_offline_sessions(
        staff=values["staff"],
        device_token=values["device_token"],
        sessions=[
            OfflineSessionItem(
                staff_id=values["staff"].id,
                device_id=values["device"].id,
                unlocked_at=now - timedelta(minutes=5),
                locked_at=None,
            )
        ],
    )
    assert records == 1


async def test_offline_sessions_sync_rejects_mismatched_device_or_business(
    staff_auth_api, db_session
) -> None:
    client, values = staff_auth_api
    login = await _login(client, values)
    timestamp = datetime.now(UTC).isoformat()
    headers = {
        "Authorization": f"Bearer {login.json()['access_token']}",
        "X-Device-Token": values["device_token"],
    }
    mismatch = await client.post(
        "/api/v1/auth/offline-sessions/sync",
        headers=headers,
        json={
            "sessions": [
                {
                    "staff_id": str(values["staff"].id),
                    "device_id": "00000000-0000-0000-0000-000000000001",
                    "unlocked_at": timestamp,
                    "locked_at": None,
                }
            ]
        },
    )
    assert mismatch.status_code == 403

    other_business = Business(name="Other shop", status=BusinessStatus.TRIAL)
    db_session.add(other_business)
    await db_session.flush()
    other_outlet = Outlet(business_id=other_business.id, name="Main", is_default=True)
    db_session.add(other_outlet)
    await db_session.flush()
    other_staff = Staff(
        business_id=other_business.id,
        outlet_id=other_outlet.id,
        name="Other cashier",
        role=StaffRole.CASHIER,
        pin_hash="not-used",
    )
    db_session.add(other_staff)
    await db_session.commit()
    other_business_session = await client.post(
        "/api/v1/auth/offline-sessions/sync",
        headers=headers,
        json={
            "sessions": [
                {
                    "staff_id": str(other_staff.id),
                    "device_id": str(values["device"].id),
                    "unlocked_at": timestamp,
                    "locked_at": None,
                }
            ]
        },
    )
    assert other_business_session.status_code == 403


async def test_offline_session_timestamps_must_be_ordered_and_timezone_aware(
    staff_auth_api,
) -> None:
    client, values = staff_auth_api
    login = await _login(client, values)
    auth_headers = {
        "Authorization": f"Bearer {login.json()['access_token']}",
        "X-Device-Token": values["device_token"],
    }
    invalid = await client.post(
        "/api/v1/auth/offline-sessions/sync",
        headers=auth_headers,
        json={
            "sessions": [
                {
                    "staff_id": str(values["staff"].id),
                    "device_id": str(values["device"].id),
                    "unlocked_at": "2026-11-12T10:00:00",
                    "locked_at": "2026-11-12T09:00:00",
                }
            ]
        },
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"

    invalid_order = await client.post(
        "/api/v1/auth/offline-sessions/sync",
        headers=auth_headers,
        json={
            "sessions": [
                {
                    "staff_id": str(values["staff"].id),
                    "device_id": str(values["device"].id),
                    "unlocked_at": "2026-11-12T10:00:00+03:00",
                    "locked_at": "2026-11-12T09:00:00+03:00",
                }
            ]
        },
    )
    assert invalid_order.status_code == 422
