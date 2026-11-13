from __future__ import annotations

import pytest

from app.core.errors import WeakPinError
from app.core.pin import validate_pin


@pytest.mark.parametrize("pin", ["2580", "1947", "7082", "58021", "580219"])
def test_accepts_non_trivial_pins(pin: str) -> None:
    assert validate_pin(pin) == pin


@pytest.mark.parametrize(
    "pin",
    [
        "0000",
        "1234",
        "1111",
        "4321",
        "2222",
        "999999",
        "2345",
        "0123",
        "9876",
        "123456",
        "654321",
        "12a4",
        "12",
        "1234567",
        "",
    ],
)
def test_rejects_weak_or_invalid_pins(pin: str) -> None:
    with pytest.raises(WeakPinError) as exc:
        validate_pin(pin)
    assert exc.value.code == "WEAK_PIN"
