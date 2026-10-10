"""Self-check for the abuse limits and the PIN rules.

Two halves. The first drives the limiter primitives directly with an injected
clock, so the window and lockout arithmetic is checked without sleeping. The
second boots the real app against a throwaway SQLite file and replays the attack
chain that these changes exist to stop: register an account, walk the sequential
house ids, guess the 6-digit join PIN, and read a child's GPS coordinates.

Run:  python test_security.py       (needs fastapi, sqlalchemy, httpx<0.28)

Reading the output: the server's own log lines ("failed PIN verification",
"identified and registered") are part of a passing run, as is passlib's
"error reading bcrypt version" warning. The signal is the final OK line and an
exit code of 0; a failure is an AssertionError naming the check.
"""
import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["SECRET_KEY"] = "test-key-not-a-secret"
os.environ["ADMIN_PASSWORD_HASH"] = ""  # exercise the no-default-password path

from fastapi import HTTPException  # noqa: E402

from ratelimit import RateLimit, FailureLock  # noqa: E402
from validators import normalize_child_pin, normalize_device_pin  # noqa: E402


def raises_429(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except HTTPException as e:
        assert e.status_code == 429, e.status_code
        assert "Retry-After" in e.headers, e.headers
        return True
    return False


# ── Limiter arithmetic ────────────────────────────────────────
def test_rate_limit():
    rl = RateLimit(3, 60, "test")
    for i in range(3):
        rl.hit("k", now=100 + i)          # three fit in the window
    assert raises_429(rl.hit, "k", now=103)
    assert not raises_429(rl.hit, "other", now=103)   # keys are independent
    # The window slides rather than resetting on a fixed boundary: at t=161 the
    # hits from t=100 and t=101 have aged out, so exactly two slots are free.
    assert not raises_429(rl.hit, "k", now=161)
    assert not raises_429(rl.hit, "k", now=161)
    assert raises_429(rl.hit, "k", now=161)
    print("  rate limit: window, per-key isolation, sliding expiry")


def test_failure_lock():
    fl = FailureLock(3, 900, 1800, "test")
    fl.guard("k", now=0)                   # nothing recorded yet
    assert fl.fail("k", now=0) is False
    assert fl.fail("k", now=1) is False
    assert fl.fail("k", now=2) is True     # third failure locks
    assert raises_429(fl.guard, "k", now=3)
    assert raises_429(fl.guard, "k", now=1799)
    fl.guard("k", now=1803)                # lockout expired
    fl.guard("k", now=1804)                # and the counter came back clean

    # A success wipes the slate, so a user who mistypes twice then gets it right
    # is never locked out on their next two mistakes.
    fl2 = FailureLock(3, 900, 1800, "test")
    fl2.fail("k", now=0)
    fl2.fail("k", now=1)
    fl2.clear("k")
    assert fl2.fail("k", now=2) is False
    assert fl2.fail("k", now=3) is False
    print("  failure lock: locks on threshold, expires, cleared by success")


def test_failures_age_out():
    # Failures spread wider than the window never accumulate into a lockout.
    fl = FailureLock(3, 100, 600, "test")
    assert fl.fail("k", now=0) is False
    assert fl.fail("k", now=200) is False
    assert fl.fail("k", now=400) is False
    fl.guard("k", now=401)
    print("  failure lock: stale failures age out of the window")


# ── PIN rules ─────────────────────────────────────────────────
def test_pin_rules():
    assert normalize_device_pin(" 1357 ") == "1357"
    assert normalize_child_pin(908172) == "908172"
    for bad in (None, "", "0000", "1111", "1234", "4321", "123", "12345", "abcd"):
        try:
            normalize_device_pin(bad)
        except ValueError:
            continue
        raise AssertionError("device PIN accepted: %r" % (bad,))
    for bad in (None, "", "0000", "1234", "123", "1234567", "99999"):
        try:
            normalize_child_pin(bad)
        except ValueError:
            continue
        raise AssertionError("child PIN accepted: %r" % (bad,))
    print("  PIN rules: 0000 and the common defaults are refused")


# ── The attack chain, against the real app ────────────────────
def test_attack_chain():
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)

    # A household: master account, a house, a child with a location on file.
    r = c.post("/api/auth/register", json={"email": "parent@x.test",
                                           "password": "parent-pass", "name": "Parent"})
    assert r.status_code == 200, r.text
    ptok = {"Authorization": "Bearer " + r.json()["token"]}
    house = c.post("/api/houses", json={"location": "Home"}, headers=ptok).json()
    real_pin = house["join_pin"]
    assert len(real_pin) == 6

    kid = c.post("/api/children", json={"name": "Kid", "pin": "8317"}, headers=ptok)
    assert kid.status_code == 200, kid.text
    ktok = c.post("/api/children/%s/login" % kid.json()["child_id"],
                  json={"pin": "8317"}).json()["token"]
    loc = c.post("/api/children/location", json={"lat": 3.1390, "lng": 101.6869},
                 headers={"Authorization": "Bearer " + ktok})
    assert loc.status_code == 200, loc.text

    # A child PIN may no longer be omitted or left at a default.
    assert c.post("/api/children", json={"name": "NoPin"}, headers=ptok).status_code == 400
    assert c.post("/api/children", json={"name": "Weak", "pin": "0000"},
                  headers=ptok).status_code == 400
    # Nor may a device PIN.
    assert c.post("/api/devices/register", json={"device_id": "esp-1", "name": "Ext"},
                  headers=ptok).status_code == 400
    assert c.post("/api/devices/register",
                  json={"device_id": "esp-1", "name": "Ext", "pin": "0000"},
                  headers=ptok).status_code == 400

    # The attacker: a fresh account, as open registration allows.
    r = c.post("/api/auth/register", json={"email": "attacker@x.test",
                                           "password": "attacker-pass", "name": "A"})
    atok = {"Authorization": "Bearer " + r.json()["token"]}

    # Guessing one house's PIN: five wrong tries, then the sixth is refused
    # before the PIN is even looked at -- so the real PIN would not get in here.
    codes = [c.post("/api/houses/join", json={"house_id": house["house_id"],
                                              "pin": "%06d" % i}, headers=atok).status_code
             for i in range(5)]
    assert codes == [403] * 5, codes
    blocked = c.post("/api/houses/join",
                     json={"house_id": house["house_id"], "pin": real_pin}, headers=atok)
    assert blocked.status_code == 429, blocked.status_code

    # And walking the id space from the same account is capped too: the
    # per-account lock trips after ten failures across all houses.
    codes = [c.post("/api/houses/join", json={"house_id": h, "pin": "000000"},
                    headers=atok).status_code for h in range(50, 60)]
    assert 429 in codes, codes

    # The locks are per account, so a second attacker account is not punished for
    # the first one's failures -- but it also cannot reach the child's location,
    # which is the whole point of the chain.
    r = c.post("/api/auth/register", json={"email": "attacker2@x.test",
                                           "password": "pass-two", "name": "A2"})
    a2 = {"Authorization": "Bearer " + r.json()["token"]}
    assert c.post("/api/houses/join", json={"house_id": house["house_id"],
                                            "pin": "000001"}, headers=a2).status_code == 403
    assert c.get("/api/children", headers=a2).json()["children"] == []

    # The master still sees the child, coordinates included.
    kids = c.get("/api/children", headers=ptok).json()["children"]
    assert kids and kids[0]["last_lat"] is not None

    # Registration itself is rate limited (5/hour/IP; 3 used above).
    codes = [c.post("/api/auth/register", json={"email": "f%d@x.test" % i,
                                                "password": "flood-pass", "name": "F"}
                    ).status_code for i in range(5)]
    assert 429 in codes, codes

    print("  attack chain: join PIN brute force and id walking both blocked,")
    print("                child GPS unreachable, master unaffected")


def test_device_pin_is_enforced_on_the_socket():
    """The WS identify check used to skip verification whenever the stored PIN was
    "0000" -- which was the default everywhere, so it skipped nearly always. Any
    stored PIN is now checked, and the device's own PIN still gets in.

    The server's answer is whether it registers the connection, not a reply
    message: a device that identifies successfully is simply left connected.
    """
    import time
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    main.REGISTER_RATE.clear_all()
    r = c.post("/api/auth/register", json={"email": "owner@x.test",
                                           "password": "owner-pass", "name": "O"})
    tok = {"Authorization": "Bearer " + r.json()["token"]}
    c.post("/api/houses", json={"location": "Socket House"}, headers=tok)
    reg = c.post("/api/devices/register",
                 json={"device_id": "esp-ws", "name": "Ext", "pin": "7391"}, headers=tok)
    assert reg.status_code == 200, reg.text

    def identify(pin):
        """True if the server accepted the identify and kept the connection."""
        # Entered by hand rather than with `with`: the context manager's own exit
        # waits on a closing handshake, which never completes for the socket the
        # server has already dropped. Close both ends explicitly instead.
        session = c.websocket_connect("/ws")
        ws = session.__enter__()
        accepted = False
        try:
            ws.send_json({"id": "esp-ws", "status": "online", "pin": pin,
                          "ip": "10.0.0.5", "ch1": "off", "ch2": "off", "ch3": "off"})
            for _ in range(40):                      # up to 2s
                if "esp-ws" in main.manager.active_connections:
                    accepted = True
                    break
                time.sleep(0.05)
        finally:
            for step in (ws.close, lambda: session.__exit__(None, None, None)):
                try:
                    step()
                except Exception:
                    pass
        return accepted

    assert identify("0000") is False, "wrong PIN was accepted"
    assert identify("") is False, "missing PIN was accepted"
    assert identify("7391") is True, "the device's own PIN was rejected"
    print("  device socket: identify needs the registered PIN, 0000 is no longer a pass")


def test_login_lockout():
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    # TestClient carries no peer address, so every call here lands in one IP
    # bucket -- including the registration limit the previous test deliberately
    # tripped. Clear it; the lock under test is keyed on the email, not the IP.
    main.REGISTER_RATE.clear_all()
    email = "lockme@x.test"
    reg = c.post("/api/auth/register", json={"email": email, "password": "right-pass",
                                             "name": "L"})
    assert reg.status_code == 200, (reg.status_code, reg.text)
    codes = [c.post("/api/auth/login", json={"email": email, "password": "wrong-%d" % i}
                    ).status_code for i in range(8)]
    assert codes == [401] * 8, codes
    r = c.post("/api/auth/login", json={"email": email, "password": "right-pass"})
    assert r.status_code == 429, r.status_code     # locked even with the right password
    main.LOGIN_LOCK.clear(email)
    ok = c.post("/api/auth/login", json={"email": email, "password": "right-pass"})
    assert ok.status_code == 200, (ok.status_code, ok.text)
    print("  login: locks after 8 wrong passwords, right password opens after reset")


def test_admin_has_no_default_password():
    from fastapi.testclient import TestClient
    import main

    c = TestClient(main.app)
    assert c.get("/admin", auth=("admin", "admin")).status_code == 401
    # The generated password is minted on first use and does work.
    main.get_admin_hash()
    pw = main._EPHEMERAL_ADMIN_PASSWORD
    assert pw and pw != "admin"
    assert c.get("/admin", auth=("admin", pw)).status_code == 200
    # Wrong guesses lock the IP out, so the generated password is not brute-able.
    for _ in range(5):
        c.get("/admin", auth=("admin", "nope"))
    assert c.get("/admin", auth=("admin", pw)).status_code == 429
    print("  /admin: no default password, generated one works, guessing locks out")


if __name__ == "__main__":
    test_rate_limit()
    test_failure_lock()
    test_failures_age_out()
    test_pin_rules()
    test_attack_chain()
    test_device_pin_is_enforced_on_the_socket()
    test_login_lockout()
    test_admin_has_no_default_password()
    print("OK: abuse limits hold and the join -> child-location chain is closed")
