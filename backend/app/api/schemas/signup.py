from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import BusinessMode, BusinessStatus, DevicePlatform, StaffRole


class Language(StrEnum):
    EN = "en"
    SW = "sw"


class SignupStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=1, max_length=32)
    language: Language | None = None
    captcha_token: str | None = Field(default=None, max_length=4096)


class SignupStartResponse(BaseModel):
    challenge_id: UUID
    resend_after_seconds: int


class OtpChallengeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: UUID
    otp: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class OtpResendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: UUID


class OtpResendResponse(BaseModel):
    challenge_id: UUID
    resend_after_seconds: int


class SignupVerifyResponse(BaseModel):
    signup_token: str
    token_type: str = "bearer"
    expires_in: int


class SignupDeviceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    platform: DevicePlatform
    fingerprint: str | None = Field(default=None, max_length=255)
    app_version: str | None = Field(default=None, max_length=32)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Device name is required")
        return value


class SignupCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_name: str = Field(min_length=1, max_length=160)
    business_name: str = Field(min_length=1, max_length=160)
    mode: BusinessMode
    county: str | None = Field(default=None, max_length=80)
    email: EmailStr | None = None
    password: str
    pin: str
    accept_terms: bool
    terms_version: str = Field(min_length=1, max_length=32)
    device: SignupDeviceRequest | None = None

    @field_validator("owner_name", "business_name", "terms_version")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field must not be blank")
        return value

    @field_validator("county")
    @classmethod
    def strip_county(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class BusinessResponse(BaseModel):
    id: UUID
    name: str
    mode: BusinessMode
    status: BusinessStatus
    trial_ends_at: datetime


class OutletResponse(BaseModel):
    id: UUID
    name: str


class StaffResponse(BaseModel):
    id: UUID
    name: str
    role: StaffRole


class SignupCompleteResponse(BaseModel):
    business: BusinessResponse
    outlet: OutletResponse
    staff: StaffResponse
    device_token: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str | None = None
    expires_in: int | None = None
    refresh_expires_in: int | None = None
