"""The device half of the local link (PROTOCOL.md section 7), step 5b.

The library's peering code is built on a laptop and driven through
host_driver.cpp. In the first half this file is the *other end*: it signs frames
with Python's hmac, plays the server's peer_grant frames, and judges what the
device answers - so the HMAC, the base64url, the replay rules and the scope
checks are checked against an implementation that is not the library's own. In
the second half two library devices talk to each other through the real server.

Run:  python test_peer_link.py

Needs what test_library.py needs. Exit 3 means it could not build the driver,
which is not a pass.

What this cannot show: that ESP-NOW delivers a frame. Frames here travel through
Python, not through a radio.
"""
import base64
import calendar
import hashlib
import hmac
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_library as lib  # noqa: E402  (also puts the server on sys.path and sets its env)
from test_library import Driver, build_driver, only  # noqa: E402

DEV = "esp32-test"
DEV_MAC = "24:6F:28:AA:BB:01"
PEER = "esp32-probe"
PEER_MAC = "24:6F:28:AA:BB:09"
PEER_SRC = "246F28AABB09"
KEY = bytes(range(32))


# ── Python as the other end ──────────────────────────────────────────────────
def mac_of(text, key=KEY):
    digest = hmac.new(key, text.encode(), hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def sign(frame, key=KEY):
    text = frame if isinstance(frame, str) else json.dumps(frame, separators=(",", ":"))
    return text + "." + mac_of(text, key)


def verify(wire, key=KEY):
    """The device's frame, checked the way a peer would, and parsed."""
    text, dot, mac = wire.rpartition(".")
    assert dot and mac == mac_of(text, key), f"device sent a frame that does not verify: {wire}"
    assert len(wire) <= 250, f"frame is {len(wire)} bytes; ESP-NOW carries 250"
    return json.loads(text)


def grant(grant_id="g-1", role="recv", scope=("fan", "msg"), key=KEY, expires="2099-01-01T00:00:00Z",
          peer=PEER, mac=PEER_MAC, device=DEV):
    return {"id": device, "type": "peer_grant", "grant_id": grant_id, "role": role,
            "peer": {"id": peer, "mac": mac}, "key": base64.b64encode(key).decode(),
            "scope": list(scope), "expires": expires}


def setf(seq, values, ep=5, kind="set", grant_id="g-1", frm=PEER):
    return {"v": 2, "from": frm, "grant": grant_id, "ep": ep, "seq": seq, "kind": kind, "values": values}


def ltx(other):
    """The frames the device put on the air: [(destination mac hex, wire text)]."""
    out = []
    for line in other:
        m = re.match(r"LTX ([0-9A-F]{12}) (.*)$", line)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def pending(d):
    m = re.search(r"pending=(\d+)", d.run("peers")[2][0])
    return int(m.group(1))


class Dev:
    """One library device whose peer is played by this script."""

    def __init__(self, exe, state_dir=None, profile="lampfan"):
        self.exe, self.state_dir, self.profile = exe, state_dir, profile
        self.d = Driver(exe, profile, state_dir)

    def reboot(self):
        self.d.close()
        self.d = Driver(self.exe, self.profile, self.state_dir)

    def give(self, **kw):
        self.d.frame(grant(**kw))

    def local(self, wire, src=PEER_SRC):
        return self.d.run(f"local {src} {wire}")

    def info(self):
        line = self.d.run("peers")[2][0]
        m = re.match(r"PEERS (\d+) epoch=(\d+) pending=(\d+)", line)
        return tuple(int(x) for x in m.groups())

    def close(self):
        self.d.close()


def silent(dev, wire, src=PEER_SRC):
    """A frame the device must not act on, answer, or write down."""
    before = pending(dev.d)
    tx, hw, other = dev.local(wire, src)
    assert hw == [] and tx == [] and ltx(other) == [] and [o for o in other if o.startswith("P")] == [], (wire, hw, other)
    assert pending(dev.d) == before, f"a frame that failed the MAC must not be logged: {wire[:60]}"


# ── part A: the device against a hand-built peer ─────────────────────────────
def test_grants_survive_reboot_and_epoch_advances(exe):
    with tempfile.TemporaryDirectory() as tmp:
        dev = Dev(exe, tmp)
        dev.give()
        assert dev.info() == (1, 1, 0)
        for expected_epoch in (2, 3):
            dev.reboot()
            count, epoch, _ = dev.info()
            assert (count, epoch) == (1, expected_epoch), (count, epoch)
        dev.close()
    print("  persistence: the grant survives a reboot and the epoch rises by one each boot (7.2)")


def test_receiving_a_set(exe):
    dev = Dev(exe)
    dev.give()
    tx, hw, other = dev.local(sign(setf(1, {"fan": 60})))
    assert hw == ["fan=60"], hw
    (dest, wire), = ltx(other)
    assert dest == PEER_SRC, "the ack goes to the grant's peer, not wherever the frame claimed"
    ack = verify(wire)
    assert ack == {"v": 2, "from": DEV, "grant": "g-1", "ep": 1, "seq": 1, "kind": "ack", "re": 1,
                   "status": "ok", "state": {"fan": 60}}, ack

    tx, hw, other = dev.local(sign(setf(2, {"msg": "hi", "fan": 10})))
    ack = verify(only(ltx(other), "ack")[1])
    assert hw == ["msg=hi", "fan=10"] and ack["seq"] == 2 and ack["re"] == 2
    assert ack["state"] == {"msg": "hi", "fan": 10}, ack
    dev.close()
    print("  set: applied, acked to the peer's MAC with a verifiable MAC, numbered in the device's own epoch")


def test_forgeries_are_dropped_silently(exe):
    dev = Dev(exe)
    dev.give()
    good = sign(setf(1, {"fan": 60}))
    body, _, mac = good.rpartition(".")
    for label, wire in [
            ("wrong key", sign(setf(1, {"fan": 60}), key=bytes(32))),
            ("tampered body", good.replace("60", "99")),
            ("truncated MAC", good[:-1]),
            ("extended MAC", good + "A"),
            ("no MAC", body),
            ("empty", ""),
            ("unknown grant", sign(setf(1, {"fan": 60}, grant_id="g-9"))),
            ("not JSON", sign("this is not json")),
            ("oversize", sign(setf(1, {"msg": "x" * 300}))),
            ("protocol 1", sign(dict(setf(1, {"fan": 60}), v=1)))]:
        silent(dev, wire)
    # the genuine frame still works afterwards: none of the above moved any state
    assert dev.local(good)[1] == ["fan=60"]
    dev.close()
    print("  forgeries: bad/absent/short/long MAC, tampering, unknown grant, garbage, oversize -> no effect,")
    print("             no answer, nothing logged (so noise cannot fill the audit buffer)")


def test_replay_and_source(exe):
    with tempfile.TemporaryDirectory() as tmp:
        dev = Dev(exe, tmp)
        dev.give()
        assert dev.local(sign(setf(1, {"fan": 1}, ep=5)))[1] == ["fan=1"]
        assert dev.local(sign(setf(2, {"fan": 2}, ep=5)))[1] == ["fan=2"]

        # Replays: same seq, older seq, older epoch. Genuine MACs, so they are
        # *logged* - unlike a forgery - but they do nothing and get no answer.
        for ep, seq in ((5, 2), (5, 1), (4, 99)):
            tx, hw, other = dev.local(sign(setf(seq, {"fan": 77}, ep=ep)))
            assert hw == [] and ltx(other) == [], (ep, seq)
        assert pending(dev.d) == 4   # the two ok sets (aggregated into one entry) + three replays

        # A frame from the wrong radio address, with a valid MAC: a key in the wrong place.
        tx, hw, other = dev.local(sign(setf(3, {"fan": 78}, ep=5)), src="246F28AABBFF")
        assert hw == [] and ltx(other) == []

        # A newer epoch resets the sequence: that is what a rebooted sender looks like.
        assert dev.local(sign(setf(1, {"fan": 3}, ep=6)))[1] == ["fan=3"]

        # What was written down: each refusal, in the audit.
        dev.d.run("ms 0")
        frame = only(dev.d.run("plog")[0], "peer_log")
        results = [e["result"] for e in frame["batch"]]
        assert results.count("replay") == 3 and results.count("bad_source") == 1, results
        assert "set" in [e["kind"] for e in frame["batch"]]

        # Reboot. The epoch is stored, the sequence is not: the next frame of the
        # stored epoch is taken whatever its seq (the spec's stated residual
        # window), and then the ordinary rule applies again.
        dev.reboot()
        assert dev.local(sign(setf(1, {"fan": 4}, ep=6)))[1] == ["fan=4"], "residual window: one frame"
        assert dev.local(sign(setf(1, {"fan": 5}, ep=6)))[1] == [], "...and no more than one"
        assert dev.local(sign(setf(2, {"fan": 6}, ep=5)))[1] == [], "an old epoch is still old"
        assert dev.local(sign(setf(2, {"fan": 7}, ep=6)))[1] == ["fan=7"]
        dev.close()
    print("  replay: same/older seq and older epoch refused and logged; wrong radio source logged; newer epoch")
    print("          accepted; after a reboot exactly one frame of the stored epoch gets through")


def test_scope_and_defence_in_depth(exe):
    dev = Dev(exe)
    seq = iter(range(1, 100))

    def ack_for(values, **kw):
        tx, hw, other = dev.local(sign(setf(next(seq), values, **kw)))
        return verify(only(ltx(other), "ack")[1]), hw

    dev.give(scope=("fan", "msg"))
    ack, hw = ack_for({"lamp": "on"})                      # a real, writable key the grant does not name
    assert (ack["status"], ack.get("failed"), hw) == ("not_permitted", "lamp", []), ack
    ack, _ = ack_for({"nope": 1})                          # and one that does not exist
    assert (ack["status"], ack["failed"]) == ("not_permitted", "nope"), \
        "an unknown key outside scope must look the same as a real one: no probing for capabilities"

    # The server should never put these in a scope. If it does - a bug, or a
    # compromised server - the device still refuses (7.2, defence in depth).
    dev.give(scope=("fan", "horn", "reset", "_batt", "motion", "nope2", "picky"))
    for key, value in (("horn", None), ("reset", None), ("_batt", 5), ("motion", "on")):
        ack, hw = ack_for({key: value})
        assert (ack["status"], ack["failed"], hw) == ("not_permitted", key, []), (key, ack)
    ack, _ = ack_for({"nope2": 1})
    assert (ack["status"], ack["failed"]) == ("unknown_capability", "nope2"), ack
    ack, _ = ack_for({"picky": "on"})
    assert (ack["status"], ack["failed"]) == ("bad_value", "picky"), "the hardware may refuse"

    dev.give(scope=("fan", "msg"))
    ack, hw = ack_for({"fan": 10, "lamp": "on"})           # partial: stops at the first refusal, keeps what applied
    assert (ack["status"], ack["failed"], ack["state"], hw) == ("not_permitted", "lamp", {"fan": 10}, ["fan=10"]), ack
    ack, _ = ack_for({"fan": 999})
    assert (ack["status"], ack["failed"]) == ("bad_value", "fan"), ack
    tx, hw, other = dev.local(sign({"v": 2, "from": PEER, "grant": "g-1", "ep": 5, "seq": next(seq), "kind": "set"}))
    assert verify(only(ltx(other), "ack")[1])["status"] == "bad_value"
    dev.close()
    print("  scope: outside it, unknown looks like real; confirm/agent:deny/reserved/read-only refused even if a")
    print("         scope names them; partial failure keeps what applied and says where it stopped")


def test_kinds_by_role(exe):
    dev = Dev(exe)
    dev.give()
    for seq, kind in ((1, "event"), (2, "msg")):
        tx, hw, other = dev.local(sign({"v": 2, "from": PEER, "grant": "g-1", "ep": 5, "seq": seq,
                                        "kind": kind, "data": {"a": seq}}))
        assert [o for o in other if o.startswith("PMSG")] == [f'PMSG {PEER} {kind} {{"a":{seq}}}'], other
        assert ltx(other) == [], "event and msg are not answered"
    tx, hw, other = dev.local(sign({"v": 2, "from": PEER, "grant": "g-1", "ep": 5, "seq": 3, "kind": "weird"}))
    assert hw == [] and ltx(other) == []
    assert pending(dev.d) == 3
    frame = only(dev.d.run("plog")[0], "peer_log")           # the strange kind is logged, and urgent
    assert [e["result"] for e in frame["batch"]][-1] == "unsupported", frame
    dev.close()
    print("  kinds: a recv device delivers event/msg to the sketch, ignores an unknown kind but logs it")


def test_expiry_needs_a_clock(exe):
    expires = calendar.timegm((2026, 12, 31, 0, 0, 0))
    dev = Dev(exe)
    dev.give(expires="2026-12-31T00:00:00Z")
    dev.d.run(f"clock {expires - 10}")
    assert dev.local(sign(setf(1, {"fan": 1})))[1] == ["fan=1"]
    dev.d.run(f"clock {expires + 1}")
    silent(dev, sign(setf(2, {"fan": 2})))                  # expired: absent
    dev.d.run("clock 0")                                    # no time known: not evaluable, so honoured
    assert dev.local(sign(setf(3, {"fan": 3})))[1] == ["fan=3"], "an unknown clock must not guess"
    dev.close()
    print("  expiry: honoured with a clock, silent after it, and never guessed at without one")


def test_control_frames(exe):
    dev = Dev(exe)
    dev.give()
    assert dev.local(sign(setf(1, {"fan": 1})))[1] == ["fan=1"]

    # The server re-sends every active grant at each identify. That must not
    # reopen the replay window, or each reconnect would be an amnesty.
    dev.give()
    tx, hw, _ = dev.local(sign(setf(1, {"fan": 9})))
    assert hw == [], "re-sending the same grant must keep the replay counters"
    # A different key is a different grant in all but its name: a fresh start.
    other_key = bytes(reversed(range(32)))
    dev.give(key=other_key)
    silent(dev, sign(setf(1, {"fan": 9})))                  # the old key no longer verifies
    assert dev.local(sign(setf(1, {"fan": 9}), key=other_key))[1] == ["fan=9"]

    # peer_sync: keep what is listed, drop what is not.
    dev.give(grant_id="g-2")
    assert dev.info()[0] == 2
    dev.d.frame({"id": DEV, "type": "peer_sync", "grants": ["g-2"]})
    assert dev.info()[0] == 1
    silent(dev, sign(setf(5, {"fan": 1}), key=other_key))   # g-1 is gone
    dev.d.frame({"id": DEV, "type": "peer_revoke", "grant_id": "g-2"})
    assert dev.info()[0] == 0
    dev.d.frame({"id": DEV, "type": "peer_sync", "grants": []})   # an empty list is a valid, complete answer

    # Malformed grants are dropped whole, not half-applied.
    good = grant()
    for label, bad in [("key too short", dict(good, key=base64.b64encode(bytes(31)).decode())),
                       ("key not base64", dict(good, key="not base64!")),
                       ("bad MAC address", dict(good, peer={"id": PEER, "mac": "24:6F:28"})),
                       ("bad role", dict(good, role="both")),
                       ("scope not a list", dict(good, scope="fan")),
                       ("bad grant id", dict(good, grant_id="x-1")),
                       ("no peer id", dict(good, peer={"mac": PEER_MAC})),
                       ("frame for another device", dict(good, id="esp32-someone-else"))]:
        dev.d.frame(bad)
        assert dev.info()[0] == 0, label

    for n in range(1, 10):                                  # the table is bounded
        dev.give(grant_id=f"g-{n}")
    assert dev.info()[0] == 8
    dev.close()
    print("  control: re-sent grant keeps replay state, new key resets it, sync/revoke/malformed/full table")


def test_sending(exe):
    dev = Dev(exe)
    dev.give(role="send", scope=("fan", "msg", "beep"))
    wires = []

    def send(cmd):
        tx, hw, other = dev.d.run(cmd)
        sent = [o for o in other if o.startswith("PSEND")][0].split()[1] == "1"
        got = ltx(other)
        wires.extend(got)
        return sent, got

    ok, got = send(f"pnum {PEER} fan 40")
    assert ok and got[0][0] == PEER_SRC
    frame = verify(got[0][1])
    assert frame == {"v": 2, "from": DEV, "grant": "g-1", "ep": 1, "seq": 1, "kind": "set",
                     "values": {"fan": 40}}, frame

    assert send(f"psw {PEER} lamp 1") == (False, []), "a key outside the scope is not sent"
    assert send("pnum esp32-nobody fan 1") == (False, []), "no grant for that peer"
    assert send(f"ptxt {PEER} msg {'x' * 300}") == (False, []), "a frame that cannot fit 250 bytes is refused, not cut"
    ok, got = send(f"pnum {PEER} fan 41")
    assert verify(got[0][1])["seq"] == 2, "a refused frame must not consume a sequence number"

    ok, got = send(f"ppress {PEER} beep")
    assert verify(got[0][1])["values"] == {"beep": None}, "a press is null (6.2)"
    ok, got = send(f"ptxt {PEER} msg hello")
    assert verify(got[0][1])["values"] == {"msg": "hello"}
    seqs = [verify(w)["seq"] for _, w in wires]
    assert seqs == [1, 2, 3, 4], seqs

    # The receiver's answer comes back as a signed ack.
    def ack(seq, status, failed=None, ep=3):
        f = {"v": 2, "from": PEER, "grant": "g-1", "ep": ep, "seq": seq, "kind": "ack", "re": 2, "status": status}
        if failed:
            f["failed"] = failed
        return sign(f)
    tx, hw, other = dev.local(ack(1, "not_permitted", "fan"))
    assert [o for o in other if o.startswith("PACK")] == [f"PACK {PEER} not_permitted fan"], other
    tx, hw, other = dev.local(ack(1, "ok"))                 # replayed
    assert [o for o in other if o.startswith("PACK")] == []
    tx, hw, other = dev.local(sign(setf(9, {"fan": 7})))   # a `set` sent *to* a sender is not a thing
    assert hw == [] and ltx(other) == []
    dev.close()
    print("  sending: signed, verifiable, numbered; out-of-scope/unknown-peer/oversize refused without using a seq;")
    print("           the peer's ack is delivered once; a set aimed at a sender is ignored")


def test_audit_buffer(exe):
    dev = Dev(exe)
    dev.give(role="send", scope=("fan",))

    # three sends inside a second are one entry standing for three frames (7.3)
    for i in range(3):
        dev.d.run(f"ms {i * 100}")
        dev.d.run(f"pnum {PEER} fan {i}")
    assert dev.d.run("plog")[2] == ["PLOG 0"], "not due: under 10 s and nothing urgent"
    dev.d.run("ms 10000")
    frame = only(dev.d.run("plog")[0], "peer_log")
    assert frame["type"] == "peer_log" and frame["id"] == DEV and frame["boot_id"] == "b-1"
    entry = only(frame["batch"], "aggregated entry")
    assert (entry["grant"], entry["dir"], entry["ep"], entry["seq"], entry["count"], entry["kind"],
            entry["peer"], entry["result"]) == ("g-1", "out", 1, 3, 3, "set", PEER, "ok"), entry
    assert "dropped" not in frame
    assert dev.d.run("plog")[2] == ["PLOG 0"], "an empty buffer sends nothing"

    # a full buffer drops the oldest and says how many (7.3)
    t = 20000
    for i in range(70):
        t += 2000
        dev.d.run(f"ms {t}")
        dev.d.run(f"pnum {PEER} fan {i}")
    assert dev.info()[2] == 64
    frame = only(dev.d.run("plog")[0], "peer_log")
    assert frame["dropped"] == 6, frame.get("dropped")
    assert len(frame["batch"]) == 20, "one frame carries what fits, well under the server's 64"
    seqs = [e["seq"] for e in frame["batch"]]
    assert seqs == sorted(seqs) and seqs[0] == 3 + 6 + 1, seqs   # oldest first, the first six gone
    assert dev.info()[2] == 44

    # something other than ok is not made to wait for the 10 s timer
    dev.close()
    dev = Dev(exe)
    dev.give()
    dev.local(sign(setf(1, {"lamp": "on"})))               # refused: lamp is outside the scope
    frame = only(dev.d.run("plog")[0], "peer_log")
    assert [e["result"] for e in frame["batch"]] == ["not_permitted"] and frame["batch"][0]["dir"] == "in"
    dev.close()
    print("  audit buffer: 3 fast sends -> one entry (count 3), due only every 10 s, oldest dropped and counted,")
    print("                20 per frame, a refusal flushes at once")


# ── part B: two library devices, the real server, no radio ───────────────────
def test_two_devices_through_the_real_server(exe):
    from fastapi.testclient import TestClient
    import main
    from test_peering import Board, household, wait_for  # the server-side helpers

    ids = {"probe": ("esp32-probe", "24:6F:28:AA:BB:11"), "fan": ("esp32-fan", "24:6F:28:AA:BB:22")}
    c = TestClient(main.app)
    main.PEER_LOG_RATE.clear_all()
    tok = household(c, "link@x.test", "Link House", [(ids["probe"][0], "4821"), (ids["fan"][0], "4821")])

    probe = Driver(exe, "lampfan", device_id=ids["probe"][0], mac=ids["probe"][1])
    fan = Driver(exe, "lampfan", device_id=ids["fan"][0], mac=ids["fan"][1])
    boards = {}
    try:
        # Each library device identifies itself, MAC included, exactly as it would.
        for name, d in (("probe", probe), ("fan", fan)):
            identify = only(d.run("identify")[0], "identify")
            assert identify["mac"] == ids[name][1]
            boards[name] = Board(c, ids[name][0], "4821", identify)
            for f in boards[name].boot:
                d.frame(f)                                  # the sync the server sent, handed to the device

        db = main.SessionLocal()
        try:
            stored = db.query(main.Device).filter(main.Device.device_id == "esp32-fan").first().mac
        finally:
            db.close()
        assert stored == ids["fan"][1], "the server stored the MAC the library reported"

        # Pair them, scope: the fan's speed and display only.
        r = c.post("/api/peerings", json={"from": "esp32-probe", "to": "esp32-fan", "scope": ["fan", "msg"]},
                   headers=tok)
        assert r.status_code == 200, r.text
        g = r.json()["grant_id"]
        probe.frame(boards["probe"].next())
        fan.frame(boards["fan"].next())

        def hop(src_driver, dst_driver, src_mac, cmd):
            """Run a command on src, carry every frame it transmits to dst, return dst's output."""
            tx, hw, other = src_driver.run(cmd)
            assert any(o.startswith("PSEND 1") for o in other), (cmd, other)
            out = []
            for _, wire in ltx(other):
                out.append(dst_driver.run("local " + src_mac.replace(":", "") + " " + wire))
            return out

        # probe -> fan: a set, carried across, applied, acked, the ack carried back
        (tx, hw, other), = hop(probe, fan, ids["probe"][1], "pnum esp32-fan fan 60")
        assert hw == ["fan=60"], hw
        (_, ack_wire), = ltx(other)
        back = probe.run("local " + ids["fan"][1].replace(":", "") + " " + ack_wire)
        assert [o for o in back[2] if o.startswith("PACK")] == ["PACK esp32-fan ok -"], back

        # more traffic, and one the fan must refuse
        hop(probe, fan, ids["probe"][1], "pnum esp32-fan fan 70")
        hop(probe, fan, ids["probe"][1], "ptxt esp32-fan msg hi")
        assert probe.run("psw esp32-fan lamp 1")[2][0] == "PSEND 0", "the sender refuses what the scope forbids"

        # Both ends report; the server lines them up (7.3).
        for d, b in ((probe, boards["probe"]), (fan, boards["fan"])):
            d.run("ms 30000")
            for frame in d.run("plog")[0]:
                b.send({k: v for k, v in frame.items() if k != "id"})

        def audit():
            return c.get(f"/api/peerings/{g}/audit", headers=tok).json()
        a = wait_for(audit, lambda x: len(x["sides"]) == 2)
        sides = {(s["reporter"], s["dir"]): s for s in a["sides"]}
        assert sides[("esp32-probe", "out")]["claimed"] == 3, sides
        assert sides[("esp32-fan", "in")]["logged"] == 3, sides
        assert a["cross_check"][0]["missing"] == 0, a["cross_check"]
        assert "key" not in str(a)

        # A frame nobody signed reaches the fan: it vanishes and leaves no trace.
        fan.run("local " + ids["probe"][1].replace(":", "") + " " + sign(setf(99, {"fan": 1}, ep=1, grant_id=g, frm="esp32-probe"),
                                                                       key=bytes(32)))
        assert fan.run("peers")[2][0].endswith("pending=0")

        # Revocation reaches both devices, and the sender stops sending.
        assert c.delete(f"/api/peerings/{g}", headers=tok).status_code == 200
        probe.frame(boards["probe"].next())
        fan.frame(boards["fan"].next())
        assert probe.run("pnum esp32-fan fan 1")[2][0] == "PSEND 0"
        assert re.match(r"PEERS 0 ", fan.run("peers")[2][0])
    finally:
        for b in boards.values():
            b.close()
        probe.close()
        fan.close()
    print("  end to end: two library devices pair through the real server, a set crosses and is acked, both ends'")
    print("              audit lines up (3 sent, 3 received), a forgery leaves no trace, revoke stops the sender")


if __name__ == "__main__":
    exe = build_driver()
    test_grants_survive_reboot_and_epoch_advances(exe)
    test_receiving_a_set(exe)
    test_forgeries_are_dropped_silently(exe)
    test_replay_and_source(exe)
    test_scope_and_defence_in_depth(exe)
    test_kinds_by_role(exe)
    test_expiry_needs_a_clock(exe)
    test_control_frames(exe)
    test_sending(exe)
    test_audit_buffer(exe)
    test_two_devices_through_the_real_server(exe)
    print("OK: the device half of the local link holds against an independent peer and the real server")
