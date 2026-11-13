from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.dependencies import get_admin_auth_service
from app.api.schemas.admin_auth import (
    AdminLoginRequest,
    AdminLoginResponse,
    AdminRefreshResponse,
    ChangePasswordRequest,
    PasswordResetCompleteRequest,
    PasswordResetStartRequest,
    PasswordResetStartResponse,
    PasswordResetVerifyRequest,
    PasswordResetVerifyResponse,
    ResetOwnPinRequest,
    TotpCodeRequest,
    TotpDisableRequest,
    TotpSetupResponse,
)
from app.api.schemas.staff_auth import LogoutRequest, RefreshRequest
from app.core.errors import AuthError
from app.models.staff import Staff
from app.services.admin_auth import AdminAuthService

router = APIRouter(prefix="/admin/auth", tags=["admin-auth"])
_bearer = HTTPBearer(auto_error=False)


def _request_ip(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


async def require_current_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    service: Annotated[AdminAuthService, Depends(get_admin_auth_service)],
) -> Staff:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthError(
            "INVALID_CREDENTIALS", "An admin access token is required.", status_code=401
        )
    return await service.authenticate_access_token(credentials.credentials)


@router.post("/login", response_model=AdminLoginResponse)
async def login(
    body: AdminLoginRequest,
    request: Request,
    service: Annotated[AdminAuthService, Depends(get_admin_auth_service)],
) -> dict:
    return await service.login(
        identifier=body.identifier,
        password=body.password,
        totp_code=body.totp_code,
        ip=_request_ip(request),
        user_agent=_user_agent(request),
    )


@router.post("/refresh", response_model=AdminRefreshResponse)
async def refresh(
    body: RefreshRequest,
    request: Request,
    service: Annotated[AdminAuthService, Depends(get_admin_auth_service)],
) -> dict:
    return await service.refresh(
        raw_refresh_token=body.refresh_token,
        ip=_request_ip(request),
        user_agent=_user_agent(request),
    )


@router.post("/logout", status_code=204)
async def logout(
    body: LogoutRequest,
    staff: Annotated[Staff, Depends(require_current_admin)],
    service: Annotated[AdminAuthService, Depends(get_admin_auth_service)],
) -> None:
    await service.logout(raw_refresh_token=body.refresh_token, staff_id=staff.id)


@router.post("/logout-all")
async def logout_all(
    request: Request,
    staff: Annotated[Staff, Depends(require_current_admin)],
    service: Annotated[AdminAuthService, Depends(get_admin_auth_service)],
) -> dict[str, int]:
    count = await service.logout_all(
        staff_id=staff.id,
        ip=_request_ip(request),
        user_agent=_user_agent(request),
    )
    return {"revoked_sessions": count}


@router.post("/2fa/setup", response_model=TotpSetupResponse)
async def setup_totp(
    staff: Annotated[Staff, Depends(require_current_admin)],
    service: Annotated[AdminAuthService, Depends(get_admin_auth_service)],
) -> dict[str, str]:
    return await service.setup_totp(staff=staff)


@router.post("/2fa/enable", status_code=204)
async def enable_totp(
    body: TotpCodeRequest,
    staff: Annotated[Staff, Depends(require_current_admin)],
    service: Annotated[AdminAuthService, Depends(get_admin_auth_service)],
) -> None:
    await service.enable_totp(staff=staff, totp_code=body.totp_code)


@router.post("/2fa/disable", status_code=204)
async def disable_totp(
    body: TotpDisableRequest,
    staff: Annotated[Staff, Depends(require_current_admin)],
    service: Annotated[AdminAuthService, Depends(get_admin_auth_service)],
) -> None:
    await service.disable_totp(
        staff=staff, password=body.password, totp_code=body.totp_code
    )


@router.post("/change-password", status_code=204)
async def change_password(
    body: ChangePasswordRequest,
    staff: Annotated[Staff, Depends(require_current_admin)],
    service: Annotated[AdminAuthService, Depends(get_admin_auth_service)],
) -> None:
    await service.change_password(
        staff=staff,
        current_password=body.current_password,
        new_password=body.new_password,
    )


@router.post("/password-reset/start", response_model=PasswordResetStartResponse)
async def password_reset_start(
    body: PasswordResetStartRequest,
    request: Request,
    service: Annotated[AdminAuthService, Depends(get_admin_auth_service)],
) -> dict:
    return await service.password_reset_start(
        phone_value=body.phone,
        ip=_request_ip(request),
        user_agent=_user_agent(request),
        accept_language=request.headers.get("accept-language"),
    )


@router.post("/password-reset/verify-otp", response_model=PasswordResetVerifyResponse)
async def password_reset_verify(
    body: PasswordResetVerifyRequest,
    request: Request,
    service: Annotated[AdminAuthService, Depends(get_admin_auth_service)],
) -> dict:
    return await service.password_reset_verify(
        challenge_id=body.challenge_id,
        otp=body.otp,
        ip=_request_ip(request),
    )


@router.post("/password-reset/complete", status_code=204)
async def password_reset_complete(
    body: PasswordResetCompleteRequest,
    request: Request,
    service: Annotated[AdminAuthService, Depends(get_admin_auth_service)],
) -> None:
    await service.password_reset_complete(
        reset_token=body.reset_token,
        new_password=body.new_password,
        ip=_request_ip(request),
        user_agent=_user_agent(request),
    )


@router.post("/reset-own-pin", status_code=204)
async def reset_own_pin(
    body: ResetOwnPinRequest,
    staff: Annotated[Staff, Depends(require_current_admin)],
    service: Annotated[AdminAuthService, Depends(get_admin_auth_service)],
) -> None:
    await service.reset_own_pin(
        staff=staff, password=body.password, new_pin=body.new_pin
    )
