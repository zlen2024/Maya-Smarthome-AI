"""Self-check for protocol 2 step 5a: the server half of the local link (§7).

The server never sees a local frame, so what it owns is the decision (who may
peer, with what scope, until when) and the record (what the devices say
happened). This drives both against the real app, with devices played over real
WebSockets.

Run:  python test_peering.py      (needs fastapi, sqlalchemy, httpx<0.28)

The server's own log lines are part of a passing run. The signal is the final OK
line and an exit code of 0.
"""
import base64
import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "peering.db")
os.environ["SECRET_KEY"] = "test-key-not-a-secret"

import time  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

MAC_PROBE = "24:6F:28:AA:BB:01"
MAC_FAN = "24:6F:28:AA:BB:02"

PROBE = {
    "proto": 2, "status": "online", "model": "probe", "fw": "1.0.0", "mac": MAC_PROBE.lower(),
    "capabilities": [{"key": "temp", "kind": "number", "label": "Temperature", "access": "r"}],
    "state": {"temp": 21},
}

FAN = {
    "proto": 2, "status": "online", "model": "fan", "fw": "1.0.0", "mac": MAC_FAN,
    "capabilities": [
        {"key": "speed", "kind": "range", "label": "Speed", "min": 0, "max": 100},
        {"key": "msg", "kind": "text", "label": "Display", "max": 16},
        {"key": "temp", "kind": "number", "label": "Room temp", "access": "r"},
        {"key": "reset", "kind": "button", "label": "Reset", "agent": "deny"},
        {"key": "lock", "kind": "switch", "label": "Lock", "confirm": True},
    ],
    "state": {"speed": 0},
}


def household(c, email, house, devices):
    """A master, a house, and claimed devices: [(id, pin)]. Returns (headers, ...)."""
    import main
    main.REGISTER_RATE.clear_all()
    r = c.post("/api/auth/register", json={"email": email, "password": "owner-pass", "name": "Owner"})
    assert r.status_code == 200, r.text
    tok = {"Authorization": "Bearer " + r.json()["token"]}
    c.post("/api/houses", json={"location": house}, headers=tok)
    for device_id, pin in devices:
        reg = c.post("/api/devices/register", json={"device_id": device_id, "name": device_id, "pin": pin},
                     headers=tok)
        assert reg.status_code == 200, reg.text
    return tok


class Board:
    """A device on a real WebSocket. Frames the server pushed are read in order."""

    def __init__(self, c, device_id, pin, frame):
        self.id = device_id
        self.session = c.websocket_connect("/ws")
        self.ws = self.session.__enter__()
        self.ws.send_json({"id": device_id, "pin": pin, **frame})
        self.welcome = self.ws.receive_json()
        assert self.welcome["type"] == "welcome", self.welcome
        self.boot = []
        if frame.get("proto", 1) >= 2:
            # every active grant, then peer_sync: read up to and including it
            while True:
                f = self.ws.receive_json()
                self.boot.append(f)
                if f["type"] == "peer_sync":
                    break

    def next(self):
        return self.ws.receive_json()

    def send(self, obj):
        self.ws.send_json({"id": self.id, **obj})

    def close(self):
        for step in (self.ws.close, lambda: self.session.__exit__(None, None, None)):
            try:
                step()
            except Exception:
                pass


def wait_for(read, done, attempts=60, delay=0.05):
    value = read()
    for _ in range(attempts):
        if done(value):
            return value
        time.sleep(delay)
        value = read()
    return value


def pair(c, tok, from_id="esp32-probe", to_id="esp32-fan", scope=("speed",), **extra):
    return c.post("/api/peerings", json={"from": from_id, "to": to_id, "scope": list(scope), **extra},
                  headers=tok)


# ── §7.1 who may pair, and what may be granted ────────────────
def test_grants_and_refusals():
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    tok = household(c, "p1@x.test", "Peer House",
                    [("esp32-probe", "4821"), ("esp32-fan", "5937"), ("esp32-old", "6143")])
    probe = Board(c, "esp32-probe", "4821", PROBE)
    fan = Board(c, "esp32-fan", "5937", FAN)
    old = Board(c, "esp32-old", "6143", {"status": "online", "ch1": "off", "ch2": "off", "ch3": "off"})
    try:
        # A protocol-1 device has no way to take part, and says so.
        r = pair(c, tok, to_id="esp32-old", scope=("ch1",))
        assert r.status_code == 409 and "protocol 1" in r.json()["detail"], r.text

        # Nothing was pushed to a fresh device: just an empty peer_sync.
        assert probe.boot == [{"id": "esp32-probe", "type": "peer_sync", "grants": []}], probe.boot

        # The happy path.
        r = pair(c, tok)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["from"]["id"] == "esp32-probe" and body["to"]["id"] == "esp32-fan"
        assert body["scope"] == ["speed"] and body["active"] is True
        assert sorted(body["delivered_to"]) == ["esp32-fan", "esp32-probe"]
        assert "key" not in body, "the key must never be returned to an app"

        sent, got = probe.next(), fan.next()
        assert (sent["type"], sent["role"]) == ("peer_grant", "send"), sent
        assert (got["type"], got["role"]) == ("peer_grant", "recv"), got
        assert sent["grant_id"] == got["grant_id"] == body["grant_id"]
        assert sent["key"] == got["key"], "both ends share one key"
        assert len(base64.b64decode(got["key"])) == 32
        # Each end is told its *peer's* id and MAC, upper-cased.
        assert sent["peer"] == {"id": "esp32-fan", "mac": MAC_FAN}, sent["peer"]
        assert got["peer"] == {"id": "esp32-probe", "mac": MAC_PROBE}, got["peer"]
        assert sent["scope"] == got["scope"] == ["speed"]
        expires = datetime.strptime(got["expires"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        assert timedelta(days=29, hours=23) < expires - datetime.now(timezone.utc) <= timedelta(days=30), got["expires"]

        # Refusals — each one a way to widen reach that §7.1 closes.
        for scope, status, needle in [
                (["nope"], 404, "does not declare"),
                (["temp"], 400, "read-only"),                    # reading is not grantable
                (["reset"], 400, "hidden from automation"),     # agent:"deny"
                (["lock"], 400, "confirmation"),                # confirm:true
                ([], 400, "non-empty"),
                (["speed", 3], 400, "non-empty")]:
            r = pair(c, tok, scope=scope)
            assert (r.status_code, needle in r.json()["detail"]) == (status, True), (scope, r.status_code, r.text)
        for days in (0, 366, "30", True):
            assert pair(c, tok, expires_days=days).status_code == 400, days
        assert pair(c, tok, from_id="esp32-fan", to_id="esp32-fan").status_code == 400
        assert pair(c, tok, from_id="esp32-nobody").status_code == 404

        # A device in someone else's house is "not found", not "forbidden": naming
        # it must not confirm that it exists.
        tok2 = household(c, "p2@x.test", "Other House", [("esp32-stranger", "7351")])
        r = pair(c, tok, from_id="esp32-stranger")
        assert r.status_code == 404, r.text
        assert pair(c, tok2, from_id="esp32-stranger", to_id="esp32-fan").status_code == 404

        # Children cannot pair.
        kid = c.post("/api/children", json={"name": "Kid", "pin": "8317"}, headers=tok).json()["child_id"]
        ktok = {"Authorization": "Bearer " + c.post(f"/api/children/{kid}/login",
                                                    json={"pin": "8317"}).json()["token"]}
        assert pair(c, ktok).status_code in (401, 403)
        assert c.get("/api/peerings", headers=ktok).status_code in (401, 403)
    finally:
        for b in (probe, fan, old):
            b.close()
    print("  pairing: key never returned, one shared 32-byte key, MACs exchanged, role per end;")
    print("           refused: protocol 1, unknown/read-only/confirm/agent:deny keys, bad expiry,")
    print("           other-house devices (as not-found), children")


def test_repair_replaces_and_sync_corrects():
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    tok = household(c, "p3@x.test", "Sync House", [("esp32-probe", "4821"), ("esp32-fan", "5937")])
    probe = Board(c, "esp32-probe", "4821", PROBE)
    fan = Board(c, "esp32-fan", "5937", FAN)
    try:
        first = pair(c, tok).json()
        g1_probe, g1_fan = probe.next(), fan.next()

        # Re-pairing replaces: new id, new key, and both ends are told the old one is gone.
        second = pair(c, tok, scope=("speed", "msg")).json()
        assert second["grant_id"] != first["grant_id"]
        for b in (probe, fan):
            got = b.next()
            assert got == {"id": b.id, "type": "peer_revoke", "grant_id": first["grant_id"]}, got
        g2_probe, g2_fan = probe.next(), fan.next()
        assert g2_probe["key"] != g1_probe["key"], "re-pairing must rotate the key"
        assert g2_fan["scope"] == ["speed", "msg"]
        listed = c.get("/api/peerings", headers=tok).json()["peerings"]
        assert [p["grant_id"] for p in listed] == [second["grant_id"]], listed
        assert g1_fan["key"] not in str(listed) and g2_fan["key"] not in str(listed)

        # The fan drops off the network; the grant is revoked while it is away,
        # so it never hears peer_revoke.
        fan.close()
        r = c.delete(f"/api/peerings/{second['grant_id']}", headers=tok)
        assert r.status_code == 200, r.text
        assert probe.next()["type"] == "peer_revoke"          # the connected end is told at once
        assert c.get("/api/peerings", headers=tok).json()["peerings"] == []

        # On reconnect the server says what is actually active — nothing — which
        # is how it learns the grant it still holds is dead (§7.1 peer_sync).
        fan = Board(c, "esp32-fan", "5937", FAN)
        assert fan.boot == [{"id": "esp32-fan", "type": "peer_sync", "grants": []}], fan.boot

        # A live grant arrives on reconnect, before the sync that lists it.
        third = pair(c, tok).json()
        probe.next()
        fan.next()
        fan.close()
        fan = Board(c, "esp32-fan", "5937", FAN)
        kinds = [f["type"] for f in fan.boot]
        assert kinds == ["peer_grant", "peer_sync"], kinds
        assert fan.boot[1]["grants"] == [third["grant_id"]]

        # Scope follows the receiver's *current* declaration. The fan's next build
        # marks `speed` confirm:true — the grant must stop covering it with nobody
        # editing the grant (§7.1: a firmware update must never widen a peer's reach).
        fan.close()
        tightened = dict(FAN, capabilities=[dict(x, confirm=True) if x["key"] == "speed" else x
                                            for x in FAN["capabilities"]])
        fan = Board(c, "esp32-fan", "5937", tightened)
        assert fan.boot[0]["scope"] == [], fan.boot[0]

        # An expired grant is absent: not synced, not listed.
        db = main.SessionLocal()
        try:
            g = db.query(main.PeerGrant).filter(main.PeerGrant.grant_id == int(third["grant_id"][2:])).first()
            g.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            db.commit()
        finally:
            db.close()
        fan.close()
        fan = Board(c, "esp32-fan", "5937", FAN)
        assert fan.boot == [{"id": "esp32-fan", "type": "peer_sync", "grants": []}], fan.boot
        assert c.get("/api/peerings", headers=tok).json()["peerings"] == []
    finally:
        for b in (probe, fan):
            b.close()
    print("  re-pair: replaces and rotates the key, both ends told; a revoke missed offline is")
    print("           corrected by peer_sync; scope tracks the receiver's declaration; expiry honoured")


# ── §7.3 audit ────────────────────────────────────────────────
def entry(grant, direction, ep, seq, **kw):
    return {"grant": grant, "dir": direction, "ep": ep, "seq": seq, "kind": "set",
            "peer": "esp32-fan" if direction == "out" else "esp32-probe",
            "summary": "speed=60", "result": "ok", **kw}


def test_audit():
    from fastapi.testclient import TestClient
    import main
    import peering

    c = TestClient(main.app)
    main.PEER_LOG_RATE.clear_all()
    tok = household(c, "p4@x.test", "Audit House",
                    [("esp32-probe", "4821"), ("esp32-fan", "5937"), ("esp32-third", "6143")])
    third_frame = dict(PROBE, mac="24:6F:28:AA:BB:03")
    probe = Board(c, "esp32-probe", "4821", PROBE)
    fan = Board(c, "esp32-fan", "5937", FAN)
    third = Board(c, "esp32-third", "6143", third_frame)
    try:
        g = pair(c, tok).json()["grant_id"]
        probe.next(), fan.next()

        def audit():
            return c.get(f"/api/peerings/{g}/audit", headers=tok).json()

        # The sender claims 118 frames in epoch 7, aggregated into two entries; the
        # receiver only admits to having seen 100.
        probe.send({"type": "peer_log", "boot_id": "b-1", "batch": [
            entry(g, "out", 7, 100, count=100), entry(g, "out", 7, 118, count=18)]})
        fan.send({"type": "peer_log", "boot_id": "b-2", "dropped": 3, "batch": [
            entry(g, "in", 7, 100, count=100)]})
        a = wait_for(audit, lambda x: len(x["sides"]) == 2)
        sides = {(s["reporter"], s["dir"]): s for s in a["sides"]}
        assert sides[("esp32-probe", "out")]["claimed"] == 118
        assert sides[("esp32-probe", "out")]["logged"] == 118
        assert sides[("esp32-fan", "in")]["logged"] == 100
        assert sides[("esp32-fan", "in")]["reporter_dropped_total"] == 3
        # The point of both ends reporting: 18 frames that were sent and never admitted.
        assert a["cross_check"] == [{"ep": 7, "sent_claimed": 118, "received_logged": 100, "missing": 18}], a["cross_check"]

        # A side whose numbers do not add up is visible on its own.
        probe.send({"type": "peer_log", "batch": [entry(g, "out", 8, 400, count=120)]})
        a = wait_for(audit, lambda x: any(s["ep"] == 8 for s in x["sides"]))
        ep8 = [s for s in a["sides"] if s["ep"] == 8][0]
        assert (ep8["claimed"], ep8["logged"], ep8["unexplained_gap"]) == (400, 120, 280), ep8

        # Entries from the wrong side, a non-party, another house, an unknown grant,
        # and malformed values are all refused — none can write the other end's story.
        bad = [
            entry(g, "out", 9, 1),                     # the *receiver* claiming to have sent
            entry("g-9999", "in", 9, 1),               # a grant that does not exist
            entry(g, "in", 9, -5),                     # negative seq
            entry(g, "in", 9, 1, count=0),             # a frame count of zero
            entry(g, "sideways", 9, 1),                # not in/out
            entry("garbage", "in", 9, 1),
            "not an object",
        ]
        fan.send({"type": "peer_log", "batch": bad})
        third.send({"type": "peer_log", "batch": [entry(g, "in", 9, 1), entry(g, "out", 9, 1)]})
        time.sleep(0.4)
        assert not [s for s in audit()["sides"] if s["ep"] == 9], "a refused entry must leave no trace"

        # A refused frame is the interesting one: it reaches the house activity log.
        fan.send({"type": "peer_log", "batch": [entry(g, "in", 10, 1, result="not_permitted")]})
        wait_for(audit, lambda x: any(s["ep"] == 10 for s in x["sides"]))
        lines = wait_for(
            lambda: [a for a in c.get("/api/activity?limit=100", headers=tok).json()["activity"]
                     if a["action"] == "peer_result"],
            lambda rows: rows)
        assert lines and "not_permitted" in lines[0]["summary"], lines
        assert lines[0]["actor_type"] == "device", lines

        # A longer batch than 64 is truncated and the excess counted as dropped.
        db = main.SessionLocal()
        try:
            fan_row = db.query(main.Device).filter(main.Device.device_id == "esp32-fan").first()
            out = peering.ingest_log(db, fan_row, {"batch": [entry(g, "in", 11, i + 1) for i in range(70)]})
            db.commit()
            assert out["accepted"] == 64, out
            total = db.query(main.PeerLogCounter).filter(
                main.PeerLogCounter.grant_id == 0, main.PeerLogCounter.reporter == "esp32-fan").first()
            assert total.dropped == 3 + 6, total.dropped   # the 3 reported earlier, plus 6 truncated

            # Retention: a device must not be able to fill the database.
            for start in range(0, 5200, 60):
                peering.ingest_log(db, fan_row, {"batch": [entry(g, "in", 12, start + i + 1)
                                                           for i in range(60)]})
            db.commit()
            kept = db.query(main.PeerLogEntry).filter(
                main.PeerLogEntry.house_id == fan_row.house_id).count()
            assert kept == peering.MAX_LOG_PER_HOUSE, kept
        finally:
            db.close()

        # The key appears in no response a person can read.
        assert "key" not in audit(), "audit must not carry the key"
    finally:
        for b in (probe, fan, third):
            b.close()
    print("  audit: both ends reported, cross-check shows the 18 frames that never arrived, a side's")
    print("         own gap shown, wrong-side/non-party/malformed entries leave no trace, batch capped,")
    print("         retention bounded")


def test_peer_log_rate_limit():
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    main.PEER_LOG_RATE.clear_all()
    tok = household(c, "p5@x.test", "Rate House", [("esp32-probe", "4821"), ("esp32-fan", "5937")])
    probe = Board(c, "esp32-probe", "4821", PROBE)
    fan = Board(c, "esp32-fan", "5937", FAN)
    try:
        g = pair(c, tok).json()["grant_id"]
        probe.next(), fan.next()
        for i in range(15):
            probe.send({"type": "peer_log", "batch": [entry(g, "out", 1, i + 1)]})
        a = wait_for(lambda: c.get(f"/api/peerings/{g}/audit", headers=tok).json(),
                     lambda x: x["sides"] and x["sides"][0]["logged"] >= 12)
        time.sleep(0.3)
        a = c.get(f"/api/peerings/{g}/audit", headers=tok).json()
        assert a["sides"][0]["logged"] == 12, a["sides"]
    finally:
        probe.close()
        fan.close()
    print("  rate limit: a device's 13th peer_log inside a minute is dropped")


def test_removing_a_device_ends_its_grants():
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    tok = household(c, "p6@x.test", "Delete House", [("esp32-probe", "4821"), ("esp32-fan", "5937")])
    probe = Board(c, "esp32-probe", "4821", PROBE)
    fan = Board(c, "esp32-fan", "5937", FAN)
    try:
        g = pair(c, tok).json()["grant_id"]
        probe.next(), fan.next()
        assert c.delete("/api/devices/esp32-fan", headers=tok).status_code == 200
        # The fan is told to factory-reset; the *other* end is told the grant is gone.
        assert probe.next() == {"id": "esp32-probe", "type": "peer_revoke", "grant_id": g}
        assert c.get("/api/peerings", headers=tok).json()["peerings"] == []
        assert c.get(f"/api/peerings/{g}/audit", headers=tok).status_code == 200   # the record outlives the pairing
    finally:
        probe.close()
        fan.close()
    print("  removal: deleting a device revokes its grants and tells the other end; the audit survives")


def test_reclaiming_into_another_house_ends_grants():
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    tok = household(c, "p7@x.test", "First House", [("esp32-probe", "4821"), ("esp32-fan", "5937")])
    probe = Board(c, "esp32-probe", "4821", PROBE)
    fan = Board(c, "esp32-fan", "5937", FAN)
    try:
        g = pair(c, tok).json()["grant_id"]
        probe.next(), fan.next()

        # Another house claims the fan. The first house's decision to let the probe
        # address it must not follow the fan into a house that never made it.
        tok2 = household(c, "p8@x.test", "Second House", [("esp32-fan", "5937")])
        assert probe.next() == {"id": "esp32-probe", "type": "peer_revoke", "grant_id": g}
        assert c.get("/api/peerings", headers=tok).json()["peerings"] == []
        # ...and the old house can no longer read that audit.
        assert c.get(f"/api/peerings/{g}/audit", headers=tok2).status_code == 404
    finally:
        probe.close()
        fan.close()
    print("  re-claim: a device that changes house takes no peering with it")


if __name__ == "__main__":
    test_grants_and_refusals()
    test_repair_replaces_and_sync_corrects()
    test_audit()
    test_peer_log_rate_limit()
    test_removing_a_device_ends_its_grants()
    test_reclaiming_into_another_house_ends_grants()
    print("OK: grants are explicit, one-way and finite; revokes are corrected on reconnect; "
          "the audit compares both ends")
