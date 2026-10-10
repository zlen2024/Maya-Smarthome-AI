"""PIN rules, in one place so the server, the tests and the error messages agree.

A device PIN is what proves to the server that the board on the other end of the
WebSocket is the one the owner provisioned, and what the firmware demands before
it will accept new WiFi credentials over BLE. A child PIN is a login credential.
Both were previously allowed to default to ``"0000"``, which made the check
decorative — so the rules are enforced here and the defaults are gone.
"""

# A PIN made of one repeated digit, or a straight run, defeats the point: these
# are what people type when they do not want to choose, and what an attacker
# tries first. The list is short on purpose — this rejects the defaults, it is
# not a password-strength policy.
_TRIVIAL = {"1234", "4321", "123456", "654321"}


def _digits_only(raw) -> str:
    return str(raw if raw is not None else "").strip()


def _reject_trivial(pin: str, what: str) -> None:
    if pin in _TRIVIAL or len(set(pin)) == 1:
        raise ValueError(
            f"{what} is too easy to guess — avoid repeated digits and runs like 1234"
        )


def normalize_device_pin(raw) -> str:
    """4 digits, not trivial. Matches the firmware and the provisioning screen."""
    pin = _digits_only(raw)
    if not pin:
        raise ValueError("pin required — a device PIN is what proves the board's identity")
    if len(pin) != 4 or not pin.isdigit():
        raise ValueError("pin must be exactly 4 digits")
    _reject_trivial(pin, "This PIN")
    return pin


def normalize_child_pin(raw) -> str:
    """4 to 6 digits, not trivial. The app's dialog asks for 4."""
    pin = _digits_only(raw)
    if not pin:
        raise ValueError("pin required — the child signs in with it")
    if not pin.isdigit() or not (4 <= len(pin) <= 6):
        raise ValueError("pin must be 4 to 6 digits")
    _reject_trivial(pin, "This PIN")
    return pin
