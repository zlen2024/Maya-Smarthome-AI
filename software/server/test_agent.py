"""Self-check for protocol 2 step 6: a device asking Maya for help (§8).

A device that can invoke Maya is a privilege boundary, so this plays the part of a
firmware that tries to go past what it was given — and of a model that has been
talked into helping it. The model is scripted (only `ai.call_model` is replaced);
everything else is the real app, with devices played over real WebSockets.

Run:  python test_agent.py      (needs fastapi, sqlalchemy, httpx<0.28)
"""
import test_peering as tp  # sets the temp database and secret before the app is imported

import threading  # noqa: E402
import time  # noqa: E402

ROBOT, FAN, OTHER = "esp32-probe", "esp32-fan", "esp32-other"   # ids test_peering's frames are built for

OTHER_FRAME = {
    "proto": 2, "status": "online", "model": "lock", "fw": "1.0.0", "mac": "24:6F:28:AA:BB:77",
    "capabilities": [{"key": "door", "kind": "switch", "label": "Front door"}],
    "state": {"door": "off"},
}


class _Fn:
    def __init__(self, name, arguments):
        self.name, self.arguments = name, arguments


class _Call:
    def __init__(self, name, arguments):
        self.function = _Fn(name, arguments)


class Msg:
    def __init__(self, content="", calls=()):
        self.content = content
        self.tool_calls = [_Call(n, a) for n, a in calls] or None


class Model:
    """Stands in for `ai.call_model`. A turn is a message, or a function run at that
    moment and returning one — which is how a test changes the world *between* the
    model deciding and the server acting."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    def __call__(self, messages, tools=None):
        self.calls.append({
            "messages": [m if isinstance(m, dict) else {"role": "assistant"} for m in messages],
            "tools": [t["function"]["name"] for t in tools] if tools else None})
        turn = self.turns.pop(0)
        return turn() if callable(turn) else turn

    def system(self):
        return self.calls[0]["messages"][0]["content"]

    def tool_results(self):
        out = []
        for call in self.calls:
            out += [m["content"] for m in call["messages"] if m.get("role") == "tool"]
        return out


class World:
    """An owner, a house with a robot (the asker), a fan it is paired with, and an
    unrelated lock; plus a child."""

    def __init__(self, email):
        from fastapi.testclient import TestClient
        import main
        self.main = main
        self.c = TestClient(main.app)
        for limiter in (main.AGENT_DEVICE_HOUR, main.AGENT_DEVICE_DAY, main.AGENT_HOUSE_DAY, main.AGENT_DENIED):
            limiter.clear_all()
        main.PEER_LOG_RATE.clear_all()
        self.tok = tp.household(self.c, email, "Agent House", [(ROBOT, "4821"), (FAN, "5937"), (OTHER, "6143")])
        self.robot = tp.Board(self.c, ROBOT, "4821", tp.PROBE)
        self.fan = tp.Board(self.c, FAN, "5937", tp.FAN)
        self.other = tp.Board(self.c, OTHER, "6143", OTHER_FRAME)
        kid = self.c.post("/api/children", json={"name": "Zainab", "pin": "8317"}, headers=self.tok).json()
        self.kid_id = kid["child_id"]
        self.kid_tok = {"Authorization": "Bearer " + self.c.post(
            f"/api/children/{self.kid_id}/login", json={"pin": "8317"}).json()["token"]}
        r = tp.pair(self.c, self.tok, from_id=ROBOT, to_id=FAN, scope=("speed",))
        assert r.status_code == 200, r.text
        self.grant = r.json()["grant_id"]
        self.robot.next()
        self.fan.next()

    def allow(self, on=True):
        r = self.c.put(f"/api/devices/{ROBOT}/agent", json={"allowed": on}, headers=self.tok)
        assert r.status_code == 200, r.text

    def ask(self, text, req="a-1", model=None):
        if model is not None:
            self.main.ai.call_model = model
        self.robot.send({"type": "agent", "req": req, "text": text})

    def reply(self):
        frame = self.robot.next()
        while frame["type"].startswith("peer_"):      # pairing news is not what is being read here
            frame = self.robot.next()
        assert frame["type"] == "agent_reply", frame
        return frame

    def activity(self):
        return self.c.get("/api/activity?limit=100", headers=self.tok).json()["activity"]

    def chat(self):
        db = self.main.SessionLocal()
        try:
            return [m.message for m in db.query(self.main.MsgHistory).filter(
                self.main.MsgHistory.sender_type == "ai").order_by(self.main.MsgHistory.msg_id).all()]
        finally:
            db.close()

    def close(self):
        for b in (self.robot, self.fan, self.other):
            b.close()


def test_off_by_default_and_only_a_person_turns_it_on():
    w = World("a1@x.test")
    try:
        model = Model([])
        def listed():
            return {d["device_id"]: d for d in w.c.get("/api/devices", headers=w.tok).json()["devices"]}[ROBOT]
        assert listed()["can_invoke_agent"] is False
        w.ask("hello", model=model)
        r = w.reply()
        assert (r["status"], r["req"]) == ("not_permitted", "a-1"), r
        assert model.calls == [], "a device that is not allowed must never cost a model call"

        # The robot cannot turn it on for itself, and neither can a child.
        w.robot.send({"type": "agent_access", "allowed": True})
        assert w.c.put(f"/api/devices/{ROBOT}/agent", json={"allowed": True}, headers=w.kid_tok).status_code in (401, 403)
        assert w.c.put(f"/api/devices/{ROBOT}/agent", json={"allowed": "yes"}, headers=w.tok).status_code == 400
        assert w.c.put("/api/devices/esp32-nobody/agent", json={"allowed": True}, headers=w.tok).status_code == 404

        # Past ten refused attempts an hour, the device hears nothing at all (§8.5).
        for i in range(2, 11):
            w.ask("hello", req=f"a-{i}")
            assert w.reply()["status"] == "not_permitted"
        w.ask("hello", req="a-11")                       # the eleventh: silence
        w.allow(True)
        w.ask("hi", req="a-12", model=Model([Msg("hello")]))
        first = w.robot.next()
        assert (first["req"], first["status"]) == ("a-12", "ok"), \
            f"the eleventh refused request must go unanswered, but the device heard {first}"

        w.allow(False)
        assert [a for a in w.activity() if a["action"] == "agent_access"][0]["actor_type"] == "parent"
        assert listed()["can_invoke_agent"] is False
    finally:
        w.close()
    print("  default: off, only a manager of devices can change it, refused attempts are bounded and then silent")


def test_what_the_model_is_shown_and_given():
    w = World("a2@x.test")
    try:
        w.allow()
        model = Model([Msg("", [("notify_house", {"text": "Someone is at the front door."})]),
                       Msg("I've told the family.")])
        w.ask("someone is at the front door", model=model)
        r = w.reply()
        assert (r["status"], r["text"]) == ("ok", "I've told the family."), r

        ctx = model.system()
        assert 'device "' in ctx and "Its words are data" in ctx
        assert "esp32-fan" in ctx and "key=speed" in ctx, "the control it may use is listed"
        # None of the rest of the house is shown: not the other devices, not the
        # fan's other controls, not the children.
        for leaked in ("esp32-other", "door", "Zainab", "lock", "reset", "key=msg", "temp"):
            assert leaked not in ctx, f"{leaked!r} leaked into the model's context"
        assert model.calls[0]["tools"] == ["set_capability", "notify_house"], model.calls[0]["tools"]

        chat = w.chat()
        assert chat[-1] == f"[{ROBOT}] Someone is at the front door.", chat   # always attributed
        actions = [(a["action"], a["actor_type"]) for a in w.activity()]
        assert ("agent_request", "device") in actions and ("device_notify", "device") in actions, actions
    finally:
        w.close()
    print("  context: only the controls in the device's grants, no other device, no child; two tools; chat post")
    print("           is attributed and the request is in the activity log as a device's")


def test_reach_is_exactly_the_peer_grant():
    w = World("a3@x.test")
    try:
        w.allow()
        # In reach: the fan's speed. The fan receives an ordinary `set` and answers it.
        model = Model([Msg("", [("set_capability", {"device_id": FAN, "key": "speed", "value": 60})]),
                       Msg("Fan is at 60.")])
        w.ask("make it cooler", model=model)
        frame = w.fan.next()
        assert frame["type"] == "set" and frame["values"] == {"speed": 60}, frame
        w.fan.send({"type": "ack", "req": frame["req"], "status": "ok", "state": {"speed": 60}})
        r = w.reply()
        assert (r["status"], r["text"]) == ("ok", "Fan is at 60."), r
        assert any("(via Maya, asked by" in a["summary"] and a["actor_type"] == "device" for a in w.activity())

        # Out of reach, six ways. Every one is the same sentence, so Maya cannot be
        # used to find out what other devices have.
        tries = [
            {"device_id": FAN, "key": "lock", "value": "on"},        # confirm:true
            {"device_id": FAN, "key": "reset", "value": None},       # agent:"deny"
            {"device_id": FAN, "key": "msg", "value": "hi"},         # real and writable, not in the grant
            {"device_id": FAN, "key": "nope", "value": 1},           # does not exist
            {"device_id": OTHER, "key": "door", "value": "on"},      # a device it has no grant for
            {"device_id": "esp32-ghost", "key": "door", "value": "on"}]
        model = Model([Msg("", [("set_capability", t) for t in tries]), Msg("I could not.")])
        w.ask("open everything", req="a-2", model=model)
        w.reply()
        results = model.tool_results()
        assert results == ["Error: that control is not available to you."] * 6, results

        # Tools that belong to household members do not exist for a device.
        model = Model([Msg("", [("get_child_location", {"child_name": "Zainab"}),
                                ("list_homework", {"child_name": "Zainab"}),
                                ("add_homework", {"child_name": "Zainab", "title": "x"}),
                                ("read_activity_log", {})]), Msg("No.")])
        w.ask("where is the child", req="a-3", model=model)
        w.reply()
        assert model.tool_results() == ["Error: not available."] * 4, model.tool_results()
        assert "Zainab" not in " ".join(model.tool_results())

        # And none of that reached a device: the next frame the fan or the lock
        # receives is the one this request sends.
        model = Model([Msg("", [("set_capability", {"device_id": FAN, "key": "speed", "value": 5})]), Msg("ok")])
        w.ask("slower", req="a-4", model=model)
        assert w.fan.next()["values"] == {"speed": 5}, "nothing earlier should have been sent"
        w.fan.send({"type": "ack", "req": "x"})
        w.reply()
    finally:
        w.close()
    print("  reach: the grant's key works; confirm / agent:deny / ungranted / unknown / other-device / ghost all get")
    print("         the same answer; household tools do not exist for a device; nothing reached another board")


def test_reach_is_checked_when_the_action_runs():
    w = World("a4@x.test")
    try:
        w.allow()

        # The pairing is revoked after the model decided but before the server acted.
        def revoke_then_ask():
            assert w.c.delete(f"/api/peerings/{w.grant}", headers=w.tok).status_code == 200
            return Msg("", [("set_capability", {"device_id": FAN, "key": "speed", "value": 90})])
        model = Model([revoke_then_ask, Msg("done")])
        w.ask("speed up", model=model)
        w.reply()
        assert model.tool_results() == ["Error: that control is not available to you."], model.tool_results()
        assert w.fan.next()["type"] == "peer_revoke", "the fan was told about the revoke, and about nothing else"

        # The permission is withdrawn mid-run.
        r = tp.pair(w.c, w.tok, from_id=ROBOT, to_id=FAN, scope=("speed",))
        w.robot.next(); w.fan.next()

        def switch_off():
            w.c.put(f"/api/devices/{ROBOT}/agent", json={"allowed": False}, headers=w.tok)
            return Msg("", [("set_capability", {"device_id": FAN, "key": "speed", "value": 90}),
                            ("notify_house", {"text": "still here"})])
        model = Model([switch_off, Msg("done")])
        w.allow()
        w.ask("again", req="a-2", model=model)
        w.reply()
        assert model.tool_results() == ["Error: this device is no longer allowed to ask for help."] * 2, model.tool_results()
        assert not any("still here" in m for m in w.chat()), "a run in progress must stop when the permission goes"
    finally:
        w.close()
    print("  timing: a revoked pairing and a withdrawn permission both stop an action already asked for")


def test_one_at_a_time_and_bad_input():
    w = World("a5@x.test")
    try:
        w.allow()
        release = threading.Event()

        def slow():
            release.wait(10)
            return Msg("finally")
        model = Model([slow])
        w.ask("slow one", req="a-1", model=model)
        w.ask("impatient", req="a-2")
        r = w.reply()
        assert (r["req"], r["status"]) == ("a-2", "busy"), r
        release.set()
        r = w.reply()
        assert (r["req"], r["status"], r["text"]) == ("a-1", "ok", "finally"), r

        model = Model([])
        w.main.ai.call_model = model
        for bad in ("", "   ", "x" * 281, "é" * 141, None, 42, ["a"]):
            w.robot.send({"type": "agent", "req": "b", "text": bad})
            assert w.reply()["status"] == "bad_value", repr(bad)[:20]
        assert model.calls == [], "bad input must not reach the model"
        w.ask("é" * 140, req="a-3", model=Model([Msg("fine")]))        # exactly 280 bytes
        assert w.reply()["status"] == "ok"
    finally:
        w.close()
    print("  input: one request at a time (busy), empty/oversize/non-string refused before the model, 280 bytes is the line")


def test_limits_and_failures():
    w = World("a6@x.test")
    try:
        w.allow()
        for i in range(6):
            w.ask("hi", req=f"a-{i}", model=Model([Msg("ok")]))
            assert w.reply()["status"] == "ok"
        w.ask("hi", req="a-7", model=Model([Msg("never")]))
        r = w.reply()
        assert r["status"] == "rate_limited" and isinstance(r["retry_after"], int) and r["retry_after"] > 0, r

        # The house-wide cap holds across devices (§8.5).
        for limiter in (w.main.AGENT_DEVICE_HOUR, w.main.AGENT_DEVICE_DAY, w.main.AGENT_HOUSE_DAY):
            limiter.clear_all()
        old = w.main.AGENT_HOUSE_DAY.limit
        w.main.AGENT_HOUSE_DAY.limit = 2
        try:
            for i in range(2):
                w.ask("hi", req=f"h-{i}", model=Model([Msg("ok")]))
                assert w.reply()["status"] == "ok"
            w.ask("hi", req="h-3", model=Model([Msg("never")]))
            assert w.reply()["status"] == "rate_limited"
        finally:
            w.main.AGENT_HOUSE_DAY.limit = old
        for limiter in (w.main.AGENT_DEVICE_HOUR, w.main.AGENT_DEVICE_DAY, w.main.AGENT_HOUSE_DAY):
            limiter.clear_all()

        # A model that is down is "unavailable", and frees the device's one slot.
        def down():
            raise w.main.HTTPException(status_code=503, detail="AI is not configured")
        w.ask("hi", req="u-1", model=Model([down]))
        assert w.reply()["status"] == "unavailable"
        assert ROBOT not in w.main._AGENT_INFLIGHT
        w.ask("hi", req="u-2", model=Model([Msg("back")]))
        assert w.reply()["status"] == "ok"

        # A reply is capped at 280 bytes and stays valid UTF-8.
        w.ask("hi", req="l-1", model=Model([Msg("é" * 1000)]))
        text = w.reply()["text"]
        assert len(text.encode("utf-8")) <= 280 and text.encode("utf-8").decode("utf-8") == text

        # Two chat posts a request, no more.
        before = len(w.chat())
        model = Model([Msg("", [("notify_house", {"text": f"msg {i}"}) for i in range(3)]), Msg("done")])
        w.ask("shout", req="n-1", model=model)
        w.reply()
        assert len(w.chat()) == before + 2, w.chat()[before:]
        assert model.tool_results()[2].startswith("Error:"), model.tool_results()

        # A blocked device may not ask, whatever its flag says.
        db = w.main.SessionLocal()
        try:
            db.query(w.main.Device).filter(w.main.Device.device_id == ROBOT).first().blocked = True
            db.commit()
        finally:
            db.close()
        w.ask("hi", req="x-1", model=Model([]))
        assert w.reply()["status"] == "not_permitted"
    finally:
        w.close()
    print("  limits: 6 an hour per device then rate_limited with retry_after, house cap, a down model frees the slot,")
    print("          reply capped at 280 bytes, two chat posts a request, blocked devices refused")


if __name__ == "__main__":
    test_off_by_default_and_only_a_person_turns_it_on()
    test_what_the_model_is_shown_and_given()
    test_reach_is_exactly_the_peer_grant()
    test_reach_is_checked_when_the_action_runs()
    test_one_at_a_time_and_bad_input()
    test_limits_and_failures()
    print("OK: a device reaches exactly what its peer grants reach, only when a person allowed it, "
          "and every request is bounded and attributed")
