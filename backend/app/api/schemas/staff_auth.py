from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import StaffRole


class StaffListItem(BaseModel):
    id: UUID
    name: str
    avatar: str | None = None


class PinLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    staff_id: UUID
    pin: str = Field(pattern=r"^\d{4,6}$")


class StaffSessionResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_expires_in: int
    must_change_pin: bool


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=32, max_length=256)


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_expires_in: int
    must_change_pin: bool


class LogoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=32, max_length=256)


class SessionItem(BaseModel):
    id: UUID
    device_id: UUID | None
    device_name: str | None
    ip: str | None
    last_used_at: datetime | None
    created_at: datetime
    expires_at: datetime


class StaffMeResponse(BaseModel):
    id: UUID
    name: str
    role: StaffRole
    business: dict | None
    outlet: dict | None
    flags: dict[str, bool]


class OfflineUnlockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pin: str = Field(pattern=r"^\d{4,6}$")


class ChangePinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_pin: str = Field(pattern=r"^\d{4,6}$")
    new_pin: str = Field(pattern=r"^\d{4,6}$")


class OfflineUnlockResponse(BaseModel):
    salt: str
    expires_at: datetime


class OfflineSessionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    staff_id: UUID
    device_id: UUID
    unlocked_at: datetime
    locked_at: datetime | None = None

    @field_validator("unlocked_at", "locked_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Offline session timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_order(self) -> OfflineSessionItem:
        if self.locked_at is not None and self.locked_at < self.unlocked_at:
            raise ValueError("locked_at must not be earlier than unlocked_at")
        return self


class OfflineSessionsSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessions: list[OfflineSessionItem] = Field(max_length=100)


class OfflineSessionsSyncResponse(BaseModel):
    recorded_sessions: int
