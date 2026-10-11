"""What an Open API key may reach (PROTOCOL.md §12).

A key used to mean "everything in the house": every device, read and command. That is
too much for "let my dashboard read the tank level", and it was the open half of a
recorded security finding. A key can now be scoped to some devices, some capability
keys, and read-only or read-and-write. This module is the whole of that decision, with
no database and no HTTP in it, so it can be tested on its own (`test_open_api.py`);
`main.py` supplies the key row and the descriptor and acts on the answer.

Three rules shape it:

* **Fail closed.** A scope that cannot be read back reaches nothing, never everything.
  The only way to reach the whole house is to be a key issued before scoping existed,
  which is stored as no scope at all.
* **Scope is applied per request, against the descriptor.** It is never recorded in the
  key and trusted. A capability that leaves a device's descriptor is unreachable
  whatever the scope says, and a key reaches only what the device declares *now*.
* **A key is not a person.** `confirm:true` capabilities are refused on this surface
  whatever the scope says (§5.4): no flag a key can send makes it one.
* **A key is an automaton.** `agent:"deny"` means the firmware author does not want
  automation touching a capability (§5.4), and an integration is exactly that. Such a
  capability does not exist as far as a key can tell: it is not listed, its state is not
  shown, and a `set` of it reads like any other key the device does not declare. (This was
  not the case in the first build of this surface, which excluded `confirm` only, as §12
  was then worded; it was tightened the same day.)
"""
import json
import re
from dataclasses import dataclass

# §5.1: `[a-z0-9_]{1,24}`; a leading underscore is a reserved health key such as `_batt`.
KEY_RE = re.compile(r"^[a-z0-9_]{1,24}$")
MAX_ENTRIES = 64


class ScopeError(Exception):
    """A scope that cannot be issued; the endpoint turns it into a 400."""


@dataclass(frozen=True)
class Scope:
    devices: frozenset | None   # None: every device in the key's house
    keys: frozenset | None      # None: every capability the device declares
    write: bool                 # False: read only

    def sees_device(self, device_id: str) -> bool:
        return self.devices is None or device_id in self.devices

    def sees_key(self, device_id: str, key: str) -> bool:
        return self.sees_device(device_id) and (self.keys is None or key in self.keys)

    @property
    def unscoped(self) -> bool:
        return self.devices is None and self.keys is None and self.write


# A key issued before scoping existed: the whole house, read and command. Those keys are
# stored with no scope, and "already-issued keys must keep meaning" exactly this (§12.1).
LEGACY = Scope(devices=None, keys=None, write=True)
# What an unreadable stored scope means. Never LEGACY.
NOTHING = Scope(devices=frozenset(), keys=frozenset(), write=False)


def parse(raw, house_device_ids: set) -> Scope | None:
    """The scope a master asked for, or None for none ("the whole house", the legacy
    meaning). Raises ScopeError for anything that is not a usable scope.

    `{"devices": [...], "keys": [...], "write": true}`. Each list is optional: leave one
    out and it is unrestricted. `write` defaults to **false**, because a key someone
    forgot to think about should be able to look and not touch. A list that is present
    must not be empty - a key that can reach nothing is a mistake, not a scope.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ScopeError("scope must be an object: {\"devices\": [...], \"keys\": [...], \"write\": false}")
    unknown = set(raw) - {"devices", "keys", "write"}
    if unknown:
        raise ScopeError(f"unknown scope field: {sorted(unknown)[0]}")

    devices = _list(raw, "devices")
    keys = _list(raw, "keys")
    if devices is not None:
        stray = [d for d in devices if d not in house_device_ids]
        if stray:
            raise ScopeError(f"{stray[0]} is not a device in this house")
    if keys is not None:
        bad = [k for k in keys if not KEY_RE.match(k)]
        if bad:
            raise ScopeError(f"{bad[0]!r} is not a valid capability key")
    write = raw.get("write", False)
    if not isinstance(write, bool):
        raise ScopeError("write must be true or false")
    return Scope(devices=frozenset(devices) if devices is not None else None,
                 keys=frozenset(keys) if keys is not None else None, write=write)


def _list(raw: dict, name: str):
    if name not in raw or raw[name] is None:
        return None
    value = raw[name]
    if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
        raise ScopeError(f"{name} must be a non-empty list of strings")
    value = list(dict.fromkeys(value))
    if len(value) > MAX_ENTRIES:
        raise ScopeError(f"{name} may name at most {MAX_ENTRIES} entries")
    return value


def dump(scope: Scope | None) -> str | None:
    if scope is None:
        return None
    return json.dumps({"devices": sorted(scope.devices) if scope.devices is not None else None,
                       "keys": sorted(scope.keys) if scope.keys is not None else None,
                       "write": scope.write}, separators=(",", ":"))


def load(text: str | None) -> Scope:
    """The scope stored on a key. No scope is the legacy whole-house meaning; a scope
    that cannot be read reaches nothing."""
    if text is None:
        return LEGACY
    try:
        value = json.loads(text)
        devices = value["devices"]
        keys = value["keys"]
        write = value["write"]
        if (devices is not None and not isinstance(devices, list)) \
                or (keys is not None and not isinstance(keys, list)) or not isinstance(write, bool):
            return NOTHING
        return Scope(devices=frozenset(devices) if devices is not None else None,
                     keys=frozenset(keys) if keys is not None else None, write=write)
    except (TypeError, ValueError, KeyError):
        return NOTHING


def automatable(caps) -> set:
    """The keys of these capabilities (descriptor objects) that automation may touch:
    everything but `agent:"deny"`, and an `agent` value the server cannot read is deny."""
    return {c.key for c in caps if c.agent == "allow"}


def describe(scope: Scope) -> dict | None:
    """The scope as the master sees it in a key listing. None means the legacy meaning,
    which the app should show as what it is: the whole house, read and command."""
    if scope.unscoped and scope is LEGACY:
        return None
    return {"devices": sorted(scope.devices) if scope.devices is not None else None,
            "keys": sorted(scope.keys) if scope.keys is not None else None,
            "write": scope.write}


def view(scope: Scope, device_id: str, payload: dict) -> dict:
    """A device's descriptor and state as this key may see them (§12): only the
    capabilities in scope, each saying whether *this key* may write it. `may_write` is
    false for a read-only key, a read-only capability and any `confirm:true` one."""
    caps = []
    for item in payload.get("capabilities", []):
        if item.get("agent", "allow") != "allow" or not scope.sees_key(device_id, item["key"]):
            continue
        writable = item.get("access", "rw") in ("rw", "w")
        caps.append({**item, "may_write": bool(scope.write and writable and not item.get("confirm"))})
    seen = {c["key"] for c in caps}
    return {**payload, "capabilities": caps,
            "state": {k: v for k, v in payload.get("state", {}).items() if k in seen}}


def set_denial(scope: Scope, device_id: str, values, caps: dict) -> dict | None:
    """Why this key may not make this `set`, or None if it may. `caps` is the device's
    current declaration, key -> Capability.

    The whole request is judged before anything is sent, so a refusal never leaves half
    of it applied. A key that is out of scope and a key the device does not declare
    get the same answer: telling them apart would let a scoped key list capabilities it
    was never given.
    """
    if not scope.write:
        return {"status": "not_permitted", "detail": "this key is read-only"}
    if not isinstance(values, dict) or not values:
        return {"status": "bad_value", "detail": "values object required"}
    for key in values:
        cap = caps.get(key)
        if cap is None or cap.agent != "allow" or not scope.sees_key(device_id, key):
            return {"status": "not_permitted", "key": key,
                    "detail": "this key may not set that capability"}
        if not cap.writable:
            return {"status": "not_permitted", "key": key, "detail": f"{key} is read-only"}
        if cap.confirm:
            return {"status": "not_permitted", "key": key, "needs_confirmation": True,
                    "detail": f"{cap.label} needs a person to confirm it, which an API key cannot do"}
    return None
