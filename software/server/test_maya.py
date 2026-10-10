"""Self-check for protocol 2 step 3: Maya drives devices through set_capability.

The model is the one thing replaced: `ai.call_model` is swapped for a script that
returns chosen tool calls. Everything after that is the real app — the context
Maya reads, the tool executor with every permission check, the dispatch to a
device over a WebSocket — reached through `/api/maya/voice`, so it runs in the
app's own event loop.

What is checked, and why it is written down: PROTOCOL.md §5.4 says `agent:"deny"`
is enforced "in code rather than in the prompt", and `confirm:true` is gated by
the server rather than by anyone's good behaviour. Both are claims about what the
code does when the model misbehaves, so the script *does* misbehave: it names a
capability it was never shown, and passes `confirmed:true` without anyone asking.

Run:  python test_maya.py      (needs fastapi, sqlalchemy, httpx<0.28, ollama)
"""
import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "maya.db")
os.environ["SECRET_KEY"] = "test-key-not-a-secret"

import threading  # noqa: E402
import time  # noqa: E402

FAN_V2 = {
    "proto": 2, "status": "online", "model": "fan_v1", "fw": "2.0.0",
    "capabilities": [
        {"key": "ch1", "kind": "switch", "label": "Fan"},
        {"key": "speed", "kind": "range", "label": "Fan speed",
         "min": 0, "max": 100, "step": 5, "unit": "%"},
        {"key": "mode", "kind": "enum", "label": "Mode", "options": ["eco", "boost"]},
        {"key": "temp", "kind": "number", "label": "Room temp", "unit": "C", "access": "r"},
        {"key": "lock", "kind": "switch", "label": "Child lock", "confirm": True},
        {"key": "reset", "kind": "button", "label": "Reset", "agent": "deny"},
    ],
    "state": {"ch1": "off", "speed": 20, "mode": "eco", "temp": 24, "lock": "off"},
}

V1 = {"status": "online", "ip": "10.0.0.7", "ch1": "off", "ch2": "off", "ch3": "off"}


class _Fn:
    def __init__(self, name, arguments):
        self.name, self.arguments = name, arguments


class _Call:
    def __init__(self, name, arguments):
        self.function = _Fn(name, arguments)


class _Msg:
    def __init__(self, content="", calls=()):
        self.content = content
        self.tool_calls = [_Call(n, a) for n, a in calls] or None


class ScriptedModel:
    """Stands in for `ai.call_model`. Each call pops the next scripted turn and
    records what Maya was shown, so a test can assert on the context she read and
    on what each tool answered."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.seen = []            # one entry per model call: the messages list

    def __call__(self, messages):
        self.seen.append([m if isinstance(m, dict) else {"role": "assistant"}
                          for m in messages])
        return self.turns.pop(0)

    def system_prompt(self):
        return self.seen[0][0]["content"]

    def tool_results(self):
        out = []
        for call in self.seen:
            out += [m["content"] for m in call if m.get("role") == "tool"]
        return out


def household(c, email, device_id, pin):
    import main
    main.REGISTER_RATE.clear_all()
    r = c.post("/api/auth/register", json={"email": email, "password": "owner-pass",
                                           "name": "Owner"})
    assert r.status_code == 200, r.text
    tok = {"Authorization": "Bearer " + r.json()["token"]}
    c.post("/api/houses", json={"location": "Maya House"}, headers=tok)
    assert c.post("/api/devices/register",
                  json={"device_id": device_id, "name": "Bench unit", "pin": pin},
                  headers=tok).status_code == 200
    return tok


def identify(c, device_id, frame, pin):
    session = c.websocket_connect("/ws")
    ws = session.__enter__()
    ws.send_json({"id": device_id, "pin": pin, **frame})
    welcome = ws.receive_json()
    assert welcome["type"] == "welcome"
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


def say(c, tok, model, words, device_ws=None, answer=None):
    """One voice turn. If `device_ws` is given the device is played from this
    thread while the request runs in another, answering with `answer(frame)`."""
    import main
    main.VOICE_RATE.clear_all()
    main.VOICE_DAY_RATE.clear_all()
    main.ai.call_model = model
    out = {}

    def call():
        out["r"] = c.post("/api/maya/voice", json={"transcript": words}, headers=tok)

    t = threading.Thread(target=call)
    t.start()
    frame = None
    try:
        if device_ws is not None:
            frame = device_ws.receive_json()
            if answer is not None:
                device_ws.send_json(answer(frame))
    finally:
        t.join(timeout=20)
    assert not t.is_alive(), "the voice request never returned"
    assert out["r"].status_code == 200, out["r"].text
    return out["r"].json()["reply"], frame


# ── What Maya is shown ────────────────────────────────────────
def test_context_comes_from_descriptors():
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    tok = household(c, "ctx@x.test", "esp32-fan", "4817")
    ws, session = identify(c, "esp32-fan", FAN_V2, "4817")
    try:
        c.put("/api/devices/esp32-fan/capabilities/ch1", json={"label": "Desk fan"},
              headers=tok)
        model = ScriptedModel([_Msg("ok")])
        say(c, tok, model, "what is on?")
        ctx = model.system_prompt()

        # A fan with a slider is as visible to Maya as a 3-channel extension.
        assert "key=speed" in ctx and "range=0..100" in ctx and "options=eco/boost" in ctx, ctx
        assert 'key=ch1 "Desk fan"' in ctx, ctx             # the house's name, not the firmware's
        assert "key=temp" in ctx and "read-only" in ctx, ctx
        assert "key=lock" in ctx and "needs confirmation" in ctx, ctx
        assert "= 24C" in ctx, ctx                          # current value with its unit

        # §5.4: agent:"deny" never reaches the model.
        assert "key=reset" not in ctx and '"Reset"' not in ctx, ctx
    finally:
        close(ws, session)
    print("  context: built from descriptors, house names win, deny-listed")
    print("           capabilities absent, confirm and read-only flagged")


# ── Setting things ────────────────────────────────────────────
def test_set_capability_v2():
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    tok = household(c, "set@x.test", "esp32-set", "5926")
    ws, session = identify(c, "esp32-set", FAN_V2, "5926")
    try:
        model = ScriptedModel([
            _Msg(calls=[("set_capability", {"device_id": "esp32-set", "key": "speed", "value": 40})]),
            _Msg("Fan speed is 40."),
        ])
        reply, frame = say(
            c, tok, model, "fan speed forty", ws,
            lambda f: {"id": "esp32-set", "type": "ack", "req": f["req"], "status": "ok",
                       "state": {"speed": 40}})
        assert frame["type"] == "set" and frame["values"] == {"speed": 40}, frame
        assert reply == "Fan speed is 40.", reply
        assert 'Fan speed on Bench unit is now 40' in model.tool_results()[0], model.tool_results()
        got = c.get("/api/devices/esp32-set/capabilities", headers=tok).json()
        assert got["state"]["speed"] == 40, got["state"]
        # It is in the activity log, attributed to Maya acting for the sender.
        log = c.get("/api/activity", headers=tok).json()["activity"]
        assert any("via Maya" in a["summary"] and "Fan speed" in a["summary"] for a in log), log

        # An illegal value is refused here and never reaches the device.
        model = ScriptedModel([
            _Msg(calls=[("set_capability", {"device_id": "esp32-set", "key": "speed", "value": 500})]),
            _Msg("That is too fast."),
        ])
        say(c, tok, model, "fan speed five hundred")
        assert "did not change" in model.tool_results()[0] and "above max" in model.tool_results()[0], \
            model.tool_results()

        # A read-only sensor cannot be set.
        model = ScriptedModel([
            _Msg(calls=[("set_capability", {"device_id": "esp32-set", "key": "temp", "value": 10})]),
            _Msg("I can only read that."),
        ])
        say(c, tok, model, "make it ten degrees")
        assert "read-only" in model.tool_results()[0], model.tool_results()
    finally:
        close(ws, session)
    print("  set_capability: v2 device gets a `set` frame, state believed, logged,")
    print("                  out-of-range and read-only refused before the wire")


def test_set_capability_v1_device():
    """A protocol-1 board has never heard of a `set` frame. The server translates
    to the v1 command it always understood; before step 3 this path would have
    sent `type:set` and timed out."""
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    tok = household(c, "v1@x.test", "esp32-v1", "6284")
    ws, session = identify(c, "esp32-v1", V1, "6284")
    try:
        model = ScriptedModel([
            _Msg(calls=[("set_capability", {"device_id": "esp32-v1", "key": "ch2", "value": "on"})]),
            _Msg("Channel 2 is on."),
        ])
        reply, frame = say(
            c, tok, model, "turn on channel two", ws,
            lambda f: {"id": "esp32-v1", "status": "ok", "ch1": "off", "ch2": "on", "ch3": "off"})
        assert frame.get("cmd") == "output_on" and frame.get("channel") == 2, frame
        assert "type" not in frame, "a v1 device must not be sent a v2 frame"
        assert "is now \"on\"" in model.tool_results()[0], model.tool_results()
        assert c.get("/api/devices/esp32-v1/capabilities",
                     headers=tok).json()["state"]["ch2"] == "on"

        # The REST endpoint takes the same route: same bug, same fix.
        result = {}

        def call():
            result["r"] = c.post("/api/devices/esp32-v1/capability",
                                 json={"values": {"ch3": "on"}}, headers=tok)

        t = threading.Thread(target=call)
        t.start()
        try:
            frame = ws.receive_json()
            assert frame.get("cmd") == "output_on" and frame.get("channel") == 3, frame
            ws.send_json({"id": "esp32-v1", "status": "ok", "ch1": "off", "ch2": "on", "ch3": "on"})
        finally:
            t.join(timeout=15)
        assert result["r"].json()["status"] == "ok", result["r"].json()
    finally:
        close(ws, session)
    print("  v1 device: set_capability and POST /capability both translate to the")
    print("             v1 command instead of sending a frame the board ignores")


# ── The gates, against a model that misbehaves ────────────────
def test_agent_deny_is_enforced_in_code():
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    tok = household(c, "deny@x.test", "esp32-deny", "7391")
    ws, session = identify(c, "esp32-deny", FAN_V2, "7391")
    try:
        # The model was never shown `reset`. It names it anyway.
        model = ScriptedModel([
            _Msg(calls=[("set_capability", {"device_id": "esp32-deny", "key": "reset", "value": None})]),
            _Msg("I can't do that."),
        ])
        say(c, tok, model, "press the reset button")      # no device_ws: nothing may be sent
        result = model.tool_results()[0]
        assert result == "Error: Bench unit has no control called reset.", result
        # Indistinguishable from a capability that does not exist.
        model = ScriptedModel([
            _Msg(calls=[("set_capability", {"device_id": "esp32-deny", "key": "nope", "value": None})]),
            _Msg("x"),
        ])
        say(c, tok, model, "press nope")
        assert model.tool_results()[0] == result.replace("reset", "nope"), model.tool_results()
    finally:
        close(ws, session)
    print("  agent:deny: a hidden capability the model names anyway is refused, and")
    print("              the refusal is identical to one that does not exist")


def test_confirm_needs_a_yes_in_a_later_turn():
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    tok = household(c, "conf@x.test", "esp32-conf", "8462")
    ws, session = identify(c, "esp32-conf", FAN_V2, "8462")
    try:
        # Turn 1: Maya asks to set a confirm:true control, then — misbehaving —
        # passes confirmed:true in the same run, as if the user had agreed.
        model = ScriptedModel([
            _Msg(calls=[("set_capability", {"device_id": "esp32-conf", "key": "lock", "value": "on"})]),
            _Msg(calls=[("set_capability", {"device_id": "esp32-conf", "key": "lock",
                                            "value": "on", "confirmed": True})]),
            _Msg("Shall I lock it?"),
        ])
        say(c, tok, model, "lock the fan")                 # nothing may reach the device
        results = model.tool_results()
        assert results[0].startswith("Needs confirmation: nothing was changed"), results
        assert results[1].startswith("Needs confirmation"), \
            "confirmed:true in the same run must not count as a yes: %r" % results

        # Turn 2: the user says yes. The *same value* with confirmed:true is honoured.
        model = ScriptedModel([
            _Msg(calls=[("set_capability", {"device_id": "esp32-conf", "key": "lock",
                                            "value": "on", "confirmed": True})]),
            _Msg("Locked."),
        ])
        reply, frame = say(
            c, tok, model, "yes, lock it", ws,
            lambda f: {"id": "esp32-conf", "type": "ack", "req": f["req"], "status": "ok",
                       "state": {"lock": "on"}})
        assert frame["values"] == {"lock": "on"}, frame
        assert "is now \"on\"" in model.tool_results()[0], model.tool_results()

        # A newer ask replaces an older one, so this runs only after the yes above
        # has been spent. With nothing pending, confirmed:true alone is refused.
        # confirmed:true with no prior ask at all is refused too.
        model = ScriptedModel([
            _Msg(calls=[("set_capability", {"device_id": "esp32-conf", "key": "lock",
                                            "value": "off", "confirmed": True})]),
            _Msg("Shall I?"),
        ])
        say(c, tok, model, "unlock the fan")
        assert model.tool_results()[0].startswith("Needs confirmation"), model.tool_results()

        # A yes is for what was asked: a different value is a new question.
        model = ScriptedModel([
            _Msg(calls=[("set_capability", {"device_id": "esp32-conf", "key": "lock", "value": "on"})]),
            _Msg("Shall I?"),
        ])
        say(c, tok, model, "lock it again")
        model = ScriptedModel([
            _Msg(calls=[("set_capability", {"device_id": "esp32-conf", "key": "lock",
                                            "value": "off", "confirmed": True})]),
            _Msg("Shall I?"),
        ])
        say(c, tok, model, "yes, unlock it")
        assert model.tool_results()[0].startswith("Needs confirmation"), model.tool_results()
    finally:
        close(ws, session)
    print("  confirm: asked once, a yes counts only in a later turn and only for the")
    print("           value asked about; confirmed:true alone is never enough")


def test_child_held_to_grants():
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    tok = household(c, "kid@x.test", "esp32-kid", "9173")
    kid = c.post("/api/children", json={"name": "Kid", "pin": "8317"}, headers=tok).json()
    ktok = {"Authorization": "Bearer " + c.post(
        f"/api/children/{kid['child_id']}/login", json={"pin": "8317"}).json()["token"]}
    ws, session = identify(c, "esp32-kid", FAN_V2, "9173")
    try:
        # The child sees every control, flagged where it is not theirs to change.
        model = ScriptedModel([_Msg("ok")])
        say(c, ktok, model, "what can I do?")
        assert "not allowed for you" in model.system_prompt(), model.system_prompt()

        model = ScriptedModel([
            _Msg(calls=[("set_capability", {"device_id": "esp32-kid", "key": "ch1", "value": "on"})]),
            _Msg("I am not allowed."),
        ])
        say(c, ktok, model, "turn the fan on")             # no grant: nothing may be sent
        assert model.tool_results()[0].startswith("Denied:"), model.tool_results()

        c.put(f"/api/children/{kid['child_id']}/grants", headers=tok, json={"grants": [
            {"device_id": "esp32-kid", "key": "ch1", "is_allowed": True}]})
        model = ScriptedModel([
            _Msg(calls=[("set_capability", {"device_id": "esp32-kid", "key": "ch1", "value": "on"})]),
            _Msg("Done."),
        ])
        reply, frame = say(
            c, ktok, model, "turn the fan on", ws,
            lambda f: {"id": "esp32-kid", "type": "ack", "req": f["req"], "status": "ok",
                       "state": {"ch1": "on"}})
        assert frame["values"] == {"ch1": "on"}, frame

        # Granting the fan does not grant its speed.
        model = ScriptedModel([
            _Msg(calls=[("set_capability", {"device_id": "esp32-kid", "key": "speed", "value": 90})]),
            _Msg("No."),
        ])
        say(c, ktok, model, "fan to ninety")
        assert model.tool_results()[0].startswith("Denied:"), model.tool_results()
    finally:
        close(ws, session)
    print("  child: sees every control, may change only what was granted, and")
    print("         Maya cannot be talked into more than the child's own rights")


def test_old_tool_is_gone():
    import ai
    assert "control_device" not in ai.TOOL_NAMES and "set_capability" in ai.TOOL_NAMES
    print("  tools: control_device replaced by set_capability")


if __name__ == "__main__":
    test_old_tool_is_gone()
    test_context_comes_from_descriptors()
    test_set_capability_v2()
    test_set_capability_v1_device()
    test_agent_deny_is_enforced_in_code()
    test_confirm_needs_a_yes_in_a_later_turn()
    test_child_held_to_grants()
    print("OK: Maya drives any device through set_capability, and the deny and "
          "confirm gates hold against a model that misbehaves")
