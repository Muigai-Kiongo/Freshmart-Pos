from __future__ import annotations

from app.core.errors import WeakPinError

_EXPLICIT_BLOCKLIST = {"0000", "1234", "1111", "4321"}


def _is_sequential(digits: str) -> bool:
    values = [int(ch) for ch in digits]
    if len(values) < 3:
        return False
    diffs = [values[i + 1] - values[i] for i in range(len(values) - 1)]
    return all(d == 1 for d in diffs) or all(d == -1 for d in diffs)


def validate_pin(pin: str) -> str:
    if not isinstance(pin, str) or not pin:
        raise WeakPinError("PIN is required")
    if not pin.isdigit():
        raise WeakPinError("PIN must be numeric")
    if not 4 <= len(pin) <= 6:
        raise WeakPinError("PIN must be 4 to 6 digits")
    if pin in _EXPLICIT_BLOCKLIST or pin in {
        p.ljust(len(pin), p[0]) for p in _EXPLICIT_BLOCKLIST
    }:
        raise WeakPinError("PIN is too easy to guess")
    if len(set(pin)) == 1:
        raise WeakPinError("PIN cannot be the same digit repeated")
    if _is_sequential(pin):
        raise WeakPinError("PIN cannot be sequential digits")
    return pin
