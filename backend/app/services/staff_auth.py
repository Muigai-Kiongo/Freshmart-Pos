from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.staff_auth import OfflineSessionItem
from app.core.clock import Clock, SystemClock
from app.core.config import Settings
from app.core.errors import AuthError, WeakPinError
from app.core.hashing import SecretHasher, generate_urlsafe_token, hash_token
from app.core.jwt import JwtError, JwtService
from app.core.lockout import AccountLockout
from app.core.pin import validate_pin
from app.core.rate_limit import SlidingWindowRateLimiter
from app.models.audit_log import AuditLog
from app.models.business import Business
from app.models.device import Device
from app.models.enums import BusinessStatus, DeviceStatus, SubjectType
from app.models.offline_unlock import OfflineUnlock
from app.models.outlet import Outlet
from app.models.refresh_token import RefreshToken
from app.models.staff import Staff


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class StaffAuthService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        redis: Redis,
        settings: Settings,
        jwt_service: JwtService,
        hasher: SecretHasher,
        clock: Clock | None = None,
    ) -> None:
        self.session = session
        self.redis = redis
        self.settings = settings
        self.jwt_service = jwt_service
        self.hasher = hasher
        self.clock = clock or SystemClock()
        self.lockout = AccountLockout(
            redis,
            self.clock,
            prefix="staff-pin-lockout",
            max_failures=settings.lockout_failures,
            base_seconds=settings.lockout_base_seconds,
        )
        self.rate_limiter = SlidingWindowRateLimiter(
            redis, self.clock, prefix="staff-pin-rate"
        )

    def _now(self) -> datetime:
        return _as_utc(self.clock.now())

    async def require_device(self, raw_token: str | None) -> Device:
        if not raw_token:
            raise AuthError(
                "DEVICE_NOT_REGISTERED",
                "A registered device is required.",
                status_code=401,
            )
        device = await self.session.scalar(
            select(Device).where(Device.device_token_hash == hash_token(raw_token))
        )
        if device is None:
            raise AuthError(
                "DEVICE_NOT_REGISTERED",
                "This device is not registered.",
                status_code=401,
            )
        if device.status != DeviceStatus.ACTIVE:
            await self.revoke_offline_unlocks(device_id=device.id)
            raise AuthError(
                "DEVICE_REVOKED", "This device has been revoked.", status_code=401
            )
        return device

    async def staff_list(
        self, *, outlet_id: uuid.UUID, device_token: str | None
    ) -> list[dict[str, Any]]:
        device = await self.require_device(device_token)
        if device.outlet_id != outlet_id:
            raise AuthError(
                "DEVICE_NOT_REGISTERED",
                "This device is not registered for this outlet.",
                status_code=403,
            )
        rows = await self.session.execute(
            select(Staff.id, Staff.name, Staff.avatar_url)
            .where(
                Staff.outlet_id == outlet_id,
                Staff.business_id == device.business_id,
                Staff.is_active.is_(True),
            )
            .order_by(Staff.name, Staff.id)
        )
        return [
            {"id": row.id, "name": row.name, "avatar": row.avatar_url} for row in rows
        ]

    async def pin_login(
        self,
        *,
        staff_id: uuid.UUID,
        pin: str,
        device_token: str | None,
        ip: str,
        user_agent: str | None,
    ) -> dict[str, Any]:
        device = await self.require_device(device_token)
        await self._check_login_rate_limits(ip=ip, device_id=device.id)

        lockout_key = str(staff_id)
        current_lockout = await self.lockout.status(lockout_key)
        if current_lockout.locked:
            raise self._locked_error(current_lockout.retry_after_seconds)

        staff = await self.session.get(Staff, staff_id)
        valid_pin = self.hasher.verify_pin_dummy_if_missing(
            pin, staff.pin_hash if staff else None
        )
        device_matches = (
            staff is not None
            and staff.business_id == device.business_id
            and staff.outlet_id == device.outlet_id
            and staff.is_active
        )
        if staff is None or not valid_pin or not device_matches:
            status = await self.lockout.register_failure(lockout_key)
            self.session.add(
                AuditLog(
                    event_type="login_failure",
                    actor_id=staff.id if staff else None,
                    business_id=staff.business_id if staff else device.business_id,
                    ip=ip,
                    user_agent=user_agent,
                    details={"method": "pin"},
                )
            )
            if status.locked:
                self.session.add(
                    AuditLog(
                        event_type="lockout",
                        actor_id=staff.id if staff else None,
                        business_id=staff.business_id if staff else device.business_id,
                        ip=ip,
                        user_agent=user_agent,
                        details={
                            "method": "pin",
                            "retry_after": status.retry_after_seconds,
                        },
                    )
                )
            await self.session.commit()
            if status.locked:
                raise self._locked_error(status.retry_after_seconds)
            raise AuthError(
                "INVALID_CREDENTIALS", "Invalid staff ID or PIN.", status_code=401
            )

        business = (
            await self.session.get(Business, staff.business_id)
            if staff.business_id
            else None
        )
        if business is None or business.status == BusinessStatus.SUSPENDED:
            raise AuthError(
                "BUSINESS_SUSPENDED",
                "This business cannot sign in right now.",
                status_code=403,
            )

        now = self._now()
        staff.last_login_at = now
        device.last_seen_at = now
        await self.lockout.register_success(lockout_key)
        response, _ = await self._issue_session(
            staff=staff,
            device=device,
            ip=ip,
            user_agent=user_agent,
            now=now,
        )
        self.session.add(
            AuditLog(
                event_type="login_success",
                actor_id=staff.id,
                business_id=staff.business_id,
                ip=ip,
                user_agent=user_agent,
                details={"method": "pin", "device_id": str(device.id)},
            )
        )
        await self.session.commit()
        return response

    async def refresh(
        self,
        *,
        raw_refresh_token: str,
        device_token: str | None,
        ip: str,
        user_agent: str | None,
    ) -> dict[str, Any]:
        device = await self.require_device(device_token)
        token_hash = hash_token(raw_refresh_token)
        result = await self.session.execute(
            select(RefreshToken)
            .where(RefreshToken.token_hash == token_hash)
            .with_for_update()
        )
        old_token = result.scalar_one_or_none()
        if old_token is None or old_token.subject_type != SubjectType.STAFF:
            raise AuthError(
                "INVALID_CREDENTIALS", "Invalid refresh token.", status_code=401
            )
        if old_token.device_id != device.id:
            raise AuthError(
                "DEVICE_REVOKED",
                "This refresh token is not bound to this device.",
                status_code=401,
            )
        if old_token.revoked_at is not None:
            if old_token.replaced_by is not None:
                await self._revoke_family_and_audit(
                    old_token, ip=ip, user_agent=user_agent
                )
                raise AuthError(
                    "TOKEN_REUSED",
                    "A rotated refresh token was reused.",
                    status_code=401,
                )
            raise AuthError(
                "INVALID_CREDENTIALS",
                "This refresh token has been revoked.",
                status_code=401,
            )
        now = self._now()
        if _as_utc(old_token.expires_at) <= now:
            raise AuthError(
                "INVALID_CREDENTIALS",
                "This refresh token has expired.",
                status_code=401,
            )
        staff = await self.session.get(Staff, old_token.subject_id)
        if staff is not None and not staff.is_active:
            await self.revoke_offline_unlocks(staff_id=staff.id)
        if (
            staff is None
            or not staff.is_active
            or staff.business_id != device.business_id
            or staff.outlet_id != device.outlet_id
        ):
            raise AuthError(
                "INVALID_CREDENTIALS", "Invalid refresh token.", status_code=401
            )
        business = (
            await self.session.get(Business, staff.business_id)
            if staff.business_id
            else None
        )
        if business is None or business.status == BusinessStatus.SUSPENDED:
            raise AuthError(
                "BUSINESS_SUSPENDED",
                "This business cannot sign in right now.",
                status_code=403,
            )

        old_token.revoked_at = now
        old_token.last_used_at = now
        response, replacement_id = await self._issue_session(
            staff=staff,
            device=device,
            ip=ip,
            user_agent=user_agent,
            now=now,
            family_id=old_token.family_id,
        )
        old_token.replaced_by = replacement_id
        device.last_seen_at = now
        await self.session.commit()
        return response

    async def logout(self, *, raw_refresh_token: str, staff_id: uuid.UUID) -> None:
        token = await self.session.scalar(
            select(RefreshToken).where(
                RefreshToken.token_hash == hash_token(raw_refresh_token)
            )
        )
        if (
            token is not None
            and token.subject_type == SubjectType.STAFF
            and token.subject_id == staff_id
            and token.revoked_at is None
        ):
            token.revoked_at = self._now()
            self.session.add(
                AuditLog(
                    event_type="logout",
                    actor_id=staff_id,
                    details={"session_id": str(token.id)},
                )
            )
            await self.session.commit()

    async def logout_all(
        self, *, staff_id: uuid.UUID, ip: str, user_agent: str | None
    ) -> int:
        now = self._now()
        result = await self.session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.subject_type == SubjectType.STAFF,
                RefreshToken.subject_id == staff_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        self.session.add(
            AuditLog(
                event_type="logout",
                actor_id=staff_id,
                ip=ip,
                user_agent=user_agent,
                details={"all_sessions": True},
            )
        )
        await self.session.commit()
        return int(cast(CursorResult[Any], result).rowcount or 0)

    async def sessions(self, *, staff_id: uuid.UUID) -> list[dict[str, Any]]:
        now = self._now()
        rows = await self.session.execute(
            select(RefreshToken, Device.name)
            .outerjoin(Device, Device.id == RefreshToken.device_id)
            .where(
                RefreshToken.subject_type == SubjectType.STAFF,
                RefreshToken.subject_id == staff_id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > now,
            )
            .order_by(RefreshToken.created_at.desc())
        )
        return [
            {
                "id": token.id,
                "device_id": token.device_id,
                "device_name": device_name,
                "ip": token.ip,
                "last_used_at": token.last_used_at,
                "created_at": token.created_at,
                "expires_at": token.expires_at,
            }
            for token, device_name in rows
        ]

    async def revoke_session(
        self, *, staff_id: uuid.UUID, session_id: uuid.UUID
    ) -> None:
        token = await self.session.scalar(
            select(RefreshToken).where(
                RefreshToken.id == session_id,
                RefreshToken.subject_type == SubjectType.STAFF,
                RefreshToken.subject_id == staff_id,
                RefreshToken.revoked_at.is_(None),
            )
        )
        if token is not None:
            now = self._now()
            await self.session.execute(
                update(RefreshToken)
                .where(
                    RefreshToken.family_id == token.family_id,
                    RefreshToken.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            self.session.add(
                AuditLog(
                    event_type="logout",
                    actor_id=staff_id,
                    details={"session_id": str(session_id)},
                )
            )
            await self.session.commit()

    async def me(self, *, staff: Staff) -> dict[str, Any]:
        business = (
            await self.session.get(Business, staff.business_id)
            if staff.business_id
            else None
        )
        outlet = (
            await self.session.get(Outlet, staff.outlet_id) if staff.outlet_id else None
        )
        return {
            "id": staff.id,
            "name": staff.name,
            "role": staff.role,
            "business": (
                {
                    "id": business.id,
                    "name": business.name,
                    "status": business.status,
                    "trial_ends_at": business.trial_ends_at,
                }
                if business
                else None
            ),
            "outlet": {"id": outlet.id, "name": outlet.name} if outlet else None,
            "flags": {
                "must_change_pin": staff.must_change_pin,
                "must_change_password": staff.must_change_password,
                "mfa_enabled": staff.mfa_enabled,
            },
        }

    async def issue_offline_unlock(
        self,
        *,
        staff: Staff,
        pin: str,
        device_token: str | None,
    ) -> dict[str, Any]:
        device = await self.require_device(device_token)
        if (
            not staff.is_active
            or staff.business_id != device.business_id
            or staff.outlet_id != device.outlet_id
            or not self.hasher.verify_pin_dummy_if_missing(pin, staff.pin_hash)
        ):
            raise AuthError(
                "INVALID_CREDENTIALS", "Invalid staff ID or PIN.", status_code=401
            )
        max_days = min(self.settings.offline_unlock_max_days, 7)
        if max_days < 1:
            raise AuthError(
                "SERVICE_UNAVAILABLE",
                "Offline unlock is not configured.",
                status_code=503,
            )

        now = self._now()
        await self.revoke_offline_unlocks(
            staff_id=staff.id, device_id=device.id, commit=False
        )
        expires_at = now + timedelta(days=max_days)
        salt = secrets.token_urlsafe(24)
        self.session.add(
            OfflineUnlock(
                staff_id=staff.id,
                device_id=device.id,
                salt=salt,
                issued_at=now,
                expires_at=expires_at,
            )
        )
        self.session.add(
            AuditLog(
                event_type="offline_unlock_issued",
                actor_id=staff.id,
                business_id=staff.business_id,
                details={
                    "device_id": str(device.id),
                    "expires_at": expires_at.isoformat(),
                },
            )
        )
        await self.session.commit()
        return {"salt": salt, "expires_at": expires_at}

    async def change_pin(
        self,
        *,
        staff: Staff,
        current_pin: str,
        new_pin: str,
    ) -> None:
        if not self.hasher.verify_pin_dummy_if_missing(current_pin, staff.pin_hash):
            raise AuthError(
                "INVALID_CREDENTIALS", "Current PIN is incorrect.", status_code=401
            )
        try:
            validate_pin(new_pin)
        except WeakPinError as exc:
            raise AuthError("WEAK_PIN", exc.message, status_code=422) from exc

        staff.pin_hash = self.hasher.hash_pin(new_pin)
        staff.must_change_pin = False
        await self.revoke_offline_unlocks(staff_id=staff.id, commit=False)
        self.session.add(
            AuditLog(
                event_type="pin_change",
                actor_id=staff.id,
                business_id=staff.business_id,
                details={"offline_unlocks_revoked": True},
            )
        )
        await self.session.commit()

    async def revoke_offline_unlock(
        self,
        *,
        staff: Staff,
        device_token: str | None,
    ) -> int:
        device = await self.require_device(device_token)
        if (
            staff.business_id != device.business_id
            or staff.outlet_id != device.outlet_id
        ):
            raise AuthError(
                "DEVICE_REVOKED",
                "This device is not registered for this staff account.",
                status_code=403,
            )
        return await self.revoke_offline_unlocks(staff_id=staff.id, device_id=device.id)

    async def revoke_offline_unlocks(
        self,
        *,
        staff_id: uuid.UUID | None = None,
        device_id: uuid.UUID | None = None,
        commit: bool = True,
    ) -> int:
        if staff_id is None and device_id is None:
            raise ValueError("At least one offline unlock owner must be specified")
        query = update(OfflineUnlock).where(OfflineUnlock.revoked_at.is_(None))
        if staff_id is not None:
            query = query.where(OfflineUnlock.staff_id == staff_id)
        if device_id is not None:
            query = query.where(OfflineUnlock.device_id == device_id)
        result = await self.session.execute(query.values(revoked_at=self._now()))
        if commit:
            await self.session.commit()
        return int(cast(CursorResult[Any], result).rowcount or 0)

    async def sync_offline_sessions(
        self,
        *,
        staff: Staff,
        device_token: str | None,
        sessions: list[OfflineSessionItem],
    ) -> int:
        device = await self.require_device(device_token)
        if (
            not staff.is_active
            or staff.business_id != device.business_id
            or staff.outlet_id != device.outlet_id
        ):
            raise AuthError(
                "DEVICE_REVOKED",
                "This device is not registered for this staff account.",
                status_code=403,
            )
        if any(item.device_id != device.id for item in sessions):
            raise AuthError(
                "DEVICE_REVOKED",
                "Offline sessions must belong to this device.",
                status_code=403,
            )

        staff_ids = {item.staff_id for item in sessions}
        if staff_ids:
            rows = await self.session.scalars(
                select(Staff).where(
                    Staff.id.in_(staff_ids),
                    Staff.business_id == device.business_id,
                    Staff.outlet_id == device.outlet_id,
                )
            )
            valid_staff_ids = {item.id for item in rows}
            if valid_staff_ids != staff_ids:
                raise AuthError(
                    "INVALID_CREDENTIALS",
                    "An offline session is outside this device's business.",
                    status_code=403,
                )

        for item in sessions:
            self.session.add(
                AuditLog(
                    event_type="login_success",
                    actor_id=item.staff_id,
                    business_id=device.business_id,
                    details={
                        "method": "offline",
                        "device_id": str(device.id),
                        "unlocked_at": item.unlocked_at.isoformat(),
                        "locked_at": item.locked_at.isoformat()
                        if item.locked_at
                        else None,
                    },
                )
            )
        await self.session.commit()
        return len(sessions)

    async def authenticate_access_token(
        self, *, token: str, device_token: str | None
    ) -> tuple[Staff, Device]:
        try:
            claims = self.jwt_service.decode(token, audience="staff")
            staff_id = uuid.UUID(claims["sub"])
            device_id = uuid.UUID(claims["device_id"])
            business_id = uuid.UUID(claims["business_id"])
            outlet_id = uuid.UUID(claims["outlet_id"])
        except (JwtError, KeyError, ValueError, TypeError) as exc:
            raise AuthError(
                "INVALID_CREDENTIALS", "Invalid access token.", status_code=401
            ) from exc
        device = await self.require_device(device_token)
        staff = await self.session.get(Staff, staff_id)
        if staff is not None and not staff.is_active:
            await self.revoke_offline_unlocks(staff_id=staff_id)
        if (
            staff is None
            or not staff.is_active
            or staff.business_id != business_id
            or staff.outlet_id != outlet_id
            or device.id != device_id
            or device.business_id != business_id
            or device.outlet_id != outlet_id
        ):
            raise AuthError(
                "INVALID_CREDENTIALS", "Invalid access token.", status_code=401
            )
        return staff, device

    async def _check_login_rate_limits(self, *, ip: str, device_id: uuid.UUID) -> None:
        checks = (
            (f"pin-ip:{ip}", self.settings.pin_login_ip_limit),
            (f"pin-device:{device_id}", self.settings.pin_login_device_limit),
        )
        for key, limit in checks:
            result = await self.rate_limiter.hit(key, limit=limit, window_seconds=60)
            if not result.allowed:
                raise AuthError(
                    "RATE_LIMITED",
                    "Too many login attempts. Try again later.",
                    status_code=429,
                    details={"retry_after": result.retry_after_seconds},
                )

    def _locked_error(self, retry_after: int) -> AuthError:
        return AuthError(
            "ACCOUNT_LOCKED",
            "This account is temporarily locked.",
            status_code=423,
            details={"retry_after": retry_after},
        )

    async def _issue_session(
        self,
        *,
        staff: Staff,
        device: Device,
        ip: str,
        user_agent: str | None,
        now: datetime,
        family_id: uuid.UUID | None = None,
    ) -> tuple[dict[str, Any], uuid.UUID]:
        access_ttl = timedelta(minutes=self.settings.staff_access_minutes)
        refresh_ttl = timedelta(days=self.settings.staff_refresh_days)
        access_token = self.jwt_service.encode(
            subject=str(staff.id),
            audience="staff",
            ttl=access_ttl,
            extra={
                "business_id": str(staff.business_id),
                "outlet_id": str(staff.outlet_id),
                "role": staff.role.value,
                "device_id": str(device.id),
            },
        )
        refresh_token = generate_urlsafe_token()
        record = RefreshToken(
            family_id=family_id or uuid.uuid4(),
            subject_type=SubjectType.STAFF,
            subject_id=staff.id,
            token_hash=hash_token(refresh_token),
            device_id=device.id,
            expires_at=now + refresh_ttl,
            ip=ip,
            user_agent=user_agent,
            last_used_at=now,
        )
        self.session.add(record)
        await self.session.flush()
        response = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": int(access_ttl.total_seconds()),
            "refresh_expires_in": int(refresh_ttl.total_seconds()),
            "must_change_pin": staff.must_change_pin,
        }
        return response, record.id

    async def _revoke_family_and_audit(
        self, token: RefreshToken, *, ip: str, user_agent: str | None
    ) -> None:
        now = self._now()
        await self.session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.family_id == token.family_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        self.session.add(
            AuditLog(
                event_type="token_reuse_detected",
                actor_id=token.subject_id,
                ip=ip,
                user_agent=user_agent,
                details={"family_id": str(token.family_id)},
            )
        )
        await self.session.commit()


def build_staff_auth_service(
    *,
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
    jwt_service: JwtService,
    hasher: SecretHasher,
    clock: Clock | None = None,
) -> StaffAuthService:
    return StaffAuthService(
        session=session,
        redis=redis,
        settings=settings,
        jwt_service=jwt_service,
        hasher=hasher,
        clock=clock,
    )
