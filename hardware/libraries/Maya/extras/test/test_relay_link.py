"""The hub relay, the library's halves (PROTOCOL.md 5.9, 7.5), step 7b.

The hub and the sensor are built on a laptop and driven through host_driver.cpp.

  Part A  each half against a hand-built other end. A sensor's frames are verified with
          Python's hmac, not the library's; a hub is fed frames from a "sensor" this
          script plays, and its relay message is read back.
  Part B  both halves through the real server: a sensor's reading crosses a hub and
          lands as the sensor's own state; a dead hub, a forged frame and a replayed one
          are each handled as the spec says.

What it settles: that a hub holds no key and forwards frames byte for byte, drops what
it can tell is wrong without pretending to authenticate, bounds its queue and each
sender, logs what the server decided; and that a sensor numbers, ages, buffers and
gives up on a hub the way 5.9 describes.

What it cannot show: that ESP-NOW delivers or acknowledges a frame. Here a frame that
"was sent" travels through Python, and "the MAC layer did not acknowledge it" is the
driver's `txok 0`.

Run:  python test_relay_link.py     (needs what test_peer_link.py needs)
"""
import base64
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_peer_link as peer  # noqa: E402  (also puts the server on sys.path and sets its env)
from test_library import Driver, build_driver, only  # noqa: E402
from test_peer_link import KEY, ltx, sign, verify  # noqa: E402

HUB = "esp32-hub"
HUB_MAC = "24:6F:28:AA:CC:01"
HUB_SRC = "246F28AACC01"
SALT = "esp32-salt"
SALT_MAC = "24:6F:28:AA:CC:02"
SALT_SRC = "246F28AACC02"
TANK = "esp32-tank"
TANK_MAC = "24:6F:28:AA:CC:03"
TANK_SRC = "246F28AACC03"
PROBE = "esp32-probe"
PROBE_MAC = "24:6F:28:AA:CC:04"
PROBE_SRC = "246F28AACC04"


def rgrant(grant_id="g-1", role="recv", scope=("salt", "_batt"), key=None, peer_id=SALT, mac=SALT_MAC,
           device=HUB, channel=None, purpose="relay", expires="2099-01-01T00:00:00Z"):
    """A peer_grant as the server pushes it. `key` is None for the hub end of a relay (7.5)."""
    frame = {"id": device, "type": "peer_grant", "grant_id": grant_id, "role": role,
             "peer": {"id": peer_id, "mac": mac}, "scope": list(scope), "expires": expires}
    if purpose is not None:
        frame["purpose"] = purpose
    if key is not None:
        frame["key"] = base64.b64encode(key).decode()
    if channel:
        frame["peer"]["channel"] = channel
    return frame


def report(seq, values, ep=1, frm=SALT, grant="g-1", age=None, kind="report", **extra):
    f = {"v": 2, "from": frm, "grant": grant, "ep": ep, "seq": seq, "kind": kind, "values": values, **extra}
    if age is not None:
        f["age"] = age
    return f


def count(d, what):
    """(queued, dropped) of a hub."""
    m = re.match(r"QUEUED (\d+) dropped=(\d+)", d.run("queued")[2][0])
    return int(m.group(1)), int(m.group(2))


def hubinfo(d):
    m = re.match(r"HUB (\S+) usable=(\d) down=(\d) channel=(\d+) fails=(\d+) announced=(\d)", d.run("hub")[2][0])
    return {"id": m.group(1), "usable": m.group(2) == "1", "down": m.group(3) == "1",
            "channel": int(m.group(4)), "fails": int(m.group(5)), "announced": m.group(6) == "1"}


def peers(d):
    return int(re.match(r"PEERS (\d+)", d.run("peers")[2][0]).group(1))


def relay_message(hub):
    """What the hub sends the server when asked, or None."""
    tx, _, other = hub.run("relay")
    if "RELAYED 1" not in other:
        return None
    return only(tx, "relay message")


def ack(results=None, **kw):
    return {"id": HUB, "type": "relay_ack", **({"results": results} if results is not None else {}), **kw}


def res(status, grant="g-1", seq=1, **kw):
    return {"grant": grant, "seq": seq, "status": status, **kw}


# ── part A: the hub ──────────────────────────────────────────────────────────
def test_grants_and_purposes(exe):
    hub = Driver(exe, "hub", device_id=HUB, mac=HUB_MAC)
    identify = only(hub.run("identify")[0], "identify")
    assert identify["hub"] is True, "a hub says so (7.5); that is all it says"
    salt = Driver(exe, "salt", device_id=SALT, mac=SALT_MAC)
    assert "hub" not in only(salt.run("identify")[0], "identify"), "a device that is not a hub does not claim to be"

    # The hub end of a relay grant has no key, and is held without one.
    hub.frame(rgrant())
    assert peers(hub) == 1
    # A control grant without a key is not a grant. Neither is a relay grant for a sender.
    hub.frame(rgrant(grant_id="g-2", purpose=None))
    assert peers(hub) == 1, "a control grant needs its key"
    salt.frame(rgrant(role="send", device=SALT, peer_id=HUB, mac=HUB_MAC))
    assert peers(salt) == 0, "the sender of a relay needs its key"
    # An unknown purpose is ignored, never read as control (7.1).
    salt.frame(rgrant(role="send", device=SALT, peer_id=HUB, mac=HUB_MAC, key=KEY, purpose="smoke-signal"))
    assert peers(salt) == 0, "a purpose this library does not know must not become a control grant"
    salt.frame(rgrant(role="send", device=SALT, peer_id=HUB, mac=HUB_MAC, key=KEY))
    assert peers(salt) == 1
    # A relay grant is permission to report, not to `set`: the control calls refuse it.
    assert salt.run(f"pnum {HUB} salt 1")[2][0] == "PSEND 0"
    hub.close()
    salt.close()
    print("  grants: the hub end has no key; a keyless control grant, a keyless sender and an unknown purpose are")
    print("          all refused; a relay grant is not usable as a control grant")


def hub_with_senders(exe, senders=("A", "B", "C")):
    """A hub paired to several sensors. Returns (driver, {name: (grant id, mac, src hex)})."""
    hub = Driver(exe, "hub", device_id=HUB, mac=HUB_MAC)
    info = {}
    for i, name in enumerate(senders, 1):
        mac = f"24:6F:28:AA:DD:{i:02X}"
        info[name] = (f"g-{i}", mac, mac.replace(":", ""), f"esp32-s{name.lower()}")
        hub.frame(rgrant(grant_id=f"g-{i}", peer_id=f"esp32-s{name.lower()}", mac=mac))
    return hub, info


def feed(hub, wire, src):
    return hub.run(f"local {src} {wire}")


def test_a_hub_forwards_what_it_cannot_check(exe):
    hub, s = hub_with_senders(exe, ("A",))
    gid, mac, src, sid = s["A"]
    # It cannot check the MAC, so a frame signed with ANY key, or no valid tag at all,
    # is queued. That is the design: the server authenticates, the hub only forwards.
    good = sign(report(1, {"salt": 21.5}, grant=gid, frm=sid), key=bytes(32))
    garbage = json.dumps(report(2, {"salt": 21.4}, grant=gid, frm=sid), separators=(",", ":")) + "." + "A" * 22
    assert feed(hub, good, src)[2] == [] and feed(hub, garbage, src)[2] == []
    assert count(hub, "q")[0] == 2

    msg = relay_message(hub)
    assert msg["type"] == "relay" and msg["id"] == HUB
    assert msg["frames"] == [good, garbage], "frames are forwarded exactly as received (the MAC is over those bytes)"
    assert relay_message(hub) is None, "one message at a time, until the server answers"
    assert count(hub, "q")[0] == 2, "a frame is not forgotten until the server has answered"
    hub.close()
    print("  hub: forwards frames signed with the wrong key or with a garbage tag - it holds no key and cannot tell -")
    print("       byte for byte, one message at a time, keeping them until the server answers")


def test_what_a_hub_can_tell_is_wrong(exe):
    hub, s = hub_with_senders(exe, ("A",))
    gid, mac, src, sid = s["A"]

    def drops(wire, why, src_=src):
        before = count(hub, "q")
        feed(hub, wire, src_)
        assert count(hub, "q") == before, why
        assert peers(hub) == 1

    seq = iter(range(1, 100))
    def ok(**kw):
        base = dict(values={"salt": 1}, grant=gid, frm=sid)
        base.update(kw)
        return sign(report(next(seq), **base))

    drops(ok(), "a frame from a different radio address", src_="246F28AAEE99")
    drops(ok(frm="esp32-other"), "a sender that is not the one paired")
    drops(ok(kind="set"), "a hub accepts reports and nothing else over a relay grant")
    drops(ok(kind="event"), "same")
    drops(ok(kind="ack"), "same")
    drops(sign(dict(report(next(seq), {"salt": 1}, grant=gid, frm=sid), v=1)), "protocol 1")
    drops(sign({k: v for k, v in report(next(seq), {"salt": 1}, grant=gid, frm=sid).items() if k != "values"}), "no values")
    drops(ok(values={}), "empty values")
    drops(ok(values=[1]), "values that are not an object")
    drops(sign(report(0, {"salt": 1}, grant=gid, frm=sid)), "seq 0")
    drops(sign(report(1, {"salt": 1}, ep=0, grant=gid, frm=sid)), "ep 0")
    drops(sign(report(1, {"salt": 1}, grant="g-9", frm=sid)), "a grant it does not hold")
    drops(ok(values={"note": "x" * 300}), "more than a radio frame carries")
    drops("not json at all.AAAAAAAAAAAAAAAAAAAAAA", "garbage")
    drops(ok(values={"note": "tab\there"}).replace("\\t", "\x01"), "a control character: it would not survive as WebSocket text")
    # bytes that are not valid UTF-8 would close the server link for every device the hub carries
    body = json.dumps(report(next(seq), {"note": "XX"}, grant=gid, frm=sid), separators=(",", ":")).encode()
    bad = body.replace(b"XX", b"\xc3\x28") + b"." + b"A" * 22
    before = count(hub, "q")
    hub.run(f"localhex {src} {bad.hex()}")
    assert count(hub, "q") == before, "malformed UTF-8"
    good = body.replace(b"XX", "é".encode()) + b"." + b"A" * 22
    hub.run(f"localhex {src} {good.hex()}")
    assert count(hub, "q")[0] == before[0] + 1, "well-formed UTF-8 (an accent) is fine"
    hub.close()
    print("  hub: drops - silently, without logging - the wrong source address, a different sender, any kind but")
    print("       report, v1, missing/empty/odd values, seq/ep 0, an unknown grant, oversize, garbage, control")
    print("       characters and malformed UTF-8; accepts well-formed UTF-8")


def test_rate_and_queue_bound(exe):
    hub, s = hub_with_senders(exe, ("A", "B", "C"))
    sent = []

    def burst(name, n, start=1, ms=0):
        gid, mac, src, sid = s[name]
        hub.run(f"ms {ms}")
        for i in range(n):
            wire = sign(report(start + i, {"salt": i}, grant=gid, frm=sid))
            feed(hub, wire, src)
            sent.append(wire)

    burst("A", 14)    # the rate is 12 a minute from one sender: two are refused
    assert count(hub, "q") == (12, 0), count(hub, "q")
    sent[:] = sent[:12]
    # a minute later the window has passed
    burst("A", 1, start=100, ms=60000)
    assert count(hub, "q")[0] == 13
    burst("B", 12, ms=60001)
    burst("C", 12, ms=60002)
    # 13 + 12 + 12 = 37 offered; the queue holds 32 and says it dropped the rest
    q, dropped = count(hub, "q")
    assert q == 32 and dropped == 5, (q, dropped)

    # The oldest are kept: what the hub forwards is a contiguous prefix, not a list with a hole.
    first = relay_message(hub)
    assert len(first["frames"]) == 16 and first["frames"] == sent[:16], "16 to a message, in arrival order"
    hub.frame(ack([res("ok", seq=i) for i in range(16)]))
    assert count(hub, "q")[0] == 16
    second = relay_message(hub)
    assert second["frames"] == sent[16:32]
    hub.close()
    print("  hub: 12 frames a minute from one sender, a window that reopens, a queue of 32 that drops the NEWEST and")
    print("       counts it, 16 frames to a message in arrival order")


def test_what_the_server_says_is_what_gets_logged(exe):
    hub, s = hub_with_senders(exe, ("A", "B"))
    for n, name in enumerate(("A", "B")):
        gid, mac, src, sid = s[name]
        for i in range(1, 5):
            feed(hub, sign(report(i, {"salt": i}, grant=gid, frm=sid)), src)
    msg = relay_message(hub)
    assert len(msg["frames"]) == 8

    # Eight answers, in order. bad_mac / bad_frame / unknown_grant are noise (7.3) and are
    # not written down; a refused frame is not sent again either.
    answers = ["ok", "not_permitted", "bad_mac", "replay", "bad_frame", "unknown_grant", "bad_value", "mystery"]
    hub.frame(ack([res(a, seq=i + 1) for i, a in enumerate(answers)]))
    assert count(hub, "q")[0] == 0
    hub.run("ms 11000")
    frame = only(hub.run("plog")[0], "peer_log")
    logged = [e["result"] for e in frame["batch"]]
    assert "bad_mac" not in logged and "bad_frame" not in logged and "unknown_grant" not in logged, logged
    assert set(logged) == {"ok", "not_permitted", "replay", "bad_value", "mystery"}, logged
    assert all(e["dir"] == "in" and e["kind"] == "report" for e in frame["batch"])
    assert {e["peer"] for e in frame["batch"]} == {"esp32-sa", "esp32-sb"}
    # `ep`/`seq` in the log are the frame's own, read off it before the server answered
    assert sorted(e["seq"] for e in frame["batch"] if e["result"] == "ok") == [1]
    hub.close()
    print("  hub: logs an `in` line with the SERVER's result - and nothing for bad_mac/bad_frame/unknown_grant;")
    print("       an unrecognised status is logged as it came, never taken as success")


def test_backing_off_and_resending(exe):
    hub, s = hub_with_senders(exe, ("A",))
    gid, mac, src, sid = s["A"]
    for i in range(1, 4):
        feed(hub, sign(report(i, {"salt": i}, grant=gid, frm=sid)), src)
    hub.run("ms 1000")
    assert relay_message(hub) is not None

    # told to slow down: keep everything, wait as long as asked
    hub.frame(ack(status="rate_limited", retry_after=30))
    assert count(hub, "q")[0] == 3
    hub.run("ms 20000")
    assert relay_message(hub) is None, "still inside the 30 s the server asked for"
    hub.run("ms 31001")
    again = relay_message(hub)
    assert again is not None and len(again["frames"]) == 3, "sent again, nothing lost"

    # an answer that covers only some of them: the rest are sent again
    hub.frame(ack([res("ok", seq=1)]))
    assert count(hub, "q")[0] == 2
    rest = relay_message(hub)
    assert len(rest["frames"]) == 2

    # no answer at all: after 10 s the same frames go again
    hub.run("ms 36000")
    assert relay_message(hub) is None
    hub.run("ms 42000")
    resent = relay_message(hub)
    assert resent is not None and resent["frames"] == rest["frames"]

    # an answer that is not an answer is ignored and does not lose frames
    hub.frame({"id": HUB, "type": "relay_ack"})
    assert count(hub, "q")[0] == 2
    hub.frame({"id": "someone-else", "type": "relay_ack", "results": [res("ok"), res("ok")]})
    assert count(hub, "q")[0] == 2, "an answer for another device is not ours"
    hub.close()
    print("  hub: rate_limited keeps the queue and waits retry_after; a short answer resends the rest; silence for")
    print("       10 s resends; a malformed or foreign answer loses nothing")


def test_hub_status(exe):
    hub = Driver(exe, "hub", device_id=HUB, mac=HUB_MAC)
    tx, _, other = hub.run("hubstatus 6")
    assert only(tx, "hub_status") == {"id": HUB, "type": "hub_status", "channel": 6} and "HUBSTATUS 1" in other
    assert hub.run("hubstatus 6")[2] == ["HUBSTATUS 0"], "unchanged: nothing to say"
    assert only(hub.run("hubstatus 11")[0], "hub_status")["channel"] == 11
    for bad in (0, 15, -1, 255):
        assert hub.run(f"hubstatus {bad}")[2] == ["HUBSTATUS 0"], bad
    hub.run("identify")
    assert hub.run("hubstatus 11")[2] == ["HUBSTATUS 1"], "a new connection says it again"
    salt = Driver(exe, "salt", device_id=SALT, mac=SALT_MAC)
    assert salt.run("hubstatus 6")[2] == ["HUBSTATUS 0"], "a device that is not a hub has no channel to report"
    hub.close()
    salt.close()
    print("  hub: reports its channel once, again when it changes and after a reconnect; refuses nonsense and non-hubs")


# ── part A: the sensor ───────────────────────────────────────────────────────
def sensor(exe, state_dir=None, device_id=SALT, mac=SALT_MAC, channel=6, scope=("salt", "_batt", "note")):
    d = Driver(exe, "salt", state_dir, device_id=device_id, mac=mac)
    d.frame(rgrant(role="send", device=device_id, peer_id=HUB, mac=HUB_MAC, key=KEY, scope=scope, channel=channel))
    d.run("secs 1000")
    return d


def wires(other):
    return [w for _, w in ltx(other)]


def test_sensor_reports(exe):
    d = sensor(exe)
    d.run("setnum salt 21.5")
    tx, _, other = d.run("report")
    assert "REPORT 1 buffered=0 lost=0 fails=0" in other, other
    (dest, wire), = ltx(other)
    assert dest == HUB_SRC, "to the hub's radio address"
    assert verify(wire) == {"v": 2, "from": SALT, "grant": "g-1", "ep": 1, "seq": 1, "kind": "report",
                            "values": {"salt": 21.5}}, wire

    # only what is in the grant, and only what changed; the rest is left for the server
    d.run("setsw led 1")
    d.run("setnum _batt 88")
    tx, _, other = d.run("report")
    assert verify(only(wires(other), "frame")) ["values"] == {"_batt": 88}, other
    assert verify(only(wires(other), "frame"))["seq"] == 2
    tx, _, other = d.run("flush")
    state = only(tx, "state")["state"]
    assert state == {"led": "on"}, "a key outside the relay scope still reaches the server the ordinary way"
    assert "hub_failed" not in only(tx, "state")
    tx, _, other = d.run("report")
    assert ltx(other) == [] and "REPORT 1 buffered=0 lost=0 fails=0" in other, "nothing changed, nothing sent"

    # readings taken together travel together; apart, apart
    d.run("setnum salt 20")
    d.run("setnum _batt 87")
    (_, wire), = ltx(d.run("report")[2])
    assert verify(wire)["values"] == {"salt": 20, "_batt": 87} and verify(wire)["seq"] == 3

    # no hub at all: the caller reports through the server, and what changed is still waiting
    bare = Driver(exe, "salt", device_id=SALT, mac=SALT_MAC)
    bare.run("setnum salt 5")
    tx, _, other = bare.run("report")
    assert "REPORT 0 buffered=0" in other[0] and ltx(other) == []
    assert only(bare.run("flush")[0], "state")["state"] == {"salt": 5}
    d.close()
    bare.close()
    print("  sensor: a signed, numbered report to the hub's address; only keys in the grant; the rest stays for the")
    print("          server; changes made together share a frame; with no hub it sends nothing and loses nothing")


def test_a_dead_hub(exe):
    d = sensor(exe)
    d.run("txok 0")

    def attempt(value, at):
        d.run(f"secs {at}")
        d.run(f"setnum salt {value}")
        return d.run("report")

    # Not acknowledged: kept, not forgotten, and the sequence number is not spent.
    tx, _, other = attempt(10, 1000)
    assert "REPORT 0 buffered=1 lost=0 fails=1" in other, other
    first_seq = verify(only(ltx(other), "frame")[1])["seq"]
    assert first_seq == 1
    tx, _, other = attempt(9, 1060)
    assert "REPORT 0 buffered=2 lost=0 fails=2" in other
    assert verify(ltx(other)[0][1])["seq"] == 1, "a frame that was not acknowledged did not use up its number"
    assert not hubinfo(d)["down"]
    tx, _, other = attempt(8, 1120)
    assert "REPORT 0 buffered=3 lost=0 fails=3" in other
    info = hubinfo(d)
    assert info["down"] and not info["usable"] and info["id"] == HUB and not info["announced"], info

    # Given up on: no more air is spent on it (5.9 rule 2) until the retry interval.
    tx, _, other = attempt(7, 1500)
    assert ltx(other) == [] and "buffered=4" in other[0], other
    tx, _, other = attempt(6, 2800)       # 1120 + 1800 = 2920: not yet
    assert ltx(other) == []

    # Fall back: the latest value goes to the server, and the first report says why (rule 3).
    assert d.run("fallback")[2] == ["FALLBACK 5"]
    d.run("setnum salt 6")
    tx, _, other = d.run("flush")
    frame = only(tx, "state")
    assert frame["hub_failed"] == HUB and frame["state"] == {"salt": 6}, frame
    d.run("setnum salt 5")
    assert "hub_failed" not in only(d.run("flush")[0], "state"), "said once"
    assert hubinfo(d)["announced"]

    # Retry (rule 5): after the interval the hub is tried again, and when it answers the
    # buffer drains oldest first with the AGE each reading had, in unbroken sequence.
    d.run("txok 1")
    d.run("secs 3000")
    assert hubinfo(d)["usable"]
    d.close()

    d = sensor(exe)
    d.run("txok 0")
    for value, at in ((10, 1000), (9, 1060)):
        attempt(value, at)
    d.run("txok 1")
    d.run("secs 1200")
    tx, _, other = d.run("report")
    frames = [verify(w) for w in wires(other)]
    assert [f["values"] for f in frames] == [{"salt": 10}, {"salt": 9}], frames
    assert [f["age"] for f in frames] == [200, 140], "each reading says how old it is"
    assert [f["seq"] for f in frames] == [1, 2], "unbroken: the failed tries spent no numbers"
    assert "REPORT 1 buffered=0 lost=0 fails=0" in other
    info = hubinfo(d)
    assert not info["down"] and not info["announced"], info
    d.close()
    print("  sensor: an unacknowledged frame is kept and spends no sequence number; three failures give up on the hub")
    print("          and stop using the air; fallback hands the latest values to the server with hub_failed, once;")
    print("          when the hub answers the buffer drains oldest first with each reading's age, in unbroken sequence")


def test_buffer_limits(exe):
    d = sensor(exe)
    d.run("txok 0")
    for i in range(20):
        d.run(f"secs {1000 + i}")
        d.run(f"setnum salt {100 + i}")
        d.run("report")
    tx, _, other = d.run("report")
    assert "buffered=16 lost=4" in other[0], other[0]
    d.run("txok 1")
    d.run("secs 2600")
    d.run("restore 0 0 0")                          # the hub is believed alive again for this drain
    frames = [verify(w) for w in wires(d.run("report")[2])]
    assert [f["values"]["salt"] for f in frames] == list(range(104, 120)), "the oldest four were dropped, in order"
    d.close()

    # A reading that cannot fit one radio frame must not block the ones behind it.
    long_id = "esp32-" + "a" * 25
    d = sensor(exe, device_id=long_id)
    d.run("txok 1")
    d.run("settext note " + '"' * 60)
    d.run("setnum salt 1")
    tx, _, other = d.run("report")
    kept = [verify(w) for w in wires(other)]
    assert all(len(w) <= 250 for w in wires(other))
    assert any(f["values"].get("salt") == 1 for f in kept), "the readings that fit still went"
    assert any("lost=1" in o for o in other), other
    d.close()
    print("  sensor: a full buffer drops the oldest and counts it; a reading too big for a frame is dropped and")
    print("          counted, and does not hold back the ones behind it")


def test_hub_channel_and_persistence(exe):
    with tempfile.TemporaryDirectory() as tmp:
        d = sensor(exe, tmp, channel=0)
        assert hubinfo(d)["channel"] == 0
        d.frame({"id": SALT, "type": "hub_channel", "hub": HUB, "channel": 11})
        assert hubinfo(d)["channel"] == 11
        for bad in (0, 15, "x", None):
            d.frame({"id": SALT, "type": "hub_channel", "hub": HUB, "channel": bad})
        d.frame({"id": SALT, "type": "hub_channel", "hub": "esp32-stranger", "channel": 3})
        assert hubinfo(d)["channel"] == 11, "only the hub it reports through can move it"
        d.close()
        d = Driver(exe, "salt", tmp, device_id=SALT, mac=SALT_MAC)    # a reboot: the channel is remembered
        assert hubinfo(d)["channel"] == 11 and hubinfo(d)["id"] == HUB
        d.close()

    # a deep-sleeping sensor carries its hub state across the sleep, announcement included
    d = sensor(exe)
    d.run("restore 3 900 0")
    info = hubinfo(d)
    assert info["down"] and not info["announced"]
    assert only(d.run("flush")[0], "state")["hub_failed"] == HUB, "woke up with the news still unsent"
    d.run("restore 3 900 1")
    assert "hub_failed" not in str(d.run("flush")[0])
    d.close()
    print("  sensor: the hub's channel is learned from the server, only for its own hub, and kept across a reboot;")
    print("          a sleeping sensor's give-up state, announcement included, survives the sleep")


# ── part B: through the real server ──────────────────────────────────────────
def test_end_to_end(exe):
    from fastapi.testclient import TestClient
    import capability_store
    import main
    from test_peering import Board, household, wait_for

    c = TestClient(main.app)
    for limit in (main.RELAY_RATE, main.HUB_STATUS_RATE, main.HUB_FAILED_RATE, main.PEER_LOG_RATE):
        limit.clear_all()
    tok = household(c, "rl@x.test", "Relay Link House", [(HUB, "4821"), (SALT, "4821")])
    hub = Driver(exe, "hub", device_id=HUB, mac=HUB_MAC)
    salt = Driver(exe, "salt", device_id=SALT, mac=SALT_MAC)
    boards = {}

    def to_server(driver, name, frame):
        boards[name].send({k: v for k, v in frame.items() if k != "id"})

    def state(device_id):
        db = main.SessionLocal()
        try:
            return capability_store.load_state(db, device_id)
        finally:
            db.close()

    def carry():
        """The hub sends what it holds; the server answers; the hub hears it."""
        msg = relay_message(hub)
        assert msg is not None, "nothing for the hub to send"
        to_server(hub, "hub", msg)
        answer = boards["hub"].next()
        assert answer["type"] == "relay_ack", answer
        hub.frame(answer)
        return msg, answer

    try:
        for name, d in (("hub", hub), ("salt", salt)):
            identify = only(d.run("identify")[0], "identify")
            boards[name] = Board(c, {"hub": HUB, "salt": SALT}[name], "4821", identify)
            for f in boards[name].boot:
                d.frame(f)
        db = main.SessionLocal()
        try:
            assert db.query(main.Device).filter(main.Device.device_id == HUB).first().is_hub is True, \
                "the server learned from the library's identify that this is a hub"
            assert db.query(main.Device).filter(main.Device.device_id == SALT).first().is_hub is False
        finally:
            db.close()

        # the hub's channel, then the pairing
        to_server(hub, "hub", only(hub.run("hubstatus 6")[0], "hub_status"))
        wait_for(lambda: _hub_channel(main), lambda v: v == 6)
        r = c.post("/api/peerings", json={"from": SALT, "to": HUB, "purpose": "relay",
                                          "scope": ["salt", "_batt"]}, headers=tok)
        assert r.status_code == 200, r.text
        g = r.json()["grant_id"]
        sensor_grant, hub_grant = boards["salt"].next(), boards["hub"].next()
        assert "key" not in hub_grant, "the server never gave the hub the key"
        assert sensor_grant["peer"]["channel"] == 6 and sensor_grant["purpose"] == "relay"
        salt.frame(sensor_grant)
        hub.frame(hub_grant)
        info = hubinfo(salt)
        assert info["id"] == HUB and info["channel"] == 6, info

        # a reading crosses: sensor -> radio -> hub -> server, and is the sensor's own state
        salt.run("setnum salt 21.5")
        salt.run("setnum _batt 88")
        salt.run("ms 1")
        sent = wires(salt.run("report")[2])
        assert len(sent) == 1
        for w in sent:
            hub.run(f"local {SALT_SRC} {w}")
        msg, answer = carry()
        assert msg["frames"] == sent, "the server was handed exactly what the sensor signed"
        assert answer["results"] == [{"grant": g, "seq": 1, "status": "ok"}], answer
        assert state(SALT)["salt"] == 21.5 and state(SALT)["_batt"] == 88
        assert "salt" not in state(HUB), "attributed to the sensor, not the hub"
        assert count(hub, "q")[0] == 0

        # the audit: the sensor says it sent one, the hub says it accepted one
        for d, name in ((salt, "salt"), (hub, "hub")):
            d.run("ms 30000")
            for f in d.run("plog")[0]:
                to_server(d, name, f)

        def audit():
            return c.get(f"/api/peerings/{g}/audit", headers=tok).json()
        a = wait_for(audit, lambda x: len(x["sides"]) == 2)
        sides = {(s["reporter"], s["dir"]): s for s in a["sides"]}
        assert sides[(SALT, "out")]["claimed"] == 1 and sides[(HUB, "in")]["logged"] == 1, sides
        assert a["cross_check"][0]["missing"] == 0, a["cross_check"]
        assert {e["kind"] for e in a["entries"]} == {"report"}

        # a replayed frame: the hub cannot tell, the server does, and the hub writes down what it said
        hub.run(f"local {SALT_SRC} {sent[0]}")
        carry()
        hub.run("ms 60000")
        logged = only(hub.run("plog")[0], "peer_log")["batch"]
        assert [e["result"] for e in logged] == ["replay"], logged
        assert state(SALT)["salt"] == 21.5

        # a forged frame: it is queued, refused by the server, and does not even reach the audit
        fake = sign(report(5, {"salt": 99}, grant=g, frm=SALT), key=bytes(32))
        hub.run(f"local {SALT_SRC} {fake}")
        msg, answer = carry()
        assert [r["status"] for r in answer["results"]] == ["bad_mac"], answer
        assert state(SALT)["salt"] == 21.5, "nothing the hub could not sign for got in"
        assert count(hub, "q")[0] == 0, "not sent again"
        hub.run("ms 120000")
        assert hub.run("plog")[2] == ["PLOG 0"], "a forged frame is not written down (7.3)"

        # the hub dies: the sensor gives up after three, then says why, once
        salt.run("txok 0")
        for i, value in enumerate((20, 19, 18)):
            salt.run(f"secs {2000 + i * 60}")
            salt.run(f"setnum salt {value}")
            assert any("REPORT 0" in o for o in salt.run("report")[2])
        assert hubinfo(salt)["down"]
        assert salt.run("fallback")[2][0].startswith("FALLBACK 3")
        frames = salt.run("flush")[0]
        to_server(salt, "salt", only(frames, "state"))
        notes = wait_for(lambda: _activity(main, SALT, "hub_failed"), lambda v: len(v) >= 1)
        assert len(notes) == 1 and "could not reach" in notes[0] and HUB in notes[0], notes
        assert wait_for(lambda: state(SALT).get("salt"), lambda v: v == 18) == 18, "the latest reading reached the server"

        # the pairing ends: the sensor has nowhere to report
        assert c.delete(f"/api/peerings/{g}", headers=tok).status_code == 200
        salt.frame(boards["salt"].next())
        hub.frame(boards["hub"].next())
        salt.run("setnum salt 1")
        tx, _, other = salt.run("report")
        assert any("REPORT 0" in o for o in other) and ltx(other) == []
    finally:
        for b in boards.values():
            b.close()
        hub.close()
        salt.close()
    print("  end to end: a hub is recognised from identify; a relay pairing gives the hub no key; a reading crosses")
    print("              sensor -> hub -> server as the sensor's own state, byte for byte; both ends' audit lines")
    print("              up; a replay is refused by the server and logged by the hub; a forgery is refused and not")
    print("              logged; a dead hub is reported once; revoking leaves the sensor nowhere to report")


def _hub_channel(main):
    db = main.SessionLocal()
    try:
        return db.query(main.Device).filter(main.Device.device_id == HUB).first().hub_channel
    finally:
        db.close()


def _activity(main, device_id, action):
    db = main.SessionLocal()
    try:
        dev = db.query(main.Device).filter(main.Device.device_id == device_id).first()
        return [a.summary for a in db.query(main.ActivityLog).filter(
            main.ActivityLog.house_id == dev.house_id, main.ActivityLog.action == action).all()]
    finally:
        db.close()


if __name__ == "__main__":
    exe = build_driver()
    test_grants_and_purposes(exe)
    test_a_hub_forwards_what_it_cannot_check(exe)
    test_what_a_hub_can_tell_is_wrong(exe)
    test_rate_and_queue_bound(exe)
    test_what_the_server_says_is_what_gets_logged(exe)
    test_backing_off_and_resending(exe)
    test_hub_status(exe)
    test_sensor_reports(exe)
    test_a_dead_hub(exe)
    test_buffer_limits(exe)
    test_hub_channel_and_persistence(exe)
    test_end_to_end(exe)
    print("OK: a hub forwards what it cannot check, bounded and logged; a sensor numbers, ages, buffers and gives up "
          "on a hub as 5.9 says; the server believes only what it can verify")
