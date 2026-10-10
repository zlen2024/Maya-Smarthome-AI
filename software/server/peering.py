"""Device-to-device grants and their audit trail (PROTOCOL.md §7, step 5a).

The server's part of the local link is deliberately small. It never sees a local
frame — they fly between the two radios — so what it owns is the *decision* (who
may peer, with what scope, until when) and the *record* (what the devices say
happened). Everything else is the devices' job, and `hardware/libraries/Maya`
does it.

This module has no WebSocket and no HTTP in it, so the rules can be tested on
their own (`test_peering.py`); `main.py` adds the endpoints and does the pushing.
"""
import base64
import json
import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

import capability_store
from models import Device, PeerGrant, PeerLogCounter, PeerLogEntry

DEFAULT_EXPIRY_DAYS = 30        # §7.1
MAX_EXPIRY_DAYS = 365
MAX_BATCH = 64                  # §7.3 — entries per peer_log frame
MAX_LOG_PER_HOUSE = 5000        # §7.3 — a device must not be able to fill the database
MAX_COUNT = 1_000_000           # one aggregated entry cannot claim more frames than this
_INT_MAX = 2_147_483_647

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
_GRANT_RE = re.compile(r"^g-(\d{1,9})$")

# Sentinel for "this reporter's total", used for the batch-level `dropped`, which
# is not attributable to a single grant because the dropped entries are gone.
TOTAL = 0


class PairingError(Exception):
    """A refusal the endpoint turns into an HTTP status."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def parse_mac(raw) -> str | None:
    """`AA:BB:CC:DD:EE:FF`, upper-cased, or None. A malformed MAC is dropped
    rather than stored, so a device with a typo is merely unpairable, not broken."""
    if isinstance(raw, str) and _MAC_RE.match(raw.strip()):
        return raw.strip().upper()
    return None


def grant_ref(grant_id: int) -> str:
    return f"g-{grant_id}"


def parse_grant_ref(raw) -> int | None:
    m = _GRANT_RE.match(raw) if isinstance(raw, str) else None
    return int(m.group(1)) if m else None


def _utc(dt: datetime | None) -> datetime | None:
    """SQLite hands datetimes back naive; everything here is UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _iso(dt: datetime) -> str:
    return _utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_active(grant: PeerGrant, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    return grant.revoked_at is None and _utc(grant.expires_at) > now


def _scope(grant: PeerGrant) -> list[str]:
    try:
        value = json.loads(grant.scope)
    except (TypeError, ValueError):
        return []
    return [k for k in value if isinstance(k, str)] if isinstance(value, list) else []


def eligible_keys(db: Session, device_id: str) -> dict:
    """The receiver capabilities a peer may be granted (§7.1): writable, not a
    reserved `_` key, and neither `confirm` nor `agent:"deny"` — those two mean a
    person or at least not an automaton stands between request and action, and a
    peer is an automaton with nobody present."""
    out = {}
    for cap in capability_store.load_capabilities(db, device_id):
        if (cap.writable and cap.known_kind and not cap.key.startswith("_")
                and not cap.confirm and cap.agent == "allow"):
            out[cap.key] = cap
    return out


def _why_not(cap) -> str:
    if cap.key.startswith("_"):
        return "reserved keys cannot be granted"
    if not cap.writable:
        return "read-only"
    if cap.confirm:
        return "it needs a person's confirmation"
    if cap.agent != "allow":
        return "it is hidden from automation"
    return "not eligible"


# ── creating and ending grants ───────────────────────────────────────────────
def create_grant(db: Session, *, house_id: int, from_id: str, to_id: str, scope,
                 expires_days=None, created_by: int | None = None,
                 now: datetime | None = None) -> PeerGrant:
    """Validate and store one grant, replacing any active one for the pair."""
    now = now or datetime.now(timezone.utc)
    if from_id == to_id:
        raise PairingError(400, "A device cannot be paired with itself")

    devices = {}
    for role, device_id in (("sender", from_id), ("receiver", to_id)):
        device = db.query(Device).filter(Device.device_id == device_id).first()
        # Both 404 and "another house" read as "not found": naming a device in
        # someone else's house must not confirm that it exists.
        if not device or device.house_id != house_id:
            raise PairingError(404, f"The {role} is not a device in this house")
        devices[device_id] = device

    # Only once both are known to be this house's: a 409 about a device is an
    # answer about that device, which a caller must not get for someone else's.
    for device in devices.values():
        if device.blocked:
            raise PairingError(409, f"{device.name} is blocked")
        if (device.proto or 1) < 2:
            raise PairingError(409, f"{device.name} speaks protocol 1 and cannot be paired")
        if not device.mac:
            raise PairingError(409, f"{device.name} has not reported its MAC address; "
                                    "it must connect once running the Maya library")

    if expires_days is None:
        expires_days = DEFAULT_EXPIRY_DAYS
    if (not isinstance(expires_days, int) or isinstance(expires_days, bool)
            or not 1 <= expires_days <= MAX_EXPIRY_DAYS):
        raise PairingError(400, f"expires_days must be 1-{MAX_EXPIRY_DAYS}")

    if not isinstance(scope, list) or not scope or not all(isinstance(k, str) for k in scope):
        raise PairingError(400, "scope must be a non-empty list of capability keys")
    scope = list(dict.fromkeys(scope))      # de-duplicated, order kept
    declared = {c.key: c for c in capability_store.load_capabilities(db, to_id)}
    allowed = eligible_keys(db, to_id)
    for key in scope:
        if key not in declared:
            raise PairingError(404, f"{devices[to_id].name} does not declare {key}")
        if key not in allowed:
            raise PairingError(400, f"{key} cannot be granted to a peer: {_why_not(declared[key])}")

    for old in db.query(PeerGrant).filter(PeerGrant.house_id == house_id,
                                          PeerGrant.from_device == from_id,
                                          PeerGrant.to_device == to_id,
                                          PeerGrant.revoked_at.is_(None)).all():
        old.revoked_at = now                # re-pairing replaces; there is no edit

    grant = PeerGrant(
        house_id=house_id, from_device=from_id, to_device=to_id,
        key=base64.b64encode(secrets.token_bytes(32)).decode("ascii"),
        scope=json.dumps(scope), expires_at=now + timedelta(days=expires_days),
        created_by=created_by, created_at=now)
    db.add(grant)
    db.flush()
    return grant


def revoke(db: Session, grant: PeerGrant, now: datetime | None = None) -> bool:
    """True if this call is what ended it."""
    if grant.revoked_at is not None:
        return False
    grant.revoked_at = now or datetime.now(timezone.utc)
    return True


def revoke_for_device(db: Session, device_id: str) -> list[PeerGrant]:
    """§7.4: removing a device, or a factory reset, ends every grant it is in."""
    ended = []
    for g in db.query(PeerGrant).filter(
            ((PeerGrant.from_device == device_id) | (PeerGrant.to_device == device_id)),
            PeerGrant.revoked_at.is_(None)).all():
        if revoke(db, g):
            ended.append(g)
    return ended


def active_grants(db: Session, device_id: str, now: datetime | None = None) -> list[PeerGrant]:
    now = now or datetime.now(timezone.utc)
    rows = db.query(PeerGrant).filter(
        (PeerGrant.from_device == device_id) | (PeerGrant.to_device == device_id),
        PeerGrant.revoked_at.is_(None)).order_by(PeerGrant.grant_id).all()
    return [g for g in rows if is_active(g, now)]


# ── frames pushed to devices ─────────────────────────────────────────────────
def grant_frame(db: Session, grant: PeerGrant, device_id: str) -> dict:
    """The `peer_grant` frame for one end of a grant (§7.1).

    The scope is intersected with what the receiver declares *now* and is still
    eligible: a key it dropped, or has since marked `confirm`, stops being
    granted without anyone editing the grant. The receiver is told the same
    thing when it next identifies, so it never holds a wider scope than the
    server would issue today."""
    other_id = grant.to_device if device_id == grant.from_device else grant.from_device
    other = db.query(Device).filter(Device.device_id == other_id).first()
    live = eligible_keys(db, grant.to_device)
    return {
        "id": device_id, "type": "peer_grant", "grant_id": grant_ref(grant.grant_id),
        "role": "send" if device_id == grant.from_device else "recv",
        "peer": {"id": other_id, "mac": other.mac if other else None},
        "key": grant.key,
        "scope": [k for k in _scope(grant) if k in live],
        "expires": _iso(grant.expires_at),
    }


def sync_frame(device_id: str, grants: list[PeerGrant]) -> dict:
    return {"id": device_id, "type": "peer_sync",
            "grants": [grant_ref(g.grant_id) for g in grants]}


def revoke_frame(device_id: str, grant: PeerGrant) -> dict:
    return {"id": device_id, "type": "peer_revoke", "grant_id": grant_ref(grant.grant_id)}


def grant_summary(db: Session, grant: PeerGrant, now: datetime | None = None) -> dict:
    """What an app may see of a grant. Never the key."""
    names = {d.device_id: d.name for d in db.query(Device).filter(
        Device.device_id.in_([grant.from_device, grant.to_device])).all()}
    return {
        "grant_id": grant_ref(grant.grant_id),
        "from": {"id": grant.from_device, "name": names.get(grant.from_device)},
        "to": {"id": grant.to_device, "name": names.get(grant.to_device)},
        "scope": _scope(grant), "expires": _iso(grant.expires_at),
        "created_at": _iso(grant.created_at) if grant.created_at else None,
        "active": is_active(grant, now),
        "revoked": grant.revoked_at is not None,
    }


# ── audit ────────────────────────────────────────────────────────────────────
def _int(raw, lo=0, hi=_INT_MAX):
    if isinstance(raw, bool) or not isinstance(raw, int) or not lo <= raw <= hi:
        return None
    return raw


def _counter(db: Session, grant_id: int, reporter: str, direction: str, ep: int) -> PeerLogCounter:
    row = db.query(PeerLogCounter).filter(
        PeerLogCounter.grant_id == grant_id, PeerLogCounter.reporter == reporter,
        PeerLogCounter.dir == direction, PeerLogCounter.ep == ep).first()
    if row is None:
        row = PeerLogCounter(grant_id=grant_id, reporter=reporter, dir=direction, ep=ep,
                             claimed=0, logged=0, dropped=0)
        db.add(row)
        db.flush()
    return row


def ingest_log(db: Session, device: Device, frame: dict, now: datetime | None = None) -> dict:
    """Store a `peer_log` batch (§7.3). Returns {"accepted", "rejected", "notable"}.

    An entry is accepted only if the reporter is a party to the grant it names and
    is reporting from the side it is on — the sender says `out`, the receiver says
    `in`. Without that, one end could write the other's half of the story, and the
    cross-check that makes the audit worth having would be worth nothing. Late
    entries for a revoked or expired grant are still taken: a device that was
    offline flushes after the fact, and that is exactly the case that matters.
    """
    now = now or datetime.now(timezone.utc)
    batch = frame.get("batch")
    if not isinstance(batch, list):
        return {"accepted": 0, "rejected": 0, "notable": []}

    overflow = max(0, len(batch) - MAX_BATCH)
    batch = batch[:MAX_BATCH]
    accepted = rejected = 0
    notable = []
    grants: dict[int, PeerGrant | None] = {}

    for entry in batch:
        if not isinstance(entry, dict):
            rejected += 1
            continue
        gid = parse_grant_ref(entry.get("grant"))
        direction = entry.get("dir")
        ep, seq = _int(entry.get("ep", 0)), _int(entry.get("seq"))
        count = _int(entry.get("count", 1), 1, MAX_COUNT)
        if gid is None or direction not in ("in", "out") or ep is None or seq is None or count is None:
            rejected += 1
            continue
        if gid not in grants:
            grants[gid] = db.query(PeerGrant).filter(PeerGrant.grant_id == gid).first()
        grant = grants[gid]
        if grant is None or grant.house_id != device.house_id:
            rejected += 1
            continue
        side = ("out" if device.device_id == grant.from_device else
                "in" if device.device_id == grant.to_device else None)
        if side is None or side != direction:
            rejected += 1
            continue

        text = lambda v, n: v[:n] if isinstance(v, str) else None   # noqa: E731
        result = text(entry.get("result"), 24)
        db.add(PeerLogEntry(
            house_id=grant.house_id, grant_id=gid, reporter=device.device_id, dir=direction,
            ep=ep, seq=seq, count=count, kind=text(entry.get("kind"), 12),
            peer=text(entry.get("peer"), 40), summary=text(entry.get("summary"), 80),
            result=result, received_at=now))
        counter = _counter(db, gid, device.device_id, direction, ep)
        counter.claimed = max(counter.claimed, seq)
        counter.logged += count
        counter.updated_at = now
        accepted += 1
        if result and result != "ok":
            notable.append({"grant": grant_ref(gid), "peer": text(entry.get("peer"), 40),
                            "result": result, "dir": direction})

    dropped = _int(frame.get("dropped", 0)) or 0
    dropped += overflow
    if dropped:
        total = _counter(db, TOTAL, device.device_id, "-", 0)
        total.dropped += dropped
        total.updated_at = now

    if accepted:
        _prune(db, device.house_id)
    return {"accepted": accepted, "rejected": rejected, "notable": notable}


def _prune(db: Session, house_id: int) -> None:
    """Oldest first out, so the log is a window rather than a hole."""
    db.flush()   # the count must see what this very batch just added
    count = db.query(PeerLogEntry).filter(PeerLogEntry.house_id == house_id).count()
    if count <= MAX_LOG_PER_HOUSE:
        return
    stale = db.query(PeerLogEntry.id).filter(PeerLogEntry.house_id == house_id) \
        .order_by(PeerLogEntry.id.asc()).limit(count - MAX_LOG_PER_HOUSE).all()
    db.query(PeerLogEntry).filter(PeerLogEntry.id.in_([r[0] for r in stale])) \
        .delete(synchronize_session=False)


def audit(db: Session, grant: PeerGrant, limit: int = 50) -> dict:
    """What each side says happened on a grant, and where the stories differ.

    `unexplained_gap` is `claimed - logged` for one side and epoch: frames the
    reporter numbered but never accounted for. The reporter's total `dropped`
    (§7.3) is shown beside it as the most overflow could explain, because a
    dropped entry's grant is gone with it and cannot be attributed.
    `cross_check` is the point of both ends reporting: per epoch, the highest
    `seq` the sender claims against the frames the receiver logged. `missing` is
    the difference, and a number there that no `dropped` total explains is a
    frame that was sent and never arrived, or arrived and was never admitted.
    """
    sides = []
    for c in db.query(PeerLogCounter).filter(PeerLogCounter.grant_id == grant.grant_id) \
            .order_by(PeerLogCounter.ep, PeerLogCounter.dir).all():
        total = db.query(PeerLogCounter).filter(
            PeerLogCounter.grant_id == TOTAL, PeerLogCounter.reporter == c.reporter).first()
        sides.append({
            "reporter": c.reporter, "dir": c.dir, "ep": c.ep, "claimed": c.claimed,
            "logged": c.logged, "unexplained_gap": max(0, c.claimed - c.logged),
            "reporter_dropped_total": total.dropped if total else 0})
    entries = db.query(PeerLogEntry).filter(PeerLogEntry.grant_id == grant.grant_id) \
        .order_by(PeerLogEntry.id.desc()).limit(limit).all()
    # The sender numbers frames in its epoch; the receiver reports the same epoch
    # because it is read from the frame. So per epoch the two stories line up.
    by_epoch = {}
    for side in sides:
        row = by_epoch.setdefault(side["ep"], {"ep": side["ep"], "sent_claimed": None,
                                               "received_logged": None})
        if side["dir"] == "out":
            row["sent_claimed"] = side["claimed"]
        else:
            row["received_logged"] = side["logged"]
    cross_check = []
    for row in by_epoch.values():
        sent, got = row["sent_claimed"], row["received_logged"]
        row["missing"] = max(0, sent - got) if sent is not None and got is not None else None
        cross_check.append(row)
    return {
        "grant": grant_summary(db, grant),
        "sides": sides,
        "cross_check": cross_check,
        "entries": [{"reporter": e.reporter, "dir": e.dir, "ep": e.ep, "seq": e.seq,
                     "count": e.count, "kind": e.kind, "peer": e.peer,
                     "summary": e.summary, "result": e.result,
                     "at": _iso(e.received_at) if e.received_at else None} for e in entries],
    }
