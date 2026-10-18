"""The Maya library, judged by the real server.

The library (src/MayaCore.*) is built on a laptop and driven through
host_driver.cpp. What it says is then fed to the server's own parser
(software/server/descriptor.py), and in the second half the real app is run with
the driver standing in for the board. So "the library implements PROTOCOL.md" is
not the author's opinion: the identify frame is accepted by parse_identify, each
`set` is answered in a way the server's ack handler understands, and a value the
device reports ends up in the database.

Run:  python test_library.py

Needs a C++ compiler (g++/clang++, or `pip install ziglang`) and the ArduinoJson
v6 headers (set ARDUINOJSON_DIR, or install the Arduino library). The server
needs fastapi, sqlalchemy and httpx<0.28, as for the other self-checks.

Exit 0 means every check ran and passed. Exit 3 means it could not build the
driver, which is *not* a pass.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIB = HERE.parent.parent
SERVER = LIB.parent.parent.parent / "software" / "server"

# The server's modules, and the environment the app wants, before importing any.
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "library.db")
os.environ["SECRET_KEY"] = "test-key-not-a-secret"
sys.path.insert(0, str(SERVER))
os.chdir(SERVER)

import descriptor  # noqa: E402  (the server's own parser)

ID = "esp32-test"
PIN = "4821"


# ── building the driver ──────────────────────────────────────────────────────
def find_arduinojson():
    candidates = [os.environ.get("ARDUINOJSON_DIR")]
    home = Path.home()
    candidates += [home / "Documents" / "Arduino" / "libraries" / "ArduinoJson" / "src",
                   home / "Arduino" / "libraries" / "ArduinoJson" / "src",
                   Path("C:/mac/user/libraries/ArduinoJson/src")]
    for c in candidates:
        if c and (Path(c) / "ArduinoJson.h").exists():
            return str(c)
    return None


def find_compiler():
    if os.environ.get("MAYA_CXX"):
        return os.environ["MAYA_CXX"].split()
    for name in ("g++", "clang++", "c++"):
        if shutil.which(name):
            return [name]
    try:
        subprocess.run([sys.executable, "-m", "ziglang", "version"], check=True,
                       capture_output=True)
        return [sys.executable, "-m", "ziglang", "c++"]
    except Exception:
        return None


def build_driver():
    aj = find_arduinojson()
    cxx = find_compiler()
    if not aj or not cxx:
        print("CANNOT RUN: " + ("ArduinoJson headers not found (set ARDUINOJSON_DIR). " if not aj else "")
              + ("No C++ compiler (install g++, or `pip install ziglang`)." if not cxx else ""))
        sys.exit(3)
    out = Path(tempfile.mkdtemp()) / ("driver.exe" if os.name == "nt" else "driver")
    cmd = cxx + ["-std=c++17", "-w", f"-I{LIB / 'src'}", f"-I{aj}",
                 str(HERE / "host_driver.cpp"), str(LIB / "src" / "MayaCore.cpp"),
                 str(LIB / "src" / "MayaPeer.cpp"), str(LIB / "src" / "MayaRelay.cpp"),
                 str(LIB / "src" / "MayaCrypto.cpp"), "-o", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        raise SystemExit("driver failed to compile - that is a library bug")
    return str(out)


class Driver:
    """One board, as a process: commands in, frames out."""

    def __init__(self, exe, profile, state_dir=None, device_id=None, mac=None):
        env = dict(os.environ)
        if device_id:
            env["MAYA_ID"] = device_id
        if mac:
            env["MAYA_MAC"] = mac
        args = [exe, profile] + ([state_dir] if state_dir else [])
        self.p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  text=True, encoding="utf-8", bufsize=1, env=env)

    def run(self, command):
        """Send one command; return (frames sent, hardware log, other lines)."""
        self.p.stdin.write(command + "\n")
        self.p.stdin.write("sync\n")
        self.p.stdin.flush()
        tx, hw, other = [], [], []
        while True:
            line = self.p.stdout.readline().rstrip("\n")
            if line == "SYNC" or line == "":
                break
            if line.startswith("TX "):
                tx.append(json.loads(line[3:]))
            elif line.startswith("HW "):
                hw.append(line[3:])
            else:
                other.append(line)
        return tx, hw, other

    def frame(self, obj):
        return self.run("frame " + json.dumps(obj))

    def set(self, values, req="r1", id=ID):
        return self.frame({"id": id, "type": "set", "req": req, "values": values})

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()


def only(items, what):
    assert len(items) == 1, f"expected exactly one {what}, got {items}"
    return items[0]


# ── part A: the library against the server's parser ──────────────────────────
def test_identify_is_what_the_server_accepts(exe):
    d = Driver(exe, "lampfan")
    tx, _, other = d.run("identify")
    d.close()
    assert not other, other
    frame = only(tx, "identify frame")

    assert frame["proto"] == 2 and frame["status"] == "online" and frame["pin"] == PIN
    assert frame["id"] == ID and frame["model"] == "host_test" and frame["fw"] == "9.9.9"
    assert frame["mac"] == "24:6F:28:AA:BB:01", "7.1: a device that can be paired says where it is on the air"

    desc = descriptor.parse_identify(frame)
    assert desc.proto == 2 and not desc.shimmed, "a v2 device must not be shimmed"
    assert desc.warnings == [], desc.warnings   # nothing dropped, nothing unrecognised

    by = desc.by_key
    expected = {"lamp": "switch", "fan": "range", "temp": "number", "mode": "enum", "msg": "text",
                "strip": "color", "wake": "time", "runfor": "duration", "horn": "button",
                "reset": "button", "pos": "location", "motion": "switch", "picky": "switch",
                "_batt": "number", "_rssi": "number", "_fw": "text"}
    assert {k: c.kind for k, c in by.items()} == expected
    assert (by["fan"].min, by["fan"].max, by["fan"].step, by["fan"].unit) == (0, 100, 5, "%")
    assert by["mode"].options == ["eco", "normal", "boost"]
    assert by["msg"].max == 8 and by["runfor"].max == 7200
    assert by["temp"].access == "r" and by["temp"].history
    assert by["motion"].access == "r" and by["pos"].access == "r"
    # §5.4 — the two safety fields survive the trip, and mean what they say.
    assert by["horn"].confirm and by["reset"].agent == "deny"
    assert by["lamp"].agent == "allow" and not by["lamp"].confirm
    # §5.3 — the reserved keys are kept, not dropped as unknown `_` keys.
    assert by["_batt"].unit == "%" and by["_rssi"].unit == "dBm"

    # Only values the sketch has actually reported are in `state`, and they pass.
    assert descriptor.coerce_state(by, frame["state"]) == {"_fw": "9.9.9"}
    print("  identify: parsed by the server's own parse_identify, 16 capabilities, nothing dropped,")
    print("            confirm/agent/reserved keys survive")


def test_set_frames(exe):
    d = Driver(exe, "lampfan")
    d.run("identify")
    by = descriptor.parse_identify(d.run("identify")[0][0]).by_key

    def clean(ack):
        # Whatever a device acks must itself pass the server's value rules.
        if "state" in ack:
            assert descriptor.coerce_state(by, ack["state"]) == ack["state"], ack
        return ack

    # one capability
    tx, hw, _ = d.set({"lamp": "on"}, req="c-1")
    ack = clean(only(tx, "ack"))
    assert ack == {"id": ID, "type": "ack", "req": "c-1", "status": "ok", "state": {"lamp": "on"}}, ack
    assert hw == ["lamp=1"], hw

    # one of every writable kind, in one frame
    tx, hw, _ = d.set({"lamp": "off", "fan": 60, "mode": "boost", "msg": "hi", "strip": "#FF8800",
                       "wake": "07:30", "runfor": 600}, req="c-2")
    ack = clean(only(tx, "ack"))
    assert ack["status"] == "ok" and ack["req"] == "c-2"
    assert ack["state"] == {"lamp": "off", "fan": 60, "mode": "boost", "msg": "hi",
                            "strip": "#ff8800", "wake": "07:30", "runfor": 600}, ack["state"]
    assert hw == ["lamp=0", "fan=60", "mode=boost", "msg=hi", "strip=#ff8800", "wake=07:30",
                  "runfor=600"], hw   # applied in the order sent (§6.2)

    # §6.2: a press is null, runs the hardware, and reports no state for it
    tx, hw, _ = d.set({"horn": None}, req="c-3")
    ack = only(tx, "ack")
    assert ack == {"id": ID, "type": "ack", "req": "c-3", "status": "ok"}, ack
    assert hw == ["horn"], hw

    # §6.2: stop at the first failure, say how far it got, no rollback
    tx, hw, _ = d.set({"lamp": "on", "fan": 999, "mode": "eco"}, req="c-4")
    ack = clean(only(tx, "ack"))
    assert ack["status"] == "bad_value" and ack["failed"] == "fan", ack
    assert ack["state"] == {"lamp": "on"}, ack            # what DID apply
    assert hw == ["lamp=1"], hw                            # `mode` never ran

    # §9 — each way a set can be refused
    for values, status, failed in [
            ({"nope": 1}, "unknown_capability", "nope"),
            ({"motion": "on"}, "not_permitted", "motion"),        # access:"r"
            ({"pos": {"lat": 1, "lng": 2}}, "not_permitted", "pos"),
            ({"mode": "turbo"}, "bad_value", "mode"),             # not an option
            ({"msg": "123456789"}, "bad_value", "msg"),           # past max 8
            ({"strip": "red"}, "bad_value", "strip"),
            ({"wake": "25:00"}, "bad_value", "wake"),
            ({"wake": "7:30"}, "bad_value", "wake"),
            ({"runfor": -1}, "bad_value", "runfor"),
            ({"runfor": 7201}, "bad_value", "runfor"),
            ({"fan": -1}, "bad_value", "fan"),
            ({"fan": "fast"}, "bad_value", "fan"),
            ({"lamp": "maybe"}, "bad_value", "lamp"),
            ({"lamp": 7}, "bad_value", "lamp"),
            ({"picky": "on"}, "bad_value", "picky")]:             # the hardware said no
        tx, hw, _ = d.set(values)
        ack = clean(only(tx, "ack"))
        assert (ack["status"], ack.get("failed")) == (status, failed), (values, ack)
        assert "state" not in ack and hw == [], (values, ack, hw)

    # a frame with no values is a bad_value, not a crash
    tx, _, _ = d.frame({"id": ID, "type": "set", "req": "c-5"})
    assert only(tx, "ack")["status"] == "bad_value"

    # §3: a frame for another id is not ours; nothing is sent, nothing runs
    tx, hw, other = d.set({"lamp": "on"}, id="esp32-someone-else")
    assert tx == [] and hw == [] and other == ["ACTION none"], (tx, hw, other)

    # a set with no `req` is answered without inventing one
    tx, _, _ = d.frame({"id": ID, "type": "set", "values": {"lamp": "off"}})
    assert "req" not in only(tx, "ack")
    d.close()
    print("  set: every kind, button press, partial failure without rollback, and the six refusals")
    print("       each ack passes the server's own value rules")


def test_state_reports(exe):
    d = Driver(exe, "lampfan")
    by = descriptor.parse_identify(d.run("identify")[0][0]).by_key

    assert d.run("setnum temp 21.5")[2] == ["SET 1"]
    tx, _, other = d.run("flush")
    frame = only(tx, "state report")
    assert frame["type"] == "state" and frame["id"] == ID and frame["state"] == {"temp": 21.5}, frame
    assert "uptime_ms" in frame
    assert descriptor.coerce_state(by, frame["state"]) == {"temp": 21.5}

    # §6.1: send only what changed. Nothing changed, so nothing is sent.
    assert d.run("flush")[0] == []
    d.run("setnum temp 21.5")
    assert d.run("flush")[0] == [], "an unchanged value must not be re-sent"

    # A failed sensor read (NaN, or infinity) is refused, keeps the last good value, and is
    # never sent: NaN != NaN would otherwise make it "changed" on every flush, and JSON
    # cannot carry it.
    for bad in ("nan", "inf", "-inf"):
        assert d.run(f"setnum temp {bad}")[2] == ["SET 0"], f"{bad} must be refused"
    assert d.run("flush")[0] == [], "a refused reading must not be reported"

    # a whole number goes out as one
    d.run("setnum temp 22")
    tx, _, _ = d.run("flush")
    assert only(tx, "state report")["state"] == {"temp": 22}

    # a read-only switch is something a sensor reports
    d.run("setsw motion 1")
    assert only(d.run("flush")[0], "state report")["state"] == {"motion": "on"}

    # the wrong kind, or an unknown key, is refused rather than guessed at
    assert d.run("setsw temp 1")[2] == ["SET 0"]
    assert d.run("setnum nope 1")[2] == ["SET 0"]

    # a value the server just acked is not dirty again (the ack carried it)
    d.set({"lamp": "on"})
    assert d.run("flush")[0] == [], "ack state must not be re-sent as a change"

    # §6.1: a full report carries everything held, and only that
    tx, _, _ = d.run("full")
    full = only(tx, "full report")
    assert full["type"] == "state"
    assert full["state"]["temp"] == 22 and full["state"]["motion"] == "on" and full["state"]["lamp"] == "on"
    assert "horn" not in full["state"], "a button has no state (§6.2)"
    assert descriptor.coerce_state(by, full["state"]) == full["state"]

    # get_status answers with the full report, and an ack if a req came with it
    tx, _, _ = d.frame({"id": ID, "type": "get_status", "req": "g-1"})
    assert [f["type"] for f in tx] == ["state", "ack"] and tx[1]["req"] == "g-1" and tx[1]["status"] == "ok"
    d.close()
    print("  state: only changes are sent, whole numbers stay whole, ack state is not re-sent,")
    print("         full report on get_status")


def test_reboot_and_factory_reset(exe):
    d = Driver(exe, "lampfan")
    d.run("identify")
    for kind, action in (("reboot", "reboot"), ("factory_reset", "factory_reset")):
        tx, _, other = d.frame({"id": ID, "type": kind, "req": "x-1"})
        # The ack goes out first; the transport acts on the action afterwards.
        assert only(tx, "ack") == {"id": ID, "type": "ack", "req": "x-1", "status": "ok"}
        assert other == [f"ACTION {action}"], other
    d.close()
    print("  reboot / factory_reset: acked first, then the transport is told to act")


def test_declarations_that_break_the_rules(exe):
    for profile, needle in (("broken", "[a-z0-9_]"), ("toomany", "32"), ("reserved", "reserved"),
                            ("toobig", "4096")):
        d = Driver(exe, profile)
        tx, _, other = d.run("identify")
        assert tx == [], f"{profile}: a refused declaration must not be sent: {tx}"
        assert any(l.startswith("IDENTIFY_REFUSED") for l in other), (profile, other)
        text = " ".join(other)
        assert needle in text or "4096" in text, (profile, other)
        d.close()
    print("  bad declarations (key, >32, reserved key, >4 KB) are refused before anything is sent")


def test_protocol1_commands_still_answered(exe):
    d = Driver(exe, "ext3")
    tx, _, _ = d.run("identify")
    desc = descriptor.parse_identify(only(tx, "identify"))
    assert not desc.shimmed and [c.key for c in desc.capabilities] == ["ch1", "ch2", "ch3"]
    assert descriptor.coerce_state(desc.by_key, only(tx, "identify")["state"]) == \
        {"ch1": "off", "ch2": "off", "ch3": "off"}

    def cmd(c, **kw):
        return d.frame({"id": ID, "cmd": c, **kw})

    # Appendix A: a bare status plus every channel, no `req`, no `type`.
    tx, hw, _ = cmd("output_on", channel=2)
    assert only(tx, "v1 ack") == {"id": ID, "status": "ok", "ch1": "off", "ch2": "on", "ch3": "off"}
    assert hw == ["ch2=1"], hw
    tx, _, _ = cmd("output_toggle", channel=2)
    assert only(tx, "v1 ack")["ch2"] == "off"
    tx, _, _ = cmd("output_on", channel=9)
    assert only(tx, "v1 ack")["status"] == "invalid_channel"
    assert only(cmd("all_on")[0], "v1 ack") == {"id": ID, "status": "ok", "ch1": "on", "ch2": "on", "ch3": "on"}
    assert only(cmd("all_off")[0], "v1 ack")["ch3"] == "off"
    assert only(cmd("led_on")[0], "v1 ack")["ch1"] == "on"
    assert only(cmd("toggle")[0], "v1 ack")["ch1"] == "off"
    tx, _, _ = cmd("get_status")
    assert tx[0]["status"] == "ok" and tx[1]["type"] == "state"
    tx, _, other = cmd("factory_reset")
    assert only(tx, "ack") == {"id": ID, "status": "factory_reset"} and other == ["ACTION factory_reset"]
    tx, _, other = cmd("reboot")
    assert only(tx, "ack") == {"id": ID, "status": "rebooting"} and other == ["ACTION reboot"]
    assert cmd("make_coffee")[0] == []   # an unknown command is ignored, as v1 firmware did
    d.close()
    print("  protocol 1: output_on/off/toggle, all_on/off, led_*, get_status, reboot, factory_reset still work")


def test_asking_maya(exe):
    d = Driver(exe, "lampfan")

    def reply(status, req="a-1", text="", **extra):
        return {"id": ID, "type": "agent_reply", "req": req, "status": status, "text": text, **extra}

    # 8.1: one frame, in the shape the server expects, with the request id it will echo
    tx, _, other = d.run("ask someone is at the front door")
    assert only(tx, "agent request") == {"id": ID, "type": "agent", "req": "a-1",
                                         "text": "someone is at the front door"}
    assert other == ["AGENT 1"]

    # one at a time: a second is refused here, without a frame, as the server would
    tx, _, other = d.run("ask are you there")
    assert tx == [] and other == ["AGENT 0"]

    # a reply for some other request is not ours
    assert d.frame(reply("ok", req="a-9", text="not for you"))[2] == ["ACTION none"]
    assert d.run("ask still waiting")[2] == ["AGENT 0"], "a stray reply must not free the slot"

    tx, _, other = d.frame(reply("ok", text="I have told the family."))
    assert "AREPLY ok 0 |I have told the family.|" in other, other
    tx, _, other = d.run("ask next")
    assert only(tx, "agent request")["req"] == "a-2", "the id moves on"

    # every status the server defines reaches the sketch, retry_after included
    n = 2   # the request now waiting is a-2
    for status, extra, expect in [("not_permitted", {}, "AREPLY not_permitted 0 ||"),
                                  ("rate_limited", {"retry_after": 1800}, "AREPLY rate_limited 1800 ||"),
                                  ("busy", {}, "AREPLY busy 0 ||"),
                                  ("bad_value", {}, "AREPLY bad_value 0 ||"),
                                  ("unavailable", {}, "AREPLY unavailable 0 ||")]:
        _, _, other = d.frame(reply(status, req=f"a-{n}", **extra))
        assert expect in other, (status, other)
        tx, _, other = d.run("ask again")
        n += 1
        assert only(tx, "request")["req"] == f"a-{n}" and other == ["AGENT 1"]

    # refused before anything is sent: empty, blank, over 280 bytes. 280 exactly is fine.
    d.close()
    d = Driver(exe, "lampfan")
    for bad in ("", "   ", "x" * 281, "\u00e9" * 141):
        tx, _, other = d.run("ask " + bad)
        assert tx == [] and other == ["AGENT 0"], (bad[:10], other)
    tx, _, other = d.run("ask " + "\u00e9" * 140)
    assert other == ["AGENT 1"] and len(only(tx, "request")["text"].encode("utf-8")) == 280
    d.close()

    # a server that never answers: give up at 45 s, then the slot is free again
    d = Driver(exe, "lampfan")
    d.run("ms 1000")
    d.run("ask hello")
    d.run("ms 45999")
    assert d.run("tick")[2] == [], "44.999 s is not yet 45"
    d.run("ms 46000")
    assert "AREPLY unavailable 0 ||" in d.run("tick")[2]
    assert d.run("ask again")[2] == ["AGENT 1"]
    d.close()
    print("  agent: request frame, one at a time, stray replies ignored, every status delivered with retry_after,")
    print("         empty/oversize refused before sending, 45 s timeout frees the slot")


# ── part B: the real server, the driver standing in for the board ────────────
def wait_for(read, done, attempts=60, delay=0.05):
    value = read()
    for _ in range(attempts):
        if done(value):
            return value
        time.sleep(delay)
        value = read()
    return value


def test_against_the_real_server(exe):
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    main.REGISTER_RATE.clear_all()
    r = c.post("/api/auth/register", json={"email": "lib@x.test", "password": "owner-pass", "name": "Owner"})
    assert r.status_code == 200, r.text
    tok = {"Authorization": "Bearer " + r.json()["token"]}
    c.post("/api/houses", json={"location": "Library House"}, headers=tok)
    reg = c.post("/api/devices/register", json={"device_id": ID, "name": "Bench", "pin": PIN}, headers=tok)
    assert reg.status_code == 200, reg.text

    d = Driver(exe, "lampfan")
    identify = only(d.run("identify")[0], "identify")

    session = c.websocket_connect("/ws")
    ws = session.__enter__()
    try:
        ws.send_json(identify)
        welcome = ws.receive_json()
        assert welcome["type"] == "welcome" and welcome["proto"] == 2, welcome
        # §7.1: a protocol-2 device is always sent peer_sync after welcome; it is
        # not what these tests are about, so read past it.
        if welcome.get("proto", 1) >= 2:
            assert ws.receive_json()["type"] == "peer_sync"

        caps = c.get(f"/api/devices/{ID}/capabilities", headers=tok).json()
        assert caps["proto"] == 2 and caps["model"] == "host_test" and caps["fw"] == "9.9.9", caps
        keys = [x["key"] for x in caps["capabilities"]]
        assert keys == [x["key"] for x in identify["capabilities"]], keys
        by = {x["key"]: x for x in caps["capabilities"]}
        assert by["horn"]["confirm"] is True and by["reset"]["agent"] == "deny"
        # No relay rows were invented for a device that declared its own shape (§4.1).
        assert c.get("/api/relays", headers=tok).json()["relays"] == []

        def drive(call):
            """Run an API call that waits on the device, and answer it as the board would."""
            result = {}
            t = threading.Thread(target=lambda: result.__setitem__("r", call()))
            t.start()
            try:
                frame = ws.receive_json()
                tx, hw, _ = d.frame(frame)
                for f in tx:
                    ws.send_json(f)
            finally:
                t.join(timeout=15)
            return result["r"], frame, hw

        def post(values, **extra):
            return lambda: c.post(f"/api/devices/{ID}/capability",
                                  json={"values": values, **extra}, headers=tok)

        # a set, end to end: REST -> server -> the library -> hardware -> ack -> database
        resp, frame, hw = drive(post({"lamp": "on", "fan": 40}))
        assert frame["type"] == "set" and frame["values"] == {"lamp": "on", "fan": 40}, frame
        assert resp.json()["status"] == "ok", resp.json()
        assert hw == ["lamp=1", "fan=40"], hw
        state = wait_for(lambda: c.get(f"/api/devices/{ID}/capabilities", headers=tok).json()["state"],
                         lambda s: s.get("fan") == 40)
        assert state["lamp"] == "on" and state["fan"] == 40, state

        # §5.4: the server holds a confirm:true control until it is confirmed ...
        held = c.post(f"/api/devices/{ID}/capability", json={"values": {"horn": None}}, headers=tok)
        assert held.json().get("needs_confirmation"), held.json()
        # ... and then the press reaches the hardware, with no state to report
        resp, frame, hw = drive(post({"horn": None}, confirmed=True))
        assert resp.json()["status"] == "ok" and hw == ["horn"], (resp.json(), hw)

        # the hardware refusing is reported to the caller, not swallowed
        resp, _, hw = drive(post({"picky": "on"}))
        assert resp.json()["status"] == "bad_value" and hw == [], resp.json()

        # the device reports on its own: temp changes, the library flushes, the server stores it
        d.run("setnum temp 23.5")
        for f in d.run("flush")[0]:
            ws.send_json(f)
        state = wait_for(lambda: c.get(f"/api/devices/{ID}/capabilities", headers=tok).json()["state"],
                         lambda s: s.get("temp") == 23.5)
        assert state["temp"] == 23.5, state

        # Device to Maya (8): a person has not yet allowed this device to ask, so the
        # answer is not_permitted and the model is never called ...
        calls = []

        class Said:
            content = "I've told the family."
            tool_calls = None
        main.ai.call_model = lambda messages, tools=None: (calls.append(1), Said())[1]

        def ask(words):
            tx, _, other = d.run("ask " + words)
            assert other == ["AGENT 1"], other
            ws.send_json(only(tx, "agent request"))
            frame = ws.receive_json()
            assert frame["type"] == "agent_reply", frame
            return d.frame(frame)[2]

        assert "AREPLY not_permitted 0 ||" in ask("someone is at the front door")
        assert calls == [], "a device that is not allowed must not cost a model call"

        # ... and once a person switches it on, the reply reaches the sketch's callback.
        assert c.put("/api/devices/esp32-test/agent", json={"allowed": True}, headers=tok).status_code == 200
        assert "AREPLY ok 0 |I've told the family.|" in ask("someone is at the front door")
        assert calls == [1]
    finally:
        for step in (ws.close, lambda: session.__exit__(None, None, None)):
            try:
                step()
            except Exception:
                pass
        d.close()
    print("  server: identify accepted and stored, set -> hardware -> ack -> database, confirm gate,")
    print("          hardware refusal reported, device-initiated state stored")


if __name__ == "__main__":
    exe = build_driver()
    test_identify_is_what_the_server_accepts(exe)
    test_set_frames(exe)
    test_state_reports(exe)
    test_reboot_and_factory_reset(exe)
    test_declarations_that_break_the_rules(exe)
    test_protocol1_commands_still_answered(exe)
    test_asking_maya(exe)
    test_against_the_real_server(exe)
    print("OK: the Maya library speaks PROTOCOL.md as the real server reads it")
