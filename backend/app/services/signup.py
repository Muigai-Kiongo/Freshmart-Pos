from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt as pyjwt
from cryptography.fernet import Fernet, InvalidToken
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.signup import Language, SignupCompleteRequest, SignupStartRequest
from app.core.clock import Clock, SystemClock
from app.core.config import Settings
from app.core.errors import AuthError
from app.core.hashing import (
    SecretHasher,
    generate_device_token,
    generate_urlsafe_token,
    hash_token,
)
from app.core.i18n import preferred_language
from app.core.jwt import JwtError, JwtService
from app.core.otp import generate_otp, hash_otp, verify_otp
from app.core.password import validate_password
from app.core.phone import normalize_ke_phone
from app.core.pin import validate_pin
from app.core.rate_limit import SlidingWindowRateLimiter
from app.integrations.sms import SmsDeliveryError, SmsProvider
from app.models.audit_log import AuditLog
from app.models.business import Business, BusinessSettings, ProductCategory
from app.models.consumed_token import ConsumedToken
from app.models.device import Device
from app.models.enums import (
    BusinessStatus,
    OtpPurpose,
    SignupSource,
    StaffRole,
    SubjectType,
    TokenPurpose,
)
from app.models.idempotency import IdempotencyKey
from app.models.otp_challenge import OtpChallenge
from app.models.outlet import Outlet
from app.models.refresh_token import RefreshToken
from app.models.staff import Staff

DEFAULT_CATEGORIES = ("General", "Produce", "Drinks", "Household")
SIGNUP_ENDPOINT = "auth.signup.complete"
IDEMPOTENCY_TTL = timedelta(hours=24)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _preferred_language(header: str | None, body: Language | None) -> Language:
    if body is not None:
        return body
    return Language(preferred_language(header))


def _signup_sms(language: Language, *, code: str | None = None) -> str:
    if code is None:
        return (
            "Nambari hii tayari imesajiliwa kwenye Freshmart POS. Ingia kwenye akaunti yako au wasiliana na usaidizi."
            if language is Language.SW
            else "This number is already registered with Freshmart POS. Log in to your account or contact support."
        )
    return (
        f"Nambari yako ya uthibitisho wa Freshmart POS ni {code}. Itaisha baada ya dakika 5."
        if language is Language.SW
        else f"Your Freshmart POS verification code is {code}. It expires in 5 minutes."
    )


def _idempotency_digest(body: SignupCompleteRequest, secret: str) -> str:
    serialized = json.dumps(
        body.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    return hmac.new(
        secret.encode("utf-8"), serialized.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _idempotency_box(secret: str) -> Fernet:
    key = hmac.new(
        secret.encode("utf-8"), b"dazu-pos/signup-idempotency/v1", hashlib.sha256
    ).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _encrypt_response(response: dict[str, Any], secret: str) -> dict[str, str]:
    serialized = json.dumps(response, sort_keys=True, separators=(",", ":"))
    return {
        "encrypted": _idempotency_box(secret)
        .encrypt(serialized.encode("utf-8"))
        .decode("ascii")
    }


def _decrypt_response(response: dict[str, Any] | None, secret: str) -> dict[str, Any]:
    try:
        if not response or set(response) != {"encrypted"}:
            raise InvalidToken
        plaintext = _idempotency_box(secret).decrypt(
            response["encrypted"].encode("ascii")
        )
        result = json.loads(plaintext)
    except (
        InvalidToken,
        KeyError,
        TypeError,
        UnicodeError,
        json.JSONDecodeError,
    ) as exc:
        raise AuthError(
            "SERVICE_UNAVAILABLE",
            "Unable to replay the prior signup response.",
            status_code=503,
        ) from exc
    if not isinstance(result, dict):
        raise AuthError(
            "SERVICE_UNAVAILABLE",
            "Unable to replay the prior signup response.",
            status_code=503,
        )
    return result


class SignupService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        redis: Redis,
        settings: Settings,
        jwt_service: JwtService,
        hasher: SecretHasher,
        sms_provider: SmsProvider,
        clock: Clock | None = None,
    ) -> None:
        self.session = session
        self.redis = redis
        self.settings = settings
        self.jwt_service = jwt_service
        self.hasher = hasher
        self.sms_provider = sms_provider
        self.clock = clock or SystemClock()
        self.limiter = SlidingWindowRateLimiter(redis, self.clock, prefix="auth:signup")

    def _now(self) -> datetime:
        now = self.clock.now()
        return _as_utc(now)

    def _otp(self) -> str:
        return (
            self.settings.dev_otp_code
            if not self.settings.is_production
            else generate_otp()
        )

    async def _check_rate_limits(self, phone: str, ip: str) -> int:
        phone_key = hashlib.sha256(phone.encode("utf-8")).hexdigest()
        ip_key = hashlib.sha256(ip.encode("utf-8")).hexdigest()
        checks = (
            (f"phone:{phone_key}", self.settings.otp_phone_hourly_limit, 3600),
            (f"ip:{ip_key}", self.settings.otp_ip_hourly_limit, 3600),
            ("global:daily", self.settings.otp_global_daily_limit, 86400),
        )
        retry_after = 0
        try:
            for key, limit, window in checks:
                result = await self.limiter.hit(key, limit=limit, window_seconds=window)
                if not result.allowed:
                    retry_after = max(retry_after, result.retry_after_seconds)
            ip_starts = await self.limiter.hit(
                f"captcha-ip:{ip_key}",
                limit=10000,
                window_seconds=3600,
            )
        except RedisError as exc:
            raise AuthError(
                "SERVICE_UNAVAILABLE",
                "Signup protection is temporarily unavailable.",
                status_code=503,
            ) from exc

        if retry_after:
            raise AuthError(
                "RATE_LIMITED",
                "Too many verification messages. Please try again later.",
                status_code=429,
                details={"retry_after_seconds": retry_after},
            )
        return ip_starts.count

    async def _verify_captcha(self, token: str, ip: str) -> None:
        secret = self.settings.turnstile_secret
        if not secret:
            raise AuthError(
                "VALIDATION_ERROR",
                "CAPTCHA verification is not configured.",
                status_code=503,
            )
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                    data={"secret": secret, "response": token, "remoteip": ip},
                )
                response.raise_for_status()
                result = response.json()
                if not isinstance(result, dict):
                    raise TypeError("CAPTCHA provider returned an invalid response")
                verified = result.get("success") is True
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            raise AuthError(
                "SERVICE_UNAVAILABLE",
                "CAPTCHA verification is temporarily unavailable.",
                status_code=503,
            ) from exc
        if not verified:
            raise AuthError(
                "VALIDATION_ERROR", "CAPTCHA verification failed.", status_code=400
            )

    async def _send_sms(self, phone: str, message: str) -> None:
        try:
            await self.sms_provider.send(phone, message)
        except SmsDeliveryError as exc:
            raise AuthError(
                "SERVICE_UNAVAILABLE",
                "Unable to send a verification message right now.",
                status_code=503,
            ) from exc

    async def start(
        self,
        request: SignupStartRequest,
        *,
        ip: str,
        user_agent: str | None,
        accept_language: str | None,
    ) -> dict[str, Any]:
        try:
            phone = normalize_ke_phone(
                request.phone, allowed_prefixes=self.settings.phone_prefix_list
            )
        except ValueError as exc:
            raise AuthError("VALIDATION_ERROR", str(exc), status_code=422) from exc

        starts = await self._check_rate_limits(phone, ip)
        if (
            self.settings.turnstile_secret
            and starts > self.settings.signup_captcha_threshold
        ):
            if not request.captcha_token:
                raise AuthError(
                    "VALIDATION_ERROR",
                    "CAPTCHA is required to continue.",
                    status_code=400,
                )
            await self._verify_captcha(request.captcha_token, ip)

        language = _preferred_language(accept_language, request.language)
        otp = self._otp()
        now = self._now()
        async with self.session.begin():
            existing_owner = await self.session.scalar(
                select(Staff.id).where(
                    Staff.role == StaffRole.OWNER, Staff.phone == phone
                )
            )
            challenge = OtpChallenge(
                purpose=OtpPurpose.SIGNUP,
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

        try:
            await self._send_sms(
                phone, _signup_sms(language, code=None if existing_owner else otp)
            )
        except AuthError:
            async with self.session.begin():
                failed_challenge = await self.session.get(
                    OtpChallenge, uuid.UUID(challenge_id)
                )
                if failed_challenge is not None:
                    await self.session.delete(failed_challenge)
            raise
        async with self.session.begin():
            self.session.add(
                AuditLog(
                    event_type="otp_sent",
                    ip=ip,
                    user_agent=user_agent,
                    details={"purpose": OtpPurpose.SIGNUP.value},
                )
            )
        return {
            "challenge_id": challenge_id,
            "resend_after_seconds": self.settings.otp_resend_cooldown_seconds,
        }

    async def resend(
        self,
        challenge_id: uuid.UUID,
        *,
        ip: str,
        user_agent: str | None,
        accept_language: str | None,
    ) -> dict[str, Any]:
        now = self._now()
        otp = self._otp()
        error: AuthError | None = None
        phone: str | None = None
        existing_owner = False
        async with self.session.begin():
            challenge = await self.session.scalar(
                select(OtpChallenge)
                .where(OtpChallenge.id == challenge_id)
                .with_for_update()
            )
            if challenge is None or challenge.purpose != OtpPurpose.SIGNUP:
                error = AuthError(
                    "OTP_INVALID", "This verification request is invalid."
                )
            elif challenge.consumed_at is not None or challenge.verified_at is not None:
                error = AuthError(
                    "OTP_INVALID", "This verification request is no longer active."
                )
            elif _as_utc(challenge.expires_at) <= now:
                challenge.consumed_at = now
                error = AuthError("OTP_EXPIRED", "This verification code has expired.")
            elif challenge.resend_count >= self.settings.otp_max_resends:
                error = AuthError(
                    "RATE_LIMITED",
                    "No more verification messages can be sent for this request.",
                    status_code=429,
                )
            else:
                last_sent_at = _as_utc(challenge.last_sent_at)
                cooldown_ends = last_sent_at + timedelta(
                    seconds=self.settings.otp_resend_cooldown_seconds
                )
                if now < cooldown_ends:
                    remaining = max(1, int((cooldown_ends - now).total_seconds()))
                    error = AuthError(
                        "RATE_LIMITED",
                        "Please wait before requesting another verification message.",
                        status_code=429,
                        details={"retry_after_seconds": remaining},
                    )
                else:
                    phone = challenge.phone
                    await self._check_rate_limits(phone, ip)
                    existing_owner = bool(
                        await self.session.scalar(
                            select(Staff.id).where(
                                Staff.role == StaffRole.OWNER, Staff.phone == phone
                            )
                        )
                    )
                    language = _preferred_language(accept_language, None)
                    await self._send_sms(
                        phone,
                        _signup_sms(language, code=None if existing_owner else otp),
                    )
                    challenge.code_hash = hash_otp(otp, self.settings.otp_pepper)
                    challenge.attempts = 0
                    challenge.resend_count += 1
                    challenge.last_sent_at = now
                    challenge.expires_at = now + timedelta(
                        seconds=self.settings.otp_ttl_seconds
                    )
                    challenge.ip = ip
                    self.session.add(
                        AuditLog(
                            event_type="otp_sent",
                            ip=ip,
                            user_agent=user_agent,
                            details={
                                "purpose": OtpPurpose.SIGNUP.value,
                                "resend": True,
                            },
                        )
                    )

        if error is not None:
            raise error
        if phone is None:
            raise AuthError(
                "SERVICE_UNAVAILABLE",
                "Unable to send a verification message right now.",
                status_code=503,
            )
        return {
            "challenge_id": str(challenge_id),
            "resend_after_seconds": self.settings.otp_resend_cooldown_seconds,
        }

    async def verify_otp(
        self, challenge_id: uuid.UUID, otp: str, *, ip: str
    ) -> dict[str, Any]:
        now = self._now()
        error: AuthError | None = None
        phone: str | None = None
        async with self.session.begin():
            challenge = await self.session.scalar(
                select(OtpChallenge)
                .where(OtpChallenge.id == challenge_id)
                .with_for_update()
            )
            if challenge is None or challenge.purpose != OtpPurpose.SIGNUP:
                error = AuthError(
                    "OTP_INVALID", "This verification request is invalid."
                )
            elif challenge.consumed_at is not None or challenge.verified_at is not None:
                code = (
                    "OTP_TOO_MANY_ATTEMPTS"
                    if challenge.attempts >= challenge.max_attempts
                    else "OTP_INVALID"
                )
                error = AuthError(
                    code,
                    "This verification request is no longer active.",
                    status_code=429 if code == "OTP_TOO_MANY_ATTEMPTS" else 400,
                )
            elif _as_utc(challenge.expires_at) <= now:
                challenge.consumed_at = now
                error = AuthError("OTP_EXPIRED", "This verification code has expired.")
            elif not verify_otp(otp, challenge.code_hash, self.settings.otp_pepper):
                challenge.attempts += 1
                self.session.add(
                    AuditLog(
                        event_type="otp_failed",
                        ip=ip,
                        details={
                            "purpose": OtpPurpose.SIGNUP.value,
                            "attempt": challenge.attempts,
                        },
                    )
                )
                if challenge.attempts >= challenge.max_attempts:
                    challenge.consumed_at = now
                    error = AuthError(
                        "OTP_TOO_MANY_ATTEMPTS",
                        "Too many incorrect verification codes. Start again.",
                        status_code=429,
                    )
                else:
                    error = AuthError(
                        "OTP_INVALID", "The verification code is incorrect."
                    )
            else:
                challenge.verified_at = now
                challenge.consumed_at = now
                phone = challenge.phone
                self.session.add(
                    AuditLog(
                        event_type="otp_verified",
                        ip=ip,
                        details={"purpose": OtpPurpose.SIGNUP.value},
                    )
                )

        if error is not None:
            raise error
        if phone is None:
            raise AuthError("OTP_INVALID", "This verification request is invalid.")
        token = self.jwt_service.encode(
            subject=phone,
            audience="signup",
            ttl=timedelta(minutes=self.settings.signup_token_minutes),
            extra={"purpose": OtpPurpose.SIGNUP.value, "phone": phone},
        )
        return {
            "signup_token": token,
            "token_type": "bearer",
            "expires_in": self.settings.signup_token_minutes * 60,
        }

    async def complete(
        self,
        body: SignupCompleteRequest,
        *,
        signup_token: str,
        idempotency_key: str,
        ip: str,
        user_agent: str | None,
    ) -> dict[str, Any]:
        try:
            claims = self.jwt_service.decode(signup_token, audience="signup")
        except JwtError as exc:
            raise AuthError(
                "INVALID_CREDENTIALS", "Invalid signup authorization.", status_code=401
            ) from exc
        if claims.get("purpose") != OtpPurpose.SIGNUP.value or claims.get(
            "phone"
        ) != claims.get("sub"):
            raise AuthError(
                "INVALID_CREDENTIALS", "Invalid signup authorization.", status_code=401
            )

        phone = claims["phone"]
        try:
            validate_password(body.password, phone_e164=phone)
            validate_pin(body.pin)
        except ValueError as exc:
            code = getattr(exc, "code", "VALIDATION_ERROR")
            status_code = (
                422
                if code in {"WEAK_PASSWORD", "WEAK_PIN", "VALIDATION_ERROR"}
                else 400
            )
            raise AuthError(
                code,
                str(exc),
                status_code=status_code,
                details=getattr(exc, "details", None),
            ) from exc
        if not body.accept_terms:
            raise AuthError(
                "VALIDATION_ERROR",
                "You must accept the terms to create an account.",
                status_code=422,
            )
        if not idempotency_key or len(idempotency_key) > 128:
            raise AuthError(
                "VALIDATION_ERROR",
                "A valid Idempotency-Key header is required.",
                status_code=422,
            )

        # The token's signing key also protects replay responses across key rotation.
        kid = pyjwt.get_unverified_header(signup_token).get("kid")
        signing_secret = self.jwt_service.signup_keys.secret_for_kid(kid)

        now = self._now()
        request_hash = _idempotency_digest(body, signing_secret)
        replay: dict[str, Any] | None = None
        try:
            async with self.session.begin():
                dialect_name = (
                    self.session.bind.dialect.name
                    if self.session.bind is not None
                    else "postgresql"
                )
                insert = sqlite_insert if dialect_name == "sqlite" else pg_insert
                await self.session.execute(
                    insert(IdempotencyKey)
                    .values(
                        id=uuid.uuid4(),
                        endpoint=SIGNUP_ENDPOINT,
                        key=idempotency_key,
                        request_hash=request_hash,
                        expires_at=now + IDEMPOTENCY_TTL,
                    )
                    .on_conflict_do_nothing(index_elements=["endpoint", "key"])
                )
                record = await self.session.scalar(
                    select(IdempotencyKey)
                    .where(
                        IdempotencyKey.endpoint == SIGNUP_ENDPOINT,
                        IdempotencyKey.key == idempotency_key,
                    )
                    .with_for_update()
                )
                if record is None:
                    raise AuthError(
                        "SERVICE_UNAVAILABLE",
                        "Unable to reserve this signup request.",
                        status_code=503,
                    )
                if (
                    _as_utc(record.expires_at) > now
                    and record.response_body is not None
                ):
                    if not hmac.compare_digest(record.request_hash, request_hash):
                        raise AuthError(
                            "VALIDATION_ERROR",
                            "This Idempotency-Key was already used for a different request.",
                            status_code=409,
                        )
                    replay = _decrypt_response(record.response_body, signing_secret)
                else:
                    consumed = await self.session.get(ConsumedToken, claims["jti"])
                    if consumed is not None and _as_utc(consumed.expires_at) > now:
                        raise AuthError(
                            "INVALID_CREDENTIALS",
                            "This signup authorization has already been used.",
                            status_code=401,
                        )

                    trial_ends_at = now + timedelta(days=self.settings.trial_days)
                    business = Business(
                        name=body.business_name,
                        county=body.county,
                        mode=body.mode,
                        status=BusinessStatus.TRIAL,
                        trial_ends_at=trial_ends_at,
                        signup_source=SignupSource.SELF,
                    )
                    self.session.add(business)
                    await self.session.flush()

                    outlet = Outlet(
                        business_id=business.id, name="Main", is_default=True
                    )
                    self.session.add(outlet)
                    await self.session.flush()

                    staff = Staff(
                        business_id=business.id,
                        outlet_id=outlet.id,
                        name=body.owner_name,
                        role=StaffRole.OWNER,
                        phone=phone,
                        phone_verified_at=now,
                        email=str(body.email).lower() if body.email else None,
                        password_hash=self.hasher.hash_password(body.password),
                        pin_hash=self.hasher.hash_pin(body.pin),
                        terms_accepted_at=now,
                        terms_version=body.terms_version,
                    )
                    self.session.add(staff)
                    await self.session.flush()

                    self.session.add(
                        BusinessSettings(
                            business_id=business.id,
                            vat_enabled=body.mode.value == "pro",
                            currency="KES",
                        )
                    )
                    for position, name in enumerate(DEFAULT_CATEGORIES):
                        self.session.add(
                            ProductCategory(
                                business_id=business.id,
                                name=name,
                                sort_order=position,
                                is_system_default=True,
                            )
                        )

                    device_token = None
                    access_token = None
                    refresh_token = None
                    refresh_expires_in = None
                    if body.device is not None:
                        device_token, device_token_hash = generate_device_token()
                        device = Device(
                            business_id=business.id,
                            outlet_id=outlet.id,
                            name=body.device.name,
                            platform=body.device.platform,
                            device_token_hash=device_token_hash,
                            fingerprint=body.device.fingerprint,
                            app_version=body.device.app_version,
                        )
                        self.session.add(device)
                        await self.session.flush()

                        access_token = self.jwt_service.encode(
                            subject=str(staff.id),
                            audience="staff",
                            ttl=timedelta(minutes=self.settings.staff_access_minutes),
                            extra={
                                "business_id": str(business.id),
                                "outlet_id": str(outlet.id),
                                "role": StaffRole.OWNER.value,
                                "device_id": str(device.id),
                            },
                        )
                        refresh_token = generate_urlsafe_token()
                        refresh_expires = now + timedelta(
                            days=self.settings.staff_refresh_days
                        )
                        refresh_expires_in = self.settings.staff_refresh_days * 86400
                        self.session.add(
                            RefreshToken(
                                family_id=uuid.uuid4(),
                                subject_type=SubjectType.STAFF,
                                subject_id=staff.id,
                                token_hash=hash_token(refresh_token),
                                device_id=device.id,
                                expires_at=refresh_expires,
                                ip=ip,
                                user_agent=user_agent,
                            )
                        )
                        self.session.add(
                            AuditLog(
                                event_type="device_registered",
                                actor_id=staff.id,
                                business_id=business.id,
                                ip=ip,
                                user_agent=user_agent,
                                details={"device_id": str(device.id)},
                            )
                        )

                    self.session.add(
                        ConsumedToken(
                            jti=claims["jti"],
                            purpose=TokenPurpose.SIGNUP,
                            expires_at=datetime.fromtimestamp(int(claims["exp"]), UTC),
                        )
                    )
                    self.session.add(
                        AuditLog(
                            event_type="signup",
                            actor_id=staff.id,
                            business_id=business.id,
                            ip=ip,
                            user_agent=user_agent,
                            details={"signup_source": SignupSource.SELF.value},
                        )
                    )

                    response: dict[str, Any] = {
                        "business": {
                            "id": str(business.id),
                            "name": business.name,
                            "mode": business.mode.value,
                            "status": business.status.value,
                            "trial_ends_at": trial_ends_at.isoformat(),
                        },
                        "outlet": {"id": str(outlet.id), "name": outlet.name},
                        "staff": {
                            "id": str(staff.id),
                            "name": staff.name,
                            "role": StaffRole.OWNER.value,
                        },
                        "device_token": device_token,
                        "access_token": access_token,
                        "refresh_token": refresh_token,
                        "token_type": "bearer" if access_token else None,
                        "expires_in": self.settings.staff_access_minutes * 60
                        if access_token
                        else None,
                        "refresh_expires_in": refresh_expires_in,
                    }
                    record.request_hash = request_hash
                    record.response_body = _encrypt_response(response, signing_secret)
                    record.status_code = 201
                    record.expires_at = now + IDEMPOTENCY_TTL
                    replay = response
        except IntegrityError as exc:
            raise AuthError(
                "INVALID_CREDENTIALS",
                "Unable to complete signup with the supplied credentials.",
                status_code=409,
            ) from exc

        if replay is None:
            raise AuthError(
                "SERVICE_UNAVAILABLE", "Unable to complete signup.", status_code=503
            )
        return replay


def build_signup_service(
    *,
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
    jwt_service: JwtService,
    hasher: SecretHasher,
    sms_provider: SmsProvider,
    clock: Clock | None = None,
) -> SignupService:
    return SignupService(
        session=session,
        redis=redis,
        settings=settings,
        jwt_service=jwt_service,
        hasher=hasher,
        sms_provider=sms_provider,
        clock=clock,
    )
