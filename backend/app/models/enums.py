from __future__ import annotations

import enum


class BusinessStatus(str, enum.Enum):
    TRIAL = "trial"
    ACTIVE = "active"
    SUSPENDED = "suspended"


class SignupSource(str, enum.Enum):
    SELF = "self"
    PLATFORM = "platform"


class BusinessMode(str, enum.Enum):
    SIMPLE = "simple"
    PRO = "pro"


class StaffRole(str, enum.Enum):
    OWNER = "owner"
    SUPERVISOR = "supervisor"
    CASHIER = "cashier"
    PLATFORM_ADMIN = "platform_admin"


class DeviceStatus(str, enum.Enum):
    ACTIVE = "active"
    REVOKED = "revoked"


class DevicePlatform(str, enum.Enum):
    ANDROID = "android"
    IOS = "ios"
    WEB = "web"
    UNKNOWN = "unknown"


class OtpPurpose(str, enum.Enum):
    SIGNUP = "signup"
    PASSWORD_RESET = "password_reset"


class SubjectType(str, enum.Enum):
    STAFF = "staff"
    ADMIN = "admin"


class TokenPurpose(str, enum.Enum):
    SIGNUP = "signup"
    PASSWORD_RESET = "password_reset"
    REFRESH = "refresh"
    DEVICE = "device"
