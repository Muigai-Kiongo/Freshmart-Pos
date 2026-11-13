"""Auth foundation tables and staff/business identity columns.

Revision ID: 0001_auth_foundation
Revises:
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_auth_foundation"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    business_mode = postgresql.ENUM("simple", "pro", name="business_mode")
    business_status = postgresql.ENUM(
        "trial", "active", "suspended", name="business_status"
    )
    signup_source = postgresql.ENUM("self", "platform", name="signup_source")
    staff_role = postgresql.ENUM(
        "owner", "supervisor", "cashier", "platform_admin", name="staff_role"
    )
    device_platform = postgresql.ENUM(
        "android", "ios", "web", "unknown", name="device_platform"
    )
    device_status = postgresql.ENUM("active", "revoked", name="device_status")
    otp_purpose = postgresql.ENUM("signup", "password_reset", name="otp_purpose")
    subject_type = postgresql.ENUM("staff", "admin", name="subject_type")
    token_purpose = postgresql.ENUM(
        "signup", "password_reset", "refresh", "device", name="token_purpose"
    )

    business_mode.create(op.get_bind(), checkfirst=True)
    business_status.create(op.get_bind(), checkfirst=True)
    signup_source.create(op.get_bind(), checkfirst=True)
    staff_role.create(op.get_bind(), checkfirst=True)
    device_platform.create(op.get_bind(), checkfirst=True)
    device_status.create(op.get_bind(), checkfirst=True)
    otp_purpose.create(op.get_bind(), checkfirst=True)
    subject_type.create(op.get_bind(), checkfirst=True)
    token_purpose.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "business",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("county", sa.String(80), nullable=True),
        sa.Column(
            "mode",
            postgresql.ENUM(name="business_mode", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="business_status", create_type=False),
            nullable=False,
        ),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "signup_source",
            postgresql.ENUM(name="signup_source", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "outlet",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "business_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("business.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False, server_default="Main"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_outlet_business_id", "outlet", ["business_id"])

    op.create_table(
        "staff",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "business_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("business.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "outlet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("outlet.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(name="staff_role", create_type=False),
            nullable=False,
        ),
        sa.Column("phone", sa.String(16), nullable=True),
        sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("pin_hash", sa.String(255), nullable=True),
        sa.Column("mfa_secret", sa.String(512), nullable=True),
        sa.Column(
            "mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "must_change_pin", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terms_version", sa.String(32), nullable=True),
        sa.Column("avatar_url", sa.String(512), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_staff_business_id", "staff", ["business_id"])
    op.create_index("ix_staff_outlet_id", "staff", ["outlet_id"])
    op.create_index("ix_staff_phone", "staff", ["phone"])
    op.create_index("ix_staff_email", "staff", ["email"])
    op.create_index(
        "uq_staff_owner_phone",
        "staff",
        ["phone"],
        unique=True,
        postgresql_where=sa.text("role = 'owner' AND phone IS NOT NULL"),
    )
    op.create_index(
        "uq_staff_owner_email",
        "staff",
        ["email"],
        unique=True,
        postgresql_where=sa.text("role = 'owner' AND email IS NOT NULL"),
    )

    op.create_table(
        "device",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "business_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("business.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "outlet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("outlet.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "platform",
            postgresql.ENUM(name="device_platform", create_type=False),
            nullable=False,
        ),
        sa.Column("device_token_hash", sa.String(64), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="device_status", create_type=False),
            nullable=False,
        ),
        sa.Column("fingerprint", sa.String(255), nullable=True),
        sa.Column("app_version", sa.String(32), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("device_token_hash", name="uq_device_token_hash"),
    )
    op.create_index("ix_device_business_id", "device", ["business_id"])
    op.create_index("ix_device_outlet_id", "device", ["outlet_id"])

    op.create_table(
        "otp_challenge",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "purpose",
            postgresql.ENUM(name="otp_purpose", create_type=False),
            nullable=False,
        ),
        sa.Column("phone", sa.String(16), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("resend_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("device_fingerprint", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_otp_challenge_phone", "otp_challenge", ["phone"])

    op.create_table(
        "refresh_token",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "subject_type",
            postgresql.ENUM(name="subject_type", create_type=False),
            nullable=False,
        ),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column(
            "device_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("device.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "replaced_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("refresh_token.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_refresh_token_hash"),
    )
    op.create_index("ix_refresh_token_family_id", "refresh_token", ["family_id"])
    op.create_index("ix_refresh_token_subject_id", "refresh_token", ["subject_id"])
    op.create_index("ix_refresh_token_device_id", "refresh_token", ["device_id"])

    op.create_table(
        "offline_unlock",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "staff_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("staff.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "device_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("device.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("salt", sa.String(64), nullable=False),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_offline_unlock_staff_id", "offline_unlock", ["staff_id"])
    op.create_index("ix_offline_unlock_device_id", "offline_unlock", ["device_id"])

    op.create_table(
        "consumed_token",
        sa.Column("jti", sa.String(64), primary_key=True),
        sa.Column(
            "purpose",
            postgresql.ENUM(name="token_purpose", create_type=False),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_audit_log_event_type", "audit_log", ["event_type"])
    op.create_index("ix_audit_log_actor_id", "audit_log", ["actor_id"])
    op.create_index("ix_audit_log_business_id", "audit_log", ["business_id"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])

    op.create_table(
        "pairing_code",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "business_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("business.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "outlet_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("outlet.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("code_hash", name="uq_pairing_code_hash"),
    )
    op.create_index("ix_pairing_code_business_id", "pairing_code", ["business_id"])
    op.create_index("ix_pairing_code_outlet_id", "pairing_code", ["outlet_id"])

    op.create_table(
        "idempotency_key",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("endpoint", sa.String(128), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_body", postgresql.JSONB(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("endpoint", "key", name="uq_idempotency_endpoint_key"),
    )

    op.create_table(
        "business_settings",
        sa.Column(
            "business_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("business.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "vat_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("currency", sa.String(8), nullable=False, server_default="KES"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "product_category",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "business_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("business.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "is_system_default", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("business_id", "name", name="uq_category_business_name"),
    )
    op.create_index(
        "ix_product_category_business_id", "product_category", ["business_id"]
    )


def downgrade() -> None:
    op.drop_table("product_category")
    op.drop_table("business_settings")
    op.drop_table("idempotency_key")
    op.drop_table("pairing_code")
    op.drop_table("audit_log")
    op.drop_table("consumed_token")
    op.drop_table("offline_unlock")
    op.drop_table("refresh_token")
    op.drop_table("otp_challenge")
    op.drop_table("device")
    op.drop_table("staff")
    op.drop_table("outlet")
    op.drop_table("business")

    postgresql.ENUM(name="token_purpose").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="subject_type").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="otp_purpose").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="device_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="device_platform").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="staff_role").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="signup_source").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="business_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="business_mode").drop(op.get_bind(), checkfirst=True)
