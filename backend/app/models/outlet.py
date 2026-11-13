from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.business import Business
    from app.models.device import Device
    from app.models.staff import Staff


class Outlet(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "outlet"

    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("business.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="Main")
    is_default: Mapped[bool] = mapped_column(nullable=False, default=True)

    business: Mapped[Business] = relationship(back_populates="outlets")
    staff: Mapped[list[Staff]] = relationship(back_populates="outlet")
    devices: Mapped[list[Device]] = relationship(back_populates="outlet")
