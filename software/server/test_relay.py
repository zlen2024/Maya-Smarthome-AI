"""Self-check for protocol 2 step 7a: the hub relay, server half (PROTOCOL.md §5.9, §7.5).

A sensor with no WiFi of its own sends a signed local frame to a hub over ESP-NOW;
the hub carries it to the server, which checks the MAC itself with the grant key and
applies the reading as the sensor's own. What matters, and what this drives:

  * only a device that said it is a hub may be paired as one, and only by a person;
  * the hub is a courier, not a witness - a frame it alters, replays, reorders,
    re-labels or carries for someone else's sensor is refused;
  * a relay grant is not "reach": it gives an agent-capable sensor nothing over the hub;
  * the hub's channel and a sensor's "my hub is dead" are passed on, once.

Frames are built here from the spec's own recipe (HMAC-SHA256 over the exact bytes,
16 bytes, base64url) rather than by the server's code, so the two cannot agree on a
mistake.

Run:  python test_relay.py      (needs fastapi, sqlalchemy, httpx<0.28)
"""
import base64
import hashlib
import hmac
import json
import time

from test_peering import Board, household, pair, wait_for  # noqa: E402  (sets the test DB up)

from datetime import datetime, timedelta, timezone  # noqa: E402

MAC_HUB = "24:6F:28:AA:CC:01"
MAC_SALT = "24:6F:28:AA:CC:02"
MAC_TANK = "24:6F:28:AA:CC:03"

HUB = {
    "proto": 2, "status": "online", "model": "ext_hub", "fw": "1.0.0", "mac": MAC_HUB, "hub": True,
    "capabilities": [
        {"key": "out1", "kind": "switch", "label": "Channel 1"},
        # The same name as a key the salt jar reports: a relay grant's scope names the
        # jar's keys, and must never be read as reach over this one.
        {"key": "salt", "kind": "range", "label": "Salt dispenser", "min": 0, "max": 100},
    ],
    "state": {"out1": False},
}

SALT = {
    "proto": 2, "status": "online", "model": "salt_jar", "fw": "1.0.0", "mac": MAC_SALT,
    "capabilities": [
        {"key": "salt", "kind": "number", "label": "Salt left", "unit": "%", "access": "r"},
        {"key": "_batt", "kind": "number", "label": "Battery", "unit": "%", "access": "r"},
        {"key": "led", "kind": "switch", "label": "Status LED", "access": "w"},   # write-only: nothing to report
        {"key": "tare", "kind": "button", "label": "Tare"},
    ],
    "state": {"salt": 50},
}

TANK = {
    "proto": 2, "status": "online", "model": "tank", "fw": "1.0.0", "mac": MAC_TANK,
    "capabilities": [
        {"key": "level", "kind": "number", "label": "Level", "access": "r"},
        {"key": "temp", "kind": "number", "label": "Temperature", "access": "r"},   # readable, left out of the grant
    ],
    "state": {"level": 10},
}


def tag(key_b64, body):
    mac = hmac.new(base64.b64decode(key_b64), body.encode(), hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def local_frame(grant, key, frm, ep, seq, values, kind="report", age=None, **extra):
    """A frame as a radio would carry it: the JSON text, a dot, the MAC."""
    obj = {"v": 2, "from": frm, "grant": grant, "ep": ep, "seq": seq, "kind": kind,
           "values": values, **extra}
    if age is not None:
        obj["age"] = age
    body = json.dumps(obj, separators=(",", ":"))
    return body + "." + tag(key, body)


def relay(hub, frames):
    hub.send({"type": "relay", "frames": frames})
    ack = hub.next()
    assert ack["type"] == "relay_ack", ack
    return ack


def statuses(ack):
    return [r["status"] for r in ack["results"]]


def state_of(device_id):
    import main
    import capability_store
    db = main.SessionLocal()
    try:
        return capability_store.load_state(db, device_id)
    finally:
        db.close()


def activity(house_name_device, action):
    import main
    db = main.SessionLocal()
    try:
        dev = db.query(main.Device).filter(main.Device.device_id == house_name_device).first()
        return [a.summary for a in db.query(main.ActivityLog).filter(
            main.ActivityLog.house_id == dev.house_id, main.ActivityLog.action == action).all()]
    finally:
        db.close()


def pair_relay(c, tok, sensor, hub, scope, **extra):
    return pair(c, tok, from_id=sensor, to_id=hub, scope=scope, purpose="relay", **extra)


def grant_and_key(sensor_board, hub_board):
    """Read the peer_grant each end was pushed. Only the sensor has the key."""
    s, h = sensor_board.next(), hub_board.next()
    assert s["type"] == h["type"] == "peer_grant" and s["grant_id"] == h["grant_id"], (s, h)
    assert "key" not in h, "the hub is a courier: a key it held would let it sign for the sensor"
    assert len(base64.b64decode(s["key"])) == 32
    return s, h


# ── §7.5 who may be a hub, and what may be relayed ────────────
def test_pairing_a_relay():
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    tok = household(c, "r1@x.test", "Relay House",
                    [("esp32-hub", "4821"), ("esp32-salt", "5937"), ("esp32-plain", "6143")])
    hub = Board(c, "esp32-hub", "4821", HUB)
    salt = Board(c, "esp32-salt", "5937", SALT)
    plain = Board(c, "esp32-plain", "6143", {**HUB, "hub": False, "mac": "24:6F:28:AA:CC:09"})
    try:
        # A device that did not say it is a hub cannot be paired as one.
        r = pair_relay(c, tok, "esp32-salt", "esp32-plain", ["salt"])
        assert r.status_code == 409 and "hub" in r.json()["detail"], r.text

        # Refusals specific to a relay: the scope is the SENDER's readable keys.
        for scope, status, needle in [
                (["led"], 400, "cannot be read"),         # write-only
                (["tare"], 400, "cannot be read"),        # a button reports nothing
                (["out1"], 404, "does not declare"),       # the hub's key, not the sensor's
                (["nope"], 404, "does not declare"),
                ([], 400, "non-empty")]:
            r = pair_relay(c, tok, "esp32-salt", "esp32-hub", scope)
            assert (r.status_code, needle in r.json()["detail"]) == (status, True), (scope, r.text)
        assert pair(c, tok, from_id="esp32-salt", to_id="esp32-hub", scope=["salt"],
                    purpose="smoke-signal").status_code == 400

        r = pair_relay(c, tok, "esp32-salt", "esp32-hub", ["salt", "_batt"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["purpose"] == "relay" and body["scope"] == ["salt", "_batt"]
        assert "key" not in body

        sent, got = grant_and_key(salt, hub)
        assert (sent["role"], got["role"]) == ("send", "recv")
        assert got["peer"] == {"id": "esp32-salt", "mac": MAC_SALT}, "the hub still learns the sensor's MAC"
        assert sent["purpose"] == got["purpose"] == "relay", "an old library must be able to tell and ignore it"
        assert sent["scope"] == got["scope"] == ["salt", "_batt"], "scope names the SENDER's keys"
        assert sent["peer"] == {"id": "esp32-hub", "mac": MAC_HUB}, "no channel known yet"

        # A control grant is a different thing and does not displace it, nor the reverse.
        r = pair(c, tok, from_id="esp32-salt", to_id="esp32-hub", scope=["out1"])
        assert r.status_code == 200, r.text
        control = hub.next()
        assert control["type"] == "peer_grant" and "purpose" not in control, control
        salt.next()
        assert {g["purpose"] for g in c.get("/api/peerings", headers=tok).json()["peerings"]} == {"relay", "control"}

        # Re-pairing the relay replaces the relay only.
        r = pair_relay(c, tok, "esp32-salt", "esp32-hub", ["salt"])
        assert r.status_code == 200
        replaced = [hub.next(), hub.next()]      # a revoke of the old relay, then the new grant
        assert {f["type"] for f in replaced} == {"peer_revoke", "peer_grant"}, replaced
        live = c.get("/api/peerings", headers=tok).json()["peerings"]
        assert sorted((g["purpose"], tuple(g["scope"])) for g in live) == [
            ("control", ("out1",)), ("relay", ("salt",))], live
    finally:
        for b in (hub, salt, plain):
            b.close()
    print("  pairing: only a device that said it is a hub; scope is the sender's readable keys (writable, button,")
    print("           the hub's own keys refused); purpose marked on the wire; control and relay coexist")


# ── §7.5 the hub is a courier, not a witness ───────────────────
def test_relaying_and_forgery():
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    main.RELAY_RATE.clear_all()
    tok = household(c, "r2@x.test", "Courier House",
                    [("esp32-hub", "4821"), ("esp32-salt", "5937"), ("esp32-tank", "6143")])
    hub = Board(c, "esp32-hub", "4821", HUB)
    salt = Board(c, "esp32-salt", "5937", SALT)
    tank = Board(c, "esp32-tank", "6143", TANK)
    try:
        assert pair_relay(c, tok, "esp32-salt", "esp32-hub", ["salt", "_batt"]).status_code == 200
        assert pair_relay(c, tok, "esp32-tank", "esp32-hub", ["level"]).status_code == 200
        sg, _ = grant_and_key(salt, hub)
        tg, _ = grant_and_key(tank, hub)
        g, k = sg["grant_id"], sg["key"]
        tgid, tkey = tg["grant_id"], tg["key"]

        # The good path. 21.5 has a dot of its own: the MAC is split off at the LAST one.
        ack = relay(hub, [local_frame(g, k, "esp32-salt", 1, 1, {"salt": 21.5, "_batt": 88})])
        assert ack["results"] == [{"grant": g, "seq": 1, "status": "ok"}], ack
        assert state_of("esp32-salt")["salt"] == 21.5 and state_of("esp32-salt")["_batt"] == 88
        assert set(state_of("esp32-hub")) == {"out1"}, "attributed to the origin, not the hub"

        # Altered by the hub: the old MAC no longer fits.
        good = local_frame(g, k, "esp32-salt", 1, 2, {"salt": 10})
        body, mac = good.rsplit(".", 1)
        forged = body.replace('"salt":10', '"salt":99') + "." + mac
        assert statuses(relay(hub, [forged])) == ["bad_mac"]
        # Signed with some other key (the hub made it up).
        wrong = local_frame(g, base64.b64encode(b"k" * 32).decode(), "esp32-salt", 1, 2, {"salt": 99})
        assert statuses(relay(hub, [wrong])) == ["bad_mac"]
        assert state_of("esp32-salt")["salt"] == 21.5, "nothing from a refused frame is stored"

        # Replays and reordering: (ep, seq) must be strictly greater than the last accepted.
        assert statuses(relay(hub, [good])) == ["ok"]                                   # seq 2
        assert statuses(relay(hub, [good])) == ["replay"]                               # the same again
        assert statuses(relay(hub, [local_frame(g, k, "esp32-salt", 1, 1, {"salt": 5})])) == ["replay"]
        assert state_of("esp32-salt")["salt"] == 10
        # A reboot is newer, not a replay: a higher epoch restarts seq.
        assert statuses(relay(hub, [local_frame(g, k, "esp32-salt", 2, 1, {"salt": 9})])) == ["ok"]
        assert statuses(relay(hub, [local_frame(g, k, "esp32-salt", 1, 99, {"salt": 1})])) == ["replay"], \
            "an old epoch stays old however high its seq"

        # Not the right kind, not from the grant's sensor, not version 2, not enough bytes.
        assert statuses(relay(hub, [local_frame(g, k, "esp32-salt", 2, 2, {"salt": 8}, kind="set")])) == ["bad_frame"]
        assert statuses(relay(hub, [local_frame(g, k, "esp32-tank", 2, 2, {"salt": 8})])) == ["bad_frame"]
        v1 = json.dumps({"v": 1, "from": "esp32-salt", "grant": g, "ep": 2, "seq": 2, "kind": "report",
                         "values": {"salt": 8}}, separators=(",", ":"))
        assert statuses(relay(hub, [v1 + "." + tag(k, v1)])) == ["bad_frame"]
        assert statuses(relay(hub, ["not a frame", 7, None, "{}.abc", ""])) == [
            "bad_frame", "bad_frame", "bad_frame", "unknown_grant", "bad_frame"]
        assert statuses(relay(hub, [local_frame(g, k, "esp32-salt", 2, 2, {"salt": 8}, pad="x" * 250)])) == ["bad_frame"], \
            "a frame no radio could have carried"

        # A frame that was consumed but changed nothing still moves the counter forward.
        assert statuses(relay(hub, [local_frame(g, k, "esp32-salt", 2, 2, {"led": True})])) == ["not_permitted"]
        assert statuses(relay(hub, [local_frame(g, k, "esp32-salt", 2, 2, {"salt": 7})])) == ["replay"]

        # Scope: what is in it is kept, what is not is named and dropped.
        ack = relay(hub, [local_frame(g, k, "esp32-salt", 2, 3, {"salt": 6, "led": True, "ghost": 1})])
        assert ack["results"][0]["status"] == "ok" and ack["results"][0]["ignored"] == ["ghost", "led"], ack
        assert state_of("esp32-salt")["salt"] == 6 and state_of("esp32-salt").get("led") is None
        # A readable key the person did not put in the grant is not carried either.
        ack = relay(hub, [local_frame(tgid, tkey, "esp32-tank", 1, 1, {"level": 12, "temp": 30})])
        assert ack["results"][0]["status"] == "ok" and ack["results"][0]["ignored"] == ["temp"], ack
        assert "temp" not in state_of("esp32-tank") and state_of("esp32-tank")["level"] == 12
        # Right key, wrong type: nothing accepted.
        assert statuses(relay(hub, [local_frame(g, k, "esp32-salt", 2, 4, {"salt": "lots"})])) == ["bad_value"]

        # Two sensors in one message, in order, each against its own grant.
        ack = relay(hub, [local_frame(g, k, "esp32-salt", 2, 5, {"salt": 5}),
                          local_frame(tgid, tkey, "esp32-tank", 1, 2, {"level": 77})])
        assert statuses(ack) == ["ok", "ok"] and state_of("esp32-tank")["level"] == 77
        # A grant for one sensor cannot be used to speak for the other.
        assert statuses(relay(hub, [local_frame(tgid, tkey, "esp32-salt", 1, 3, {"salt": 1})])) == ["bad_frame"]

        # Buffered readings (§5.9 rule 4): age places the reading in the past, and a
        # late one never lies on top of a fresher one.
        assert statuses(relay(hub, [local_frame(g, k, "esp32-salt", 2, 6, {"salt": 4}, age=3600)])) == ["bad_value"], \
            "a reading from an hour ago must not replace one from just now"
        assert state_of("esp32-salt")["salt"] == 5
        assert statuses(relay(hub, [local_frame(g, k, "esp32-salt", 2, 7, {"salt": 3}, age=8 * 86400)])) == ["bad_frame"]
        assert statuses(relay(hub, [local_frame(g, k, "esp32-salt", 2, 7, {"salt": 3}, age=-1)])) == ["bad_frame"]
        old_age = local_frame(tgid, tkey, "esp32-tank", 1, 3, {"level": 60}, age=120)
        assert statuses(relay(hub, [old_age])) == ["bad_value"], "tank was written moments ago"

        # More than 16 frames in one message: the rest are ignored, not queued.
        many = [local_frame(g, k, "esp32-salt", 3, n, {"salt": n}) for n in range(1, 21)]
        ack = relay(hub, many)
        assert len(ack["results"]) == 16, len(ack["results"])
    finally:
        for b in (hub, salt, tank):
            b.close()
    print("  relay: a frame is accepted only with a valid MAC, a newer (ep, seq), the grant's own sensor, scope;")
    print("         altered/foreign-key/replayed/older-epoch/wrong-kind/v1/oversize frames refused; values attributed to")
    print("         the sensor; late readings never overwrite fresher ones; at most 16 frames a message")


# ── whose hub, whose house, and for how long ───────────────────
def test_relay_authority():
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    main.RELAY_RATE.clear_all()
    tok = household(c, "r3@x.test", "Own House",
                    [("esp32-hub", "4821"), ("esp32-salt", "5937"), ("esp32-hub2", "6143")])
    tok2 = household(c, "r4@x.test", "Rival House", [("esp32-rival", "7351")])
    hub = Board(c, "esp32-hub", "4821", HUB)
    salt = Board(c, "esp32-salt", "5937", SALT)
    hub2 = Board(c, "esp32-hub2", "6143", {**HUB, "mac": "24:6F:28:AA:CC:07"})
    rival = Board(c, "esp32-rival", "7351", {**HUB, "mac": "24:6F:28:AA:CC:08"})
    try:
        assert pair_relay(c, tok, "esp32-salt", "esp32-hub", ["salt"]).status_code == 200
        sg, _ = grant_and_key(salt, hub)
        g, k = sg["grant_id"], sg["key"]

        # Another hub in the same house, and a hub in someone else's house, holding a
        # captured frame: neither is the grant's receiver. The answer is the same for
        # "no such grant" and "not yours", so they cannot probe which exist.
        frame = local_frame(g, k, "esp32-salt", 1, 1, {"salt": 30})
        assert statuses(relay(hub2, [frame])) == ["unknown_grant"]
        assert statuses(relay(rival, [frame])) == ["unknown_grant"]
        assert statuses(relay(hub, [local_frame("g-424242", k, "esp32-salt", 1, 1, {"salt": 30})])) == ["unknown_grant"]
        assert state_of("esp32-salt") == {"salt": 50}

        # A hub that has since been claimed into another house carries nothing for this one.
        db = main.SessionLocal()
        try:
            hub_row = db.query(main.Device).filter(main.Device.device_id == "esp32-hub").first()
            home = hub_row.house_id
            hub_row.house_id = db.query(main.Device).filter(main.Device.device_id == "esp32-rival").first().house_id
            db.commit()
            assert statuses(relay(hub, [frame])) == ["unknown_grant"]
            hub_row.house_id = home
            db.commit()
        finally:
            db.close()

        # A relay grant is not reach: an agent-capable sensor gains nothing over the hub.
        db = main.SessionLocal()
        try:
            db.query(main.Device).filter(main.Device.device_id == "esp32-salt").first().can_invoke_agent = True
            db.commit()
            assert main._device_reach(db, "esp32-salt") == {}, "scope names the sensor's keys, not the hub's"
        finally:
            db.close()

        # Without the flag the hub is just a device: it is not heard.
        db = main.SessionLocal()
        try:
            db.query(main.Device).filter(main.Device.device_id == "esp32-hub").first().is_hub = False
            db.commit()
        finally:
            db.close()
        hub.send({"type": "relay", "frames": [frame]})
        hub.send({"type": "hub_status", "channel": 6})
        time.sleep(0.5)      # nothing comes back, so give the server time to have ignored them
        db = main.SessionLocal()
        try:
            db.query(main.Device).filter(main.Device.device_id == "esp32-hub").first().is_hub = True
            db.commit()
        finally:
            db.close()
        assert statuses(relay(hub, [frame])) == ["ok"], "the frame was never consumed by the earlier refusal"

        # Ending the pairing ends the relay at once, whatever the hub still holds.
        grant_ref = c.get("/api/peerings", headers=tok).json()["peerings"][0]["grant_id"]
        assert c.delete(f"/api/peerings/{grant_ref}", headers=tok).status_code == 200
        assert hub.next()["type"] == "peer_revoke" and salt.next()["type"] == "peer_revoke"
        assert statuses(relay(hub, [local_frame(g, k, "esp32-salt", 1, 2, {"salt": 1})])) == ["unknown_grant"]

        # An expired grant is as good as none.
        assert pair_relay(c, tok, "esp32-salt", "esp32-hub", ["salt"]).status_code == 200
        sg, _ = grant_and_key(salt, hub)
        db = main.SessionLocal()
        try:
            row = db.query(main.PeerGrant).filter(main.PeerGrant.grant_id == int(sg["grant_id"][2:])).first()
            row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            db.commit()
        finally:
            db.close()
        assert statuses(relay(hub, [local_frame(sg["grant_id"], sg["key"], "esp32-salt", 1, 1, {"salt": 2})])) \
            == ["unknown_grant"]

        # Rate limit: calls, not frames. The hub is told, with when to try again.
        main.RELAY_RATE.clear_all()
        for _ in range(30):
            hub.send({"type": "relay", "frames": []})
            assert hub.next()["type"] == "relay_ack"
        hub.send({"type": "relay", "frames": []})
        limited = hub.next()
        assert limited["status"] == "rate_limited" and limited["retry_after"] >= 1, limited
    finally:
        for b in (hub, salt, hub2, rival):
            b.close()
    print("  authority: another hub, another house, a missing grant, a revoked or expired one, or a device that")
    print("             withdrew its hub flag all get nothing; a relay grant gives an agent no reach; rate limited per call")


# ── the hub's channel, and a hub that has died ─────────────────
def test_channel_and_hub_failed():
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    main.HUB_STATUS_RATE.clear_all()
    main.HUB_FAILED_RATE.clear_all()
    tok = household(c, "r5@x.test", "Channel House",
                    [("esp32-hub", "4821"), ("esp32-salt", "5937"), ("esp32-stray", "6143")])
    hub = Board(c, "esp32-hub", "4821", HUB)
    salt = Board(c, "esp32-salt", "5937", SALT)
    stray = Board(c, "esp32-stray", "6143", {**TANK, "mac": "24:6F:28:AA:CC:0A"})
    try:
        assert pair_relay(c, tok, "esp32-salt", "esp32-hub", ["salt"]).status_code == 200
        grant_and_key(salt, hub)

        # The hub reports its channel; the sensor that depends on it is told.
        for bad in (0, 15, "6", True):      # four of the six this minute the rate limit allows
            hub.send({"type": "hub_status", "channel": bad})
        hub.send({"type": "hub_status", "channel": 11})
        pushed = salt.next()
        assert pushed == {"id": "esp32-salt", "type": "hub_channel", "hub": "esp32-hub", "channel": 11}, pushed
        hub.send({"type": "hub_status", "channel": 11})       # unchanged: nothing to say
        # A device that is not a hub cannot announce one.
        stray.send({"type": "hub_status", "channel": 3})
        # and a sensor that connects later is handed the channel with its grant
        salt.close()
        salt = Board(c, "esp32-salt", "5937", SALT)
        assert salt.boot[0]["type"] == "peer_grant" and salt.boot[0]["peer"]["channel"] == 11, salt.boot
        db = main.SessionLocal()
        try:
            assert db.query(main.Device).filter(main.Device.device_id == "esp32-hub").first().hub_channel == 11
            assert db.query(main.Device).filter(main.Device.device_id == "esp32-stray").first().hub_channel is None
        finally:
            db.close()

        # hub_failed: believed only from a sensor paired to that hub, and said once.
        salt.send({"type": "state", "state": {"salt": 40}, "hub_failed": "esp32-hub"})
        notes = wait_for(lambda: activity("esp32-salt", "hub_failed"), lambda v: len(v) >= 1)
        assert len(notes) == 1 and "could not reach" in notes[0], notes
        salt.send({"type": "state", "state": {"salt": 39}, "hub_failed": "esp32-hub"})
        stray.send({"type": "state", "state": {"level": 1}, "hub_failed": "esp32-hub"})   # not paired to it
        salt.send({"type": "state", "state": {"salt": 38}, "hub_failed": "esp32-ghost"})   # no such hub
        salt.send({"type": "state", "state": {"salt": 38}, "hub_failed": "esp32-stray"})   # a real device, not its hub
        salt.send({"type": "state", "state": {"salt": 37}, "hub_failed": 12})              # not an id
        salt.send({"type": "state", "state": {"salt": 36}})
        wait_for(lambda: state_of("esp32-salt").get("salt"), lambda v: v == 36)
        assert len(activity("esp32-salt", "hub_failed")) == 1, "once, and only for a real pairing"
        assert state_of("esp32-salt")["salt"] == 36, "the state in the same frame is still kept"
    finally:
        for b in (hub, salt, stray):
            b.close()
    print("  hub: its channel is stored and pushed to dependants and to a sensor that connects later; hub_failed is")
    print("       believed only for a real pairing and noted once")


if __name__ == "__main__":
    test_pairing_a_relay()
    test_relaying_and_forgery()
    test_relay_authority()
    test_channel_and_hub_failed()
    print("OK: a hub carries readings it cannot forge, replay or widen; the server checks every frame itself")
