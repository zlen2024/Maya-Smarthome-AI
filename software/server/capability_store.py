"""Reading and writing capability descriptors and state.

The database half of migration step 1 (`PROTOCOL.md` §10). `descriptor.py` decides
what a frame *means*; this module decides what is kept. It is a separate module
because `main.py` is already the largest file in the repo by a wide margin
(`wiki/pages/known-gaps.md`) and steps 2 and 3 both land there.

Two rules shape everything here:

* **The firmware is the authority on what a device can do.** Capability rows are
  rewritten wholesale on every identify, so a capability dropped from a new
  firmware build disappears instead of lingering.
* **The house is the authority on what things are called.** A member may rename
  a capability and the app's name wins over the firmware's (§5.1), so a rewrite
  must not clobber a label a person chose. Today those names live in
  `Relay.name`; `label_overrides` is where step 2 will hand them in.
"""
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models import CapabilityState, Device, DeviceCapability
from descriptor import KINDS, Capability, Descriptor, coerce_state


def _dump(value) -> str:
    return json.dumps(value, separators=(",", ":"))


def _load(raw):
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        # A row written by an older build, or hand-edited. Returning it as text
        # is better than raising while rendering a device list.
        return raw


def store_descriptor(db: Session, device: Device, desc: Descriptor) -> None:
    """Replace the device's declared capabilities and merge the state it reported.

    Caller commits. The capability rows are replaced, not merged: see the module
    docstring. State is merged rather than replaced, because §6.1 allows a
    partial state report and an identify's `state` may be partial too.
    """
    device.proto = desc.proto
    if desc.model:
        device.model = desc.model
    if desc.fw:
        device.fw = desc.fw
    # report_every is cleared when a device stops declaring one: a device that
    # gave up its schedule is a device the server must stop expecting on one.
    device.report_every = desc.report_every

    declared = {c.key: c for c in desc.capabilities}
    existing = {row.key: row for row in db.query(DeviceCapability).filter(
        DeviceCapability.device_id == device.device_id).all()}

    for key, row in existing.items():
        if key not in declared:
            db.delete(row)
    # State for a capability that no longer exists would be unreadable — nothing
    # knows its kind any more — so it goes with it.
    for row in db.query(CapabilityState).filter(
            CapabilityState.device_id == device.device_id).all():
        if row.key not in declared:
            db.delete(row)

    for position, cap in enumerate(desc.capabilities):
        row = existing.get(cap.key)
        if row is None:
            row = DeviceCapability(device_id=device.device_id, key=cap.key)
            db.add(row)
        row.kind = cap.kind
        row.label = cap.label
        row.access = cap.access
        row.unit = cap.unit
        row.group = cap.group
        row.options = _dump(cap.options) if cap.options else None
        row.min = cap.min
        row.max = cap.max
        row.step = cap.step
        row.history = cap.history
        row.agent = cap.agent
        row.confirm = cap.confirm
        row.position = position

    if desc.state:
        merge_state(db, device.device_id, desc.state, capabilities=desc.capabilities)


def merge_state(db: Session, device_id: str, values: dict,
                capabilities: list[Capability] | None = None) -> dict:
    """Upsert reported values. Returns what was actually written.

    `values` must already have been through `descriptor.coerce_state` or
    `coerce_value`; passing `capabilities` re-checks them against the declaration,
    which is what callers that received a raw frame should do.
    """
    if capabilities is not None:
        values = coerce_state({c.key: c for c in capabilities}, values)
    if not values:
        return {}

    rows = {row.key: row for row in db.query(CapabilityState).filter(
        CapabilityState.device_id == device_id,
        CapabilityState.key.in_(list(values.keys()))).all()}
    now = datetime.now(timezone.utc)
    for key, value in values.items():
        row = rows.get(key)
        if row is None:
            row = CapabilityState(device_id=device_id, key=key)
            db.add(row)
        row.value = _dump(value)
        row.updated_at = now
    return values


def load_capabilities(db: Session, device_id: str) -> list[Capability]:
    """Stored declarations, back as `descriptor.Capability` objects.

    Returning the same type the parser produces is what lets `coerce_value`
    validate an incoming *set* against a declaration made at identify time,
    without a second set of rules for the stored shape.
    """
    out = []
    for row in db.query(DeviceCapability).filter(
            DeviceCapability.device_id == device_id).order_by(
            DeviceCapability.position).all():
        options = _load(row.options)
        out.append(Capability(
            key=row.key, kind=row.kind, label=row.label, access=row.access or "rw",
            unit=row.unit, group=row.group,
            options=options if isinstance(options, list) else None,
            min=row.min, max=row.max, step=row.step,
            history=bool(row.history), agent=row.agent or "allow",
            confirm=bool(row.confirm), known_kind=row.kind in KINDS,
        ))
    return out


def load_state(db: Session, device_id: str) -> dict:
    return {row.key: _load(row.value) for row in db.query(CapabilityState).filter(
        CapabilityState.device_id == device_id).all()}


def descriptor_payload(db: Session, device: Device, *,
                       for_agent: bool = False,
                       label_overrides: dict[str, str] | None = None) -> dict:
    """The device's descriptor and state, in the shape the app and Maya read.

    `for_agent=True` applies §5.4: capabilities marked `agent:"deny"` are removed
    *before* the model is called, the same way `_execute_maya_tool` enforces
    permission in code rather than in the prompt. The filtering happens here so
    step 3 cannot forget it.
    """
    caps = load_capabilities(db, device.device_id)
    if for_agent:
        caps = [c for c in caps if c.agent == "allow"]
    state = load_state(db, device.device_id)
    overrides = label_overrides or {}

    out = []
    for cap in caps:
        item = cap.to_dict()
        if cap.key in overrides and overrides[cap.key]:
            item["label"] = overrides[cap.key]
        out.append(item)
    return {
        "proto": device.proto or 1,
        "model": device.model,
        "fw": device.fw,
        "report_every": device.report_every,
        "capabilities": out,
        "state": {k: v for k, v in state.items() if k in {c.key for c in caps}},
    }
