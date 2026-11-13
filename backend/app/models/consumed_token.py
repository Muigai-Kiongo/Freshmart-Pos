from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import TokenPurpose


class ConsumedToken(Base):
    """Single-use JWT jti tracker (Redis with TTL is also acceptable at runtime)."""

    __tablename__ = "consumed_token"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    purpose: Mapped[TokenPurpose] = mapped_column(
        Enum(
            TokenPurpose,
            name="token_purpose",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
