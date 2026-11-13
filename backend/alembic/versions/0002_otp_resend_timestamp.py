"""Track the most recent OTP delivery for resend cooldown enforcement.

Revision ID: 0002_otp_resend_timestamp
Revises: 0001_auth_foundation
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_otp_resend_timestamp"
down_revision: str | Sequence[str] | None = "0001_auth_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "otp_challenge",
        sa.Column(
            "last_sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_column("otp_challenge", "last_sent_at")
