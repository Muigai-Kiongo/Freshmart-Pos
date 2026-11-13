from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from app.api.dependencies import get_signup_service
from app.api.schemas.signup import (
    OtpChallengeRequest,
    OtpResendRequest,
    OtpResendResponse,
    SignupCompleteRequest,
    SignupCompleteResponse,
    SignupStartRequest,
    SignupStartResponse,
    SignupVerifyResponse,
)
from app.core.errors import AuthError
from app.services.signup import SignupService

router = APIRouter(prefix="/auth", tags=["signup"])


def _request_ip(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


@router.post("/signup/start", response_model=SignupStartResponse)
async def signup_start(
    body: SignupStartRequest,
    request: Request,
    service: Annotated[SignupService, Depends(get_signup_service)],
) -> dict:
    return await service.start(
        body,
        ip=_request_ip(request),
        user_agent=_user_agent(request),
        accept_language=request.headers.get("accept-language"),
    )


@router.post("/signup/verify-otp", response_model=SignupVerifyResponse)
async def signup_verify_otp(
    body: OtpChallengeRequest,
    request: Request,
    service: Annotated[SignupService, Depends(get_signup_service)],
) -> dict:
    return await service.verify_otp(
        body.challenge_id, body.otp, ip=_request_ip(request)
    )


@router.post("/otp/resend", response_model=OtpResendResponse)
async def signup_resend_otp(
    body: OtpResendRequest,
    request: Request,
    service: Annotated[SignupService, Depends(get_signup_service)],
) -> dict:
    return await service.resend(
        body.challenge_id,
        ip=_request_ip(request),
        user_agent=_user_agent(request),
        accept_language=request.headers.get("accept-language"),
    )


@router.post("/signup/complete", response_model=SignupCompleteResponse, status_code=201)
async def signup_complete(
    body: SignupCompleteRequest,
    request: Request,
    service: Annotated[SignupService, Depends(get_signup_service)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ],
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    if authorization is None:
        raise AuthError(
            "INVALID_CREDENTIALS", "Signup authorization is required.", status_code=401
        )
    scheme, separator, signup_token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not signup_token.strip():
        raise AuthError(
            "INVALID_CREDENTIALS", "Invalid signup authorization.", status_code=401
        )
    return await service.complete(
        body,
        signup_token=signup_token.strip(),
        idempotency_key=idempotency_key,
        ip=_request_ip(request),
        user_agent=_user_agent(request),
    )
