from __future__ import annotations


class AuthUtilityError(ValueError):
    """Raised by auth utilities before HTTP layers exist."""

    def __init__(self, code: str, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class AuthError(AuthUtilityError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict | None = None,
    ) -> None:
        super().__init__(code, message, details=details)
        self.status_code = status_code


class PhoneNormalizationError(AuthUtilityError):
    def __init__(self, message: str = "Invalid phone number") -> None:
        super().__init__("VALIDATION_ERROR", message)


class WeakPasswordError(AuthUtilityError):
    def __init__(
        self,
        message: str = "Password does not meet requirements",
        *,
        details: dict | None = None,
    ) -> None:
        super().__init__("WEAK_PASSWORD", message, details=details)


class WeakPinError(AuthUtilityError):
    def __init__(
        self,
        message: str = "PIN does not meet requirements",
        *,
        details: dict | None = None,
    ) -> None:
        super().__init__("WEAK_PIN", message, details=details)
