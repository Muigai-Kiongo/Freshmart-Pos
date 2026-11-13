from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import BusinessMode, BusinessStatus, SignupSource
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.outlet import Outlet
    from app.models.staff import Staff


class Business(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "business"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    county: Mapped[str | None] = mapped_column(String(80), nullable=True)
    mode: Mapped[BusinessMode] = mapped_column(
        Enum(
            BusinessMode,
            name="business_mode",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=BusinessMode.SIMPLE,
    )
    status: Mapped[BusinessStatus] = mapped_column(
        Enum(
            BusinessStatus,
            name="business_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=BusinessStatus.TRIAL,
    )
    trial_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    signup_source: Mapped[SignupSource] = mapped_column(
        Enum(
            SignupSource,
            name="signup_source",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=SignupSource.SELF,
    )

    outlets: Mapped[list[Outlet]] = relationship(back_populates="business")
    staff: Mapped[list[Staff]] = relationship(back_populates="business")
    settings: Mapped[BusinessSettings | None] = relationship(
        back_populates="business", uselist=False
    )


class BusinessSettings(TimestampMixin, Base):
    __tablename__ = "business_settings"

    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("business.id", ondelete="CASCADE"),
        primary_key=True,
    )
    vat_enabled: Mapped[bool] = mapped_column(nullable=False, default=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="KES")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    business: Mapped[Business] = relationship(back_populates="settings")


class ProductCategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_category"
    __table_args__ = (
        UniqueConstraint("business_id", "name", name="uq_category_business_name"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("business.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)
    is_system_default: Mapped[bool] = mapped_column(nullable=False, default=False)
