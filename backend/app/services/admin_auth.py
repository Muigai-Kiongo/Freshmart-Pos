from __future__ import annotations

import base64
import io
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pyotp
import qrcode
from redis.asyncio import Redis
from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock, SystemClock
from app.core.config import Settings
from app.core.crypto import SecretBox
from app.core.errors import AuthError, WeakPasswordError, WeakPinError
from app.core.hashing import SecretHasher, generate_urlsafe_token, hash_token
from app.core.i18n import preferred_language
from app.core.jwt import JwtError, JwtService
from app.core.lockout import AccountLockout
from app.core.otp import generate_otp, hash_otp, verify_otp
from app.core.password import validate_password
from app.core.phone import normalize_ke_phone
from app.core.pin import validate_pin
from app.core.rate_limit import SlidingWindowRateLimiter
from app.integrations.sms import SmsDeliveryError, SmsProvider
from app.models.audit_log import AuditLog
from app.models.business import Business
from app.models.consumed_token import ConsumedToken
from app.models.enums import (
    BusinessStatus,
    OtpPurpose,
    StaffRole,
    SubjectType,
    TokenPurpose,
)
from app.models.offline_unlock import OfflineUnlock
from app.models.otp_challenge import OtpChallenge
from app.models.refresh_token import RefreshToken
from app.models.staff import Staff


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class AdminAuthService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        redis: Redis,
        settings: Settings,
        jwt_service: JwtService,
        hasher: SecretHasher,
        sms_provider: SmsProvider,
        secret_box: SecretBox | None,
        clock: Clock | None = None,
    ) -> None:
        self.session = session
        self.redis = redis
        self.settings = settings
        self.jwt_service = jwt_service
        self.hasher = hasher
        self.sms_provider = sms_provider
        self.secret_box = secret_box
        self.clock = clock or SystemClock()
        self.lockout = AccountLockout(
            redis,
            self.clock,
            prefix="admin-password-lockout",
            max_failures=settings.lockout_failures,
            base_seconds=settings.lockout_base_seconds,
        )
        self.rate_limiter = SlidingWindowRateLimiter(
            redis, self.clock, prefix="admin-auth-rate"
        )

    def _now(self) -> datetime:
        return _as_utc(self.clock.now())

    async def login(
        self,
        *,
        identifier: str,
        password: str,
        totp_code: str | None,
        ip: str,
        user_agent: str | None,
    ) -> dict[str, Any]:
        rate = await self.rate_limiter.hit(
            f"login-ip:{ip}",
            limit=self.settings.admin_login_ip_limit,
            window_seconds=60,
        )
        if not rate.allowed:
            raise AuthError(
                "RATE_LIMITED",
                "Too many login attempts. Try again later.",
                status_code=429,
                details={"retry_after": rate.retry_after_seconds},
            )

        normalized = self._normalize_identifier(identifier)
        lockout_key = hash_token(normalized)
        status = await self.lockout.status(lockout_key)
        if status.locked:
            raise self._locked_error(status.retry_after_seconds)
        staff = await self.session.scalar(
            select(Staff).where(
                Staff.role.in_([StaffRole.OWNER, StaffRole.PLATFORM_ADMIN]),
                or_(func.lower(Staff.email) == normalized, Staff.phone == normalized),
            )
        )
        password_valid = self.hasher.verify_password_dummy_if_missing(
            password, staff.password_hash if staff else None
        )
        valid = bool(staff and staff.is_active and password_valid)
        if not valid:
            status = await self.lockout.register_failure(lockout_key)
            self.session.add(
                AuditLog(
                    event_type="login_failure",
                    actor_id=staff.id if staff else None,
                    business_id=staff.business_id if staff else None,
                    ip=ip,
                    user_agent=user_agent,
                    details={"method": "password"},
                )
            )
            if status.locked:
                self.session.add(
                    AuditLog(
                        event_type="lockout",
                        actor_id=staff.id if staff else None,
                        business_id=staff.business_id if staff else None,
                        ip=ip,
                        user_agent=user_agent,
                        details={
                            "method": "password",
                            "retry_after": status.retry_after_seconds,
                        },
                    )
                )
            await self.session.commit()
            if status.locked:
                raise self._locked_error(status.retry_after_seconds)
            raise AuthError(
                "INVALID_CREDENTIALS",
                "Invalid identifier or password.",
                status_code=401,
            )

        assert staff is not None
        if staff.mfa_enabled:
            if not staff.mfa_secret or not self._verify_totp(
                staff.mfa_secret, totp_code
            ):
                if totp_code is None:
                    return {
                        "mfa_required": True,
                        "cookie_mode": self.settings.admin_cookie_mode,
                    }
                status = await self.lockout.register_failure(lockout_key)
                self.session.add(
                    AuditLog(
                        event_type="login_failure",
                        actor_id=staff.id,
                        business_id=staff.business_id,
                        ip=ip,
                        user_agent=user_agent,
                        details={"method": "password_totp"},
                    )
                )
                if status.locked:
                    self.session.add(
                        AuditLog(
                            event_type="lockout",
                            actor_id=staff.id,
                            business_id=staff.business_id,
                            ip=ip,
                            user_agent=user_agent,
                            details={
                                "method": "password_totp",
                                "retry_after": status.retry_after_seconds,
                            },
                        )
                    )
                await self.session.commit()
                if status.locked:
                    raise self._locked_error(status.retry_after_seconds)
                raise AuthError(
                    "INVALID_CREDENTIALS",
                    "Invalid identifier or password.",
                    status_code=401,
                )
        elif staff.role == StaffRole.PLATFORM_ADMIN:
            raise AuthError(
                "MFA_REQUIRED",
                "Platform administrators must configure multi-factor authentication.",
                status_code=403,
            )

        business = (
            await self.session.get(Business, staff.business_id)
            if staff.business_id
            else None
        )
        if staff.role == StaffRole.OWNER and business is None:
            raise AuthError(
                "INVALID_CREDENTIALS",
                "Invalid identifier or password.",
                status_code=401,
            )
        if business is not None and business.status == BusinessStatus.SUSPENDED:
            raise AuthError(
                "BUSINESS_SUSPENDED",
                "This business cannot sign in right now.",
                status_code=403,
            )
        now = self._now()
        staff.last_login_at = now
        await self.lockout.register_success(lockout_key)
        response, _ = await self._issue_session(
            staff=staff,
            ip=ip,
            user_agent=user_agent,
            now=now,
            mfa=staff.mfa_enabled,
        )
        self.session.add(
            AuditLog(
                event_type="login_success",
                actor_id=staff.id,
                business_id=staff.business_id,
                ip=ip,
                user_agent=user_agent,
                details={"method": "password", "mfa": staff.mfa_enabled},
            )
        )
        await self.session.commit()
        return response

    async def authenticate_access_token(self, token: str) -> Staff:
        try:
            claims = self.jwt_service.decode(token, audience="admin")
            staff_id = uuid.UUID(claims["sub"])
            mfa_claim = claims["mfa"]
            if not isinstance(mfa_claim, bool):
                raise TypeError("Invalid MFA claim")
        except (JwtError, KeyError, ValueError, TypeError) as exc:
            raise AuthError(
                "INVALID_CREDENTIALS", "Invalid admin access token.", status_code=401
            ) from exc
        staff = await self.session.get(Staff, staff_id)
        if (
            staff is None
            or not staff.is_active
            or staff.role not in {StaffRole.OWNER, StaffRole.PLATFORM_ADMIN}
            or (staff.mfa_enabled and not mfa_claim)
            or (staff.role == StaffRole.PLATFORM_ADMIN and not staff.mfa_enabled)
        ):
            raise AuthError(
                "INVALID_CREDENTIALS", "Invalid admin access token.", status_code=401
            )
        return staff

    async def refresh(
        self, *, raw_refresh_token: str, ip: str, user_agent: str | None
    ) -> dict[str, Any]:
        result = await self.session.execute(
            select(RefreshToken)
            .where(RefreshToken.token_hash == hash_token(raw_refresh_token))
            .with_for_update()
        )
        old_token = result.scalar_one_or_none()
        if old_token is None or old_token.subject_type != SubjectType.ADMIN:
            raise AuthError(
                "INVALID_CREDENTIALS", "Invalid refresh token.", status_code=401
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
        if (
            staff is None
            or not staff.is_active
            or staff.role not in {StaffRole.OWNER, StaffRole.PLATFORM_ADMIN}
            or (staff.role == StaffRole.OWNER and staff.business_id is None)
            or (staff.mfa_enabled and not staff.mfa_secret)
            or (staff.role == StaffRole.PLATFORM_ADMIN and not staff.mfa_enabled)
        ):
            raise AuthError(
                "INVALID_CREDENTIALS", "Invalid refresh token.", status_code=401
            )
        business = (
            await self.session.get(Business, staff.business_id)
            if staff.business_id
            else None
        )
        if staff.role == StaffRole.OWNER and business is None:
            raise AuthError(
                "INVALID_CREDENTIALS", "Invalid refresh token.", status_code=401
            )
        if business is not None and business.status == BusinessStatus.SUSPENDED:
            raise AuthError(
                "BUSINESS_SUSPENDED",
                "This business cannot sign in right now.",
                status_code=403,
            )
        old_token.revoked_at = now
        old_token.last_used_at = now
        response, replacement_id = await self._issue_session(
            staff=staff,
            ip=ip,
            user_agent=user_agent,
            now=now,
            mfa=staff.mfa_enabled,
            family_id=old_token.family_id,
        )
        old_token.replaced_by = replacement_id
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
            and token.subject_type == SubjectType.ADMIN
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
        result = await self.session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.subject_type == SubjectType.ADMIN,
                RefreshToken.subject_id == staff_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=self._now())
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

    async def setup_totp(self, *, staff: Staff) -> dict[str, str]:
        if self.secret_box is None:
            raise AuthError(
                "SERVICE_UNAVAILABLE",
                "MFA encryption is not configured.",
                status_code=503,
            )
        if staff.mfa_enabled:
            raise AuthError(
                "VALIDATION_ERROR",
                "Multi-factor authentication is already enabled.",
                status_code=409,
            )
        secret = pyotp.random_base32()
        staff.mfa_secret = self.secret_box.encrypt(secret)
        self.session.add(
            AuditLog(
                event_type="mfa_setup",
                actor_id=staff.id,
                business_id=staff.business_id,
                details={"status": "pending"},
            )
        )
        await self.session.commit()
        account = staff.email or staff.phone or str(staff.id)
        uri = pyotp.TOTP(secret).provisioning_uri(
            name=account, issuer_name=self.settings.jwt_issuer
        )
        image = qrcode.make(uri)
        buffer = io.BytesIO()
        image.save(buffer)
        return {
            "secret": secret,
            "otpauth_uri": uri,
            "qr_png_base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
        }

    async def enable_totp(self, *, staff: Staff, totp_code: str) -> None:
        secret = self._decrypt_totp_secret(staff)
        if not self._verify_totp_secret(secret, totp_code):
            raise AuthError(
                "INVALID_CREDENTIALS", "Invalid verification code.", status_code=401
            )
        staff.mfa_enabled = True
        await self._revoke_admin_sessions(staff.id)
        self.session.add(
            AuditLog(
                event_type="mfa_enabled",
                actor_id=staff.id,
                business_id=staff.business_id,
                details={},
            )
        )
        await self.session.commit()

    async def disable_totp(
        self, *, staff: Staff, password: str, totp_code: str
    ) -> None:
        if staff.role == StaffRole.PLATFORM_ADMIN:
            raise AuthError(
                "MFA_REQUIRED",
                "Platform administrators cannot disable multi-factor authentication.",
                status_code=403,
            )
        if (
            not self.hasher.verify_password_dummy_if_missing(
                password, staff.password_hash
            )
            or not staff.mfa_enabled
            or not self._verify_totp(staff.mfa_secret, totp_code)
        ):
            raise AuthError(
                "INVALID_CREDENTIALS",
                "Invalid password or verification code.",
                status_code=401,
            )
        staff.mfa_enabled = False
        staff.mfa_secret = None
        await self._revoke_admin_sessions(staff.id)
        self.session.add(
            AuditLog(
                event_type="mfa_disabled",
                actor_id=staff.id,
                business_id=staff.business_id,
                details={},
            )
        )
        await self.session.commit()

    async def change_password(
        self,
        *,
        staff: Staff,
        current_password: str,
        new_password: str,
    ) -> None:
        if not self.hasher.verify_password_dummy_if_missing(
            current_password, staff.password_hash
        ):
            raise AuthError(
                "INVALID_CREDENTIALS", "Current password is incorrect.", status_code=401
            )
        try:
            validate_password(new_password, phone_e164=staff.phone)
        except WeakPasswordError as exc:
            raise AuthError(
                "WEAK_PASSWORD", exc.message, status_code=422, details=exc.details
            ) from exc
        staff.password_hash = self.hasher.hash_password(new_password)
        staff.password_changed_at = self._now()
        staff.must_change_password = False
        await self._revoke_admin_sessions(staff.id)
        self.session.add(
            AuditLog(
                event_type="password_change",
                actor_id=staff.id,
                business_id=staff.business_id,
                details={},
            )
        )
        await self.session.commit()

    async def password_reset_start(
        self,
        *,
        phone_value: str,
        ip: str,
        user_agent: str | None,
        accept_language: str | None,
    ) -> dict[str, Any]:
        phone = self._normalize_phone(phone_value)
        await self._check_reset_rate_limits(phone=phone, ip=ip)
        owner_exists = bool(
            await self.session.scalar(
                select(Staff.id).where(
                    Staff.role == StaffRole.OWNER, Staff.phone == phone
                )
            )
        )
        otp = generate_otp()
        now = self._now()
        challenge = OtpChallenge(
            purpose=OtpPurpose.PASSWORD_RESET,
            phone=phone,
            code_hash=hash_otp(otp, self.settings.otp_pepper),
            attempts=0,
            max_attempts=self.settings.otp_max_attempts,
            resend_count=0,
            expires_at=now + timedelta(seconds=self.settings.otp_ttl_seconds),
            last_sent_at=now,
            ip=ip,
        )
        self.session.add(challenge)
        await self.session.flush()
        challenge_id = str(challenge.id)
        await self.session.commit()
        if owner_exists:
            language = preferred_language(accept_language)
            message = (
                f"Nambari yako ya kuweka upya nenosiri la DaZu ni {otp}. Itaisha baada ya dakika 5."
                if language == "sw"
                else f"Your DaZu password reset code is {otp}. It expires in 5 minutes."
            )
            try:
                await self.sms_provider.send(phone, message)
            except SmsDeliveryError as exc:
                await self.session.delete(challenge)
                await self.session.commit()
                raise AuthError(
                    "SERVICE_UNAVAILABLE",
                    "Unable to send a verification message right now.",
                    status_code=503,
                ) from exc
            self.session.add(
                AuditLog(
                    event_type="otp_sent",
                    ip=ip,
                    user_agent=user_agent,
                    details={"purpose": "password_reset"},
                )
            )
            await self.session.commit()
        return {
            "message": "If the number is registered, a verification code has been sent.",
            "challenge_id": challenge_id,
            "resend_after_seconds": self.settings.otp_resend_cooldown_seconds,
        }

    async def password_reset_verify(
        self, *, challenge_id: uuid.UUID, otp: str, ip: str
    ) -> dict[str, Any]:
        now = self._now()
        challenge = await self.session.scalar(
            select(OtpChallenge)
            .where(OtpChallenge.id == challenge_id)
            .with_for_update()
        )
        if challenge is None or challenge.purpose != OtpPurpose.PASSWORD_RESET:
            raise AuthError("OTP_INVALID", "This verification request is invalid.")
        if challenge.consumed_at is not None or challenge.verified_at is not None:
            code = (
                "OTP_TOO_MANY_ATTEMPTS"
                if challenge.attempts >= challenge.max_attempts
                else "OTP_INVALID"
            )
            raise AuthError(
                code,
                "This verification request is no longer active.",
                status_code=429 if code == "OTP_TOO_MANY_ATTEMPTS" else 400,
            )
        if _as_utc(challenge.expires_at) <= now:
            challenge.consumed_at = now
            await self.session.commit()
            raise AuthError("OTP_EXPIRED", "This verification code has expired.")
        if not verify_otp(otp, challenge.code_hash, self.settings.otp_pepper):
            challenge.attempts += 1
            self.session.add(
                AuditLog(
                    event_type="otp_failed",
                    ip=ip,
                    details={
                        "purpose": "password_reset",
                        "attempt": challenge.attempts,
                    },
                )
            )
            if challenge.attempts >= challenge.max_attempts:
                challenge.consumed_at = now
                await self.session.commit()
                raise AuthError(
                    "OTP_TOO_MANY_ATTEMPTS",
                    "Too many incorrect verification codes. Start again.",
                    status_code=429,
                )
            await self.session.commit()
            raise AuthError("OTP_INVALID", "The verification code is incorrect.")

        owner = await self.session.scalar(
            select(Staff.id).where(
                Staff.role == StaffRole.OWNER, Staff.phone == challenge.phone
            )
        )
        if owner is None:
            challenge.consumed_at = now
            await self.session.commit()
            raise AuthError("OTP_INVALID", "This verification request is invalid.")
        challenge.verified_at = now
        challenge.consumed_at = now
        jti = str(uuid.uuid4())
        self.session.add(
            AuditLog(
                event_type="otp_verified", ip=ip, details={"purpose": "password_reset"}
            )
        )
        await self.session.commit()
        reset_token = self.jwt_service.encode(
            subject=challenge.phone,
            audience="reset",
            ttl=timedelta(minutes=self.settings.reset_token_minutes),
            extra={
                "purpose": OtpPurpose.PASSWORD_RESET.value,
                "phone": challenge.phone,
            },
            jti=jti,
        )
        return {
            "reset_token": reset_token,
            "token_type": "bearer",
            "expires_in": self.settings.reset_token_minutes * 60,
        }

    async def password_reset_complete(
        self, *, reset_token: str, new_password: str, ip: str, user_agent: str | None
    ) -> None:
        try:
            claims = self.jwt_service.decode(reset_token, audience="reset")
        except JwtError as exc:
            raise AuthError(
                "INVALID_CREDENTIALS",
                "Invalid password reset authorization.",
                status_code=401,
            ) from exc
        if claims.get("purpose") != OtpPurpose.PASSWORD_RESET.value or claims.get(
            "phone"
        ) != claims.get("sub"):
            raise AuthError(
                "INVALID_CREDENTIALS",
                "Invalid password reset authorization.",
                status_code=401,
            )

        async with self.session.begin():
            dialect_name = (
                self.session.bind.dialect.name
                if self.session.bind is not None
                else "postgresql"
            )
            insert = sqlite_insert if dialect_name == "sqlite" else pg_insert
            consumed = await self.session.execute(
                insert(ConsumedToken)
                .values(
                    jti=claims["jti"],
                    purpose=TokenPurpose.PASSWORD_RESET,
                    expires_at=datetime.fromtimestamp(int(claims["exp"]), UTC),
                )
                .on_conflict_do_nothing(index_elements=["jti"])
            )
            if not cast(CursorResult[Any], consumed).rowcount:
                raise AuthError(
                    "INVALID_CREDENTIALS",
                    "This password reset authorization was already used.",
                    status_code=401,
                )
            owner = await self.session.scalar(
                select(Staff)
                .where(Staff.role == StaffRole.OWNER, Staff.phone == claims["phone"])
                .with_for_update()
            )
            if owner is None:
                raise AuthError(
                    "INVALID_CREDENTIALS",
                    "Invalid password reset authorization.",
                    status_code=401,
                )
            try:
                validate_password(new_password, phone_e164=owner.phone)
            except WeakPasswordError as exc:
                raise AuthError(
                    "WEAK_PASSWORD", exc.message, status_code=422, details=exc.details
                ) from exc
            owner.password_hash = self.hasher.hash_password(new_password)
            owner.password_changed_at = self._now()
            owner.must_change_password = False
            await self.session.execute(
                update(RefreshToken)
                .where(
                    RefreshToken.subject_type.in_(
                        [SubjectType.ADMIN, SubjectType.STAFF]
                    ),
                    RefreshToken.subject_id == owner.id,
                    RefreshToken.revoked_at.is_(None),
                )
                .values(revoked_at=self._now())
            )
            self.session.add(
                AuditLog(
                    event_type="password_change",
                    actor_id=owner.id,
                    business_id=owner.business_id,
                    ip=ip,
                    user_agent=user_agent,
                    details={"method": "password_reset"},
                )
            )

    async def reset_own_pin(self, *, staff: Staff, password: str, new_pin: str) -> None:
        if staff.role != StaffRole.OWNER:
            raise AuthError(
                "INVALID_CREDENTIALS",
                "Only an owner can reset their PIN here.",
                status_code=403,
            )
        if not self.hasher.verify_password_dummy_if_missing(
            password, staff.password_hash
        ):
            raise AuthError("INVALID_CREDENTIALS", "Invalid password.", status_code=401)
        try:
            validate_pin(new_pin)
        except WeakPinError as exc:
            raise AuthError("WEAK_PIN", exc.message, status_code=422) from exc
        staff.pin_hash = self.hasher.hash_pin(new_pin)
        staff.must_change_pin = False
        await self.session.execute(
            update(OfflineUnlock)
            .where(
                OfflineUnlock.staff_id == staff.id, OfflineUnlock.revoked_at.is_(None)
            )
            .values(revoked_at=self._now())
        )
        await self.session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.subject_id == staff.id, RefreshToken.revoked_at.is_(None)
            )
            .values(revoked_at=self._now())
        )
        self.session.add(
            AuditLog(
                event_type="pin_change",
                actor_id=staff.id,
                business_id=staff.business_id,
                details={"method": "password_reset"},
            )
        )
        await self.session.commit()

    async def _issue_session(
        self,
        *,
        staff: Staff,
        ip: str,
        user_agent: str | None,
        now: datetime,
        mfa: bool,
        family_id: uuid.UUID | None = None,
    ) -> tuple[dict[str, Any], uuid.UUID]:
        access_ttl = timedelta(minutes=self.settings.admin_access_minutes)
        refresh_ttl = timedelta(days=self.settings.admin_refresh_days)
        access_token = self.jwt_service.encode(
            subject=str(staff.id),
            audience="admin",
            ttl=access_ttl,
            extra={
                "business_id": str(staff.business_id) if staff.business_id else None,
                "role": staff.role.value,
                "mfa": mfa,
            },
        )
        raw_refresh = generate_urlsafe_token()
        record = RefreshToken(
            family_id=family_id or uuid.uuid4(),
            subject_type=SubjectType.ADMIN,
            subject_id=staff.id,
            token_hash=hash_token(raw_refresh),
            device_id=None,
            expires_at=now + refresh_ttl,
            ip=ip,
            user_agent=user_agent,
            last_used_at=now,
        )
        self.session.add(record)
        await self.session.flush()
        return (
            {
                "mfa_required": False,
                "access_token": access_token,
                "refresh_token": raw_refresh,
                "token_type": "bearer",
                "expires_in": int(access_ttl.total_seconds()),
                "refresh_expires_in": int(refresh_ttl.total_seconds()),
                "cookie_mode": self.settings.admin_cookie_mode,
            },
            record.id,
        )

    async def _revoke_family_and_audit(
        self, token: RefreshToken, *, ip: str, user_agent: str | None
    ) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.family_id == token.family_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=self._now())
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

    async def _revoke_admin_sessions(self, staff_id: uuid.UUID) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.subject_type == SubjectType.ADMIN,
                RefreshToken.subject_id == staff_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=self._now())
        )

    async def _check_reset_rate_limits(self, *, phone: str, ip: str) -> None:
        checks = (
            (
                f"reset-phone:{hash_token(phone)}",
                self.settings.password_reset_phone_hourly_limit,
                3600,
            ),
            (f"reset-ip:{ip}", self.settings.password_reset_ip_hourly_limit, 3600),
            (
                f"reset-global:{self._now().date().isoformat()}",
                self.settings.password_reset_global_daily_limit,
                86400,
            ),
        )
        for key, limit, window in checks:
            result = await self.rate_limiter.hit(
                key, limit=limit, window_seconds=window
            )
            if not result.allowed:
                raise AuthError(
                    "RATE_LIMITED",
                    "Too many verification requests. Try again later.",
                    status_code=429,
                    details={"retry_after": result.retry_after_seconds},
                )

    def _normalize_identifier(self, value: str) -> str:
        stripped = value.strip()
        if "@" in stripped:
            return stripped.lower()
        try:
            return normalize_ke_phone(
                stripped, allowed_prefixes=self.settings.phone_prefix_list
            )
        except ValueError:
            return stripped.lower()

    def _normalize_phone(self, value: str) -> str:
        try:
            return normalize_ke_phone(
                value, allowed_prefixes=self.settings.phone_prefix_list
            )
        except ValueError as exc:
            raise AuthError("VALIDATION_ERROR", str(exc), status_code=422) from exc

    def _decrypt_totp_secret(self, staff: Staff) -> str:
        if self.secret_box is None or not staff.mfa_secret:
            raise AuthError(
                "INVALID_CREDENTIALS", "MFA setup is incomplete.", status_code=401
            )
        try:
            return self.secret_box.decrypt(staff.mfa_secret)
        except ValueError as exc:
            raise AuthError(
                "SERVICE_UNAVAILABLE",
                "Unable to access the MFA secret.",
                status_code=503,
            ) from exc

    def _verify_totp(self, encrypted_secret: str | None, code: str | None) -> bool:
        if not encrypted_secret or code is None or self.secret_box is None:
            return False
        try:
            secret = self.secret_box.decrypt(encrypted_secret)
        except ValueError as exc:
            raise AuthError(
                "SERVICE_UNAVAILABLE",
                "Unable to access the MFA secret.",
                status_code=503,
            ) from exc
        return self._verify_totp_secret(secret, code)

    def _verify_totp_secret(self, secret: str, code: str) -> bool:
        return pyotp.TOTP(secret).verify(code, valid_window=1)

    def _locked_error(self, retry_after: int) -> AuthError:
        return AuthError(
            "ACCOUNT_LOCKED",
            "This account is temporarily locked.",
            status_code=423,
            details={"retry_after": retry_after},
        )


def build_admin_auth_service(
    *,
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
    jwt_service: JwtService,
    hasher: SecretHasher,
    sms_provider: SmsProvider,
    secret_box: SecretBox | None,
    clock: Clock | None = None,
) -> AdminAuthService:
    return AdminAuthService(
        session=session,
        redis=redis,
        settings=settings,
        jwt_service=jwt_service,
        hasher=hasher,
        sms_provider=sms_provider,
        secret_box=secret_box,
        clock=clock,
    )
