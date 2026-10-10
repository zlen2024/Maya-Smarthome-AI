"""Protocol 2 capability descriptors: parse, validate, coerce, and shim v1.

This is `PROTOCOL.md` §4-§6 as code, and migration step 1 of §10 — the server
accepts and stores what a device declares about itself, and synthesises a
descriptor on behalf of devices that declare nothing. Nothing here touches the
database or the WebSocket, so the rules can be tested on their own
(`test_descriptor.py`).

The point of the protocol, kept in view: a contributor builds new hardware, drops
it in `hardware/`, and it appears and is controllable **without editing
`software/`**. Every decision below is in service of that, which is why unknown
things degrade rather than being rejected — a device the server does not fully
understand must still work as far as it can.

Where this file makes a choice the document does not state outright, the comment
says so.
"""
import json
import re
from dataclasses import dataclass, field

PROTO_MAX = 2                   # the highest version this server speaks (§4)
MAX_CAPABILITIES = 32           # §5.5
MAX_DESCRIPTOR_BYTES = 4096     # §5.5 — keeps the frame inside one ESP32 StaticJsonDocument

# §5.1 — stable id, unique per device, and the permission and history key, so it
# is validated strictly rather than sanitised.
KEY_RE = re.compile(r"^[a-z0-9_]{1,24}$")

# §5.2 — a closed set of ten. Adding one costs a widget in the app, so new
# expressiveness is supposed to arrive as a *field* instead.
KINDS = frozenset({"switch", "range", "number", "text", "enum", "button",
                   "color", "time", "duration", "location"})

# §5.3 — the `_` namespace belongs to the protocol document. A device may report
# these; it may not invent others. `_report_every` is the odd one out: it is a
# setting rather than a health reading, and declaring it is how a sleepy device
# says its check-in interval is adjustable (§5.8). Leaving it out of this set
# dropped the capability silently, which made the interval unadjustable on every
# device that offered it.
RESERVED_KEYS = frozenset({"_batt", "_rssi", "_fw", "_uptime", "_report_every"})

ACCESS_VALUES = frozenset({"rw", "r", "w"})

# The three channels every protocol-1 device has, hardcoded end to end today.
V1_CHANNEL_KEYS = ("ch1", "ch2", "ch3")

_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class DescriptorError(Exception):
    """A descriptor the server refuses outright. `code` is an ack status from §9."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass
class Capability:
    """One declared capability, normalised. Unknown extra fields are dropped
    here rather than stored: §1 rule 4 says they must not be fatal, and storing
    them would imply a meaning the server does not have."""
    key: str
    kind: str
    label: str
    access: str = "rw"
    unit: str | None = None
    group: str | None = None
    options: list[str] | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    history: bool = False
    agent: str = "allow"
    confirm: bool = False
    # False when `kind` is not one of the ten. The capability is kept so a v2.x
    # device is not crippled by an old server, but it is forced read-only — see
    # `_normalise_one`.
    known_kind: bool = True

    @property
    def writable(self) -> bool:
        return self.access in ("rw", "w")

    @property
    def readable(self) -> bool:
        return self.access in ("rw", "r")

    def to_dict(self) -> dict:
        """The shape the app and Maya read. Omits anything unset so a lamp's
        descriptor does not carry nine nulls."""
        out = {"key": self.key, "kind": self.kind, "label": self.label,
               "access": self.access}
        for name in ("unit", "group", "options", "min", "max", "step"):
            value = getattr(self, name)
            if value is not None:
                out[name] = value
        if self.history:
            out["history"] = True
        if self.agent != "allow":
            out["agent"] = self.agent
        if self.confirm:
            out["confirm"] = True
        return out


@dataclass
class Descriptor:
    """What a device says it is, after validation."""
    proto: int
    capabilities: list[Capability] = field(default_factory=list)
    state: dict = field(default_factory=dict)
    model: str | None = None
    fw: str | None = None
    report_every: int | None = None
    shimmed: bool = False
    # Why anything was dropped. Surfaced in the server log and stored nowhere:
    # it is a message to whoever is writing the firmware, not device data.
    warnings: list[str] = field(default_factory=list)

    @property
    def by_key(self) -> dict[str, Capability]:
        return {c.key: c for c in self.capabilities}


def negotiate_proto(raw) -> int:
    """§4: the device sends the highest version it supports, the server replies
    with `min(device, server_max)`. Absent, unparseable or < 1 means 1 — a
    garbled version must land on the shimmed path, never on an unsupported one."""
    try:
        proto = int(raw)
    except (TypeError, ValueError):
        return 1
    return max(1, min(proto, PROTO_MAX))


def _as_number(raw):
    if isinstance(raw, bool):
        raise ValueError("expected a number, got a boolean")
    if isinstance(raw, (int, float)):
        return raw
    raise ValueError(f"expected a number, got {type(raw).__name__}")


def _opt_number(spec: dict, name: str):
    if name not in spec:
        return None
    try:
        return _as_number(spec[name])
    except ValueError:
        return None          # a bad bound is dropped; the capability survives


def _normalise_one(spec, warn) -> Capability | None:
    """One entry of `capabilities[]`. Returns None when it cannot be stored at all."""
    if not isinstance(spec, dict):
        warn("capability entry is not an object")
        return None

    key = spec.get("key")
    if not isinstance(key, str) or not KEY_RE.match(key):
        warn(f"capability key {key!r} is not [a-z0-9_] up to 24 chars")
        return None
    if key.startswith("_") and key not in RESERVED_KEYS:
        # §5.3: contributors MUST NOT define new `_` keys. Dropping the one
        # capability is the fail-closed answer — it never existed as far as the
        # rest of the stack is concerned — where rejecting the whole device
        # would brick a board over a naming slip.
        warn(f"capability key {key!r} is in the reserved `_` namespace")
        return None

    kind = spec.get("kind")
    if not isinstance(kind, str) or not kind:
        warn(f"{key}: missing kind")
        return None

    known = kind in KINDS
    label = spec.get("label")
    label = label if isinstance(label, str) and label.strip() else key

    access = spec.get("access", "rw")
    if access not in ACCESS_VALUES:
        # Not stated in the document. Chosen to match §5.4's reasoning about
        # `agent`: when a declaration cannot be understood, the safe reading is
        # the one that does not permit writes to hardware.
        if "access" in spec:
            warn(f"{key}: unknown access {access!r}, treating as read-only")
        access = "r"
    if not known:
        # §11: a device using a kind this server has never heard of degrades to a
        # read-only raw value rather than being dropped, so a v2.x device still
        # reports usefully against a v2.0 server.
        warn(f"{key}: unknown kind {kind!r}, keeping it read-only")
        access = "r"

    options = None
    if kind == "enum":
        raw_options = spec.get("options")
        options = [o for o in raw_options if isinstance(o, str)] if isinstance(raw_options, list) else []
        if not options:
            warn(f"{key}: enum without usable options")
            return None          # a dropdown with nothing in it cannot be rendered

    agent = spec.get("agent", "allow")
    if agent not in ("allow", "deny"):
        # §5.4, and the only MUST of its kind here: an unrecognised value fails
        # closed, because a typo should hide a capability from Maya, never expose
        # a dangerous one.
        if "agent" in spec:
            warn(f"{key}: unknown agent {agent!r}, treating as deny")
        agent = "deny"

    unit = spec.get("unit") if isinstance(spec.get("unit"), str) else None
    group = spec.get("group") if isinstance(spec.get("group"), str) else None
    return Capability(
        key=key, kind=kind, label=label, access=access, unit=unit, group=group,
        options=options,
        min=_opt_number(spec, "min"), max=_opt_number(spec, "max"),
        step=_opt_number(spec, "step"),
        # `history` is only meaningful for number and range (§5.1)
        history=bool(spec.get("history")) and kind in ("number", "range"),
        agent=agent, confirm=bool(spec.get("confirm")), known_kind=known,
    )


def coerce_value(cap: Capability, raw):
    """A reported or requested value, in the type its `kind` implies.

    Raises ValueError, which the caller turns into a `bad_value` ack for a set,
    or into a dropped key for a state report. Being strict here is what lets the
    stored state be trusted later: the app renders it without re-checking.
    """
    kind = cap.kind
    if not cap.known_kind:
        # Nothing is known about the value's type, so it is kept as given and
        # only bounded in size. The app shows it as a raw read-only value.
        if isinstance(raw, (str, int, float, bool)) or raw is None:
            return raw
        raise ValueError("unsupported value for an unknown kind")

    if kind == "switch":
        if isinstance(raw, bool):
            return "on" if raw else "off"
        text = str(raw).strip().lower()
        if text in ("on", "true", "1"):
            return "on"
        if text in ("off", "false", "0"):
            return "off"
        raise ValueError("switch takes on/off")

    if kind in ("range", "number", "duration"):
        value = _as_number(raw)
        lo = cap.min if cap.min is not None else (0 if kind == "duration" else None)
        if lo is not None and value < lo:
            raise ValueError(f"below min {lo}")
        if cap.max is not None and value > cap.max:
            raise ValueError(f"above max {cap.max}")
        return value

    if kind == "text":
        if not isinstance(raw, str):
            raise ValueError("text takes a string")
        limit = int(cap.max) if cap.max is not None else None
        if limit is not None and len(raw) > limit:
            raise ValueError(f"longer than {limit} characters")
        return raw

    if kind == "enum":
        if raw not in (cap.options or []):
            raise ValueError(f"not one of {cap.options}")
        return raw

    if kind == "button":
        # §5.2: momentary, no state. A button carries no value in either
        # direction, so anything sent for it is discarded rather than stored.
        return None

    if kind == "color":
        if not isinstance(raw, str) or not _COLOR_RE.match(raw):
            raise ValueError("colour takes #RRGGBB")
        return raw.lower()

    if kind == "time":
        if not isinstance(raw, str) or not _TIME_RE.match(raw):
            raise ValueError("time takes HH:MM, 24-hour")
        return raw

    if kind == "location":
        if not isinstance(raw, dict):
            raise ValueError("location takes {lat, lng}")
        try:
            lat, lng = _as_number(raw["lat"]), _as_number(raw["lng"])
        except (KeyError, ValueError):
            raise ValueError("location takes {lat, lng}")
        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            raise ValueError("location out of range")
        return {"lat": lat, "lng": lng}

    raise ValueError(f"no rule for kind {kind!r}")   # unreachable while KINDS is the guard


def coerce_state(by_key: dict[str, Capability], state, warn=None) -> dict:
    """Validate a reported state map against the declared capabilities.

    A report is observational, so a bad or undeclared key is dropped and the rest
    is kept — one wrong value must not discard a frame that also carried a good
    temperature reading.
    """
    out = {}
    if not isinstance(state, dict):
        return out
    for key, raw in state.items():
        cap = by_key.get(key)
        if cap is None:
            if warn:
                warn(f"state for undeclared capability {key!r} ignored")
            continue
        if cap.kind == "button":
            continue
        if not cap.readable:
            # access:"w" is write-only: a value coming back for it is a firmware
            # bug, not something to store under a key the app will not show.
            if warn:
                warn(f"state for write-only capability {key!r} ignored")
            continue
        try:
            out[key] = coerce_value(cap, raw)
        except ValueError as e:
            if warn:
                warn(f"state for {key!r} ignored: {e}")
    return out


def _shim_v1_capabilities() -> list[Capability]:
    """§4: a device with no `proto` is served exactly as today, with the server
    synthesising the three switches on its behalf so the rest of the stack sees
    only v2 shapes.

    Labels stay generic: §5.1 gives the app's name precedence over the
    firmware's, and the house's own channel names already live in `Relay.name`.
    """
    return [Capability(key=key, kind="switch", label=f"Channel {i}")
            for i, key in enumerate(V1_CHANNEL_KEYS, start=1)]


def v1_state(frame: dict) -> dict:
    """The `ch1`/`ch2`/`ch3` of any protocol-1 frame as a v2 state map.

    Identify, heartbeat and ack all carry all three channels (Appendix A), which
    is what keeps the whole relay row in sync off a single-channel command.
    """
    out = {}
    for key in V1_CHANNEL_KEYS:
        if key in frame:
            try:
                out[key] = coerce_value(Capability(key=key, kind="switch", label=key), frame[key])
            except ValueError:
                continue
    return out


def parse_identify(frame: dict) -> Descriptor:
    """An identify frame (§5) into a validated descriptor.

    Raises DescriptorError only for the two limits of §5.5; everything else
    degrades, with a warning, so that one malformed capability cannot stop a
    device from working.
    """
    proto = negotiate_proto(frame.get("proto"))
    warnings: list[str] = []

    def warn(message: str):
        if len(warnings) < 40:
            warnings.append(message)

    if proto < 2:
        caps = _shim_v1_capabilities()
        return Descriptor(proto=1, capabilities=caps, shimmed=True,
                          state=v1_state(frame),
                          model=frame.get("model") if isinstance(frame.get("model"), str) else None,
                          fw=frame.get("fw") if isinstance(frame.get("fw"), str) else None)

    size = len(json.dumps(frame, separators=(",", ":")).encode("utf-8"))
    if size > MAX_DESCRIPTOR_BYTES:
        raise DescriptorError("descriptor_too_large",
                              f"{size} bytes, limit {MAX_DESCRIPTOR_BYTES}")

    raw_caps = frame.get("capabilities")
    if not isinstance(raw_caps, list):
        warn("no capabilities array; treating the device as declaring nothing")
        raw_caps = []
    if len(raw_caps) > MAX_CAPABILITIES:
        raise DescriptorError("descriptor_too_large",
                              f"{len(raw_caps)} capabilities, limit {MAX_CAPABILITIES}")

    caps: list[Capability] = []
    seen: set[str] = set()
    for spec in raw_caps:
        cap = _normalise_one(spec, warn)
        if cap is None:
            continue
        if cap.key in seen:
            # §5.1 requires uniqueness. First declaration wins, so a device
            # cannot quietly change a capability's meaning further down the list.
            warn(f"duplicate capability key {cap.key!r} ignored")
            continue
        seen.add(cap.key)
        caps.append(cap)

    by_key = {c.key: c for c in caps}
    report_every = frame.get("report_every")
    try:
        report_every = int(report_every) if report_every is not None else None
        if report_every is not None and report_every <= 0:
            report_every = None
    except (TypeError, ValueError):
        warn("report_every is not a number; ignoring it")
        report_every = None

    return Descriptor(
        proto=proto,
        capabilities=caps,
        state=coerce_state(by_key, frame.get("state"), warn),
        model=frame.get("model") if isinstance(frame.get("model"), str) else None,
        fw=frame.get("fw") if isinstance(frame.get("fw"), str) else None,
        report_every=report_every,
        warnings=warnings,
    )
