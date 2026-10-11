"""Self-check for the Open API (PROTOCOL.md §12): what a scoped key may reach.

The first half drives `open_api.py` directly - the scope rules with no database and no
HTTP in the way. The second half boots the real app, issues real keys, and plays devices
over WebSockets so that a `set` really is carried to a board and acknowledged.

What matters, and what this drives:

  * a key issued before scoping existed still means the whole house, read and command;
  * a scoped key reaches only its devices and its capabilities, on v1 as well as v2, and
    what is outside its scope reads as *not found*, the same as a device that is not there;
  * a key is read-only unless it was issued otherwise, and `confirm:true` is refused to any
    key - the body flag that satisfies it for the app is not even looked at;
  * the whole of a request is judged before anything is sent;
  * scope is applied against the descriptor as it is now, and an unreadable scope reaches
    nothing rather than everything;
  * everything §12.2 lists as out of reach (children, pairing, other keys) is out of reach.

Run:  python test_open_api.py      (needs fastapi, sqlalchemy, httpx<0.28)

The server's own log lines are part of a passing run. The signal is the final OK line and
an exit code of 0.
"""
import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "openapi.db")
os.environ["SECRET_KEY"] = "test-key-not-a-secret"

import json  # noqa: E402
import threading  # noqa: E402

import open_api  # noqa: E402
from sqlalchemy import text  # noqa: E402
from descriptor import Capability  # noqa: E402
from open_api import LEGACY, NOTHING, Scope, ScopeError  # noqa: E402

HOUSE = {"esp32-fan", "esp32-jar", "esp32-old"}


def cap(key, kind="switch", access="rw", confirm=False, label=None):
    return Capability(key=key, kind=kind, label=label or key, access=access, confirm=confirm,
                      known_kind=True)


# ── the rules, on their own ───────────────────────────────────
def test_parsing():
    assert open_api.parse(None, HOUSE) is None, "no scope is the legacy whole-house key"

    s = open_api.parse({"devices": ["esp32-jar"], "keys": ["salt", "_batt"]}, HOUSE)
    assert s == Scope(frozenset({"esp32-jar"}), frozenset({"salt", "_batt"}), False), s
    assert s.write is False, "a scope that does not say is read-only"
    assert open_api.parse({"write": True}, HOUSE) == Scope(None, None, True), "each list is optional"
    assert open_api.parse({"devices": ["esp32-jar", "esp32-jar"]}, HOUSE).devices == frozenset({"esp32-jar"})

    for raw, why in [
            ("everything", "not an object"),
            ([], "a list"),
            ({"devices": []}, "an empty list reaches nothing"),
            ({"keys": []}, "an empty list reaches nothing"),
            ({"devices": "esp32-jar"}, "a string, not a list"),
            ({"devices": ["esp32-jar", 3]}, "a non-string entry"),
            ({"devices": ["esp32-elsewhere"]}, "a device that is not in this house"),
            ({"keys": ["Salt"]}, "not a valid key"),
            ({"keys": ["a" * 25]}, "too long to be a key"),
            ({"keys": ["has space"]}, "not a valid key"),
            ({"write": "yes"}, "write is a boolean"),
            ({"write": 1}, "write is a boolean"),
            ({"admin": True}, "an unknown field is a typo, not a permission"),
            ({"devices": [f"d{i}" for i in range(65)]}, "more than 64")]:
        try:
            open_api.parse(raw, HOUSE | {f"d{i}" for i in range(65)})
        except ScopeError:
            continue
        raise AssertionError(f"scope {raw!r} should be refused: {why}")
    print("  parse: no scope is legacy; lists optional; write defaults to false; empty, foreign, malformed and")
    print("         unknown-field scopes are refused")


def test_storage_fails_closed():
    s = open_api.parse({"devices": ["esp32-jar"], "keys": ["salt"], "write": True}, HOUSE)
    assert open_api.load(open_api.dump(s)) == s, "round trip"
    assert open_api.load(open_api.dump(Scope(None, None, False))) == Scope(None, None, False)
    assert open_api.load(None) is LEGACY, "no stored scope is a key from before scoping"
    for garbage in ("", "garbage", "[]", "{}", '{"devices":"x","keys":null,"write":true}',
                    '{"devices":null,"keys":null}', '{"devices":null,"keys":null,"write":"yes"}',
                    '{"devices":null,"keys":3,"write":true}', "null", "7"):
        got = open_api.load(garbage)
        assert got == NOTHING and not got.sees_device("esp32-jar") and not got.write, \
            f"{garbage!r} must reach nothing, got {got}"
    assert open_api.describe(LEGACY) is None, "the legacy key is shown as having no scope"
    assert open_api.describe(Scope(None, None, True)) == {"devices": None, "keys": None, "write": True}, \
        "an unrestricted key that was *issued* so is not mistaken for a legacy one"
    print("  storage: round-trips; no scope is legacy; anything unreadable - empty, wrong type, missing field -")
    print("           reaches nothing, never everything")


def test_what_a_scope_sees_and_sets():
    s = Scope(frozenset({"esp32-fan"}), frozenset({"ch1", "speed", "lock", "temp"}), True)
    assert s.sees_device("esp32-fan") and not s.sees_device("esp32-jar")
    assert s.sees_key("esp32-fan", "speed") and not s.sees_key("esp32-fan", "mode")
    assert not s.sees_key("esp32-jar", "speed"), "a key name is only meaningful on a device in scope"

    payload = {"proto": 2, "capabilities": [
        {"key": "ch1", "kind": "switch"}, {"key": "speed", "kind": "range"},
        {"key": "mode", "kind": "enum"}, {"key": "lock", "kind": "switch", "confirm": True},
        {"key": "temp", "kind": "number", "access": "r"}, {"key": "bell", "kind": "button", "access": "w"}],
        "state": {"ch1": "on", "speed": 5, "mode": "eco", "lock": "off", "temp": 21}}
    v = open_api.view(s, "esp32-fan", payload)
    assert [c["key"] for c in v["capabilities"]] == ["ch1", "speed", "lock", "temp"], v["capabilities"]
    assert {c["key"]: c["may_write"] for c in v["capabilities"]} == {
        "ch1": True, "speed": True, "lock": False, "temp": False}, "confirm and read-only are never writable by a key"
    assert v["state"] == {"ch1": "on", "speed": 5, "lock": "off", "temp": 21}, "state is cut to the same keys"
    ro = open_api.view(Scope(None, None, False), "esp32-fan", payload)
    assert not any(c["may_write"] for c in ro["capabilities"]), "a read-only key may write nothing"
    assert payload["state"]["mode"] == "eco", "viewing must not alter the original"

    caps = {c.key: c for c in (cap("ch1"), cap("speed", "range"), cap("mode", "enum"),
                               cap("lock", confirm=True), cap("temp", "number", "r"))}
    assert open_api.set_denial(s, "esp32-fan", {"ch1": "on", "speed": 5}, caps) is None
    for values, status, needle in [
            ({"mode": "eco"}, "not_permitted", "may not set"),                 # declared, outside the scope
            ({"ghost": 1}, "not_permitted", "may not set"),                    # not declared at all
            ({"lock": "on"}, "not_permitted", "person"),                       # confirm
            ({"temp": 3}, "not_permitted", "read-only"),                       # a sensor
            ({"ch1": "on", "mode": "eco"}, "not_permitted", "may not set"),    # one bad key sinks the request
            ({}, "bad_value", "values"), ("on", "bad_value", "values"), (None, "bad_value", "values")]:
        d = open_api.set_denial(s, "esp32-fan", values, caps)
        assert d and d["status"] == status and needle in d["detail"], (values, d)
    a = open_api.set_denial(s, "esp32-fan", {"mode": "eco"}, caps)
    b = open_api.set_denial(s, "esp32-fan", {"ghost": 1}, caps)
    assert {k: v for k, v in a.items() if k != "key"} == {k: v for k, v in b.items() if k != "key"}, \
        "out of scope and undeclared read the same, or a scoped key could list what it was not given"
    assert open_api.set_denial(Scope(None, None, False), "esp32-fan", {"ch1": "on"}, caps)["detail"].startswith("this key is read-only")
    assert open_api.set_denial(Scope(frozenset({"esp32-jar"}), None, True), "esp32-fan", {"ch1": "on"}, caps) \
        ["status"] == "not_permitted", "a device outside the scope"
    print("  rules: a scope sees only its devices and keys, a view carries may_write for *this* key, and a set is refused")
    print("         whole for an out-of-scope, undeclared, read-only or confirm capability - all of which read the same")


# ── the real app ──────────────────────────────────────────────
FAN = {
    "proto": 2, "status": "online", "model": "fan", "fw": "1.0.0", "mac": "24:6F:28:AA:EE:01",
    "capabilities": [
        {"key": "ch1", "kind": "switch", "label": "Fan"},
        {"key": "speed", "kind": "range", "label": "Speed", "min": 0, "max": 100, "step": 5},
        {"key": "mode", "kind": "enum", "label": "Mode", "options": ["eco", "boost"]},
        {"key": "lock", "kind": "switch", "label": "Child lock", "confirm": True},
        {"key": "temp", "kind": "number", "label": "Room temp", "access": "r"},
    ],
    "state": {"ch1": "off", "speed": 0, "mode": "eco", "lock": "off", "temp": 21},
}
JAR = {
    "proto": 2, "status": "online", "model": "jar", "fw": "1.0.0", "mac": "24:6F:28:AA:EE:02",
    "capabilities": [
        {"key": "salt", "kind": "number", "label": "Salt left", "unit": "%", "access": "r"},
        {"key": "_batt", "kind": "number", "label": "Battery", "access": "r"},
    ],
    "state": {"salt": 40, "_batt": 88},
}
VAULT = {
    "proto": 2, "status": "online", "model": "vault", "fw": "1.0.0", "mac": "24:6F:28:AA:EE:03",
    "capabilities": [{"key": "ch1", "kind": "switch", "label": "Door lock", "confirm": True}],
    "state": {"ch1": "off"},
}
OLD = {"status": "online", "ch1": "off", "ch2": "off", "ch3": "off"}


def call_and_answer(c, board, request, reply):
    """Run an HTTP request that blocks on a device while this thread plays the device.
    `reply(frame)` returns what the device sends back, or None to send nothing."""
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("r", request()))
    t.start()
    frame = board.next()
    answer = reply(frame)
    if answer is not None:
        board.ws.send_json({"id": board.id, **answer})
    t.join(timeout=15)
    assert not t.is_alive(), "the request never returned"
    return out["r"], frame


def ack_for(**state):
    return lambda f: {"type": "ack", "req": f["req"], "status": "ok", "state": state}


def test_the_real_app():
    from fastapi.testclient import TestClient
    import main
    from test_peering import Board, household

    c = TestClient(main.app)
    for limit in (main.OPEN_API_RATE, main.OPEN_API_WRITE_RATE):
        limit.clear_all()
    tok = household(c, "oa@x.test", "Open House",
                    [("esp32-fan", "4821"), ("esp32-jar", "5937"), ("esp32-old", "6143"), ("esp32-vault", "7351")])
    db = main.SessionLocal()
    try:
        house_id = db.query(main.Account).filter(main.Account.email == "oa@x.test").first().house_id
    finally:
        db.close()
    other_tok = household(c, "ob@x.test", "Other House", [("esp32-else", "8317")])

    fan = Board(c, "esp32-fan", "4821", FAN)
    jar = Board(c, "esp32-jar", "5937", JAR)
    old = Board(c, "esp32-old", "6143", OLD)
    vault = Board(c, "esp32-vault", "7351", VAULT)
    boards = [fan, jar, old, vault]

    def issue(name, scope="omit", expect=200):
        body = {"name": name}
        if scope != "omit":
            body["scope"] = scope
        r = c.post(f"/api/houses/{house_id}/api-keys", json=body, headers=tok)
        assert r.status_code == expect, (name, scope, r.status_code, r.text)
        return r.json()

    def H(key):
        return {"X-API-Key": key["api_key"]}

    try:
        # ── issuing ──
        legacy = issue("legacy")
        assert legacy["scope"] is None, "a key issued without a scope is the legacy whole-house key"
        dash = issue("dashboard", {"devices": ["esp32-jar"], "keys": ["salt"]})
        assert dash["scope"] == {"devices": ["esp32-jar"], "keys": ["salt"], "write": False}, dash["scope"]
        control = issue("fan control", {"devices": ["esp32-fan"], "keys": ["ch1", "speed", "lock"], "write": True})
        old_ch1 = issue("one channel", {"devices": ["esp32-old"], "keys": ["ch1"], "write": True})
        for bad in ({"devices": ["esp32-else"]}, {"devices": []}, {"keys": ["Bad Key"]}, {"write": "yes"},
                    {"nonsense": 1}, "everything"):
            issue("bad", bad, expect=400)
        # only the master may issue, and only for their own house
        assert c.post(f"/api/houses/{house_id}/api-keys", json={"name": "x"}, headers=other_tok).status_code == 403
        listed = c.get(f"/api/houses/{house_id}/api-keys", headers=tok).json()["api_keys"]
        assert {k["name"]: k["scope"] for k in listed}["legacy"] is None
        assert {k["name"]: k["scope"] for k in listed}["dashboard"]["write"] is False
        assert all("api_key" not in k and "key_hash" not in k for k in listed), "the key itself is never listed"

        # ── v2 read, legacy key: the whole house ──
        r = c.get("/api/open/v2/devices", headers=H(legacy))
        assert r.status_code == 200, r.text
        devices = {d["device_id"]: d for d in r.json()["devices"]}
        assert set(devices) == {"esp32-fan", "esp32-jar", "esp32-old", "esp32-vault"}, set(devices)
        fan_caps = {x["key"]: x for x in devices["esp32-fan"]["capabilities"]}
        assert set(fan_caps) == {"ch1", "speed", "mode", "lock", "temp"}
        assert {k: v["may_write"] for k, v in fan_caps.items()} == {
            "ch1": True, "speed": True, "mode": True, "lock": False, "temp": False}, \
            "even the unrestricted key is told it cannot write a confirm capability or a sensor"
        assert devices["esp32-fan"]["state"]["speed"] == 0 and devices["esp32-fan"]["online"] is True
        assert [x["key"] for x in devices["esp32-old"]["capabilities"]] == ["ch1", "ch2", "ch3"], "the shim, as ordinary capabilities"

        # ── v2 read, a dashboard key: one device, one capability, nothing else ──
        r = c.get("/api/open/v2/devices", headers=H(dash)).json()["devices"]
        assert [d["device_id"] for d in r] == ["esp32-jar"], r
        assert [x["key"] for x in r[0]["capabilities"]] == ["salt"], "the battery is not in scope"
        assert r[0]["state"] == {"salt": 40}, "nor is its value"
        assert not any(x["may_write"] for x in r[0]["capabilities"])
        assert c.get("/api/open/v2/devices/esp32-jar", headers=H(dash)).status_code == 200
        out_of_scope = c.get("/api/open/v2/devices/esp32-fan", headers=H(dash))
        missing = c.get("/api/open/v2/devices/esp32-nothing", headers=H(dash))
        foreign = c.get("/api/open/v2/devices/esp32-else", headers=H(dash))
        assert out_of_scope.status_code == missing.status_code == foreign.status_code == 404
        assert out_of_scope.json() == missing.json() == foreign.json(), \
            "out of scope, absent and another house's device are indistinguishable"

        # ── v2 set ──
        # a read-only key
        r = c.post("/api/open/v2/devices/esp32-jar/set", json={"values": {"salt": 1}}, headers=H(dash))
        assert r.status_code == 403 and r.json()["detail"].startswith("this key is read-only"), r.text
        r = c.post("/api/open/v2/devices/esp32-fan/set", json={"values": {"ch1": "on"}}, headers=H(dash))
        assert r.status_code == 404, "and it cannot tell that the fan exists"

        # refusals leave nothing on the wire: the next frame the fan sees is the allowed set below
        for values, needle in [({"mode": "boost"}, "may not set"),                     # declared, not in scope
                               ({"ghost": 1}, "may not set"),                           # not declared
                               ({"lock": "on"}, "person"),                              # confirm
                               ({"ch1": "on", "mode": "boost"}, "may not set")]:        # one bad key sinks the lot
            r = c.post("/api/open/v2/devices/esp32-fan/set", json={"values": values}, headers=H(control))
            assert r.status_code == 403 and r.json()["status"] == "not_permitted" and needle in r.json()["detail"], \
                (values, r.status_code, r.text)
        r = c.post("/api/open/v2/devices/esp32-fan/set", json={"values": {"lock": "on"}, "confirmed": True},
                   headers=H(control))
        assert r.status_code == 403 and r.json().get("needs_confirmation") is True, \
            "the body flag that satisfies the app's confirm step means nothing to a key"
        r = c.post("/api/open/v2/devices/esp32-fan/set", json={"values": {}}, headers=H(control))
        assert r.status_code == 400
        r = c.post("/api/open/v2/devices/esp32-fan/set", json={"values": {"speed": 500}}, headers=H(control))
        assert r.json()["status"] == "bad_value", "a value the declaration forbids is stopped before the device"
        r = c.post("/api/open/v2/devices/esp32-fan/set", json={}, headers=H(control))
        assert r.status_code == 400

        # the allowed one is carried to the board and answered
        r, frame = call_and_answer(
            c, fan, lambda: c.post("/api/open/v2/devices/esp32-fan/set",
                                   json={"values": {"ch1": "on", "speed": 60}}, headers=H(control)),
            ack_for(ch1="on", speed=60))
        assert frame["type"] == "set" and frame["values"] == {"ch1": "on", "speed": 60}, \
            f"the first frame the fan saw must be the allowed set, not a refused one: {frame}"
        assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["state"] == {"ch1": "on", "speed": 60}, r.text
        got = c.get("/api/open/v2/devices/esp32-fan", headers=H(control)).json()
        assert got["state"]["speed"] == 60 and "mode" not in got["state"], "state follows the set, cut to scope"

        # attribution: the activity log says a key did it, and which
        db = main.SessionLocal()
        try:
            rows = db.query(main.ActivityLog).filter(main.ActivityLog.house_id == house_id,
                                                     main.ActivityLog.actor_type == "api").all()
            assert len(rows) == 1 and "fan control" in rows[0].summary and rows[0].actor_id == control["key_id"], \
                [r.summary for r in rows]
        finally:
            db.close()

        # a sensor and a hidden capability, through the unrestricted key
        r = c.post("/api/open/v2/devices/esp32-fan/set", json={"values": {"temp": 3}}, headers=H(legacy))
        assert r.status_code == 403 and "read-only" in r.json()["detail"]
        r = c.post("/api/open/v2/devices/esp32-vault/set", json={"values": {"ch1": "on"}, "confirmed": True},
                   headers=H(legacy))
        assert r.status_code == 403 and r.json().get("needs_confirmation") is True

        # ── scope is judged against the descriptor as it is now ──
        fan.close()
        trimmed = dict(FAN, capabilities=[x for x in FAN["capabilities"] if x["key"] != "speed"])
        fan = Board(c, "esp32-fan", "4821", trimmed)
        boards[0] = fan
        got = c.get("/api/open/v2/devices/esp32-fan", headers=H(control)).json()
        assert [x["key"] for x in got["capabilities"]] == ["ch1", "lock"], "a capability that left the descriptor is gone"
        r = c.post("/api/open/v2/devices/esp32-fan/set", json={"values": {"speed": 10}}, headers=H(control))
        assert r.status_code == 403, "...and unreachable, whatever the key's scope says"

        # ── an unreadable stored scope reaches nothing ──
        db = main.SessionLocal()
        try:
            row = db.query(main.ApiKey).filter(main.ApiKey.key_id == dash["key_id"]).first()
            row.scope = "{this is not json"
            db.commit()
        finally:
            db.close()
        assert c.get("/api/open/v2/devices", headers=H(dash)).json() == {"devices": []}
        assert c.get("/api/open/v1/devices", headers=H(dash)).json() == {"devices": []}
        assert c.get("/api/open/v2/devices/esp32-jar", headers=H(dash)).status_code == 404

        # ── v1 is frozen, not unscoped ──
        v1 = c.get("/api/open/v1/devices", headers=H(legacy)).json()["devices"]
        by_id = {d["device_id"]: d for d in v1}
        assert [x["channel"] for x in by_id["esp32-old"]["channels"]] == [1, 2, 3], "legacy: unchanged"
        v1 = c.get("/api/open/v1/devices", headers=H(old_ch1)).json()["devices"]
        assert [d["device_id"] for d in v1] == ["esp32-old"]
        assert [x["channel"] for x in v1[0]["channels"]] == [1], "a channel is a capability key and is scoped as one"
        assert c.get("/api/open/v1/devices/esp32-fan", headers=H(old_ch1)).status_code == 404

        for body in ({"cmd": "on", "channel": 2}, {"cmd": "all_on"}, {"cmd": "all_off"}):
            r = c.post("/api/open/v1/devices/esp32-old/command", json=body, headers=H(old_ch1))
            assert r.status_code == 403, (body, r.text)
        r = c.post("/api/open/v1/devices/esp32-old/command", json={"cmd": "on", "channel": 1}, headers=H(dash))
        assert r.status_code in (403, 404), "a read-only key may not switch (and this one cannot see the device)"
        r = c.post("/api/open/v1/devices/esp32-jar/command", json={"cmd": "on", "channel": 1}, headers=H(issue("ro", {"write": False})))
        assert r.status_code == 403 and "may not" in r.json()["detail"], r.text

        r, frame = call_and_answer(
            c, old, lambda: c.post("/api/open/v1/devices/esp32-old/command", json={"cmd": "on", "channel": 1},
                                   headers=H(old_ch1)),
            lambda f: {"status": "ok", "ch1": "on", "ch2": "off", "ch3": "off"})
        assert frame["cmd"] == "output_on" and frame["channel"] == 1, frame
        assert r.status_code == 200 and r.json()["status"] == "ok", r.text

        # the confirm gate on the frozen surface: before, v1 could switch a lock a person had to approve
        r = c.post("/api/open/v1/devices/esp32-vault/command", json={"cmd": "on", "channel": 1}, headers=H(legacy))
        assert r.status_code == 403 and "confirm" in r.json()["detail"], r.text

        # ── §12.2: what a key may never reach ──
        nothing_for_keys = [
            ("get", "/api/peerings"), ("post", "/api/peerings"),
            ("get", f"/api/houses/{house_id}/api-keys"), ("post", f"/api/houses/{house_id}/api-keys"),
            ("delete", f"/api/houses/{house_id}/api-keys/{legacy['key_id']}"),
            ("get", "/api/children"), ("get", "/api/devices"),
            ("post", "/api/devices/esp32-fan/command"), ("post", "/api/devices/esp32-fan/capability"),
            ("put", "/api/devices/esp32-fan/agent"), ("get", "/api/activity"),
        ]
        for method, path in nothing_for_keys:
            r = getattr(c, method)(path, headers=H(legacy), **({"json": {}} if method in ("post", "put") else {}))
            assert r.status_code in (401, 403), f"an API key must not reach {method.upper()} {path}: {r.status_code}"

        # ── limits, revocation, other houses ──
        main.OPEN_API_WRITE_RATE.clear_all()
        codes = [c.post("/api/open/v2/devices/esp32-fan/set", json={"values": {"mode": "boost"}},
                        headers=H(control)).status_code for _ in range(22)]
        assert codes[:20] == [403] * 20 and codes[20] == 429, codes[18:]
        assert c.get("/api/open/v2/devices", headers=H(control)).status_code == 200, "reading is a separate budget"
        main.OPEN_API_RATE.clear_all()
        codes = [c.get("/api/open/v2/devices", headers=H(control)).status_code for _ in range(62)]
        assert codes[:60] == [200] * 60 and codes[60] == 429, "a loop in someone's script is bounded: 60 requests a minute"
        main.OPEN_API_RATE.clear_all()

        assert c.delete(f"/api/houses/{house_id}/api-keys/{legacy['key_id']}", headers=tok).status_code == 200
        for path in ("/api/open/v1/devices", "/api/open/v2/devices"):
            assert c.get(path, headers=H(legacy)).status_code == 401, path
        assert c.get("/api/open/v2/devices", headers={"X-API-Key": "maya_not-a-key"}).status_code == 401
        assert c.get("/api/open/v2/devices").status_code in (401, 403)

        # the other house's own key sees only its own device
        db = main.SessionLocal()
        try:
            other_house = db.query(main.Account).filter(main.Account.email == "ob@x.test").first().house_id
        finally:
            db.close()
        theirs = c.post(f"/api/houses/{other_house}/api-keys", json={"name": "theirs"}, headers=other_tok).json()
        seen = [d["device_id"] for d in c.get("/api/open/v2/devices", headers=H(theirs)).json()["devices"]]
        assert seen == ["esp32-else"], seen
        assert c.get("/api/open/v2/devices/esp32-fan", headers=H(theirs)).status_code == 404

        # ── a database from before scoping gains the column and its keys keep their meaning ──
        db = main.SessionLocal()
        try:
            db.query(main.ApiKey).filter(main.ApiKey.key_id == control["key_id"]).update({"scope": None})
            db.commit()
            db.execute(text("ALTER TABLE api_keys DROP COLUMN scope"))
            db.commit()
        finally:
            db.close()
        main.run_migrations()
        db = main.SessionLocal()
        try:
            row = db.query(main.ApiKey).filter(main.ApiKey.key_id == control["key_id"]).first()
            assert row.scope is None, "an existing key is migrated to no scope"
        finally:
            db.close()
        assert open_api.load(None) is LEGACY
        assert len(c.get("/api/open/v2/devices", headers=H(control)).json()["devices"]) == 4, \
            "...which is the whole house, as before"
    finally:
        for b in boards:
            b.close()
    print("  app: a legacy key is the whole house; a dashboard key sees one device and one capability, and the")
    print("       rest is 'not found'; a set is judged whole and refused for out-of-scope/undeclared/read-only/")
    print("       confirm (the body flag is ignored); the allowed one reaches the board and is logged to the key;")
    print("       the same scope holds on v1, which also stops switching a confirm channel; a trimmed descriptor")
    print("       and an unreadable scope close the key; children, pairing and other keys are out of reach;")
    print("       writes are rate limited; revoked, foreign and migrated keys behave")


if __name__ == "__main__":
    test_parsing()
    test_storage_fails_closed()
    test_what_a_scope_sees_and_sets()
    test_the_real_app()
    print("OK: a key reaches what it was given and no more; a key is not a person")
