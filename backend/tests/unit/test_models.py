from __future__ import annotations

from app.db.base import Base
from app.models import (  # noqa: F401
    AuditLog,
    Business,
    ConsumedToken,
    Device,
    IdempotencyKey,
    OfflineUnlock,
    OtpChallenge,
    Outlet,
    PairingCode,
    RefreshToken,
    Staff,
)


def test_expected_tables_are_registered() -> None:
    tables = set(Base.metadata.tables)
    assert {
        "business",
        "business_settings",
        "product_category",
        "outlet",
        "staff",
        "device",
        "otp_challenge",
        "refresh_token",
        "offline_unlock",
        "consumed_token",
        "audit_log",
        "pairing_code",
        "idempotency_key",
    }.issubset(tables)


def test_staff_has_auth_columns() -> None:
    columns = set(Staff.__table__.c.keys())
    assert {
        "phone",
        "phone_verified_at",
        "email",
        "password_hash",
        "pin_hash",
        "mfa_secret",
        "mfa_enabled",
        "must_change_pin",
        "must_change_password",
        "password_changed_at",
        "last_login_at",
        "terms_accepted_at",
        "terms_version",
    }.issubset(columns)


def test_owner_partial_unique_indexes() -> None:
    names = {index.name for index in Staff.__table__.indexes}
    assert "uq_staff_owner_phone" in names
    assert "uq_staff_owner_email" in names
