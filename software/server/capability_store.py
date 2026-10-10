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

from models import (CapabilityGrant, CapabilityLabel, CapabilityState, Device,
                    DeviceCapability)
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
    # Everything keyed on a capability that no longer exists goes with it. State
    # would be unreadable — nothing knows its kind any more. A grant would be a
    # permission for something that does not exist, and if the key ever returns
    # §5.10 requires it to return denied, which only holds if the old row is
    # gone. A label would name a capability nobody can see.
    for model in (CapabilityState, CapabilityGrant, CapabilityLabel):
        for row in db.query(model).filter(model.device_id == device.device_id).all():
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


def house_labels(db: Session, device_id: str) -> dict[str, str]:
    """The names house members gave this device's capabilities (§5.11)."""
    return {row.key: row.label for row in db.query(CapabilityLabel).filter(
        CapabilityLabel.device_id == device_id).all()}


def set_house_label(db: Session, device_id: str, key: str, label: str | None) -> None:
    """Name a capability, or clear the name.

    Clearing *is* the reset (§5.11): with no row, the firmware's own label
    applies again, and there is no third state to represent.
    """
    row = db.query(CapabilityLabel).filter(
        CapabilityLabel.device_id == device_id, CapabilityLabel.key == key).first()
    if label is None or not label.strip():
        if row:
            db.delete(row)
        return
    if row is None:
        row = CapabilityLabel(device_id=device_id, key=key)
        db.add(row)
    row.label = label.strip()
    row.updated_at = datetime.now(timezone.utc)


def child_grants(db: Session, child_id: int,
                 device_id: str | None = None) -> dict[tuple[str, str], bool]:
    """Every grant for this child, keyed `(device_id, capability key)`."""
    q = db.query(CapabilityGrant).filter(CapabilityGrant.child_id == child_id)
    if device_id is not None:
        q = q.filter(CapabilityGrant.device_id == device_id)
    return {(row.device_id, row.key): bool(row.is_allowed) for row in q.all()}


def child_may_write(db: Session, child_id: int, device_id: str, key: str) -> bool:
    """§5.10: absent means denied.

    The default is the whole point — a capability nobody has granted is one a
    firmware update just introduced, and it must not become reachable because it
    appeared.
    """
    row = db.query(CapabilityGrant).filter(
        CapabilityGrant.child_id == child_id,
        CapabilityGrant.device_id == device_id,
        CapabilityGrant.key == key).first()
    return bool(row and row.is_allowed)


def set_grant(db: Session, child_id: int, device_id: str, key: str,
              is_allowed: bool) -> CapabilityGrant:
    """Grant or deny one capability to one child. Caller commits."""
    row = db.query(CapabilityGrant).filter(
        CapabilityGrant.child_id == child_id,
        CapabilityGrant.device_id == device_id,
        CapabilityGrant.key == key).first()
    if row is None:
        row = CapabilityGrant(child_id=child_id, device_id=device_id, key=key)
        db.add(row)
    row.is_allowed = bool(is_allowed)
    return row


def descriptor_payload(db: Session, device: Device, *,
                       for_agent: bool = False,
                       label_overrides: dict[str, str] | None = None,
                       child_id: int | None = None) -> dict:
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
    # §5.11 precedence: the house's name, else the firmware's, else the key.
    # `label_overrides` is the caller's last word on top of that, which is how
    # the v1 relay names were read through before they were migrated.
    overrides = dict(house_labels(db, device.device_id))
    overrides.update(label_overrides or {})
    grants = child_grants(db, child_id, device.device_id) if child_id is not None else None

    out = []
    for cap in caps:
        item = cap.to_dict()
        if overrides.get(cap.key):
            item["label"] = overrides[cap.key]
        if grants is not None:
            # A child is told what they may write, so the app can render a
            # control they cannot use as visibly locked rather than letting them
            # tap it and collect a 403. Reading is house-wide either way (§5.10).
            item["may_write"] = bool(cap.writable and grants.get((device.device_id, cap.key)))
        out.append(item)
    return {
        "proto": device.proto or 1,
        "model": device.model,
        "fw": device.fw,
        "report_every": device.report_every,
        "capabilities": out,
        "state": {k: v for k, v in state.items() if k in {c.key for c in caps}},
    }
