from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import Any, Literal
from uuid import uuid4

import jwt
from jwt import InvalidTokenError

from app.core.clock import Clock, SystemClock

Audience = Literal["staff", "admin", "signup", "reset"]
ALGORITHM = "HS256"


class JwtError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _parse_secret_map(
    current_kid: str, current_secret: str, extra: str | None
) -> dict[str, str]:
    keys = {current_kid: current_secret}
    if extra:
        for item in extra.split(","):
            item = item.strip()
            if not item:
                continue
            if ":" not in item:
                raise JwtError(
                    "VALIDATION_ERROR", "JWT secret rotation entries must be kid:secret"
                )
            kid, secret = item.split(":", 1)
            keys[kid.strip()] = secret.strip()
    return keys


@dataclass(frozen=True)
class JwtKeys:
    current_kid: str
    secrets: dict[str, str]

    @classmethod
    def from_settings(
        cls,
        *,
        kid: str,
        secret: str,
        extra: str | None = None,
    ) -> JwtKeys:
        return cls(current_kid=kid, secrets=_parse_secret_map(kid, secret, extra))

    def signing_secret(self) -> tuple[str, str]:
        return self.current_kid, self.secrets[self.current_kid]

    def secret_for_kid(self, kid: str | None) -> str:
        if kid and kid in self.secrets:
            return self.secrets[kid]
        if kid is None and self.current_kid in self.secrets:
            return self.secrets[self.current_kid]
        raise JwtError("INVALID_CREDENTIALS", "Unknown signing key")


def jwt_service_from_settings(settings, clock: Clock | None = None) -> JwtService:
    kid = settings.jwt_kid
    return JwtService(
        issuer=settings.jwt_issuer,
        staff=JwtKeys.from_settings(
            kid=kid, secret=settings.jwt_staff_secret, extra=settings.jwt_staff_secrets
        ),
        admin=JwtKeys.from_settings(
            kid=kid, secret=settings.jwt_admin_secret, extra=settings.jwt_admin_secrets
        ),
        signup=JwtKeys.from_settings(
            kid=kid,
            secret=settings.jwt_signup_secret,
            extra=settings.jwt_signup_secrets,
        ),
        reset=JwtKeys.from_settings(
            kid=kid, secret=settings.jwt_reset_secret, extra=settings.jwt_reset_secrets
        ),
        clock=clock,
    )


class JwtService:
    def __init__(
        self,
        *,
        issuer: str,
        staff: JwtKeys,
        admin: JwtKeys,
        signup: JwtKeys,
        reset: JwtKeys,
        clock: Clock | None = None,
    ) -> None:
        self.issuer = issuer
        self.staff_keys = staff
        self.admin_keys = admin
        self.signup_keys = signup
        self.reset_keys = reset
        self.clock = clock or SystemClock()

    def _keys_for_audience(self, aud: Audience) -> JwtKeys:
        return {
            "staff": self.staff_keys,
            "admin": self.admin_keys,
            "signup": self.signup_keys,
            "reset": self.reset_keys,
        }[aud]

    def encode(
        self,
        *,
        subject: str,
        audience: Audience,
        ttl: timedelta,
        extra: dict[str, Any] | None = None,
        jti: str | None = None,
    ) -> str:
        now = self.clock.now()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        keys = self._keys_for_audience(audience)
        kid, secret = keys.signing_secret()
        payload: dict[str, Any] = {
            "sub": subject,
            "iss": self.issuer,
            "aud": audience,
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int((now + ttl).timestamp()),
            "jti": jti or str(uuid4()),
        }
        if extra:
            payload.update(extra)
        return jwt.encode(
            payload, secret, algorithm=ALGORITHM, headers={"kid": kid, "typ": "JWT"}
        )

    def decode(self, token: str, *, audience: Audience) -> dict[str, Any]:
        keys = self._keys_for_audience(audience)
        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError as exc:
            raise JwtError("INVALID_CREDENTIALS", "Invalid token") from exc
        kid = header.get("kid")
        secret = keys.secret_for_kid(kid)
        try:
            payload = jwt.decode(
                token,
                secret,
                algorithms=[ALGORITHM],
                audience=audience,
                issuer=self.issuer,
                options={
                    "require": ["exp", "iat", "nbf", "iss", "aud", "sub", "jti"],
                    "verify_exp": False,
                    "verify_nbf": False,
                },
            )
        except InvalidTokenError as exc:
            raise JwtError("INVALID_CREDENTIALS", "Invalid token") from exc
        now = int(self.clock.now().timestamp())
        if int(payload["nbf"]) > now:
            raise JwtError("INVALID_CREDENTIALS", "Token is not yet valid")
        if int(payload["exp"]) <= now:
            raise JwtError("INVALID_CREDENTIALS", "Token has expired")
        return payload
