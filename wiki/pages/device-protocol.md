# Device protocol v2 — what is built

`PROTOCOL.md`, at the repo root, is the contract: the single source of truth for
what a protocol version means. This page is the other half — **what of it exists
in the code**, and what a reader will and will not find if they go looking.

The goal the protocol exists for: a contributor builds new hardware, drops it in
`hardware/`, and it appears and is controllable in the app **without editing
`software/`**. Today's protocol 1 hardcodes three boolean relay channels from
firmware to app — `ch1`/`ch2`/`ch3` appeared 76 times across 6 files when the
migration was planned.

## Status: steps 1, 3 and 4 done, step 2 server-complete, spec at revision 2.1 (2026-10-10)

§10 defines a six-step migration order. Only the first is implemented.

| Step | State |
|---|---|
| 1. Server accepts and stores descriptors; shims protocol 1 | **done** |
| 2. App renders from the descriptor instead of three hardcoded toggles | server done; app partly — see below |
| 3. Maya swaps her relay tool for a generic `set_capability` | **done** |
| 4. Extract the Arduino library | **done** (compiles for ESP32; not yet flashed) |
| 5. Peering: grants, local link, audit (§7) | not started |
| 6. Device to Maya (§8) | not started |

**Steps 1–3 needed no firmware change.** The shipped ESP32 still speaks protocol 1 and
is served by the shim — which is the point of the migration order, and what
`test_descriptor.py` checks rather than assumes.

## What step 1 added

| File | Role |
|---|---|
| `software/server/descriptor.py` | §4-§6 as validation logic. Parses an identify frame, validates keys and kinds, coerces values per kind, synthesises the protocol-1 descriptor. No database, no sockets. |
| `software/server/capability_store.py` | The database half: rewrite declarations, merge state, read it back, and build the payload the app and Maya consume. |
| `models.DeviceCapability` | One row per declared capability. |
| `models.CapabilityState` | One row per capability's current value. |
| `Device.proto` / `.model` / `.fw` / `.report_every` | What the device said it is. |
| `GET /api/devices/{id}/capabilities` | The descriptor + state, for any device, whichever protocol it speaks. |
| `POST /api/devices/{id}/capability` | §6.2 `set`, by capability key. |
| `software/server/test_descriptor.py` | 11 checks: the validation rules, then two devices played against the real app over a WebSocket. |

## The decisions worth knowing

**Both representations run at once, on purpose.** `Relay.is_on` is still what the
app and Maya read; `capability_state` is what they will read after step 2. Every
write path updates both (`_mirror_channels_to_relays`, `_record_v1_channels` in
`main.py`). That redundancy is deliberate and temporary: it is what lets step 1
ship without touching the app, and it is step 2's job to remove it.

**`value` is JSON text, not a typed column.** Appendix B named `Relay.is_on` as
the single most load-bearing assumption in the codebase — it is a `Boolean`, so a
number, a string or a colour cannot be stored in it at all. Rather than widen it,
step 1 introduced a separate table whose one `value` column holds `"on"`, `27.5`,
`"#ff8800"` or `{"lat":…,"lng":…}`. `descriptor.coerce_value` has already
guaranteed the shape matches the capability's kind before anything is written, so
a reader does not re-validate.

**Capability rows are replaced on every identify, never merged.** The firmware is
the authority on what a device *can* do, so a capability dropped from a new build
disappears, along with its stored state — which would otherwise be unreadable,
since nothing would know its kind any more. Labels are the exception: §5.1 gives
a house member's name precedence over the firmware's, and those names live in
`Relay.name` today, applied as overrides in `_capability_label_overrides`.

**Unknown things degrade; they are not rejected.** A device the server does not
fully understand must still work as far as it can, or the protocol fails at its
own purpose. So: an unknown `kind` is kept but forced read-only (§11's "degrades
to a read-only raw value"), an undeclared or out-of-range value in a *report* is
dropped while the rest of the frame is kept, and an unknown field is ignored
(§1 rule 4). Only §5.5's two limits reject outright, with
`descriptor_too_large`.

**Two flags fail closed.** An unrecognised `agent` value becomes `deny` — §5.4
makes this a MUST, because a typo should hide a capability from Maya, never
expose a dangerous one. An unrecognised `access` value becomes `r`, which the
document does not specify; the same reasoning was applied, since the safe reading
of a declaration you cannot parse is the one that does not write to hardware.

**`agent:"deny"` filtering lives in `capability_store.descriptor_payload`,** not
in whatever step 3 writes. §5.4 warns that the filter must land *in the same
change* as the generic tool; putting it in the only function that builds Maya's
view means step 3 cannot forget it. `for_agent=True` is already covered by a test
even though nothing calls it yet.

## Two bugs the step-1 tests found

Both were pre-existing, in the command path step 1 had to touch:

1. **A v2 ack switched relays off.** The ack handler read `json_data.get("ch1",
   "off")` — safe for a v1 ack, which always carries all three channels
   (Appendix A), and wrong for a v2 ack, which carries none of them. The missing
   keys defaulted to `"off"` and were written to the `Relay` rows, so a fan set
   to on showed as off in the app. The branch now only reads channel keys that
   are actually present.
2. **An error ack was never correlated.** `{"status":"invalid_channel"}` (v1) and
   `{"type":"ack","status":"bad_value"}` (v2) matched no branch in the WebSocket
   handler, so nothing resolved the waiting command and the caller sat through
   the full 5-second timeout for an answer that had already arrived. All ack
   shapes now share one branch.

A third was a race rather than a bug in a branch: `wait_for_ack` registered its
future **after** the command was sent, so a device that acked inside a
millisecond — before the sending task was scheduled again — would have its ack
dropped. `arm_ack` now reserves the slot before the send, for both the v1 and v2
paths.

## Document revision 2.1 — the holes step 1 found

Implementing step 1 turned up eight questions the document did not answer, plus
one place where it contradicted itself. All were written up on 2026-10-10 (spec
revision 2.1, `proto` unchanged at 2), because a half-specified protocol is worse
than an unimplemented one — the next person builds against the gap and the gap
becomes the contract.

| What was undefined | Now |
|---|---|
| What claiming creates, when the server does not yet know what the device is | §4.1 — the device record and nothing else |
| What a permission *is*, though §5.1 calls `key` "the permission key" | §5.10 — a grant per (child, device, key), governing writes |
| Where a member's capability name lives, though §5.1 says it wins | §5.11 — house name, else firmware label, else key |
| What `history:true` promises | §5.12 — on-change sampling, the gap rule, 30 days, 5,000 points |
| The `status` vocabulary for a sleeping device | §5.8 — `online` / `asleep` / `stale` / `offline`, derived |
| How the Open API grows capabilities, and per-key scoping | §12 — v1 frozen, v2 is the capability surface |
| Who enforces `confirm:true` | §5.4 — the server, on evidence from the client |
| A button press on the wire, a partial `set` failure, an unknown `access` | §6.2, §9, §5.1 |

**The contradiction:** §5.8 declares `_report_every` as the way a sleepy device
says its interval is adjustable, but §5.3's reserved-key table never listed it —
so `descriptor.py`, which implements §5.3 strictly, dropped the capability
silently. The table now lists it, the code accepts it, and a test covers it. This
is the failure mode the `_` namespace rule is supposed to prevent, arriving
through the document rather than through a contributor.

Three of the new rules were small enough to implement in the same pass, because
they constrain code step 1 had just written and leaving them unimplemented would
have created the gap immediately:

- `confirm:true` is enforced in `_dispatch_set`, not in the clients. A set
  touching such a capability without `"confirmed": true` is refused with
  `not_permitted` and never reaches the device.
- A failing ack's `failed` key is passed through to the caller.
- `_report_every` is accepted as a reserved key.

**§4.1 was implemented in step 2**, with the permission and label conversions,
because all three touch the same tables and splitting them would have meant
converting twice.

## Step 2 (2026-10-10): the three conversions, and the app

§10 bundles three conversions into step 2 because they touch the same tables.
All three are done on the server:

| Section | What changed |
|---|---|
| §4.1 | `register_device` creates the device record and nothing else. The shim's `SmartExtension` + three `Relay` rows are created when a **protocol-1 device identifies** (`_ensure_v1_backing_rows`), which is the first moment three channels are a fact. A protocol-2 device never gets them. |
| §5.10 | `capability_grants` replaces `permissions`. Enforcement for every path — the v1 command endpoint, the capability endpoint and Maya — runs through `_child_capability_denial`. |
| §5.11 | `capability_labels` replaces `Relay.name` as the store. Renaming through either route writes the same row. |

**The data was converted, not duplicated.** The migration copies each per-relay
permission onto `(device_id, "ch<n>")`, verifies the count, then **drops the
`permissions` table**; relay names that still read "Channel N" carry no intent
and are left out, so the firmware's own label applies. `/api/permissions`
survives as a *translating facade* over the grant store — a second spelling, not
a second source of truth, which is the distinction §10 draws. Verified against a
database carrying the old table: three permissions became three grants with their
allow/deny values intact, two real names became labels, the table went.

**One bug fell out of §5.11.** Re-claiming a device used to reset every channel
name back to "Channel N" — a member's "Television" was silently wiped on every
re-provision. The block that did it was the same block §4.1 required removing.

**The app** — written, **not compiled**: there is no Flutter SDK on this machine,
so every Dart change here is reviewed rather than built, and `flutter analyze`
is the next step before any APK.

- `lib/widgets/capability_control.dart` (new) renders one capability by `kind`:
  all ten, plus a read-only fallback for a `kind` this build has never heard of
  (§11). It asks before setting anything declared `confirm: true` and only then
  claims the confirmation (§5.4). `CapabilityChrome` renders the reserved `_`
  keys as device chrome (§5.3) — except `_report_every`, which is a setting.
- `devices_tab.dart` renders each device from `GET .../capabilities` instead of
  three hardcoded toggles, merges both v1 channel keys and v2 `state` from the
  broadcast stream, and translates ack statuses (§9) into sentences.
- The permission sheet in `children_tab.dart` lists every writable capability in
  the house from `/api/children/{id}/grants`, so a parent can grant a fan's
  speed, not only a relay channel.
- **Still on the v1 shapes:** `home_tab.dart`'s channel summary and rename, and
  `device_management_tab.dart`. Both keep working through the shim and the
  facade; neither shows a non-channel capability.

## Step 3 (2026-10-10): Maya drives any device

Only `control_device` was a relay tool; the other five (child location, homework,
screen time, activity log) have nothing to do with capabilities, so the plan's
"swaps her six fixed tools" overstates it. `set_capability(device_id, key, value,
confirmed)` replaces the one that mattered, and Maya's house state is now built
from `descriptor_payload(for_agent=True)` — a fan's speed slider is as visible to
her as a three-channel extension. Details of both gates are in
[Maya AI agent](maya-ai-agent.md#set_capability-two-gates-a-misbehaving-model-cannot-walk-through).

**A pre-existing bug surfaced, on the path step 3 depends on.** `_dispatch_set`
sent a `{"type":"set"}` frame to *every* device, including protocol-1 boards,
which have never heard of one — so `POST /capability` against a v1 device would
have timed out. It now translates to the v1 command each key always mapped to
(`_dispatch_set_v1`), stopping at the first failure and reporting `failed` plus
what did apply, as §6.2 asks. `test_maya.py` covers both entry points. It went
unnoticed through step 2 because the step-1 tests only exercised the v1 *command*
endpoint against a v1 device, and the `set` endpoint only against a v2 one.

**The model is the only thing replaced in the test.** `test_maya.py` swaps
`ai.call_model` for a script, and everything else — the context she reads, the
executor and every permission check, the dispatch over a WebSocket — is the real
app, reached through `/api/maya/voice` so it runs in the app's own event loop.
The script misbehaves on purpose: it names a capability it was never shown, and
passes `confirmed:true` with nobody having asked.

## What a reader will not find

Specified, not built — each has a section to build against:

- **`report_every` doing anything** (§5.8). It is stored and nothing reads it, so
  `status` is still "a socket is open" — the vocabulary exists on paper only. The
  three call sites are `ConnectionManager`, the device list endpoint and Maya's
  house context.
- **History** (§5.12). The flag is stored per capability; no series is retained.
- **The public API's v2 surface** (§12). `/api/open/v1/*` is unchanged and still
  speaks three channels through the shim.
- **Any of §7 or §8** — peering, the local ESP-NOW link, the audit plane, or
  device-to-Maya. Steps 5 and 6.

## Where to look

- `PROTOCOL.md` §4 (negotiation), §5 (descriptor), §6 (messages), §9 (errors),
  Appendix A (protocol 1), Appendix B (what v2 costs this codebase)
- `software/server/descriptor.py` — every rule, with the section it comes from
- `software/server/test_descriptor.py` — the rules as executable examples,
  including the salt jar from §5.7
- [data model](data-model.md) for the two new tables, [server
  backend](server-backend.md) for where the handlers sit

## Step 4 (2026-10-10): the Arduino library

`hardware/libraries/Maya` — a contributor's sketch declares capabilities and
supplies handlers; everything the protocol cares about is the library's.

```cpp
Maya maya("my_lamp", "1.0.0");
maya.addSwitch("lamp", "Lamp", [](bool on) { digitalWrite(2, on); return true; });
maya.addNumber("temp", "Temperature").unit("C").history();
maya.begin();   // ... maya.loop(); maya.setNumber("temp", t);
```

**Two halves, split so the claim is checkable.** `MayaCore.{h,cpp}` is the
protocol with no hardware in it — it needs only ArduinoJson, so it builds on a
laptop. `Maya.{h,cpp}` is the radio half: BLE provisioning, WiFi, the WebSocket
and the zombie-link watchdog, moved from `smartextension.ino` with the same
behaviour (the BLE UUIDs, status codes `0/1/2/4/6/8/9`, the PIN rules and the
"every flash starts clean" wipe are part of what the app expects).

**Verification, and its limit.** `extras/test/test_library.py` (7 checks) builds
the core with a C++ compiler and drives it through a small stdin/stdout driver.
What it says is judged by the **server's own code**: the identify frame must pass
`descriptor.parse_identify` with no warnings, every ack's `state` must survive
`coerce_state`, and the second half connects the same code to the real app over a
WebSocket (set → hardware → ack → database, the `confirm` hold, a hardware
refusal reported back, device-initiated state stored). Two deliberate bugs were
introduced to confirm the checks bite — letting a write through to a read-only
capability, and re-sending an acked value as a change — and both failed the run.
Both examples then **compile for ESP32** with arduino-cli (core 2.0.17).
**Nothing has been flashed.** `Maya.cpp` is moved code that has only been
compiled, so the first real board is the first real test of it.

**Things the build found, worth keeping:**

- The first draft put the protocol in `namespace maya` and the examples used a
  variable called `maya`, which does not compile (`expected primary-expression
  before '.'`). The namespace is `mayalib` so the obvious name is free.
- The BLE `getValue()` returns `std::string` on ESP32 core 2.x and `String` on
  3.x; `smartextension.ino` as written does not build on 2.0.17 for that reason.
  The library converts through `c_str()` so it builds on either.
- BLE + TLS + WiFi is ~1.7 MB, over the default 1.2 MB app partition. Both the
  library and the old sketch need the **Huge APP** partition scheme; the old
  `SETUP.md` never said so.
- The "wipe on a new build" fingerprint used `__DATE__ __TIME__`, which inside a
  library is baked in when *the library* is compiled — a cached object would never
  notice a new sketch. It is now `ESP.getSketchMD5()`.

**Declarations the library refuses** (and prints on Serial at `begin()`): a bad
key, a duplicate, a `_` key it does not own, more than 32 capabilities, a
descriptor over 4 KB. Nothing is sent in that case — the server would only reject
it — so a wrong sketch fails loudly on the bench instead of silently on the wire.

**Not in the library yet:** peering (§7), device→Maya (§8), `report_every`
(§5.8). `hardware/smartextension/smartextension.ino` is untouched and remains the
shipped firmware until `examples/SmartExtension3ch` has run on a real board.
