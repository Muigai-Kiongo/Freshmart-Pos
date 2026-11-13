from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    database_url: str = "postgresql+asyncpg://dazu:dazu@localhost:5432/dazu_pos"
    redis_url: str = "redis://localhost:6379/0"

    jwt_issuer: str = "dazu-pos"
    jwt_kid: str = "v1"
    jwt_staff_secret: str = "dev-staff-secret-change-me-min-32-chars"
    jwt_admin_secret: str = "dev-admin-secret-change-me-min-32-chars"
    jwt_signup_secret: str = "dev-signup-secret-change-me-min-32-chars"
    jwt_reset_secret: str = "dev-reset-secret-change-me-min-32-chars"
    jwt_staff_secrets: str | None = None
    jwt_admin_secrets: str | None = None
    jwt_signup_secrets: str | None = None
    jwt_reset_secrets: str | None = None

    pin_pepper: str = "dev-pin-pepper-change-me-min-32-chars"
    otp_pepper: str = "dev-otp-pepper-change-me-min-32-chars"
    mfa_encryption_key: str = ""

    otp_ttl_seconds: int = 300
    otp_resend_cooldown_seconds: int = 60
    otp_max_resends: int = 3
    otp_max_attempts: int = 5
    otp_phone_hourly_limit: int = 3
    otp_ip_hourly_limit: int = 20
    otp_global_daily_limit: int = 10000
    signup_captcha_threshold: int = 5
    allowed_phone_prefixes: str = "2547,2541"
    admin_cookie_mode: bool = False
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    at_api_key: str = ""
    at_username: str = ""
    at_sender_id: str = "DAZU"
    turnstile_secret: str | None = None

    argon2_time_cost: int = 3
    argon2_memory_kib: int = 65536
    argon2_parallelism: int = 2

    trial_days: int = 14
    staff_access_minutes: int = 15
    admin_access_minutes: int = 10
    staff_refresh_days: int = 30
    admin_refresh_days: int = 7
    signup_token_minutes: int = 15
    reset_token_minutes: int = 15
    offline_unlock_max_days: int = 7
    lockout_failures: int = 5
    lockout_base_seconds: int = 15 * 60
    pin_login_ip_limit: int = 60
    pin_login_device_limit: int = 30
    admin_login_ip_limit: int = 30
    password_reset_phone_hourly_limit: int = 3
    password_reset_ip_hourly_limit: int = 20
    password_reset_global_daily_limit: int = 10000

    # Dev/test OTP accepted by the non-production SMS provider.
    dev_otp_code: str = "000000"

    @field_validator("cors_origins", "allowed_phone_prefixes", mode="before")
    @classmethod
    def strip_spaces(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"prod", "production"}

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def phone_prefix_list(self) -> list[str]:
        return [
            item.strip()
            for item in self.allowed_phone_prefixes.split(",")
            if item.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
