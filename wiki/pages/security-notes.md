# Security notes

Security-relevant facts surfaced while indexing the codebase, kept here rather
than buried in module pages. Each was read from source and is cited by
`path:line`. This is a record of *what the code does*, not a pentest.

This is a final-year-project demo deployed to Fly.io (`fly.toml`). The pattern
that ran through the original findings was a single one: **the insecure value was
what you got when an env var was simply absent**, or when a field was left at its
default. The 2026-10-10 pass removed every instance of that pattern — findings 1,
2 and 6 below are fixed, and 4's operational half is closed. The dates matter
here: items marked **FIXED** describe code that no longer exists, kept because
the reasoning is the part worth preserving.

## 1. JWT signing key fell back to a hardcoded literal — FIXED 2026-10-10

```python
# software/server/auth.py — before
SECRET_KEY = os.environ.get("SECRET_KEY", "maya-smarthome-secret-key-change-in-production")
```

Signs every access token (`create_access_token`, `auth.py:38`) and is the
verification key for the HTTP API **and** the mobile WebSocket handshake. With
`SECRET_KEY` unset, anyone who had read this repo could mint a valid token for
any account, including `sub` values of the form `child_<id>`. Tokens last 24h
(`ACCESS_TOKEN_EXPIRE_MINUTES = 1440`).

The live deployment was never exposed — `SECRET_KEY` is set as a Fly secret, so
the fallback was unreachable there. It was fixed anyway because the repo is
public: a fork that deployed without the secret would have signed tokens with a
key published on GitHub, and nothing would have looked wrong.

Now (`auth.py:18-22`): no literal. Absent in development yields
`secrets.token_urlsafe(32)` per process plus a printed warning — tokens then die
on restart, which is visible, instead of being forgeable, which is not.

## 2. `/admin` fell back to password `admin` — FIXED 2026-10-10

```python
# software/server/main.py — before
DEFAULT_ADMIN_PASSWORD_HASH = hash_password("admin")
```

HTTP Basic with username `admin`, on a public URL, with a password readable in
the source — whenever `ADMIN_PASSWORD_HASH` was unset.

Now (`get_admin_hash`, `main.py:273`): there is no fixed fallback. Without the
env var a random password is minted once per process and printed to the log, so a
local run stays usable and no deployment carries a guessable one. `admin_page`
also compares the username with `secrets.compare_digest` and is behind
`ADMIN_LOCK` (`main.py:308`), five wrong attempts per IP then a 30-minute
lockout, so the generated password cannot be ground down either.

Note the separation, unchanged: the `/admin` **page** is Basic-auth'd, while the
`/api/admin/*` JSON endpoints and `/db` are gated by
`current_user.role != AccountRole.admin` on a JWT. They are independent gates —
hardening one does not harden the other.

## 3. House join PINs and device PINs are stored in plaintext

Still true, and accepted for now:

- `join_pin` is a 6-digit random string (`_generate_pin`) stored as a plain
  column. It is returned in API responses — guarded by `is_master` in the members
  listing. Comparison is now `secrets.compare_digest` (`main.py:507`) rather than
  `!=`: a plain comparison returns faster the earlier it finds a mismatching
  digit, which turns 10**6 guesses into roughly 6 × 10.
- `devices.pin` is plaintext too, because the firmware stores its own copy in
  ESP32 Preferences and sends it on identify; the server compares the two.

What changed is that neither can be a *known* value any more — see finding 6.
Hashing them would be the next step; it buys little while the device must present
the cleartext PIN on every connect, and it would break the one place a PIN is
legitimately displayed (the master's own join PIN).

Account passwords, by contrast, *are* properly hashed — bcrypt via passlib
(`auth.py:20`), and child PINs go through `hash_password` as well.

## 4. Open API keys: SHA-256, unsalted — rate limiting added 2026-10-10

```python
# software/server/auth.py
def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()
```

`get_api_key_house` resolves an `X-API-Key` header to a house and gates the three
`/api/open/v1/*` endpoints. A single unsalted SHA-256 is **acceptable here**:
keys are minted as `"maya_" + secrets.token_urlsafe(32)` — 256 bits of CSPRNG
entropy, so there is nothing for a salt to defend against (no rainbow table, no
brute force). Only the hash is stored and the plaintext is returned exactly once,
which is the right shape. Revocation is a `revoked` flag checked in the same
query.

The remaining weakness was operational: no rate limiting, and no per-key scope
narrower than the whole house. **Both are now closed.** Rate limiting came first (60
requests a minute per key). Scoping came 2026-10-11 (§12.1): a key may be limited to some
devices, some capability keys, and read-only; see
[§12 below](#12-what-an-open-api-key-can-reach--scoped-2026-10-11).

## 5. Maya's tool permissions are enforced server-side — correctly

Worth recording as a **positive** finding, since it is the design decision most
likely to be undone by accident. `ai.py`'s docstring states it plainly, and the
system prompt tells the model "Permission and privacy are enforced by the tools,
not by you". The enforcement really does live in `_execute_maya_tool` —
device-blocked checks, `_child_command_denial` for child senders, and parent-only
guards — **not** in the prompt.

Keep it that way: the model's tool schemas are described in the code as guidance
for the model only. Since tools are string-dispatched with no graph edge (see
[known-gaps §4](known-gaps.md#4-mayas-ai-tools-are-string-dispatched--no-edges-at-all)),
a permission check dropped from one branch would not show up in any query.

## 6. A guessable chain reached a child's GPS coordinates — FIXED 2026-10-10

The most serious finding of the 2026-09-08 review, and the reason the whole pass
happened. It needed no physical proximity, no RF equipment and no stolen
credential — only plain HTTP:

```
1. Register an account        -> registration is open
2. Pick a house_id            -> sequential Integer PK (models.py:34), not random
3. Brute force its join_pin   -> 6 digits, compared with !=, no rate limit at all
4. POST /api/houses/join      -> now an ordinary member of that house
5. GET  /api/children         -> last_lat, last_lng, last_seen_at for every child
```

A search for `ratelimit|limiter|attempts|lockout|throttle` across the server
returned nothing, so step 3 was 1,000,000 combinations with no lockout and no
delay: a few hours at 50 requests/second, and the sequential ids meant an
attacker did not have to know which house to aim at. Contrast with login, which
bcrypt slowed down by accident rather than by design.

**Fixed** by making the guess expensive rather than by hiding the data, since the
data is what a parent legitimately opens the app to see:

- `JOIN_LOCK` — 5 failures per (account, house) then a 1-hour lockout. A 6-digit
  PIN at 5 tries/hour is ~23 years of uninterrupted guessing.
- `JOIN_WALK_LOCK` — 10 failures per account across *all* houses, so walking the
  id space dies as fast as hammering one house (`main.py:501`).
- `REGISTER_RATE` — 5 accounts/hour/IP, because a fresh account is what resets a
  per-account budget.
- Constant-time PIN comparison (`main.py:507`).
- Every failed join is written to the target house's activity log via
  `log_activity`, so a quiet attack becomes visible to the people who live there.

`test_security.py::test_attack_chain` replays the five steps above against the
real app and asserts the attacker is stopped at step 3 — including that the real
PIN is refused once the lockout is in force, and that a second account cannot see
the child.

**Accepted, not fixed:** `list_children` (`main.py:910`) returns coordinates to
any member of the house, not only the master. A co-parent or grandparent who was
deliberately given the join PIN is a legitimate viewer, and there is no
finer-grained role than `is_master` / `can_manage_devices` to express "member who
may not see locations". Narrowing it is a product decision with UI work attached;
recorded here so it is a choice rather than an oversight.

## 7. Default PINs made the device PIN check decorative — FIXED 2026-10-10

`"0000"` was the default at every layer at once, which is what made it harmful:

| Layer | Before |
|---|---|
| Migration | `ALTER TABLE devices ADD COLUMN pin TEXT DEFAULT '0000'` |
| `register_device` | `pin = str(payload.get("pin", "0000")).strip() or "0000"` |
| `create_child` | `pin = payload.get("pin", "0000")` |
| App | PIN field pre-filled with `0000`, helper text "Default PIN is 0000" |
| Firmware | `prefs.getString("pin", "0000")` |
| WS identify | `if stored_pin and stored_pin != "0000":` — **skipped the check** |

The last row is the point: the server verified a device's PIN only when it was
*not* the value that everything else defaulted to. In practice the check never
ran, and a device could be impersonated on the socket, or re-provisioned over
BLE by anyone in range.

Now:

- `validators.py` holds one rule each for device and child PINs — 4 digits (4-6
  for a child), no repeated-digit PINs, no `1234`/`4321` — raising `ValueError`
  that both endpoints turn into a 400 (`main.py:896`, `main.py:1193`). There is
  no default to fall back to.
- WS identify checks any stored PIN with `compare_digest` (`main.py:2225`).
- Firmware: `isAcceptablePin` (now in `hardware/libraries/Maya/src/Maya.cpp`, moved
  unchanged from `smartextension.ino` on 2026-10-10) refuses to *store* a PIN that
  cannot protect the board, answering BLE status `9`; an empty PIN means "unclaimed"
  and is the only state that provisions without one. The old `!= "0000"` exemption is gone.
- App: no pre-filled PIN, and the same rule checked before anything is written
  over BLE.

The three rules are deliberately duplicated in three languages; each file points
at the other two, because a device whose firmware and server disagree about what
a valid PIN is would simply fail to connect.

On startup the server now names any device still holding the old default PIN
(`warn_about_legacy_device_pins`, `software/server/main.py:117`). Those rows are
compared like any other, but against a value published in this repo, so identify
proves nothing for them until the owner re-provisions the board. Nothing is
rewritten automatically: changing a PIN the firmware still holds would lock a
working device out.

**Reflash required** for the firmware half. The existing boards keep working
without it: they send the PIN they were provisioned with, and the server now
compares it instead of skipping. Until they are reflashed, a board still in BLE
range can be re-provisioned by anyone who knows its current PIN is `0000`.

## Abuse limits, in one place

`software/server/ratelimit.py` — two primitives, both in-process:

| Guard | Scope | Limit |
|---|---|---|
| `JOIN_LOCK` | account + house | 5 failures/h → 1h lockout |
| `JOIN_WALK_LOCK` | account | 10 failures/h → 1h lockout |
| `LOGIN_LOCK` | email | 8 failures/15m → 15m lockout |
| `CHILD_PIN_LOCK` | child | 5 failures/15m → 15m lockout |
| `ADMIN_LOCK` | IP | 5 failures/15m → 30m lockout |
| `LOGIN_RATE` | IP | 30 requests/5m |
| `REGISTER_RATE` | IP | 5 requests/h |
| `VOICE_RATE` / `VOICE_DAY_RATE` | caller | 20/min, 300/day |
| `OPEN_API_RATE` | API key | 60/min |

Successes clear a `FailureLock`, so a household that mistypes is never punished.
`VOICE_*` is a budget guard as much as an abuse one: every call to
`/api/maya/voice` is a paid Ollama request, so an unbounded client loop could
drain the account.

**The honest limitation:** this state lives in one process' RAM. That fits the
deployment — a single uvicorn process against one SQLite file — but behind
several instances each would hold its own counters, so the effective limit is
multiplied by the instance count. Counters also reset on restart. This is why the
lockouts that matter also write to the activity log, which survives both.

## 8. Any house could re-claim a device id another house owned — FIXED 2026-10-10

Found while testing step 5a. `POST /api/devices/register` set `existing.house_id` to
the caller's house without asking whether the device already belonged to someone else,
so anyone who could add devices could take a device record from its owner by naming its
id (`esp32-` plus the low 32 bits of the MAC). The device itself stayed safe — the PIN
the claimer set would not match the firmware's, so the board was refused at identify —
but the owner silently lost the record and every pairing it carried.

**The fix** (PROTOCOL.md §4.1): an id another house has claimed is answered `409` until
that house removes the device. Re-claiming within the same house is unchanged (ordinary
re-provisioning, pairings kept). Two exceptions, neither a way round the owner: a global
admin, whose job includes repairing exactly this, and a record whose house no longer
exists, which nobody is left to object for. A device that does change house takes none
of its peering grants with it.

**The 409 is itself counted** (5 an hour per account, then `429`), so the refusal
cannot be used to walk the id space asking which ids are taken. It does confirm that an
id is registered, which is a weaker disclosure than the one it replaced.

**Tested** (`test_peering.py`, `test_a_claimed_device_cannot_be_taken`): the second
house is refused and the owner's name, PIN and pairings are untouched; the owner may
re-claim; removal frees the id; an admin and an orphan record may move; and with the
guard deliberately removed the test fails, which is the original hijack.

**What this costs:** a second-hand device must be removed from the previous owner's
house before it can be claimed. If that owner cannot be reached, an admin can move it.
There is no "I have the device in my hand" override — a physical reset clears the
board, not the server's record, and a rule that trusted possession would be the hole
again. The app's add-device screen now receives a `409` with an explanation; its
wording has not been reviewed (no Flutter SDK).

## 9. Peering keys are stored in clear — by necessity

`peer_grants.key` holds the 32-byte HMAC key unhashed, because the server must
re-send it whenever a device reconnects. It is never returned by any API (checked
in `test_peering.py`: the grant list and the audit contain no key), only pushed
down the device's own PIN-authenticated WebSocket. A database leak therefore
exposes the keys, which is the same exposure device PINs already have (§3). The
mitigations are the ones §7.4 builds in: grants expire (30 days by default, 365 at
most), re-pairing rotates the key, and revocation is immediate for a connected
device and corrected by `peer_sync` for one that was offline.

## 10. A device that can ask Maya is a new way to reach the house

Added with step 6. A device invoking Maya could, if nothing stopped it, ask her to act
on other devices, read the house, or talk to the family. What stops it, all in code:

- **Permission is off by default and only a person turns it on** — a device cannot set
  it, nor can a child or an API key.
- **Reach is the device's own outgoing peer grants**, recomputed when each action runs.
  A control marked `confirm:true` or `agent:"deny"` can never be in a peer scope, so a
  device can never cause one to be set through Maya.
- **Two tools only.** The household tools (a child's location, homework, screen time, the
  activity log) do not exist for a device, and the executor refuses them by name.
- **The model sees only what the device can reach.** Not the other devices, not the children.
- **The device's text is untrusted.** The prompt says so, but nothing depends on it.
- **Bounded**: 6/hour and 30/day per device, 100/day per house, one outstanding request,
  refused attempts limited too, so a device cannot spend the model budget.

**Residual risks, stated:** `notify_house` puts words a device chose — through the model
— into the family chat, where a child can read them. It is capped (two per request, 280
bytes) and always labelled with the device's name, but it is the one place untrusted text
reaches a person. A hostile *firmware* can also spend its allowance every hour. And the
quality of the model's behaviour under hostile text has not been tested with the real model.

## 11. A hub carries other devices' words (step 7a, 2026-10-11)

A hub forwards readings for sensors that cannot reach the server, so what it forwards
becomes house state. It sits in a cupboard, listens to anyone in radio range, and is
the least trustworthy device in the system. What the design does about that, in code:

- **The hub is never given the key.** A first draft shared the grant key with the hub
  (every §7.1 grant has one key for both ends) and had the server re-check the MAC "with
  the same key". That proved nothing about the hub: holding the key, it could sign any
  reading. `grant_frame` now omits `key` from a relay grant's hub end, and the test
  asserts it. This was found in review, before the library existed.
- **The server authenticates every relayed frame itself** (`ingest_relay`): the grant
  must be a relay grant naming *this* hub, in this house, unexpired, with the hub still
  declaring itself one; the MAC must verify; `from`, `kind`, `v` must match; `(ep, seq)`
  must be strictly newer than what the server stored, which survives restarts, so a
  captured frame cannot be replayed through any hub, ever.
- **Scope is the person's.** Only keys in the grant, and still reportable now, are
  stored; the rest are named and dropped. A relay grant is **not** reach under §8: a
  sensor that may ask Maya gains nothing over the hub's same-named keys.
- **A late reading never overwrites a fresher one**, and a reading may claim to be at
  most 7 days old.
- **Bounded.** 30 `relay` messages a minute per hub, 16 frames each; `hub_status` 6 a
  minute; one `hub_failed` notice per sensor and hub per 6 hours.
- **One answer for every reason a grant is unusable** (`unknown_grant`), so a hub cannot
  probe which grants exist elsewhere.

**The library follows the same rule (step 7b).** A hub's relay-grant path has no key to check
a MAC with and does not pretend to: it drops what it can see is wrong (the wrong radio address, a
different sender, any kind but `report`, malformed or non-UTF-8 text — which would otherwise close
the server link for every sensor it carries), bounds each sender to 12 frames a minute and its own
queue to 32 (dropping the newest), and forwards the rest exactly as received. That a hub is
never sent the key is tested on the server (`test_relay.py`). The library also stores no key for
the hub end of a relay grant even if one arrives, but that is not observable from outside and is
not tested. A hub's audit lines are written only for what the server decided.

**Residual risks, stated:** a hub can **withhold, delay or drop** a sensor's readings —
visible in the audit (the sensor's `out` count against what the server accepted), but a
sensor that sleeps through the outage loses those readings unless it buffered them. It can
forward out of order, which loses the older reading. Anyone who can spoof a paired sensor's
radio address makes the hub forward junk to the server, which refuses it; the hub's
per-sender rate limit and queue bound (spec, library not yet built) and the server's rate
limit bound the cost. And `hub_failed` is the sensor's word: believed only for a real
pairing, but a sensor that lies can make a family check a hub that is fine, once per six
hours.

## 12. What an Open API key can reach — scoped 2026-10-11

This closes the second half of §4. Until now a key granted read and command over **every
device in its house**, and the frozen v1 surface could switch a channel the firmware had marked
`confirm:true` — the one control a person is meant to approve. What is true now, in code
(`open_api.py`, `main.py`):

- **A key can be scoped** to a list of devices, a list of capability keys and read-only or
  read-write. **`write` defaults to false**, an unknown field in the scope is refused (a typo
  must not widen a key), and a list that is present may not be empty.
- **Fail closed.** A stored scope that cannot be read back reaches **nothing**; only a key with
  no scope at all — one issued before this existed — means the whole house. The migration adds
  a nullable column, so nothing already issued changed meaning.
- **Not found, not forbidden.** A device outside the scope is a `404`, indistinguishable from
  one that does not exist or belongs to another house, so a scoped key cannot learn what else
  is in the house. An out-of-scope capability and an undeclared one are refused identically for
  the same reason.
- **A set is judged whole before anything is sent.** One refused key and none of it applies.
- **`confirm:true` is refused to every key**, v1 included, and a `confirmed` field in the body is
  not read: it is evidence a person said yes, and a key is not one.
- **Scope is applied against the descriptor as it is now**, per request, not recorded in the key
  and trusted: a capability the device no longer declares is unreachable whatever the key says.
- **Attribution.** An accepted set is logged as done by that key, by name — not as a parent.
- **Limits per key:** 60 requests a minute, 20 of them `set`s.
- **Never reachable by a key** (§12.2): children, pairing, other keys, reboot, reset. None of
  those routes accepts an API key at all; the test checks eleven of them.

**Residual risks, stated.** A **legacy key is still the whole house, read and command**; the
master has to replace it to narrow it, and nothing yet tells them which keys are legacy beyond
`"scope": null` in the listing — the app's key screen does not show it. The app and the web
portal **cannot set a scope**, so in practice a scoped key is issued by API call today. A
scoped key's scope **cannot be edited**; reissue and revoke. A key that may `set` a device may
set anything on it that is not read-only or `confirm` — including something the firmware author
would rather no automation touched, because `agent:"deny"` hides a capability from *Maya*, not
from a key (§12 only excludes `confirm`). That is a decision worth revisiting.
