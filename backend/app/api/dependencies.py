from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.crypto import SecretBox
from app.core.errors import AuthError
from app.core.hashing import Argon2Params, SecretHasher, hash_token
from app.core.jwt import JwtService, jwt_service_from_settings
from app.db.redis import get_redis_client
from app.db.session import get_db
from app.integrations.sms import SmsProvider, create_sms_provider
from app.models.device import Device
from app.models.enums import DeviceStatus, StaffRole
from app.models.staff import Staff
from app.services.admin_auth import AdminAuthService, build_admin_auth_service
from app.services.signup import SignupService, build_signup_service
from app.services.staff_auth import StaffAuthService, build_staff_auth_service

_bearer = HTTPBearer(auto_error=False)


def get_redis() -> Redis:
    return get_redis_client()


def get_jwt_service(settings: Annotated[Settings, Depends(get_settings)]) -> JwtService:
    return jwt_service_from_settings(settings)


def get_secret_hasher(
    settings: Annotated[Settings, Depends(get_settings)],
) -> SecretHasher:
    return _secret_hasher(
        settings.argon2_time_cost,
        settings.argon2_memory_kib,
        settings.argon2_parallelism,
        settings.pin_pepper,
    )


@lru_cache(maxsize=8)
def _secret_hasher(
    time_cost: int, memory_cost: int, parallelism: int, pin_pepper: str
) -> SecretHasher:
    return SecretHasher(
        Argon2Params(
            time_cost=time_cost, memory_cost=memory_cost, parallelism=parallelism
        ),
        pin_pepper=pin_pepper,
    )


def get_sms_provider(
    settings: Annotated[Settings, Depends(get_settings)],
) -> SmsProvider:
    return create_sms_provider(settings)


async def get_current_staff(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    service: Annotated[StaffAuthService, Depends(get_staff_auth_service)],
    device_token: Annotated[str | None, Header(alias="X-Device-Token")] = None,
) -> Staff:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthError(
            "INVALID_CREDENTIALS", "A staff access token is required.", status_code=401
        )
    staff, _ = await service.authenticate_access_token(
        token=credentials.credentials, device_token=device_token
    )
    return staff


async def get_current_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    service: Annotated[AdminAuthService, Depends(get_admin_auth_service)],
) -> Staff:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthError(
            "INVALID_CREDENTIALS", "An admin access token is required.", status_code=401
        )
    return await service.authenticate_access_token(credentials.credentials)


def require_role(*roles: StaffRole | str):
    allowed = {role.value if isinstance(role, StaffRole) else role for role in roles}

    async def dependency(staff: Annotated[Staff, Depends(get_current_staff)]) -> Staff:
        if staff.role.value not in allowed:
            raise AuthError(
                "INVALID_CREDENTIALS",
                "This action requires a different role.",
                status_code=403,
            )
        return staff

    return dependency


async def require_active_business(
    staff: Annotated[Staff, Depends(get_current_staff)],
) -> Staff:
    if staff.business_id is None:
        raise AuthError(
            "INVALID_CREDENTIALS",
            "This staff member is not attached to a business.",
            status_code=401,
        )
    return staff


async def require_device(
    redis: Annotated[Redis, Depends(get_redis)],
    session: Annotated[AsyncSession, Depends(get_db)],
    device_token: Annotated[str | None, Header(alias="X-Device-Token")] = None,
) -> Device:
    if not device_token:
        raise AuthError(
            "DEVICE_NOT_REGISTERED", "A registered device is required.", status_code=401
        )

    cache_key = f"device-status:{hash_token(device_token)}"
    cached = await redis.get(cache_key)
    if cached is not None:
        cached_value = cached.decode("utf-8") if isinstance(cached, bytes) else cached
        if cached_value == "revoked":
            raise AuthError(
                "DEVICE_REVOKED", "This device has been revoked.", status_code=401
            )
        if cached_value == "active":
            device = await session.scalar(
                select(Device).where(
                    Device.device_token_hash == hash_token(device_token)
                )
            )
            if device is not None:
                return device

    device = await session.scalar(
        select(Device).where(Device.device_token_hash == hash_token(device_token))
    )
    if device is None:
        await redis.setex(cache_key, 60, "missing")
        raise AuthError(
            "DEVICE_NOT_REGISTERED", "This device is not registered.", status_code=401
        )
    if device.status != DeviceStatus.ACTIVE:
        await redis.setex(cache_key, 60, "revoked")
        raise AuthError(
            "DEVICE_REVOKED", "This device has been revoked.", status_code=401
        )
    await redis.setex(cache_key, 60, "active")
    return device


def get_signup_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
    jwt_service: Annotated[JwtService, Depends(get_jwt_service)],
    hasher: Annotated[SecretHasher, Depends(get_secret_hasher)],
    sms_provider: Annotated[SmsProvider, Depends(get_sms_provider)],
) -> SignupService:
    return build_signup_service(
        session=session,
        redis=redis,
        settings=settings,
        jwt_service=jwt_service,
        hasher=hasher,
        sms_provider=sms_provider,
    )


def get_staff_auth_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
    jwt_service: Annotated[JwtService, Depends(get_jwt_service)],
    hasher: Annotated[SecretHasher, Depends(get_secret_hasher)],
) -> StaffAuthService:
    return build_staff_auth_service(
        session=session,
        redis=redis,
        settings=settings,
        jwt_service=jwt_service,
        hasher=hasher,
    )


def get_admin_auth_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
    jwt_service: Annotated[JwtService, Depends(get_jwt_service)],
    hasher: Annotated[SecretHasher, Depends(get_secret_hasher)],
    sms_provider: Annotated[SmsProvider, Depends(get_sms_provider)],
) -> AdminAuthService:
    secret_box = (
        SecretBox(settings.mfa_encryption_key) if settings.mfa_encryption_key else None
    )
    return build_admin_auth_service(
        session=session,
        redis=redis,
        settings=settings,
        jwt_service=jwt_service,
        hasher=hasher,
        sms_provider=sms_provider,
        secret_box=secret_box,
    )
