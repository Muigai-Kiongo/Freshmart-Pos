from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AdminLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identifier: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=1024)
    totp_code: str | None = Field(default=None, pattern=r"^\d{6}$")


class AdminLoginResponse(BaseModel):
    mfa_required: bool = False
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str | None = None
    expires_in: int | None = None
    refresh_expires_in: int | None = None
    cookie_mode: bool = False


class AdminRefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_expires_in: int
    cookie_mode: bool = False


class TotpCodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    totp_code: str = Field(pattern=r"^\d{6}$")


class TotpDisableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=1024)
    totp_code: str = Field(pattern=r"^\d{6}$")


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


class PasswordResetStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=1, max_length=32)


class PasswordResetStartResponse(BaseModel):
    message: str
    challenge_id: UUID
    resend_after_seconds: int


class PasswordResetVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: UUID
    otp: str = Field(pattern=r"^\d{6}$")


class PasswordResetVerifyResponse(BaseModel):
    reset_token: str
    token_type: str = "bearer"
    expires_in: int


class PasswordResetCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reset_token: str = Field(min_length=1, max_length=4096)
    new_password: str = Field(min_length=1, max_length=1024)


class ResetOwnPinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=1024)
    new_pin: str = Field(pattern=r"^\d{4,6}$")


class TotpSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str
    qr_png_base64: str
