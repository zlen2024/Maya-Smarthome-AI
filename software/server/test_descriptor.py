"""Self-check for protocol 2 step 1: descriptors in, state stored, v1 shimmed.

The first half drives `descriptor.py` directly — the validation rules of
PROTOCOL.md §5 with no database in the way. The second half boots the real app
and plays two devices against it over a WebSocket: a protocol-1 board that
declares nothing, and a protocol-2 one that declares the salt jar from §5.7,
including answering a `set` frame with an ack so the round trip is real.

Run:  python test_descriptor.py      (needs fastapi, sqlalchemy, httpx<0.28)

The server's own log lines are part of a passing run. The signal is the final OK
line and an exit code of 0.
"""
import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "proto.db")
os.environ["SECRET_KEY"] = "test-key-not-a-secret"

import json  # noqa: E402
import threading  # noqa: E402

from descriptor import (MAX_CAPABILITIES, Capability, DescriptorError,  # noqa: E402
                        coerce_state, coerce_value, negotiate_proto, parse_identify)

SALT_JAR = {
    "id": "esp32-saltjar-01", "proto": 2, "status": "online",
    "pin": "2201", "model": "jar_scale_v1", "fw": "1.1.0",
    "report_every": 900,
    "capabilities": [
        {"key": "weight", "kind": "number", "label": "Salt left", "unit": "g",
         "min": 0, "max": 1000, "access": "r", "history": True},
        {"key": "note", "kind": "text", "label": "Status", "access": "r"},
        {"key": "_batt", "kind": "number", "unit": "%", "access": "r"},
    ],
    "state": {"weight": 180, "note": "Running low", "_batt": 74},
}


# ── §4: version negotiation ───────────────────────────────────
def test_negotiation():
    assert negotiate_proto(None) == 1          # absent means 1
    assert negotiate_proto(1) == 1
    assert negotiate_proto(2) == 2
    assert negotiate_proto(99) == 2            # min(device, server_max)
    assert negotiate_proto("garbage") == 1     # unparseable lands on the shim
    assert negotiate_proto(0) == 1
    print("  negotiation: absent/garbage means 1, higher clamps to the server max")


# ── §4: the protocol-1 shim ───────────────────────────────────
def test_v1_shim():
    desc = parse_identify({"id": "esp32-old", "status": "online", "pin": "1357",
                           "ip": "10.0.0.9", "ch1": "on", "ch2": "off", "ch3": "on"})
    assert desc.proto == 1 and desc.shimmed
    assert [c.key for c in desc.capabilities] == ["ch1", "ch2", "ch3"]
    assert all(c.kind == "switch" and c.access == "rw" for c in desc.capabilities)
    assert desc.state == {"ch1": "on", "ch2": "off", "ch3": "on"}
    # A device that reports only some channels still parses; the rest are simply
    # not reported yet.
    assert parse_identify({"id": "x", "status": "online", "ch2": "on"}).state == {"ch2": "on"}
    print("  v1 shim: three switches synthesised, channel states read")


# ── §5.1-§5.5: descriptor validation ──────────────────────────
def test_descriptor_validation():
    desc = parse_identify(SALT_JAR)
    assert desc.proto == 2 and not desc.shimmed
    assert [c.key for c in desc.capabilities] == ["weight", "note", "_batt"]
    assert desc.model == "jar_scale_v1" and desc.fw == "1.1.0" and desc.report_every == 900
    assert desc.state == {"weight": 180, "note": "Running low", "_batt": 74}
    weight = desc.by_key["weight"]
    assert weight.history and weight.access == "r" and weight.unit == "g"
    assert not weight.writable and weight.readable
    assert desc.warnings == [], desc.warnings

    # A sensor-only device is a first-class citizen (§5.7), not an error.
    assert all(not c.writable for c in desc.capabilities)

    def one(spec, **frame):
        return parse_identify({"id": "x", "proto": 2, "capabilities": [spec], **frame})

    # §5.4 MUST: an unrecognised agent value fails closed.
    assert one({"key": "horn", "kind": "button", "agent": "sure"}).by_key["horn"].agent == "deny"
    assert one({"key": "horn", "kind": "button", "agent": "deny"}).by_key["horn"].agent == "deny"
    assert one({"key": "horn", "kind": "button"}).by_key["horn"].agent == "allow"

    # An unknown access value is treated as read-only rather than as writable.
    assert one({"key": "x1", "kind": "switch", "access": "wr"}).by_key["x1"].access == "r"

    # §11: an unknown kind degrades to a read-only raw value instead of being
    # dropped, so a v2.x device is not crippled by a v2.0 server.
    cap = one({"key": "aroma", "kind": "smell"}).by_key["aroma"]
    assert cap.kind == "smell" and cap.access == "r" and not cap.known_kind

    # §5.3: the `_` namespace belongs to the document; others are dropped.
    assert one({"key": "_secret", "kind": "number"}).capabilities == []
    assert one({"key": "_rssi", "kind": "number"}).by_key["_rssi"].key == "_rssi"
    # `_report_every` is reserved too, and writable — declaring it is how a sleepy
    # device says its check-in interval is adjustable (§5.8). It was missing from
    # the reserved set, so the capability was being dropped silently.
    interval = one({"key": "_report_every", "kind": "duration", "label": "Check in every",
                    "min": 900, "max": 86400}).by_key["_report_every"]
    assert interval.writable and interval.min == 900 and interval.max == 86400

    # §5.1: keys are validated, not sanitised.
    for bad_key in ("Ch1", "ch-1", "ch 1", "", "x" * 25, 7):
        assert one({"key": bad_key, "kind": "switch"}).capabilities == [], bad_key

    # A dropdown with nothing in it cannot be rendered.
    assert one({"key": "mode", "kind": "enum"}).capabilities == []
    assert one({"key": "mode", "kind": "enum", "options": ["eco", "boost"]}).by_key["mode"].options \
        == ["eco", "boost"]

    # First declaration of a duplicate key wins.
    dup = parse_identify({"id": "x", "proto": 2, "capabilities": [
        {"key": "ch1", "kind": "switch", "label": "First"},
        {"key": "ch1", "kind": "switch", "label": "Second"}]})
    assert len(dup.capabilities) == 1 and dup.by_key["ch1"].label == "First"

    # label defaults to the key; history only applies to number and range.
    assert one({"key": "ch1", "kind": "switch"}).by_key["ch1"].label == "ch1"
    assert one({"key": "ch1", "kind": "switch", "history": True}).by_key["ch1"].history is False
    assert one({"key": "t", "kind": "number", "history": True}).by_key["t"].history is True

    # §1 rule 4: an unknown field is ignored, never fatal.
    assert one({"key": "ch1", "kind": "switch", "nonsense": {"deep": [1, 2]}}).by_key["ch1"].kind \
        == "switch"
    print("  validation: agent and access fail closed, unknown kinds degrade,")
    print("              reserved keys and bad keys dropped, unknown fields ignored")


def test_limits():
    too_many = {"id": "x", "proto": 2, "capabilities": [
        {"key": f"k{i}", "kind": "switch"} for i in range(MAX_CAPABILITIES + 1)]}
    try:
        parse_identify(too_many)
        raise AssertionError("33 capabilities accepted")
    except DescriptorError as e:
        assert e.code == "descriptor_too_large", e.code

    too_big = {"id": "x", "proto": 2, "capabilities": [
        {"key": "ch1", "kind": "switch", "label": "L" * 5000}]}
    try:
        parse_identify(too_big)
        raise AssertionError("5 KB descriptor accepted")
    except DescriptorError as e:
        assert e.code == "descriptor_too_large", e.code

    # Exactly 32 is allowed -- the limit is inclusive.
    ok = parse_identify({"id": "x", "proto": 2, "capabilities": [
        {"key": f"k{i}", "kind": "switch"} for i in range(MAX_CAPABILITIES)]})
    assert len(ok.capabilities) == MAX_CAPABILITIES
    print("  limits: 32 capabilities and 4 KB enforced, 32 itself allowed")


# ── §5.2: value types ─────────────────────────────────────────
def test_value_types():
    def cap(kind, **kw):
        return Capability(key="k", kind=kind, label="k", **kw)

    assert coerce_value(cap("switch"), "ON") == "on"
    assert coerce_value(cap("switch"), True) == "on"
    assert coerce_value(cap("switch"), 0) == "off"
    assert coerce_value(cap("range", min=0, max=100, step=5), 40) == 40
    assert coerce_value(cap("number"), 27.5) == 27.5
    assert coerce_value(cap("text", max=5), "abcde") == "abcde"
    assert coerce_value(cap("enum", options=["eco", "boost"]), "eco") == "eco"
    assert coerce_value(cap("button"), "anything") is None
    assert coerce_value(cap("color"), "#FF8800") == "#ff8800"
    assert coerce_value(cap("time"), "07:30") == "07:30"
    assert coerce_value(cap("duration", max=7200), 600) == 600
    assert coerce_value(cap("location"), {"lat": 3.1, "lng": 101.6}) == {"lat": 3.1, "lng": 101.6}

    bad = [
        (cap("switch"), "maybe"), (cap("number"), "27.5"), (cap("number"), True),
        (cap("range", min=0, max=100), 101), (cap("range", min=10, max=100), 9),
        (cap("text", max=3), "abcd"), (cap("text"), 5),
        (cap("enum", options=["eco"]), "boost"),
        (cap("color"), "red"), (cap("color"), "#ff88"),
        (cap("time"), "7:30"), (cap("time"), "24:00"), (cap("time"), "07:60"),
        (cap("duration"), -1), (cap("duration", max=60), 61),
        (cap("location"), {"lat": 3.1}), (cap("location"), {"lat": 91, "lng": 0}),
    ]
    for c, value in bad:
        try:
            coerce_value(c, value)
        except ValueError:
            continue
        raise AssertionError("%s accepted %r" % (c.kind, value))
    print("  value types: all ten kinds coerced, out-of-range and wrong types refused")


def test_state_reports_are_lenient():
    caps = {c.key: c for c in [
        Capability(key="ch1", kind="switch", label="ch1"),
        Capability(key="temp", kind="number", label="temp", min=0, max=50, access="r"),
        Capability(key="msg", kind="text", label="msg", access="w"),
        Capability(key="horn", kind="button", label="horn"),
    ]}
    notes = []
    written = coerce_state(caps, {
        "ch1": "on",            # good
        "temp": 99,             # out of range -> dropped
        "unknown": 1,           # undeclared -> dropped
        "msg": "hello",         # write-only -> nothing to store
        "horn": None,           # button has no state
    }, warn=notes.append)
    # One bad value must not discard the frame's good reading.
    assert written == {"ch1": "on"}, written
    assert len(notes) == 3, notes
    assert coerce_state(caps, "not a dict") == {}
    print("  state reports: bad and undeclared keys dropped, good values kept")


# ── The two devices, against the real app ─────────────────────
def _house_with_device(c, email, device_id, pin):
    r = c.post("/api/auth/register", json={"email": email, "password": "owner-pass",
                                           "name": "Owner"})
    tok = {"Authorization": "Bearer " + r.json()["token"]}
    c.post("/api/houses", json={"location": "Proto House"}, headers=tok)
    reg = c.post("/api/devices/register",
                 json={"device_id": device_id, "name": "Bench unit", "pin": pin},
                 headers=tok)
    assert reg.status_code == 200, reg.text
    return tok


def test_v1_device_end_to_end():
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    main.REGISTER_RATE.clear_all()
    tok = _house_with_device(c, "v1@x.test", "esp32-v1", "1357")

    session = c.websocket_connect("/ws")
    ws = session.__enter__()
    try:
        ws.send_json({"id": "esp32-v1", "status": "online", "pin": "1357",
                      "ip": "10.0.0.9", "ch1": "on", "ch2": "off", "ch3": "off"})
        welcome = ws.receive_json()
        assert welcome["type"] == "welcome", welcome
        assert welcome["proto"] == 1 and welcome["server_proto_max"] == 2

        got = c.get("/api/devices/esp32-v1/capabilities", headers=tok).json()
        assert got["proto"] == 1, got
        assert [cap["key"] for cap in got["capabilities"]] == ["ch1", "ch2", "ch3"]
        assert all(cap["kind"] == "switch" for cap in got["capabilities"])
        assert got["state"] == {"ch1": "on", "ch2": "off", "ch3": "off"}, got["state"]

        # A member's own channel name wins over the firmware's label (§5.1).
        relays = c.get("/api/relays", headers=tok).json()["relays"]
        relay_id = next(r["relay_id"] for r in relays
                        if r["device_id"] == "esp32-v1" and r["channel_number"] == 1)
        renamed = c.put(f"/api/relays/{relay_id}", json={"name": "Television"}, headers=tok)
        assert renamed.status_code == 200, renamed.text
        got = c.get("/api/devices/esp32-v1/capabilities", headers=tok).json()
        assert got["capabilities"][0]["label"] == "Television", got["capabilities"][0]

        # A heartbeat keeps both representations in step: the capability state
        # the app will read after step 2, and the Relay rows it reads today.
        ws.send_json({"id": "esp32-v1", "type": "heartbeat", "uptime_ms": 42000,
                      "ch1": "off", "ch2": "on", "ch3": "off"})
        state = _wait_for(lambda: c.get("/api/devices/esp32-v1/capabilities",
                                        headers=tok).json()["state"],
                          lambda v: v.get("ch2") == "on")
        assert state == {"ch1": "off", "ch2": "on", "ch3": "off"}, state
        relays = c.get("/api/relays", headers=tok).json()["relays"]
        by_channel = {r["channel_number"]: r["is_on"] for r in relays
                      if r["device_id"] == "esp32-v1"}
        assert by_channel == {1: False, 2: True, 3: False}, by_channel
    finally:
        _close(ws, session)
    print("  v1 device: shimmed descriptor served, labels overridden, both")
    print("             representations kept in step by one heartbeat")


def test_v2_device_end_to_end():
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    main.REGISTER_RATE.clear_all()
    tok = _house_with_device(c, "v2@x.test", "esp32-saltjar-01", "2201")

    session = c.websocket_connect("/ws")
    ws = session.__enter__()
    try:
        ws.send_json(SALT_JAR)
        welcome = ws.receive_json()
        assert welcome["proto"] == 2, welcome

        got = c.get("/api/devices/esp32-saltjar-01/capabilities", headers=tok).json()
        assert got["proto"] == 2 and got["model"] == "jar_scale_v1"
        assert got["report_every"] == 900
        assert [cap["key"] for cap in got["capabilities"]] == ["weight", "note", "_batt"]
        weight = got["capabilities"][0]
        assert weight["unit"] == "g" and weight["min"] == 0 and weight["max"] == 1000
        assert weight["history"] is True and weight["access"] == "r"
        assert got["state"] == {"weight": 180, "note": "Running low", "_batt": 74}

        # §6.1: a partial state report merges rather than replacing.
        ws.send_json({"id": "esp32-saltjar-01", "type": "state", "uptime_ms": 900000,
                      "state": {"weight": 120}})
        state = _wait_for(lambda: c.get("/api/devices/esp32-saltjar-01/capabilities",
                                        headers=tok).json()["state"],
                          lambda v: v.get("weight") == 120)
        assert state == {"weight": 120, "note": "Running low", "_batt": 74}, state

        # Everything on this device is read-only, so a write is refused before
        # anything reaches the wire.
        r = c.post("/api/devices/esp32-saltjar-01/capability",
                   json={"values": {"weight": 500}}, headers=tok)
        assert r.json()["status"] == "not_permitted", r.json()
        r = c.post("/api/devices/esp32-saltjar-01/capability",
                   json={"values": {"nope": 1}}, headers=tok)
        assert r.json()["status"] == "unknown_capability", r.json()
    finally:
        _close(ws, session)
    print("  v2 device: salt jar descriptor stored as declared, partial state")
    print("             merged, read-only and unknown keys refused")


def test_v2_set_round_trip():
    """A writable v2 device, driven through POST /capability: the server must send
    a `set` frame with a `req`, and believe the state the device echoes back."""
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    main.REGISTER_RATE.clear_all()
    tok = _house_with_device(c, "fan@x.test", "esp32-fan", "4817")

    session = c.websocket_connect("/ws")
    ws = session.__enter__()
    try:
        ws.send_json({
            "id": "esp32-fan", "proto": 2, "status": "online", "pin": "4817",
            "model": "fan_v1", "fw": "2.0.1",
            "capabilities": [
                {"key": "ch1", "kind": "switch", "label": "Fan"},
                {"key": "speed", "kind": "range", "label": "Fan speed",
                 "min": 0, "max": 100, "step": 5, "unit": "%"},
                {"key": "mode", "kind": "enum", "label": "Mode",
                 "options": ["eco", "normal", "boost"]},
                {"key": "reset", "kind": "button", "label": "Reset", "agent": "deny"},
                {"key": "lock", "kind": "switch", "label": "Child lock", "confirm": True},
            ],
            "state": {"ch1": "off", "speed": 0, "mode": "eco", "lock": "off"},
        })
        assert ws.receive_json()["proto"] == 2

        # The POST blocks until the device acks, so the device has to be played
        # from this thread while the request runs in another.
        result = {}

        def call():
            result["response"] = c.post(
                "/api/devices/esp32-fan/capability",
                json={"values": {"ch1": "on", "speed": 60}}, headers=tok)

        caller = threading.Thread(target=call)
        caller.start()
        try:
            frame = ws.receive_json()
            assert frame["type"] == "set", frame
            assert frame["values"] == {"ch1": "on", "speed": 60}, frame
            assert frame["req"], frame
            ws.send_json({"id": "esp32-fan", "type": "ack", "req": frame["req"],
                          "status": "ok", "state": {"ch1": "on", "speed": 60}})
        finally:
            caller.join(timeout=15)
        assert not caller.is_alive(), "the POST never returned"

        body = result["response"].json()
        assert body["status"] == "ok", body
        assert body["state"] == {"ch1": "on", "speed": 60}, body

        got = c.get("/api/devices/esp32-fan/capabilities", headers=tok).json()
        assert got["state"]["ch1"] == "on" and got["state"]["speed"] == 60, got["state"]

        # The v2 ack carries no bare ch1/ch2/ch3, and must not be read as if it
        # did: defaulting them to "off" would switch the relay row off behind the
        # device's back. The channel keys it *does* report are mirrored across.
        relays = {r["channel_number"]: r["is_on"]
                  for r in c.get("/api/relays", headers=tok).json()["relays"]
                  if r["device_id"] == "esp32-fan"}
        assert relays.get(1) is True, relays

        # An error ack must resolve the waiting command, not leave the caller in
        # the 5-second timeout for an answer that already arrived.
        def call_refused():
            result["refused"] = c.post("/api/devices/esp32-fan/capability",
                                       json={"values": {"mode": "boost"}}, headers=tok)

        caller = threading.Thread(target=call_refused)
        caller.start()
        try:
            frame = ws.receive_json()
            assert frame["values"] == {"mode": "boost"}, frame
            ws.send_json({"id": "esp32-fan", "type": "ack", "req": frame["req"],
                          "status": "busy"})
        finally:
            caller.join(timeout=15)
        # "busy" rather than "timeout" is the whole assertion: the device's error
        # ack was correlated to the waiting command. Before the ack branch was
        # unified, an error status matched no branch, nothing resolved the
        # command, and this came back as "timeout" 5 seconds later.
        #
        # Do not assert on how long it took. TestClient builds a fresh event loop
        # per request, so the ack is resolved from a different loop than the one
        # awaiting it and only lands when the timeout expires. One uvicorn process
        # has a single loop, where it is immediate.
        assert result["refused"].json()["status"] == "busy", result["refused"].json()
        # ...and a refused set left the stored state alone.
        got = c.get("/api/devices/esp32-fan/capabilities", headers=tok).json()
        assert got["state"]["mode"] == "eco", got["state"]

        # A value the declaration forbids never reaches the device.
        r = c.post("/api/devices/esp32-fan/capability",
                   json={"values": {"speed": 150}}, headers=tok).json()
        assert r["status"] == "bad_value", r
        r = c.post("/api/devices/esp32-fan/capability",
                   json={"values": {"mode": "turbo"}}, headers=tok).json()
        assert r["status"] == "bad_value", r

        # §5.4: a `confirm:true` capability is refused without the evidence that a
        # human said yes, and the refusal never reaches the device.
        r = c.post("/api/devices/esp32-fan/capability",
                   json={"values": {"lock": "on"}}, headers=tok).json()
        assert r["status"] == "not_permitted" and r.get("needs_confirmation"), r

        # With the flag, the set goes out. Both values are legal by the
        # declaration, so this exercises a failure the *device* decides on —
        # §6.2's partial apply, which the server cannot predict.
        def call_confirmed():
            result["confirmed"] = c.post(
                "/api/devices/esp32-fan/capability",
                json={"values": {"lock": "on", "mode": "boost"}, "confirmed": True},
                headers=tok)

        caller = threading.Thread(target=call_confirmed)
        caller.start()
        try:
            frame = ws.receive_json()
            assert frame["values"] == {"lock": "on", "mode": "boost"}, frame
            # The lock engaged, then the motor refused the mode change.
            ws.send_json({"id": "esp32-fan", "type": "ack", "req": frame["req"],
                          "status": "busy", "failed": "mode",
                          "state": {"lock": "on"}})
        finally:
            caller.join(timeout=15)
        body = result["confirmed"].json()
        assert body["status"] == "busy" and body["failed"] == "mode", body
        assert body["state"] == {"lock": "on"}, body
        # What did apply was stored; what did not kept its old value.
        got = c.get("/api/devices/esp32-fan/capabilities", headers=tok).json()
        assert got["state"]["lock"] == "on", got["state"]
        assert got["state"]["mode"] == "eco", got["state"]

        # §5.4: `agent:"deny"` is filtered out before Maya is ever called.
        import capability_store
        from database import SessionLocal
        from models import Device
        db = SessionLocal()
        try:
            device = db.query(Device).filter(Device.device_id == "esp32-fan").first()
            human = capability_store.descriptor_payload(db, device)
            agent = capability_store.descriptor_payload(db, device, for_agent=True)
        finally:
            db.close()
        assert "reset" in {cap["key"] for cap in human["capabilities"]}
        assert "reset" not in {cap["key"] for cap in agent["capabilities"]}
        assert {c["key"]: c.get("agent") for c in human["capabilities"]}["reset"] == "deny"
        assert any(c.get("confirm") for c in human["capabilities"])
    finally:
        _close(ws, session)
    print("  v2 set: `set` frame sent with a req, ack echo believed and stored,")
    print("          bad values stopped here, agent:deny hidden from Maya")


def test_oversized_descriptor_is_rejected_on_the_socket():
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    main.REGISTER_RATE.clear_all()
    tok = _house_with_device(c, "big@x.test", "esp32-big", "5926")

    session = c.websocket_connect("/ws")
    ws = session.__enter__()
    try:
        ws.send_json({"id": "esp32-big", "proto": 2, "status": "online", "pin": "5926",
                      "capabilities": [{"key": f"k{i}", "kind": "switch"}
                                       for i in range(40)]})
        frame = ws.receive_json()
        assert frame["type"] == "error" and frame["status"] == "descriptor_too_large", frame
    finally:
        _close(ws, session)
    # Nothing was stored for it, and the device is not left registered as online.
    got = c.get("/api/devices/esp32-big/capabilities", headers=tok).json()
    assert got["capabilities"] == [], got
    print("  oversized descriptor: refused with descriptor_too_large, nothing stored")


def test_legacy_paths_still_work():
    """Step 1's promise: nothing else changes. The v1 command endpoint still
    drives a shimmed device and still answers with the three channel keys."""
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    main.REGISTER_RATE.clear_all()
    tok = _house_with_device(c, "legacy@x.test", "esp32-legacy", "6284")

    session = c.websocket_connect("/ws")
    ws = session.__enter__()
    try:
        ws.send_json({"id": "esp32-legacy", "status": "online", "pin": "6284",
                      "ch1": "off", "ch2": "off", "ch3": "off"})
        assert ws.receive_json()["proto"] == 1

        result = {}

        def call():
            result["response"] = c.post("/api/devices/esp32-legacy/command",
                                        json={"cmd": "on", "channel": 1}, headers=tok)

        caller = threading.Thread(target=call)
        caller.start()
        try:
            frame = ws.receive_json()
            assert frame["cmd"] == "output_on" and frame["channel"] == 1, frame
            assert "type" not in frame, "a v1 device must not be sent a v2 frame"
            ws.send_json({"id": "esp32-legacy", "status": "ok",
                          "ch1": "on", "ch2": "off", "ch3": "off"})
        finally:
            caller.join(timeout=15)
        body = result["response"].json()
        assert body["status"] == "ok" and body["ch1"] == "on", body

        # ...and the ack fed the capability tables too, so the v2 view of a v1
        # device is correct without the app changing at all.
        state = _wait_for(lambda: c.get("/api/devices/esp32-legacy/capabilities",
                                        headers=tok).json()["state"],
                          lambda v: v.get("ch1") == "on")
        assert state["ch1"] == "on", state
    finally:
        _close(ws, session)
    print("  legacy paths: v1 command still sends `cmd`/`channel` and its ack")
    print("                now also lands in the capability tables")


# ── helpers ───────────────────────────────────────────────────
def _wait_for(read, done, attempts=40, delay=0.05):
    """Poll `read` until `done` or the attempts run out, then return the last value.

    The WebSocket handler commits on the app's event loop while the test drives
    HTTP from the outside, so a read taken immediately can land before the write.
    """
    import time
    value = read()
    for _ in range(attempts):
        if done(value):
            return value
        time.sleep(delay)
        value = read()
    return value


def _close(ws, session):
    for step in (ws.close, lambda: session.__exit__(None, None, None)):
        try:
            step()
        except Exception:
            pass


if __name__ == "__main__":
    test_negotiation()
    test_v1_shim()
    test_descriptor_validation()
    test_limits()
    test_value_types()
    test_state_reports_are_lenient()
    test_v1_device_end_to_end()
    test_v2_device_end_to_end()
    test_v2_set_round_trip()
    test_oversized_descriptor_is_rejected_on_the_socket()
    test_legacy_paths_still_work()
    print("OK: descriptors stored as declared, protocol 1 shimmed, v1 paths intact")
