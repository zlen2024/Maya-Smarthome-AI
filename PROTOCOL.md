# Maya Device Protocol

**Version 2 (draft)** · Status: proposed, not yet implemented
Contract between Maya firmware (`hardware/*`, and the Arduino library repo) and
the Maya backend (`software/server`) + app (`software/mobile`).

Protocol 1 is what ships today: three boolean relay channels, hardcoded end to
end. Protocol 2 replaces that with **self-describing devices**, so a contributor
can build new hardware, drop it in `hardware/`, and have it appear and be
controllable in the app **without editing `software/`**.

> **Who must read this:** anyone writing firmware against the Maya library, and
> anyone changing `main.py`'s WebSocket handlers or the app's device screens.
> The library repo pins a protocol version; this file is the single source of
> truth for what that version means.

---

## 1. Design rules

1. **Devices describe themselves.** The server stores what a device declares; it
   does not know device types in advance. Adding hardware must never require a
   server or app change.
2. **The app renders from the descriptor.** UI is chosen by capability `kind`,
   never by device model.
3. **Old firmware keeps working.** A device that never sends `proto` is treated
   as protocol 1 and shimmed. No deployed ESP32 needs reflashing.
4. **Unknown fields are ignored, never fatal.** Both directions. This is what
   lets v2.x add capability kinds without breaking v2.0 devices.
5. **The server is the authority on permission,** even where it is not on the
   data path. See §7.

## 2. The three planes

Device-to-device traffic runs locally for speed, but the household still needs
visibility and access control. Those are separate concerns, so they run on
separate planes:

| Plane | Path | Transport | Authoritative? | Latency |
|---|---|---|---|---|
| **Control** | device to server | WebSocket/TLS | **Yes** — grants, permissions, descriptors | ~100ms+ |
| **Data** | device to device | ESP-NOW (local) | No — carries payload only | ~2-10ms |
| **Audit** | device to server | WebSocket, batched | No — observational | seconds-minutes |

**The consequence, stated plainly:** once a peering is granted, the server
**cannot block an individual local message** — it only learns about it afterwards
from the audit plane, and only if the sender chooses to report it. Enforcement
therefore happens **at pairing time**, not per message: the server issues a
peering grant with a shared key, and a device MUST refuse local frames from any
peer not in its granted allowlist. A revoked grant takes effect when the device
next reaches the server (§7.4).

This is the deliberate trade: local speed and offline operation, in exchange for
per-message enforcement. Do not describe the audit plane as a security control —
it is a record, not a gate.

---

## 3. Transport

**Control/audit:** the existing WebSocket. Device connects to `/ws` (or `/`) and
sends an identify frame. All frames are single-line JSON objects. Every frame
carries `id` (the device id); the server ignores frames whose `id` does not match
the connection it identified as.

**Data:** ESP-NOW between devices on the same WiFi channel. ESP-NOW requires
peers on the AP's channel — devices in station mode on the same AP satisfy this.
A device MUST NOT change WiFi channel to reach a peer.

## 4. Version negotiation

The device declares `proto` in its identify frame. Absent means 1.

```
device: { "id":"esp32-9f83b1c1", "proto":2, ... }
server: { "type":"welcome", "proto":2, "server_proto_max":2 }
```

- Device sends the highest version it supports; the server replies with the
  version it will actually speak (`min(device, server_max)`).
- **Protocol 1 shim:** a device with no `proto` is served exactly as today. The
  server synthesises a 3-switch descriptor (`ch1`, `ch2`, `ch3`) on its behalf so
  the rest of the stack sees only v2 shapes. Legacy commands (`output_on`,
  `output_off`, `output_toggle`, `all_on`, `all_off`, `led_on`, `led_off`,
  `toggle`, `get_status`) keep working unchanged.
- A v2 device MUST also accept the legacy command names, so a v2 device still
  works against a server that has not been upgraded yet.

---

## 5. Capability descriptor

Sent in the identify frame. This is the heart of v2.

```json
{
  "id": "esp32-9f83b1c1",
  "proto": 2,
  "status": "online",
  "pin": "1234",
  "ip": "192.168.0.42",
  "model": "smart_extension_3ch",
  "fw": "2.0.1",
  "capabilities": [
    {"key":"ch1",   "kind":"switch", "label":"Channel 1"},
    {"key":"speed", "kind":"range",  "label":"Fan speed", "min":0, "max":100, "step":5, "unit":"%"},
    {"key":"temp",  "kind":"number", "label":"Temperature", "unit":"C", "access":"r", "history":true},
    {"key":"motion","kind":"switch", "label":"Motion", "access":"r"},
    {"key":"mode",  "kind":"enum",   "label":"Mode", "options":["eco","normal","boost"]},
    {"key":"msg",   "kind":"text",   "label":"Display", "max":32, "access":"w"},
    {"key":"wake",  "kind":"time",   "label":"Wake at"},
    {"key":"runfor","kind":"duration","label":"Run for", "max":7200},
    {"key":"horn",  "kind":"button", "label":"Horn"},
    {"key":"reset", "kind":"button", "label":"Reset", "agent":"deny"},
    {"key":"_batt", "kind":"number", "unit":"%", "access":"r"}
  ],
  "state": {"ch1":"off","speed":40,"temp":27.5,"motion":"off","mode":"eco","_batt":86}
}
```

### 5.1 Capability fields

| Field | Required | Meaning |
|---|---|---|
| `key` | yes | Stable id, unique per device. `[a-z0-9_]` up to 24 chars. Never renumber across firmware versions — it is the permission and history key. |
| `kind` | yes | Drives UI and value type. Table below. |
| `label` | no | Human name. Defaults to `key`. A house member may rename it; the app's name wins over the firmware's. |
| `access` | no | `rw` (default), `r` read-only sensor, `w` write-only actuator. |
| `unit` | no | Display suffix only. Never parsed. |
| `group` | no | Free-text; the app groups capabilities sharing a value. |
| `history` | no | `true` asks the server to retain a time series and the app to draw a sparkline. Only meaningful for `number` and `range`. |
| `agent` | no | `allow` (default) or `deny`. See §5.4 — this is a safety control, not a hint. |
| `confirm` | no | `true` means Maya must ask the user before setting it, and the app shows a confirm step. |

**Kinds are expensive; fields are free.** Every `kind` is a widget the app must
implement forever, and a contributor cannot add one without editing
`software/` — which is exactly what this protocol exists to avoid. Fields, by
contrast, are covered by §1 rule 4 (unknown fields are ignored). So when
something new needs expressing, **add a field, not a kind**, unless the value
type itself is genuinely new. The list in §5.2 is intended to stay closed.

### 5.2 Capability kinds

Ten kinds, closed set:

| `kind` | Value type | Extra fields | App widget |
|---|---|---|---|
| `switch` | `"on"` / `"off"` | — | Toggle, or status dot if `access:"r"` |
| `range` | number | `min`, `max`, `step` | Slider |
| `number` | number | `min`, `max`, `unit` | Field, or readout if `access:"r"` |
| `text` | string | `max` (chars) | Text field, or label if `access:"r"` |
| `enum` | string | `options[]` | Dropdown |
| `button` | `null` | — | Button (momentary; no state) |
| `color` | `"#RRGGBB"` | — | Colour picker |
| `time` | `"HH:MM"` (24h, device-local) | — | Time picker |
| `duration` | number (seconds) | `max` | Duration picker |
| `location` | `{"lat":…,"lng":…}` | — | Map pin |

**There is no separate sensor kind.** A binary sensor — PIR, reed switch, water
leak, a physical button — is `switch` with `access:"r"`. A numeric sensor is
`number` with `access:"r"`. Adding a `sensor` kind would duplicate every value
type, which is why access direction is a field instead.

An app that meets an unknown `kind` MUST render a read-only raw value rather than
hide the capability — this is what lets a v2.1 device stay usable on a v2.0 app.

### 5.3 Reserved keys

Keys beginning with `_` are reserved for device health, which nearly every device
reports. Declaring them is optional, but a device that reports these facts MUST
use these keys rather than inventing its own, so the app can render them
consistently in the device card header without knowing the device type:

| Key | Kind | Meaning |
|---|---|---|
| `_batt` | `number`, `unit:"%"`, `access:"r"` | Battery charge |
| `_rssi` | `number`, `unit:"dBm"`, `access:"r"` | WiFi signal |
| `_fw` | `text`, `access:"r"` | Firmware version |
| `_uptime` | `number`, `unit:"s"`, `access:"r"` | Seconds since boot |

The app renders reserved keys as device chrome, not as controls in the main list.
Contributors MUST NOT define new `_`-prefixed keys; that namespace belongs to
this document.

### 5.4 Keeping Maya away from dangerous capabilities

Migration step 3 (§10) replaces Maya's six fixed tools with a generic
`set_capability`, which means **Maya can address every capability a device
declares** unless told otherwise. That is fine for a lamp and not fine for a
`button` labelled "Reset": a vague instruction could plausibly get it pressed.

Two controls, declared by the firmware:

- `"agent":"deny"` — the capability is omitted from the descriptor Maya sees. It
  is not merely discouraged in a prompt; the server filters it out before the
  model is called, the same way `_execute_maya_tool` enforces permission in code
  today rather than in the system prompt.
- `"confirm":true` — Maya must ask and receive a clear yes before setting it, and
  the app shows a confirmation step for human taps too.

Firmware SHOULD set `agent:"deny"` on anything destructive or irreversible
(factory reset, reboot, pairing controls, anything driving a motor into a hard
stop), and `confirm:true` on anything merely disruptive.

Servers MUST treat an unrecognised `agent` value as `deny`. Failing closed is the
right default for a safety flag: a typo should hide a capability, never expose a
dangerous one.

### 5.5 Limits

At most **32 capabilities** per device, descriptor no larger than **4 KB**
serialised. A larger descriptor is rejected with `descriptor_too_large`. This
keeps the frame inside a single `StaticJsonDocument` on the ESP32 side.
Reserved keys (§5.3) count toward the 32.

---

## 6. Control-plane messages

### 6.1 Device to server

**Identify** — first frame after connect. Shape as §5. The server verifies `pin`
before accepting anything else (unchanged from v1).

**State report** — replaces the `ch1/ch2/ch3` heartbeat.

```json
{"id":"esp32-...", "type":"state", "uptime_ms":123456, "state":{"ch1":"on","temp":27.9}}
```

Partial state is allowed: send only what changed. The server merges. A full state
report SHOULD accompany every identify and every `get_status`.

**Ack** — a reply to a command, correlated by `req`.

```json
{"id":"esp32-...", "type":"ack", "req":"c-8123", "status":"ok", "state":{"ch1":"on"}}
```

`status` is `ok` or an error code (§9). The v1 ack — a bare
`{"id","status":"ok","ch1","ch2","ch3"}` with no `req` — remains valid for
protocol 1 devices; the server correlates those to the outstanding command as it
does today.

### 6.2 Server to device

**Set** — the generic replacement for `output_on` / `output_off`.

```json
{"id":"esp32-...", "type":"set", "req":"c-8123", "values":{"ch1":"on","speed":60}}
```

Multiple capabilities in one frame apply atomically where the hardware allows it;
otherwise apply in order and report the first failure. `req` MUST be echoed in
the ack. Also defined: `{"type":"get_status"}`, `{"type":"reboot"}`,
`{"type":"factory_reset"}` — same semantics as their v1 `cmd` equivalents.

---

## 7. Device to device

### 7.1 Pairing (control plane — this is the enforcement point)

A house member pairs two devices in the app. The server then pushes a grant to
**both** devices:

```json
{"id":"esp32-a", "type":"peer_grant", "grant_id":"g-42",
 "peer":{"id":"esp32-b","mac":"24:6F:28:AA:BB:CC"},
 "key":"<32-byte base64>", "scope":["speed","msg"], "expires":"2026-12-31T00:00:00Z"}
```

Rules a device MUST follow:

1. Maintain an allowlist of granted peers. **Silently drop local frames from any
   sender not in it.** This is the only real access control on the data plane.
2. Honour `scope`: a peer may only address the capability keys listed. Reject
   others with `not_permitted` and report it (§7.3).
3. Persist grants across reboot; drop them on `factory_reset`.
4. Treat an expired grant as absent.

### 7.2 Local frame (data plane)

```json
{"v":2, "from":"esp32-a", "grant":"g-42", "seq":118, "ts":123456,
 "kind":"set", "values":{"speed":60}}
```

- `seq` is a per-(sender, grant) counter, monotonic since boot. It exists so the
  server can **detect gaps** in the audit log — a receiver SHOULD reject a `seq`
  it has already seen (replay).
- `ts` is sender `millis()`, not wall clock. Combined with `boot_id` in the audit
  batch it lets the server order events without the device having a real clock.
- `kind` is `set`, `event`, or `msg` (free payload for device-defined chatter).
- Frames MUST be authenticated with the grant `key`. An unauthenticated frame is
  dropped, not processed.

### 7.3 Audit (audit plane)

Local activity is reported to the server **batched, best-effort, and bounded**:

```json
{"id":"esp32-a", "type":"peer_log", "boot_id":"b-9f3", "batch":[
  {"grant":"g-42","seq":118,"ts":123456,"kind":"set","peer":"esp32-b","summary":"speed=60","result":"ok"},
  {"grant":"g-42","seq":119,"ts":123890,"kind":"set","peer":"esp32-b","result":"not_permitted"}
]}
```

- **Buffer when offline.** A bounded ring buffer (RECOMMENDED at least 64
  entries) that flushes on reconnect. Without this, visibility disappears exactly
  when the network is broken — which is when it matters most.
- **On overflow, drop oldest and set `"dropped":<n>`** on the next batch. The
  server records a gap. Never let logging block or fail the local data path.
- **Do not log every frame at high rate.** A device exchanging frames faster than
  about 1 Hz MUST aggregate (count, first/last `ts`, last value) rather than emit
  one entry per frame.
- Flush at most every 10 s, or immediately for a `result` other than `ok`.

Because `seq` is monotonic, the server can report "device A claims 400 frames,
logged 120" — so silence is visible as a gap rather than looking like inactivity.

### 7.4 Revocation

Revoking a pairing removes it server-side immediately and pushes
`{"type":"peer_revoke","grant_id":"g-42"}` to both devices. A device that is
offline keeps operating on the stale grant until it reconnects — an accepted
window, and the reason grants carry `expires`. Keep expiry short (days, not
years) for anything sensitive.

---

## 8. Device to Maya

A device may ask Maya to act, which is how a robot becomes an agent:

```json
{"id":"robot-01", "type":"agent", "req":"a-7", "text":"someone is at the front door"}
```

The server runs the normal agent loop with `sender_role: "device"` and replies:

```json
{"id":"robot-01", "type":"agent_reply", "req":"a-7", "text":"I've told the family."}
```

**This is a privilege boundary, not a convenience.** A device that can invoke
Maya can ask Maya to act on *other* devices, so:

- A device role MUST be granted explicitly per device (`can_invoke_agent`), off
  by default.
- Tool calls made on behalf of a device are constrained to that device's granted
  scope — a device may not reach devices it has no grant for, exactly as a child
  is constrained by `_child_command_denial` today.
- Every device-initiated agent turn is written to the activity log with
  `actor_type: "device"`, so it is attributable.
- Rate-limit per device. A chattering robot must not be able to exhaust the model
  budget or spam house chat.

---

## 9. Errors

Ack `status` values: `ok`, `unknown_capability`, `bad_value`, `not_permitted`,
`busy`, `unsupported`, `descriptor_too_large`. Anything unrecognised MUST be
treated as a generic failure, never as success.

Server-side outcomes on the control plane are unchanged: `not_connected` when the
device has no live socket, `timeout` when no ack arrives within 5 s.

---

## 10. Compatibility matrix

| Device \ Server | Server v1 | Server v2 |
|---|---|---|
| **Firmware v1** | works (today) | works — server shims a 3-switch descriptor |
| **Firmware v2** | works — v2 device must still accept v1 command names (§4) | full v2 |

Migration order matters. Build it in this sequence, because each step is useful
on its own and none of them breaks what is already deployed:

1. Server accepts and stores descriptors; shims protocol 1. Nothing else changes.
2. App renders from the descriptor instead of three hardcoded toggles.
3. Maya swaps its six fixed tools for a generic `set_capability`, driven by the
   descriptors already in its house context — filtering `agent:"deny"` and
   honouring `confirm` (§5.4) **in the same change**, not as a follow-up.
4. **Extract the Arduino library** — by now it only has to implement a written
   protocol, so it is thin and stable.
5. Peering: grants, local link, audit.
6. Device to Maya.

## 11. Versioning rules for the library repo

- The library declares one `MAYA_PROTO` integer. It does not negotiate below it.
- **Free changes** — a new optional *field* — bump the minor version of this
  document and require no library or app change. §1 rule 4 covers them.
- **A new `kind` is not free.** It costs a widget in the app, and until that
  ships, devices using it degrade to a read-only raw value (§5.2). Adding one
  bumps the minor version, but MUST be planned alongside the app change. This is
  why §5.2 is a closed set of ten and new expressiveness should arrive as a
  field.
- **Breaking changes** (renamed field, changed semantics) bump `proto` and MUST
  add a row to the matrix in §10.
- This file is the source of truth. If library docs and this file disagree, this
  file wins, and the library has a bug.

---

## Appendix A — Protocol 1 (what ships today)

Recorded so the shim can be written from a spec rather than by reading firmware.

- **Identify:** `{"id","status":"online","pin","ip","ch1","ch2","ch3"}`
- **Heartbeat:** `{"id","type":"heartbeat","uptime_ms","ch1","ch2","ch3"}`
- **Command:** `{"id","cmd","channel"}` where `cmd` is one of `output_on`,
  `output_off`, `output_toggle`, `all_on`, `all_off`, `get_status`, `led_on`,
  `led_off`, `toggle`, `factory_reset`, `reboot`
- **Ack:** `{"id","status":"ok","ch1","ch2","ch3"}` — all three channels always,
  which is why a single-channel command keeps the whole relay row in sync
- **Error ack:** `{"id","status":"invalid_channel"}`

The server maps `on` to `output_on` and `off` to `output_off` (`_FIRMWARE_CMD`,
`software/server/main.py:1347`) so callers — the app, the Open API, and Maya —
can use the short names. Channels are GPIO 2, 4, 5; channel defaults to 1 when
absent.

## Appendix B — What v2 costs on the existing codebase

`ch1`/`ch2`/`ch3` appears **76 times across 6 files**. These all change together
in migration step 1-2:

| File | What is hardcoded |
|---|---|
| `software/server/main.py` | Three literal variables in both WS handlers, the broadcast payload, `_dispatch_command`'s ack filter |
| `software/server/models.py` | `Heartbeat.ch1/ch2/ch3` columns; `Relay.is_on` is `Boolean`, so numbers and text do not fit |
| `software/mobile/lib/screens/devices_tab.dart` | Fixed three toggles |
| `software/mobile/lib/screens/device_management_tab.dart` | Channel rename UI, 1-3 |
| `software/mobile/lib/screens/home_tab.dart` | Channel summary tiles |
| `hardware/smartextension/smartextension.ino` | `NUM_OUTPUTS 3`, `OUTPUT_NAMES`, `OUTPUT_PINS` |

`Relay.is_on` being a `Boolean` is the single most load-bearing assumption: a
typed capability value cannot be stored in it at all. Step 1 should introduce a
capability/state table rather than widen `Relay`.
