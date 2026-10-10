"""Self-check for protocol 2 step 2's server half: claiming, grants, labels.

PROTOCOL.md §10 puts three conversions in step 2 because they touch the same
tables: §4.1 (claiming creates the device record and nothing else), §5.10
(permissions key on a capability, not a relay) and §5.11 (a house member's name
for a capability beats the firmware's). This drives all three against the real
app, including the `/api/permissions` facade the shipped Flutter app still calls.

Run:  python test_grants.py      (needs fastapi, sqlalchemy, httpx<0.28)

The server's own log lines are part of a passing run. The signal is the final OK
line and an exit code of 0.
"""
import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "grants.db")
os.environ["SECRET_KEY"] = "test-key-not-a-secret"

import time  # noqa: E402

V1_IDENTIFY = {"status": "online", "ip": "10.0.0.7",
               "ch1": "off", "ch2": "off", "ch3": "off"}

FAN_V2 = {
    "proto": 2, "status": "online", "model": "fan_v1", "fw": "2.0.0",
    "capabilities": [
        {"key": "ch1", "kind": "switch", "label": "Fan"},
        {"key": "speed", "kind": "range", "label": "Fan speed",
         "min": 0, "max": 100, "step": 5, "unit": "%"},
        {"key": "temp", "kind": "number", "label": "Room temp", "unit": "C",
         "access": "r"},
    ],
    "state": {"ch1": "off", "speed": 0, "temp": 24},
}


def household(c, email, device_id, pin, child_pin="8317"):
    """A master, a house, a claimed device and one child."""
    import main
    main.REGISTER_RATE.clear_all()
    r = c.post("/api/auth/register", json={"email": email, "password": "owner-pass",
                                           "name": "Owner"})
    assert r.status_code == 200, r.text
    tok = {"Authorization": "Bearer " + r.json()["token"]}
    c.post("/api/houses", json={"location": "Grants House"}, headers=tok)
    reg = c.post("/api/devices/register",
                 json={"device_id": device_id, "name": "Bench unit", "pin": pin},
                 headers=tok)
    assert reg.status_code == 200, reg.text
    kid = c.post("/api/children", json={"name": "Kid", "pin": child_pin}, headers=tok)
    assert kid.status_code == 200, kid.text
    child_id = kid.json()["child_id"]
    ktok = {"Authorization": "Bearer " + c.post(
        f"/api/children/{child_id}/login", json={"pin": child_pin}).json()["token"]}
    return tok, child_id, ktok


def identify(c, device_id, frame, pin):
    """Connect as the device and leave the socket open; returns (ws, session)."""
    session = c.websocket_connect("/ws")
    ws = session.__enter__()
    ws.send_json({"id": device_id, "pin": pin, **frame})
    welcome = ws.receive_json()
    assert welcome["type"] == "welcome", welcome
    # §7.1: a protocol-2 device is always sent peer_sync after welcome; it is
    # not what these tests are about, so read past it.
    if welcome.get("proto", 1) >= 2:
        assert ws.receive_json()["type"] == "peer_sync"
    return ws, session


def close(ws, session):
    for step in (ws.close, lambda: session.__exit__(None, None, None)):
        try:
            step()
        except Exception:
            pass


# ── §4.1 claiming ─────────────────────────────────────────────
def test_claiming_creates_nothing_but_the_device():
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    tok, _, _ = household(c, "claim@x.test", "esp32-claim", "1357")

    # Claimed, not yet connected: the server knows an id, a PIN and a name, so
    # that is all it has created. No channels invented on its behalf.
    assert c.get("/api/relays", headers=tok).json()["relays"] == []
    caps = c.get("/api/devices/esp32-claim/capabilities", headers=tok).json()
    assert caps["capabilities"] == [], caps

    # The shim's rows appear when a protocol-1 device identifies — the first
    # moment "three channels" is a fact rather than a guess.
    ws, session = identify(c, "esp32-claim", V1_IDENTIFY, "1357")
    try:
        relays = _wait_for(lambda: c.get("/api/relays", headers=tok).json()["relays"],
                           lambda v: len(v) == 3)
        assert [r["channel_number"] for r in relays] == [1, 2, 3], relays
        caps = c.get("/api/devices/esp32-claim/capabilities", headers=tok).json()
        assert [x["key"] for x in caps["capabilities"]] == ["ch1", "ch2", "ch3"]

        # Re-claiming used to reset every channel name back to "Channel N",
        # silently wiping a name a member had chosen. §5.11 forbids that.
        relay_id = relays[0]["relay_id"]
        c.put(f"/api/relays/{relay_id}", json={"name": "Television"}, headers=tok)
        again = c.post("/api/devices/register",
                       json={"device_id": "esp32-claim", "name": "Bench unit",
                             "pin": "1357"}, headers=tok)
        assert again.status_code == 200, again.text
        named = [r for r in c.get("/api/relays", headers=tok).json()["relays"]
                 if r["relay_id"] == relay_id][0]
        assert named["name"] == "Television", named

        # Identifying again does not duplicate the backing rows.
        ws.send_json({"id": "esp32-claim", "pin": "1357", **V1_IDENTIFY})
        time.sleep(0.3)
        assert len(c.get("/api/relays", headers=tok).json()["relays"]) == 3
    finally:
        close(ws, session)
    print("  claiming: no channels until a v1 device identifies, rows not")
    print("            duplicated, and a re-claim no longer wipes a name")


# ── §5.10 grants ──────────────────────────────────────────────
def test_grants_default_to_denied():
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    tok, child_id, ktok = household(c, "grant@x.test", "esp32-fan2", "4817")
    ws, session = identify(c, "esp32-fan2", FAN_V2, "4817")
    try:
        # Every writable capability is listed for the parent, granted or not: a
        # list of only the grants looks identical to a list of nothing at all.
        listed = c.get(f"/api/children/{child_id}/grants", headers=tok).json()["grants"]
        by_key = {g["key"]: g for g in listed}
        assert set(by_key) == {"ch1", "speed"}, by_key          # `temp` is read-only
        assert all(g["is_allowed"] is False for g in listed), listed

        # A capability nobody has granted is denied — the default that stops a
        # firmware update widening what a child can reach.
        r = c.post("/api/devices/esp32-fan2/capability",
                   json={"values": {"ch1": "on"}}, headers=ktok)
        assert r.status_code == 403, r.text
        assert "permission" in r.json()["detail"].lower(), r.json()

        # The child's own read says so, rather than letting them tap and collect
        # a 403 — and reading state is house-wide either way (§5.10).
        seen = c.get("/api/devices/esp32-fan2/capabilities", headers=ktok).json()
        flags = {x["key"]: x.get("may_write") for x in seen["capabilities"]}
        assert flags == {"ch1": False, "speed": False, "temp": False}, flags
        assert seen["state"]["temp"] == 24, seen["state"]

        # The parent grants one capability, not the device.
        put = c.put(f"/api/children/{child_id}/grants", headers=tok, json={"grants": [
            {"device_id": "esp32-fan2", "key": "ch1", "is_allowed": True}]})
        assert put.status_code == 200, put.text

        result = {}

        def call():
            result["r"] = c.post("/api/devices/esp32-fan2/capability",
                                 json={"values": {"ch1": "on"}}, headers=ktok)

        import threading
        caller = threading.Thread(target=call)
        caller.start()
        try:
            frame = ws.receive_json()
            assert frame["values"] == {"ch1": "on"}, frame
            ws.send_json({"id": "esp32-fan2", "type": "ack", "req": frame["req"],
                          "status": "ok", "state": {"ch1": "on"}})
        finally:
            caller.join(timeout=15)
        assert result["r"].json()["status"] == "ok", result["r"].json()

        # The other capability is still shut. "May use the fan" is not "may set
        # the fan's speed".
        r = c.post("/api/devices/esp32-fan2/capability",
                   json={"values": {"speed": 40}}, headers=ktok)
        assert r.status_code == 403, r.text

        flags = {x["key"]: x.get("may_write") for x in
                 c.get("/api/devices/esp32-fan2/capabilities", headers=ktok).json()["capabilities"]}
        assert flags == {"ch1": True, "speed": False, "temp": False}, flags

        # A read-only capability cannot be granted at all: there is nothing to
        # write, and reading needs no grant.
        bad = c.put(f"/api/children/{child_id}/grants", headers=tok, json={"grants": [
            {"device_id": "esp32-fan2", "key": "temp", "is_allowed": True}]})
        assert bad.status_code == 400, bad.text
        # Nor can a capability the device never declared.
        bad = c.put(f"/api/children/{child_id}/grants", headers=tok, json={"grants": [
            {"device_id": "esp32-fan2", "key": "nope", "is_allowed": True}]})
        assert bad.status_code == 404, bad.text
    finally:
        close(ws, session)
    print("  grants: denied by default, granted per key not per device,")
    print("          read-only and undeclared keys refused, child told what it may write")


def test_grant_dies_with_its_capability():
    """§5.10: a grant for a capability that left the descriptor is deleted, so a
    key that reappears in a later build reappears denied."""
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    tok, child_id, ktok = household(c, "shrink@x.test", "esp32-shrink", "5926")

    ws, session = identify(c, "esp32-shrink", FAN_V2, "5926")
    try:
        c.put(f"/api/children/{child_id}/grants", headers=tok, json={"grants": [
            {"device_id": "esp32-shrink", "key": "speed", "is_allowed": True}]})
        granted = {g["key"]: g["is_allowed"] for g in
                   c.get(f"/api/children/{child_id}/grants", headers=tok).json()["grants"]}
        assert granted["speed"] is True, granted
    finally:
        close(ws, session)

    # A new firmware build drops `speed`.
    smaller = dict(FAN_V2, capabilities=[FAN_V2["capabilities"][0]], state={"ch1": "off"})
    ws, session = identify(c, "esp32-shrink", smaller, "5926")
    try:
        keys = _wait_for(
            lambda: [x["key"] for x in c.get("/api/devices/esp32-shrink/capabilities",
                                             headers=tok).json()["capabilities"]],
            lambda v: v == ["ch1"])
        assert keys == ["ch1"], keys
        listed = c.get(f"/api/children/{child_id}/grants", headers=tok).json()["grants"]
        assert [g["key"] for g in listed] == ["ch1"], listed

        # And when it comes back, it comes back denied.
        close(ws, session)
        ws, session = identify(c, "esp32-shrink", FAN_V2, "5926")
        listed = _wait_for(
            lambda: {g["key"]: g["is_allowed"] for g in
                     c.get(f"/api/children/{child_id}/grants", headers=tok).json()["grants"]},
            lambda v: "speed" in v)
        assert listed["speed"] is False, listed
    finally:
        close(ws, session)
    print("  grants: deleted with their capability, and a returning key is denied")


# ── §5.11 labels ──────────────────────────────────────────────
def test_labels():
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    tok, _, _ = household(c, "label@x.test", "esp32-label", "6284")
    ws, session = identify(c, "esp32-label", FAN_V2, "6284")
    try:
        def label_of(key):
            caps = c.get("/api/devices/esp32-label/capabilities", headers=tok).json()
            return {x["key"]: x["label"] for x in caps["capabilities"]}[key]

        assert label_of("speed") == "Fan speed"          # the firmware's
        r = c.put("/api/devices/esp32-label/capabilities/speed",
                  json={"label": "Breeze"}, headers=tok)
        assert r.status_code == 200 and r.json()["custom"] is True, r.text
        assert label_of("speed") == "Breeze"

        # A firmware re-declare must not overwrite a name a person chose.
        ws.send_json({"id": "esp32-label", "pin": "6284", **FAN_V2})
        time.sleep(0.3)
        assert label_of("speed") == "Breeze"

        # Clearing *is* the reset: the firmware's label applies again.
        r = c.put("/api/devices/esp32-label/capabilities/speed",
                  json={"label": None}, headers=tok)
        assert r.json()["custom"] is False and r.json()["label"] == "Fan speed", r.json()
        assert label_of("speed") == "Fan speed"

        # An undeclared key cannot be named.
        assert c.put("/api/devices/esp32-label/capabilities/nope",
                     json={"label": "x"}, headers=tok).status_code == 404
    finally:
        close(ws, session)
    print("  labels: house name beats firmware, survives a re-declare, clearing resets")


# ── the facade the shipped app still calls ────────────────────
def test_relay_facade_shares_one_store():
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    tok, child_id, ktok = household(c, "facade@x.test", "esp32-facade", "7391")
    ws, session = identify(c, "esp32-facade", V1_IDENTIFY, "7391")
    try:
        relays = _wait_for(lambda: c.get("/api/relays", headers=tok).json()["relays"],
                           lambda v: len(v) == 3)
        relay_id = [r["relay_id"] for r in relays if r["channel_number"] == 2][0]

        # Granting through the old relay-shaped endpoint...
        made = c.post("/api/permissions", headers=tok,
                      json={"child_id": child_id, "relay_id": relay_id, "is_allowed": True})
        assert made.status_code == 200, made.text
        assert made.json()["key"] == "ch2", made.json()

        # ...is the same row the capability view reports. One store, two spellings.
        granted = {g["key"]: g["is_allowed"] for g in
                   c.get(f"/api/children/{child_id}/grants", headers=tok).json()["grants"]}
        assert granted["ch2"] is True and granted["ch1"] is False, granted

        listed = c.get("/api/permissions", headers=tok).json()["permissions"]
        assert [p["relay_id"] for p in listed] == [relay_id], listed
        perm_id = listed[0]["permission_id"]

        # The child may now switch channel 2 through the v1 command path.
        result = {}

        def call(cmd, channel):
            result["r"] = c.post("/api/devices/esp32-facade/command",
                                 json={"cmd": cmd, "channel": channel}, headers=ktok)

        import threading
        caller = threading.Thread(target=call, args=("on", 2))
        caller.start()
        try:
            frame = ws.receive_json()
            assert frame["cmd"] == "output_on" and frame["channel"] == 2, frame
            ws.send_json({"id": "esp32-facade", "status": "ok",
                          "ch1": "off", "ch2": "on", "ch3": "off"})
        finally:
            caller.join(timeout=15)
        assert result["r"].json()["status"] == "ok", result["r"].json()

        # ...but not channel 1, and the refusal comes from the grant store.
        caller = threading.Thread(target=call, args=("on", 1))
        caller.start()
        caller.join(timeout=15)
        assert result["r"].status_code == 403, result["r"].text

        # Revoking through the facade revokes the grant.
        assert c.put(f"/api/permissions/{perm_id}", json={"is_allowed": False},
                     headers=tok).status_code == 200
        granted = {g["key"]: g["is_allowed"] for g in
                   c.get(f"/api/children/{child_id}/grants", headers=tok).json()["grants"]}
        assert granted["ch2"] is False, granted
        assert c.delete(f"/api/permissions/{perm_id}", headers=tok).status_code == 200
        assert c.get("/api/permissions", headers=tok).json()["permissions"] == []
    finally:
        close(ws, session)
    print("  facade: /api/permissions and the grant view are one store, and the")
    print("          v1 command path is refused from it")


def _wait_for(read, done, attempts=40, delay=0.05):
    """Poll until the app's event loop has committed what we are reading."""
    value = read()
    for _ in range(attempts):
        if done(value):
            return value
        time.sleep(delay)
        value = read()
    return value


if __name__ == "__main__":
    test_claiming_creates_nothing_but_the_device()
    test_grants_default_to_denied()
    test_grant_dies_with_its_capability()
    test_labels()
    test_relay_facade_shares_one_store()
    print("OK: claiming creates only the device, grants key on capabilities, "
          "labels belong to the house")
