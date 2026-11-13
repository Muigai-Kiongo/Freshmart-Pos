from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.dependencies import get_staff_auth_service
from app.api.schemas.staff_auth import (
    ChangePinRequest,
    LogoutRequest,
    OfflineSessionsSyncRequest,
    OfflineSessionsSyncResponse,
    OfflineUnlockRequest,
    OfflineUnlockResponse,
    PinLoginRequest,
    RefreshRequest,
    RefreshResponse,
    SessionItem,
    StaffListItem,
    StaffMeResponse,
    StaffSessionResponse,
)
from app.core.errors import AuthError
from app.models.staff import Staff
from app.services.staff_auth import StaffAuthService

router = APIRouter(prefix="/auth", tags=["staff-auth"])
_bearer = HTTPBearer(auto_error=False)


def _request_ip(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


async def require_current_staff(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    service: Annotated[StaffAuthService, Depends(get_staff_auth_service)],
    device_token: Annotated[str | None, Header(alias="X-Device-Token")] = None,
) -> Staff:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthError(
            "INVALID_CREDENTIALS", "A staff access token is required.", status_code=401
        )
    staff, _ = await service.authenticate_access_token(
        token=credentials.credentials,
        device_token=device_token,
    )
    return staff


@router.get("/staff-list", response_model=list[StaffListItem])
async def staff_list(
    service: Annotated[StaffAuthService, Depends(get_staff_auth_service)],
    outlet_id: Annotated[UUID, Query()],
    device_token: Annotated[str | None, Header(alias="X-Device-Token")] = None,
) -> list[dict]:
    return await service.staff_list(outlet_id=outlet_id, device_token=device_token)


@router.post("/pin-login", response_model=StaffSessionResponse)
async def pin_login(
    body: PinLoginRequest,
    request: Request,
    service: Annotated[StaffAuthService, Depends(get_staff_auth_service)],
    device_token: Annotated[str | None, Header(alias="X-Device-Token")] = None,
) -> dict:
    return await service.pin_login(
        staff_id=body.staff_id,
        pin=body.pin,
        device_token=device_token,
        ip=_request_ip(request),
        user_agent=_user_agent(request),
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    body: RefreshRequest,
    request: Request,
    service: Annotated[StaffAuthService, Depends(get_staff_auth_service)],
    device_token: Annotated[str | None, Header(alias="X-Device-Token")] = None,
) -> dict:
    return await service.refresh(
        raw_refresh_token=body.refresh_token,
        device_token=device_token,
        ip=_request_ip(request),
        user_agent=_user_agent(request),
    )


@router.post("/logout", status_code=204)
async def logout(
    body: LogoutRequest,
    staff: Annotated[Staff, Depends(require_current_staff)],
    service: Annotated[StaffAuthService, Depends(get_staff_auth_service)],
) -> None:
    await service.logout(raw_refresh_token=body.refresh_token, staff_id=staff.id)


@router.post("/logout-all")
async def logout_all(
    request: Request,
    staff: Annotated[Staff, Depends(require_current_staff)],
    service: Annotated[StaffAuthService, Depends(get_staff_auth_service)],
) -> dict[str, int]:
    count = await service.logout_all(
        staff_id=staff.id,
        ip=_request_ip(request),
        user_agent=_user_agent(request),
    )
    return {"revoked_sessions": count}


@router.get("/sessions", response_model=list[SessionItem])
async def sessions(
    staff: Annotated[Staff, Depends(require_current_staff)],
    service: Annotated[StaffAuthService, Depends(get_staff_auth_service)],
) -> list[dict]:
    return await service.sessions(staff_id=staff.id)


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(
    session_id: UUID,
    staff: Annotated[Staff, Depends(require_current_staff)],
    service: Annotated[StaffAuthService, Depends(get_staff_auth_service)],
) -> None:
    await service.revoke_session(staff_id=staff.id, session_id=session_id)


@router.get("/me", response_model=StaffMeResponse)
async def me(
    staff: Annotated[Staff, Depends(require_current_staff)],
    service: Annotated[StaffAuthService, Depends(get_staff_auth_service)],
) -> dict:
    return await service.me(staff=staff)


@router.post("/change-pin", status_code=204)
async def change_pin(
    body: ChangePinRequest,
    staff: Annotated[Staff, Depends(require_current_staff)],
    service: Annotated[StaffAuthService, Depends(get_staff_auth_service)],
) -> None:
    await service.change_pin(
        staff=staff, current_pin=body.current_pin, new_pin=body.new_pin
    )


@router.post("/offline-unlock/issue", response_model=OfflineUnlockResponse)
async def issue_offline_unlock(
    body: OfflineUnlockRequest,
    staff: Annotated[Staff, Depends(require_current_staff)],
    service: Annotated[StaffAuthService, Depends(get_staff_auth_service)],
    device_token: Annotated[str | None, Header(alias="X-Device-Token")] = None,
) -> dict:
    return await service.issue_offline_unlock(
        staff=staff,
        pin=body.pin,
        device_token=device_token,
    )


@router.post("/offline-unlock/revoke")
async def revoke_offline_unlock(
    staff: Annotated[Staff, Depends(require_current_staff)],
    service: Annotated[StaffAuthService, Depends(get_staff_auth_service)],
    device_token: Annotated[str | None, Header(alias="X-Device-Token")] = None,
) -> dict[str, int]:
    count = await service.revoke_offline_unlock(staff=staff, device_token=device_token)
    return {"revoked_unlocks": count}


@router.post("/offline-sessions/sync", response_model=OfflineSessionsSyncResponse)
async def sync_offline_sessions(
    body: OfflineSessionsSyncRequest,
    staff: Annotated[Staff, Depends(require_current_staff)],
    service: Annotated[StaffAuthService, Depends(get_staff_auth_service)],
    device_token: Annotated[str | None, Header(alias="X-Device-Token")] = None,
) -> dict[str, int]:
    count = await service.sync_offline_sessions(
        staff=staff,
        device_token=device_token,
        sessions=body.sessions,
    )
    return {"recorded_sessions": count}
