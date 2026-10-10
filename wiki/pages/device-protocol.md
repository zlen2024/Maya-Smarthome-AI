# Device protocol v2 — what is built

`PROTOCOL.md`, at the repo root, is the contract: the single source of truth for
what a protocol version means. This page is the other half — **what of it exists
in the code**, and what a reader will and will not find if they go looking.

The goal the protocol exists for: a contributor builds new hardware, drops it in
`hardware/`, and it appears and is controllable in the app **without editing
`software/`**. Today's protocol 1 hardcodes three boolean relay channels from
firmware to app — `ch1`/`ch2`/`ch3` appeared 76 times across 6 files when the
migration was planned.

## Status: step 1 of 6 (2026-10-10)

§10 defines a six-step migration order. Only the first is implemented.

| Step | State |
|---|---|
| 1. Server accepts and stores descriptors; shims protocol 1 | **done** |
| 2. App renders from the descriptor instead of three hardcoded toggles | not started |
| 3. Maya swaps her six fixed tools for a generic `set_capability` | not started |
| 4. Extract the Arduino library | not started |
| 5. Peering: grants, local link, audit (§7) | not started |
| 6. Device to Maya (§8) | not started |

**No firmware change was needed or made.** The ESP32 still speaks protocol 1 and
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

## What a reader will not find

- **Per-capability permissions.** `Permission` still keys on `relay_id`, so a
  child may set `ch1`/`ch2`/`ch3` through the new endpoint under exactly the
  rights they already had, and anything else is refused outright. §5.1 calls the
  capability key "the permission key"; making that true is a schema change that
  belongs with step 2.
- **`report_every` doing anything.** It is stored, and nothing reads it yet.
  §5.8 redefines `status` as "reported within its expected interval" rather than
  "a socket is open", which reaches `ConnectionManager`, the device list endpoint
  and Maya's house context — three places, deliberately out of step 1.
- **History.** `history:true` is stored per capability; no time series is
  retained. The app's sparkline (§5.1) has nothing to draw yet.
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
