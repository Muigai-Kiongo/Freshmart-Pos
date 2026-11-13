from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import StaffRole
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.business import Business
    from app.models.outlet import Outlet


class Staff(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "staff"
    __table_args__ = (
        Index(
            "uq_staff_owner_phone",
            "phone",
            unique=True,
            postgresql_where=text("role = 'owner' AND phone IS NOT NULL"),
            sqlite_where=text("role = 'owner' AND phone IS NOT NULL"),
        ),
        Index(
            "uq_staff_owner_email",
            "email",
            unique=True,
            postgresql_where=text("role = 'owner' AND email IS NOT NULL"),
            sqlite_where=text("role = 'owner' AND email IS NOT NULL"),
        ),
        Index("ix_staff_phone", "phone"),
        Index("ix_staff_email", "email"),
    )

    business_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("business.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    outlet_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outlet.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    role: Mapped[StaffRole] = mapped_column(
        Enum(
            StaffRole, name="staff_role", values_callable=lambda x: [e.value for e in x]
        ),
        nullable=False,
        default=StaffRole.CASHIER,
    )
    phone: Mapped[str | None] = mapped_column(String(16), nullable=True)
    phone_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pin_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mfa_secret: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    must_change_pin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    terms_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    terms_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    business: Mapped[Business | None] = relationship(back_populates="staff")
    outlet: Mapped[Outlet | None] = relationship(back_populates="staff")
