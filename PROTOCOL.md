# Maya Device Protocol

**Version 2 (draft), document revision 2.2** · Status: §10 step 1 implemented
2026-10-10; steps 2-6 proposed. The server stores descriptors and shims protocol 1; the app, Maya and
the firmware are untouched and still speak protocol 1. See
`wiki/pages/device-protocol.md` for what exists versus what is still on paper —
this file stays the contract either way, and describes the finished protocol, not
the current build.

Revision 2.1 (2026-10-10) closed the questions step 1 could not answer from the
document: claiming (§4.1), permissions (§5.10), labels (§5.11), history (§5.12),
the status vocabulary (§5.8), the public API surface (§12), and the smaller
interop gaps marked there. `proto` stays **2** — one optional ack field was added
(§6.2), which §11 classes as a free change.

Revision 2.2 (2026-10-10) specified the device-to-device link (§7) well enough to
build: who may pair and what may be granted, the one-way grant and its `role`,
the frame MAC and size limit, `(ep, seq)` replay ordering, `peer_sync`, and what
the audit keeps. Two optional fields were added — `mac` in identify, and
`role`/`dir`/`ep`/`count` in the peering frames — and two frame types,
`peer_sync` and the local `ack`. Nothing was renamed, so `proto` stays **2**.
The first draft's `ts` on local frames was dropped, because ordering never needed
it; no implementation existed to break.
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

### 4.1 Claiming, and what the server may assume before identify

A device must be **claimed** by a house before the server will talk to it: the
owner provisions it over BLE and registers the id, and an unclaimed device that
dials in is told to factory-reset (Appendix A). Claiming happens *before* the
first identify, which fixes what the server can possibly know at that moment:
**a device id, a PIN, and a name the owner typed.** Nothing about the hardware.

**Therefore claiming creates the device record and nothing else.** No channels,
no sub-entities, no assumed shape. Every structural fact comes from the
descriptor at identify, because that is the first moment the server knows what
the device is.

This is not a refinement; it is the rule that makes §1 rule 1 true. The server
that ships today creates a `SmartExtension` and exactly **three** `Relay` rows
for every device at registration, whatever it turns out to be — so the salt jar
of §5.7 is born with three relays it does not have, and a contributor's new
hardware arrives pre-shaped like a 3-channel extension. A server that guesses at
claim time cannot host hardware it has never heard of.

Rules:

- Claiming stores the id, the house, the PIN and the owner's name. It MUST NOT
  create capability, channel or relay records.
- **The shim's backing rows are created on first identify of a protocol-1
  device** (§4), not at claim time — that identify is when three channels first
  become a known fact. A protocol-2 device never gets them, even if it declares
  `ch1`-`ch3`.
- Re-claiming an existing id updates the name and PIN and leaves the descriptor
  alone. The firmware re-declares on its next identify anyway.
- Who may claim is a house question, not a protocol one: the master or a member
  they have authorised.

**Migration.** Devices claimed before this rule keep their relay rows; they are
the shim's backing store until step 2 takes `Relay` off the read path. New claims
create none. A server implementing this MUST NOT retro-create relay rows to make
old and new devices look alike — that is the guess this section exists to
forbid.

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

Top-level descriptor fields: `id`, `proto`, `status` and `pin` are required;
`ip`, `mac`, `model`, `fw`, `report_every`, `wake_mah` and `batt_mah` are optional.
`mac` is the WiFi station MAC and is required **to be paired** (§7.1). The
last two are a battery device's energy per wake and its pack capacity, which let
the app state the cost of a reporting interval instead of guessing at it
(§5.8). `report_every` (seconds)
declares how often the device intends to report and is what lets the server tell
a sleeping device from a dead one — see §5.7 and §5.8.

### 5.1 Capability fields

| Field | Required | Meaning |
|---|---|---|
| `key` | yes | Stable id, unique per device. `[a-z0-9_]` up to 24 chars. Never renumber across firmware versions — it is the permission and history key. |
| `kind` | yes | Drives UI and value type. Table below. |
| `label` | no | Human name. Defaults to `key`. A house member may rename it; the app's name wins over the firmware's. |
| `access` | no | `rw` (default), `r` read-only sensor, `w` write-only actuator. **An unrecognised value MUST be treated as `r`** — the safe reading of a declaration the server cannot parse is the one that does not write to hardware. Same reasoning as `agent` below, and stated because an implementation that guessed `rw` instead would let a peer write a capability this one refuses. |
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

#### What each kind is for

**`switch`** — anything with exactly two states.
As an actuator (`rw`, the default): a relay channel, an LED, a solenoid lock, a
pump. As a sensor (`access:"r"`): a PIR motion detector, a reed switch on a door,
a water-leak probe, a physical push button the firmware reports.
`{"key":"lock","kind":"switch","label":"Front door"}`

**`range`** — a bounded number the user drags. You know the limits.
Dimmer brightness, fan speed, servo angle, volume, motor duty cycle.
`{"key":"dim","kind":"range","label":"Brightness","min":0,"max":255}`

**`number`** — a typed numeric value where the *unit* carries the meaning, and
the range may be open. Almost always a sensor: temperature (DHT22), humidity,
distance (HC-SR04), soil moisture, power draw in watts, CO2 in ppm. Writable when
it is a setpoint — a target temperature the user types rather than drags.
`{"key":"temp","kind":"number","label":"Temperature","unit":"C","access":"r","history":true}`

**`text`** — free-form string. Writable: a message to show on an LCD or OLED.
Read-only: the last RFID tag scanned, a status line the firmware composes.
`{"key":"msg","kind":"text","label":"Display","max":32,"access":"w"}`

**`enum`** — a closed set of named choices the firmware defines.
Operating mode (eco/normal/boost), input source, speed preset.
`{"key":"mode","kind":"enum","label":"Mode","options":["eco","normal","boost"]}`

**`button`** — a momentary action with no state. Pressing it *does* something;
there is nothing to read back. Buzzer beep, horn, calibrate, dispense, reset.
`{"key":"beep","kind":"button","label":"Find me"}`

**`color`** — an RGB value. LED strip, mood lamp, status indicator.
`{"key":"strip","kind":"color","label":"Light strip"}`

**`time`** — a time of day, device-local, no date. Alarm, "turn on at", the start
of a daily schedule.
`{"key":"wake","kind":"time","label":"Wake at"}`

**`duration`** — a length of time in seconds. "Run the fan for 30 minutes",
watering length, sleep timer. Use `max` to keep the picker sane.
`{"key":"runfor","kind":"duration","label":"Run for","max":7200}`

**`location`** — a geographic point. Robot position, GPS tracker, pet collar.
Renders as a map pin, reusing the map the app already uses for child location.
`{"key":"pos","kind":"location","label":"Position","access":"r"}`

#### Choosing between similar kinds

| If you are unsure | Use | Because |
|---|---|---|
| `range` or `number`? | `range` when the user **drags** between known limits; `number` when the value is **measured or typed** and the unit carries the meaning | A slider with no meaningful max is unusable; a temperature reading is not a slider |
| `switch` or `button`? | `switch` if it has a state you can read back; `button` if pressing it is a one-off event | "Is the lamp on?" has an answer. "Is the horn?" does not |
| `enum` or `text`? | `enum` when the firmware knows every valid value | An `enum` gives the user a dropdown and gives Maya a list it cannot get wrong |
| `number` or `range` for a setpoint? | `number` with `min`/`max` | A target temperature is typed, not dragged, and wants its unit shown |

#### Annotated example

The canonical descriptor above, with the reasoning spelled out. JSON has no
comments — this block is illustrative only, do not send it as-is:

```jsonc
"capabilities": [
  // Plain actuator. access defaults to "rw", so it is omitted.
  {"key":"ch1", "kind":"switch", "label":"Channel 1"},

  // Bounded, draggable -> range. step makes the slider snap to 5s.
  {"key":"speed", "kind":"range", "label":"Fan speed",
   "min":0, "max":100, "step":5, "unit":"%"},

  // Measured, not set -> number + access:"r". history draws a sparkline.
  {"key":"temp", "kind":"number", "label":"Temperature",
   "unit":"C", "access":"r", "history":true},

  // A binary SENSOR is still a switch -- direction is access, not kind.
  {"key":"motion", "kind":"switch", "label":"Motion", "access":"r"},

  // Firmware knows every valid value -> enum, so Maya cannot invent one.
  {"key":"mode", "kind":"enum", "label":"Mode",
   "options":["eco","normal","boost"]},

  // Write-only: the device shows it, it never reads back.
  {"key":"msg", "kind":"text", "label":"Display", "max":32, "access":"w"},

  // Time of day, no date. Device-local -- the device owns its own clock.
  {"key":"wake", "kind":"time", "label":"Wake at"},

  // Seconds. max keeps the picker to a sensible 2 hours.
  {"key":"runfor", "kind":"duration", "label":"Run for", "max":7200},

  // Momentary: no state to read back.
  {"key":"horn", "kind":"button", "label":"Horn"},

  // Destructive -> hidden from Maya entirely. See 5.4.
  {"key":"reset", "kind":"button", "label":"Reset", "agent":"deny"},

  // Reserved key: rendered as device chrome, not as a control. See 5.3.
  {"key":"_batt", "kind":"number", "unit":"%", "access":"r"}
]
```

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
| `_report_every` | `duration`, `access:"rw"`, with `min`/`max` | Declaring it means "my check-in interval is adjustable" (§5.8) |

The app renders reserved keys as device chrome, not as controls in the main list —
except `_report_every`, which is a setting and renders with the duration picker.

Contributors MUST NOT define new `_`-prefixed keys; that namespace belongs to
this document. **A server MUST drop an unrecognised `_` key** rather than store
it or reject the device: the capability then simply does not exist, which is the
fail-closed reading, where refusing the whole descriptor would brick a board over
a naming slip. The consequence runs the other way too — a key added to this table
is invisible to any server built before it, so adding one is the same kind of
change as adding a `kind` (§11) and MUST be planned with the server and app
alongside it.

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

#### Who enforces `confirm`

"Maya must ask the user" and "the app shows a confirm step" are both *client*
behaviour, and a flag enforced only in clients is enforced nowhere: the same
capability is reachable from the REST API and from a third party's API key. So
the gate is in the server, and the clients' job is to produce the evidence for
it:

- A `set` touching a `confirm:true` capability MUST carry `"confirmed": true`,
  and a server MUST refuse one that does not, with `not_permitted`.
- Only a client acting for a present human may send that flag: the app sets it
  after the user taps through the confirm step, and Maya sets it only after an
  explicit yes **in the turn she asked for it**, never inferred from a general
  instruction given earlier.
- **An API key is not a human.** A `confirm:true` capability MUST be refused on
  the public API (§12) whatever flags the request carries. A third-party
  integration that needs it is asking for a human's consent to be delegated to a
  script, which is the thing the flag exists to prevent.
- `confirm` and `agent` are independent and both apply. `agent:"deny"` hides a
  capability from Maya entirely; `confirm:true` lets her reach it only with a
  yes.

### 5.5 Limits

At most **32 capabilities** per device, descriptor no larger than **4 KB**
serialised. A larger descriptor is rejected with `descriptor_too_large`. This
keeps the frame inside a single `StaticJsonDocument` on the ESP32 side.
Reserved keys (§5.3) count toward the 32.

### 5.6 Worked examples

Two complete descriptors for hardware someone might actually contribute. Neither
needs a single line of change in `software/` — that is the whole point.

**A plant waterer.** Soil sensor, a pump, and a daily schedule.

```json
{
  "id": "esp32-planter-01", "proto": 2, "status": "online",
  "pin": "4417", "model": "planter_v1", "fw": "1.0.0",
  "capabilities": [
    {"key":"pump",   "kind":"switch",  "label":"Pump"},
    {"key":"moist",  "kind":"number",  "label":"Soil moisture", "unit":"%", "access":"r", "history":true},
    {"key":"water_at","kind":"time",   "label":"Water at"},
    {"key":"amount", "kind":"duration","label":"Water for", "max":120},
    {"key":"empty",  "kind":"switch",  "label":"Tank empty", "access":"r"},
    {"key":"prime",  "kind":"button",  "label":"Prime pump", "confirm":true},
    {"key":"_batt",  "kind":"number",  "unit":"%", "access":"r"}
  ],
  "state": {"pump":"off","moist":38,"water_at":"07:30","amount":20,"empty":"off","_batt":91}
}
```

Worth noticing: `empty` is a sensor, so it is a `switch` with `access:"r"` rather
than some new kind. `prime` is `confirm:true` because running a dry pump damages
it — disruptive, but not destructive enough for `agent:"deny"`. The user can
still ask Maya "water the plant now" and it will work.

**A small robot.** Movement, a voice, and a presence sensor.

```json
{
  "id": "esp32-robot-01", "proto": 2, "status": "online",
  "pin": "8890", "model": "maya_robot_v1", "fw": "0.3.1",
  "capabilities": [
    {"key":"drive",  "kind":"enum",    "label":"Drive", "options":["stop","forward","back","left","right"]},
    {"key":"speed",  "kind":"range",   "label":"Speed", "min":0, "max":100, "step":10, "unit":"%"},
    {"key":"head",   "kind":"range",   "label":"Head angle", "min":-90, "max":90, "unit":"deg"},
    {"key":"say",    "kind":"text",    "label":"Say", "max":120, "access":"w"},
    {"key":"eyes",   "kind":"color",   "label":"Eyes"},
    {"key":"near",   "kind":"number",  "label":"Obstacle", "unit":"cm", "access":"r"},
    {"key":"pos",    "kind":"location","label":"Position", "access":"r"},
    {"key":"dock",   "kind":"button",  "label":"Return to dock"},
    {"key":"stop",   "kind":"button",  "label":"Emergency stop"},
    {"key":"calib",  "kind":"button",  "label":"Calibrate", "agent":"deny"},
    {"key":"_batt",  "kind":"number",  "unit":"%", "access":"r"}
  ],
  "state": {"drive":"stop","speed":40,"head":0,"eyes":"#33CCFF","near":145,"_batt":62}
}
```

Two decisions here are worth copying:

- **`drive` is an `enum`, not a `vector`.** Discrete movement commands survive the
  ~100ms control-plane latency; live joystick driving does not (see the v2.1
  notes). An `enum` also hands Maya a list it cannot get wrong, so "Maya, move the
  robot forward" maps cleanly.
- **`stop` has no `agent` flag** — Maya *should* be able to trigger an emergency
  stop. `calib` is `agent:"deny"` because a mid-calibration robot is stuck until
  a human intervenes. The flags encode "what is safe for an agent to do", not
  "what is important".

### 5.7 Sensor-only devices

A device with **no writable capability at all** is a first-class citizen, not a
degenerate case. Plenty of useful hardware only ever reports: a salt jar that
weighs what is left, a soil probe in a field, a water tank level, a mailbox
sensor. The value is being able to check from somewhere else — knowing the salt
is nearly out *while you are already at the market*.

**A kitchen salt jar.** One number, and something to say about it.

```json
{
  "id": "esp32-saltjar-01", "proto": 2, "status": "online",
  "pin": "2201", "model": "jar_scale_v1", "fw": "1.1.0",
  "report_every": 900,
  "capabilities": [
    {"key":"weight", "kind":"number", "label":"Salt left", "unit":"g",
     "min":0, "max":1000, "access":"r", "history":true},
    {"key":"note",   "kind":"text",   "label":"Status", "access":"r"},
    {"key":"_batt",  "kind":"number", "unit":"%", "access":"r"}
  ],
  "state": {"weight":180, "note":"Running low — about a week left", "_batt":74}
}
```

Two things make this work as a glanceable card rather than a bare number:

- **Always give a read-only `number` a `min` and `max`.** With them the app can
  draw a gauge or progress bar — "Salt ▓▓▒▒▒▒ 180 g" reads at a glance on a phone
  in a shop. Without them all it can show is `180`, which means nothing unless you
  already know the jar's capacity.
- **`history:true`** turns "180 g" into a trend. Falling fast or flat since
  Tuesday are very different facts.

**The `note` pattern — let the device speak for itself.** A read-only `text`
capability is the device's own sentence about its state, composed in firmware.
This is where a contributor's creativity lives, and it costs the protocol
nothing:

```jsonc
// Firmware decides what to say. The server and app never parse this --
// it is shown to the human as-is, so anything goes.
{"key":"note", "kind":"text", "label":"Status", "access":"r"}

//   "Running low -- about a week left"
//   "Pokok sedih, tanah kering 3 hari"      <- a farm probe with personality
//   "Refilled! Back to full."
```

Because Maya sees capabilities as house context, a device's `note` also lands in
Maya's context for free — so "Maya, is the salt running out?" is answerable
without anyone writing a salt-specific tool.

**A farm soil probe.** Several sensors, still nothing writable.

```json
{
  "id": "esp32-field-07", "proto": 2, "status": "online",
  "pin": "7731", "model": "soil_probe_v2", "fw": "2.0.0",
  "report_every": 1800,
  "capabilities": [
    {"key":"moist", "kind":"number", "label":"Soil moisture", "unit":"%",
     "min":0, "max":100, "access":"r", "history":true},
    {"key":"temp",  "kind":"number", "label":"Soil temp", "unit":"C", "access":"r", "history":true},
    {"key":"ph",    "kind":"number", "label":"pH", "min":3, "max":10, "access":"r"},
    {"key":"mood",  "kind":"text",   "label":"How the plant feels", "access":"r"},
    {"key":"_batt", "kind":"number", "unit":"%", "access":"r"},
    {"key":"_rssi", "kind":"number", "unit":"dBm", "access":"r"}
  ],
  "state": {"moist":19, "temp":28.4, "ph":6.2, "mood":"Thirsty. No rain since Tuesday.", "_batt":58, "_rssi":-79}
}
```

**`report_every`** (seconds, top level, optional) is how often the device intends
to report. It exists so silence can be interpreted: a probe that promised every
30 minutes and has said nothing for three hours is a *problem*, while one that
promised every 30 minutes and reported 5 minutes ago is *fine*. Without it the
server cannot tell a sleeping device from a dead one — see §5.8.

The app SHOULD render a device whose capabilities are all `access:"r"` as a
readout card rather than a control card, and MUST NOT show it as broken merely
for having nothing to press.

### 5.8 Battery-powered devices that sleep

Both examples above are only realistic battery-powered — a salt jar is not near a
socket, and a field probe certainly is not. Such a device deep-sleeps and wakes
briefly to report, which breaks an assumption v2 inherits from v1: **that a
device holds a WebSocket open, and that an open socket is what "online" means.**
A probe reporting every 30 minutes would sit permanently `offline` under today's
`Device.status`.

#### Why sleeping is not optional

Measured against a plausible salt jar — ESP32 plus a load cell and HX711 on
3xAA (about 1760 mAh usable through a buck converter):

| Mode | Average draw | Life |
|---|---|---|
| WiFi held open, no sleep | ~110-135 mA | **~15 hours** |
| Deep sleep, report every 15 min | ~0.7 mA equiv. | ~3.5 months |
| Deep sleep, report every 30 min | ~0.4 mA equiv. | ~6 months |
| Deep sleep, report hourly | ~0.2 mA equiv. | **~1 year** |

A wake cycle — boot, join WiFi, report, sleep — is roughly 3-5 s at ~120 mA, so
about **0.17 mAh per wake**. The ESP32's radio dominates everything else; the
load cell is noise by comparison.

So a sensor-only device on batteries **cannot** hold a socket open. This is not a
preference, it is a factor of roughly 200.

Two hardware traps will silently destroy these numbers, and firmware authors MUST
be warned about both:

- **A DevKit board draws 5-20 mA even in deep sleep** — the onboard USB-serial
  chip and LDO never sleep. That alone is ~480 mAh/day: flat in four days. Use a
  bare module or a board designed for low power.
- **A load cell bridge draws continuously while powered** (~9 mA for a 350 ohm
  bridge, ~240 mAh/day). Power it down between reads via the HX711's power-down
  pin or a MOSFET, or the ESP32's sleeping makes no difference.

#### Three device classes

Whether a device may sleep follows from what it declares, so no new field is
needed to decide it:

| Class | Test | Connection | Command latency |
|---|---|---|---|
| **Always-on** | has a writable capability that must respond promptly | holds the WebSocket | ~100 ms |
| **Sleepy** | has a writable capability, but latency-tolerant, on batteries | wakes and polls a hub (§5.9) | up to one poll interval |
| **Sensor-only** | no writable capability **other than reserved `_` config keys** | wakes, reports, sleeps | n/a — the server never needs to reach it |

The dividing line is **not** whether a device sleeps — both of the last two do.
It is **whether the server ever has something to send down**:

- Always-on — you press it and expect it *now*. A relay channel, a lock, a pump.
- Sleepy — you set it and it happens *shortly*. An e-ink room label, a scheduled
  irrigation valve, a battery curtain motor.
- Sensor-only — you only ever *read* it. A salt jar, a field probe, a tank level.

Note the exception in the sensor-only test. Declaring `_report_every` (§5.8,
"Letting the user choose the interval") makes a capability writable, but it is
device configuration delivered on the check-in response, not something the server
must reach the device to do. **A device does not become sleepy merely by letting
the user adjust its reporting interval.** Reserved `_` keys never change a
device's class; only a functional capability does.

**A sensor-only device is the easy case and should be preferred**: because the
server never has to reach it, it has no reachability problem at all. The salt jar
and the field probe are both this class, even when their interval is adjustable.

Sleepy is the combination of the other two, not a third mechanism: the `pending`
queue from sensor-only check-in, carrying the `set` payloads of always-on. An
implementation can ship always-on and sensor-only first and add sleepy later
without redesigning either.

#### Check-in: the device pulls, the server never pushes

A sleeping device cannot be reached at all — see "Why the server can never simply
reach out" at the end of this section — so **anything the server wants to tell it
rides on the response to the device's own check-in.** A single HTTP request per
wake gets both directions:

```
POST /api/devices/{id}/report
  {"pin":"2201", "state":{"weight":180,"_batt":74}, "boot_id":"b-3f1", "seq":412}

200 OK
  {"ack":true, "report_every":1800, "pending":[{"type":"set","values":{"led":"on"}}]}
```

- `pending` is a queue the server has been holding since the last check-in.
  It MAY be empty, and usually is.
- `report_every` in the response is the **desired** interval. The device adopts it
  and uses it from the next sleep onward.
- HTTP is RECOMMENDED over a WebSocket session for this class: one request, no
  handshake, and the response is the downstream channel. A brief WS session is
  permitted and behaves identically, but pays the identify handshake on every
  wake for no benefit.
- The endpoint MUST enforce the same PIN and house checks as the WebSocket
  identify path. It is a second ingest route, not a second trust model.

**Config changes therefore take effect at the next check-in, not immediately.**
Moving a jar from hourly to 15-minutely applies within the hour. This is the same
bounded-latency property as commands, and the app should say so rather than
implying the change is instant.

#### Letting the user choose the interval

The reporting interval is a genuine user preference — battery life traded against
freshness — so it is exposed as a normal capability rather than a special case:

```json
{"key":"_report_every", "kind":"duration", "label":"Check in every",
 "min":900, "max":86400, "access":"rw"}
```

Declaring `_report_every` (a reserved key, §5.3) means "this interval is
adjustable". It renders with the existing duration picker, travels the existing
`set` path, and is delivered on the next check-in like any other queued command —
no new machinery anywhere.

- **The device sets `min` and `max`, and the server MUST clamp to them.** The
  firmware knows its own power budget; a user who could choose 10 seconds would
  flatten the battery in a day without understanding why.
- A device with a fixed interval simply does not declare the capability. The
  top-level `report_every` field still tells the server what to expect.
- The top-level `report_every` remains authoritative for liveness. A device that
  accepts a new interval MUST report the new value in its next descriptor, so the
  server is never judging silence against a stale expectation.
- The app SHOULD show the consequence next to the choice — "hourly, about a year"
  against "every 15 minutes, about 3 months". A device MAY declare `wake_mah` and
  `batt_mah` so the app can compute this instead of guessing.

#### What `status` now means

`status` MUST stop meaning "a socket is open" and start meaning **"reported
within its expected interval"**, with a tolerance of at least two missed
intervals before a device is called offline. A jar on an hourly schedule is
perfectly healthy having said nothing for 50 minutes.

This reaches `ConnectionManager`, the device list endpoint, and Maya's house
context — all three currently equate liveness with an open connection.

**The vocabulary.** Prose is not enough here: three call sites and the app have
to agree on the same words, so `status` is exactly one of four values, derived
and never stored as an opinion:

| `status` | Derivation | What it means to a person |
|---|---|---|
| `online` | A live socket, **or** a check-in within `report_every` | Here now |
| `asleep` | No socket, `report_every` declared, last report within `2 × report_every` | Fine — napping on schedule |
| `stale` | No socket, `report_every` declared, last report older than `2 × report_every` | Should have reported and has not |
| `offline` | No socket and no `report_every` declared | Should be connected and is not |

Two intervals of tolerance is the minimum, not a target: one missed wake is a
weak WiFi moment, not a fault.

- **`asleep` is healthy and MUST NOT be presented as a problem.** A jar on an
  hourly schedule that said nothing for 50 minutes is working perfectly, and an
  app that greys it out teaches the owner to ignore the only signal that matters.
- **`stale` is the one worth a person's attention** — flat battery, out of range,
  crashed between wakes. The app SHOULD show when it was last heard from, because
  "4 hours ago on an hourly schedule" and "4 hours ago on a daily one" are
  different situations.
- Maya MUST distinguish them in words. "The jar is asleep, it last reported 20
  minutes ago" is true; "the jar is offline" is not.
- A `set` to a device with no socket still answers `not_connected` immediately
  (§9) — except for a device with `report_every`, where the server queues it and
  answers that it is pending delivery at the next check-in. The caller is told
  which of the two happened; it is never left to assume.

#### Why the server can never simply reach out

Worth stating once, because it is the constraint every option above is shaped by:
an ESP32 sits on a private address behind the home router's NAT. The server has
no route to it. Every server-to-device message in this protocol travels down a
connection **the device opened** — which is exactly what `ConnectionManager`
does, keyed by the socket the device dialled in on.

NAT traversal does not rescue this. STUN or hole punching still needs the device
to send outbound first and to keep the mapping alive; UPnP may open a port but
nothing answers it while the CPU is asleep; IPv6 removes NAT but not sleep, and
home routers firewall inbound IPv6 by default anyway. Cellular NB-IoT does solve
it properly — the network pages the device and it has scheduled wake windows —
but that is a modem and a SIM, not WiFi.

There is no protocol that avoids the rule: **something must hold an outbound
connection, or the device is unreachable until it wakes.**

---

### 5.9 Hubs, and how a battery device actually reaches the server

A **hub** is any mains-powered device that holds the WebSocket to the server and
relays for battery devices over ESP-NOW. A house with a hub gets roughly three
times the battery life on its sensors and makes the sleepy class viable at all;
a house without one still works, more slowly. **A hub is an optimisation, never a
requirement** — every device MUST function without one.

#### The asymmetry everything here follows from

**Transmitting is cheap. Receiving is expensive.** The cost of a wake cycle is
almost entirely connection setup, not the payload:

| Step | WiFi + HTTPS | ESP-NOW |
|---|---|---|
| Boot | ~250 ms | ~250 ms |
| Associate + DHCP | 1-3 s | — |
| TLS handshake | 1-2 s | — |
| Send (+ reply) | ~200 ms | ~5-20 ms |
| **Per wake** | **~3-5 s, ~0.17 mAh** | **~0.3-0.4 s, ~0.012 mAh** |

ESP-NOW is connectionless: no association, no DHCP, no TLS. That is the whole of
its advantage, and it applies **only to devices that wake, transmit, and sleep.**

A device that stays awake to *receive* must keep its radio on, which costs
~90 mA — no better than holding a WiFi connection. On 3xAA (~1760 mAh usable)
that is **about 19 hours**. ESP32 connectionless power save (a periodic wake
window) softens this to days, not months. Firmware MUST NOT idle-listen for
ESP-NOW on batteries:

| Receive strategy | Average draw | 3xAA life |
|---|---|---|
| Idle RX, always listening | ~90 mA | **~19 hours** |
| Wake window, ~10% duty | ~10 mA | ~7 days |
| Wake window, ~2% duty | ~3 mA | ~24 days |
| Scheduled wake, poll, sleep | ~0.06 mA | **~1-3 years** |

This is why hubs are mains-powered and battery devices always *ask* rather than
*wait*.

#### Sensor-only: ESP-NOW primary, WiFi fallback

A sensor-only device SHOULD prefer a hub and fall back to the §5.8 HTTP check-in:

| Path | Per wake | Hourly | 3xAA life |
|---|---|---|---|
| ESP-NOW to hub | ~0.012 mAh | ~1.5 mAh/day | **~3 years** |
| WiFi + HTTPS report | ~0.17 mAh | ~5.3 mAh/day | ~1 year |

On the hub path most of the daily budget is deep-sleep leakage rather than
reporting, so the saving is better spent on **freshness** than on lifetime:
ESP-NOW every 5 minutes costs about the same as WiFi once an hour — twelve times
the resolution for the same battery.

Rules:

1. **Detect hub failure from the ESP-NOW send callback.** The MAC layer reports
   whether the frame was acknowledged, so a dead hub is known immediately with no
   timeout to pay for.
2. **Fall back after 3 consecutive failures**, not one. A single miss is
   interference, not an outage.
3. **Say why.** The first fallback report MUST include
   `{"hub_failed":"<hub device id>"}` so the server can tell the user to check
   the hub. A hub that dies quietly would otherwise look like sensors gradually
   going flat.
4. **Buffer if both paths fail.** Keep readings in the bounded ring buffer of
   §7.3 with their `ts`, and flush when either path returns. Never discard a
   reading because the network was down.
5. Retry the hub periodically while on the fallback path, and return to it when
   it answers.

Degrading from hub to WiFi costs roughly a year of battery instead of three. That
is an acceptable loss for a fault that announces itself.

#### Sleepy: poll the hub

A sleepy device has something to receive, so it wakes, **asks** the hub for
anything queued, acts, and sleeps. It never waits:

```
wake -> ESP-NOW to hub: "anything for me?"
     -> hub answers immediately from its queue
     -> act -> sleep
```

This is the §5.8 `pending` queue with ESP-NOW as the transport instead of HTTP —
not a third mechanism. A poll costs slightly more than a bare send (~0.015 mAh)
because the radio stays on briefly for the reply.

| Poll interval | Per day | 3xAA life | Command latency |
|---|---|---|---|
| 30 s | ~44 mAh | ~6 weeks | 30 s |
| 1 min | ~23 mAh | ~2.5 months | 1 min |
| **5 min** | **~5.5 mAh** | **~1 year** | **5 min** |
| 15 min | ~2.6 mAh | ~1.8 years | 15 min |

**Sleepy is a hub-only class.** Polling the same way over WiFi costs ~0.17 mAh a
poll — about 36 days at a 5-minute interval, which is not a product. So unlike
sensor-only, a sleepy device has no useful WiFi fallback: when its hub is gone it
SHOULD fall back to running its own stored schedule locally and reporting once a
day, not to polling over WiFi.

**A sleepy device can never respond immediately.** Nothing safety-critical — a
door lock, an alarm, a heater cut-off — may be a sleepy capability. If it must
happen now, it is always-on and it is mains-powered.

#### What a hub must do

- Be mains-powered, and hold the WebSocket as an always-on device (§5.8).
- Keep a per-peer queue of `pending` commands and hand them over on contact.
- Relay peer state reports upward, attributed to the **origin** device id, not
  its own.
- Authenticate every local frame with the peering grant key of §7.2 — at the
  application layer, not by relying on ESP-NOW's own encryption, whose encrypted
  peer count is capped well below the 20-peer ceiling and would otherwise limit
  how many probes a farm could run.
- Report its current WiFi channel to the server (below).

A hub is a single point of failure for the devices that depend on it, which is
why rule 3 above exists and why every device keeps a working path without one.

#### Channel discovery

ESP-NOW requires both ends on the same WiFi channel, and a home router that
picks its channel automatically will move without warning — silently breaking
every pairing in the house.

- A battery device SHOULD associate to WiFi at provisioning and on a slow
  schedule (daily is enough) to learn the current channel and refresh its status,
  then switch the radio off and keep only its stored credentials.
- A hub MUST report its channel to the server whenever it changes, so the server
  can hand it to peers on their next contact.
- A device that fails to reach its hub MUST consider a channel change among the
  causes and rescan before concluding the hub is dead.

#### Range

Range is measured to the **hub**, not to the router. This can be better than WiFi
association — ESP-NOW reaches hundreds of metres line-of-sight at low rates,
which suits a field probe — or worse, if the hub sits in a cupboard. Hub
placement is a real deployment decision, not an afterthought.

### 5.10 Permissions: who may address a capability

§5.1 calls `key` "the permission key" and §1 rule 5 makes the server the
authority on permission, but nothing so far says what a permission *is*. It is
this:

**A grant is a row per (child, device, capability key), and it governs writing.**

The unit is the key because the key is the only stable identifier a device
promises never to renumber. Two things follow that are worth stating, because the
obvious alternatives are both wrong:

- **Not per `group`.** `group` is free text a firmware build chooses, so a grant
  stored against it would change meaning on a firmware update — a child granted
  "Lights" could silently acquire whatever the next build decided to call
  lights. The app MAY offer "grant the whole group" as a convenience; what it
  stores is still one row per key.
- **Not per device.** "This child may use the fan" is not the same as "this child
  may set the fan's `reset` button".

#### Defaults, and what happens when a descriptor changes

- **A capability the server has not seen before is denied to every child.** A
  firmware update MUST NOT be able to widen what a child can reach. The parent
  grants it, or it stays shut.
- **Adults are not gated per capability.** Any adult member of the house may
  address any capability of any device in it, as today. A second adult tier is a
  real question — it is the same question as who may see a child's location — but
  it is a *role* design, not a capability one, and inventing half of it here
  would produce two half-models.
- **When a capability leaves the descriptor, its grants are deleted with it**,
  exactly as its stored state is. If the key comes back in a later build it comes
  back denied. §5.1 makes "never renumber a key" a firmware MUST; this is the
  server's protection against firmware that breaks it, and it fails in the safe
  direction.

#### Reading is house-wide; only writing is granted

A child who may not switch the heater may still see that it is on.

This is deliberate. Hiding state produces an app that lies by omission, and it
protects nothing: the child is standing in the room with the heater. The
exception needs no rule — `access:"w"` has no state to read, so for a write-only
capability the grant is the only gate there is.

If a capability ever genuinely needs a hidden value, that is a new **field**, not
a change to this rule (§5.1: kinds are expensive, fields are free).

#### How it composes with the other two gates

Three independent checks, all of which must pass, and none of which substitutes
for another:

| Gate | Asks | Defined in |
|---|---|---|
| `agent` | May a model address this at all? | §5.4 |
| `confirm` | Has a human just said yes? | §5.4 |
| Grant | Is this child allowed to write this key? | here |

Maya acting for a child needs all three: the capability not denied to agents, a
confirmation if the capability asks for one, and the child's own grant. That is
the shape the server already has for relay channels — the permission is checked
in the tool implementation, not described to the model — and §5.4 is explicit
that this must not regress into prompt instructions.

**Migration.** Existing per-relay permissions map one-to-one onto keys `ch1`,
`ch2`, `ch3` of the relay's device, which is a mechanical conversion and should
be done as one, with the old table dropped in the same change rather than left as
a second source of truth.

### 5.11 Labels: who owns a capability's name

§5.1 says a house member may rename a capability and that their name wins over
the firmware's. Spelling that out, because precedence is the whole of it:

**House name, else the firmware's `label`, else the `key`.**

- The house name is stored per `(device, key)` on the server and set by a member
  with the right to manage devices — the same right that renames a channel today.
- **A firmware update MUST NOT overwrite it.** Someone named that socket
  "Television" on purpose; a new build is not a reason to call it "Channel 1"
  again. This is the one place where the descriptor is *not* the authority, and
  the reason is that the name is the only part of a capability that belongs to
  the household rather than to the hardware.
- Clearing the house name falls back to the firmware's label. There is no third
  state and no "reset to default" flag — clearing *is* the reset.
- Renaming never touches the key. Grants and history survive a rename, which is
  the point of keeping them keyed on `key`.
- **Migration.** Existing `Relay.name` values become the house names for `ch1`,
  `ch2` and `ch3`. Until step 2, a server MAY read them through directly; after
  it, they are ordinary label rows.

### 5.12 History: what `history:true` costs

§5.1 lets a capability ask the server to retain a time series, and §5.7 leans on
it — "falling fast" and "flat since Tuesday" are the two facts that make a salt
jar worth having. What it never said is what the server promises, which left the
flag meaning nothing in particular.

The constraint is concrete and should be stated before the rules: one SQLite file
on one small instance. A 1 Hz sensor stored naively is about 2.6 million rows a
month, so retention is bounded in three ways at once.

**Sampling — on change, at most one point per minute.** No point is written when
the value has not changed. A series is therefore a list of changes, not a tick
log.

**The gap rule, which is what makes that safe to draw:**

- A gap shorter than `2 × report_every` (or, for a socket device, than two missed
  heartbeats) means *nothing changed*. The app draws it as a flat segment, which
  is the truth.
- A longer gap means *the device was not reporting*. The app MUST draw a break,
  not a flat line. A flat line through an outage is a graph that invents data,
  and it is exactly how someone concludes a tank was full all weekend when the
  sensor was dead.

**Retention — 30 days, and at most 5,000 points per capability**, oldest dropped
first, trimmed on a daily sweep. A chattering device loses its own old data and
nobody else's.

**Reading** — `GET` by device and key with a `since`, returning `[[ts, value], …]`
oldest first, at most 1,000 points, **decimated server-side** when the window
holds more. A sparkline cannot show more than that and a phone should not parse
it.

Only `number` and `range` can carry history (§5.1). On any other kind the flag is
ignored rather than refused — a device that sets it on a `switch` is confused, not
broken.

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

**Pressing a button.** A `button` has no state, so there is no value to send and
none to read back: the press is `null`.

```json
{"id":"esp32-...", "type":"set", "req":"c-9", "values":{"horn":null}}
```

The ack omits the button from its `state` — there is nothing to report — and a
device MUST NOT invent one. A button in a *state* report is ignored (§6.1).

**When part of a multi-key set fails.** The device stops at the first failure and
says exactly what happened:

```json
{"id":"esp32-...", "type":"ack", "req":"c-9", "status":"bad_value",
 "failed":"speed", "state":{"ch1":"on"}}
```

- `status` is the failing capability's error code (§9), `failed` names it, and
  `state` carries **what did apply before the failure** — here `ch1` went on and
  `speed` was refused.
- **There is no rollback.** A device cannot generally un-ring a bell or un-open a
  valve, and a protocol that pretended otherwise would have devices lying about
  physical state. Reporting precisely how far it got is more useful than a clean
  story that is false.
- A caller that needs all-or-nothing must ask for one capability at a time. The
  atomic case is a hardware property, not a promise this protocol can make.

**One command at a time per device.** The server MUST NOT have two commands
outstanding to the same device: it sends, waits for the ack or the 5 s timeout,
then sends the next. `req` is therefore a cross-check that an ack belongs to the
command being awaited, not a multiplexing key — a library author should not build
pipelining against it, and a device need keep only one `req` in memory.

---

## 7. Device to device

This section defines the local link itself. Its largest user is the hub relay of
§5.9 — a battery device pairing with a hub is an ordinary peering, and the frames
it sends are ordinary local frames. Read §5.9 for *why* a device would use this;
read here for *how* it is secured and shaped.

Three planes meet here, and each rule below belongs to exactly one of them:
**who may peer** is decided on the control plane (§7.1, the server); **what a
frame looks like and whether to believe it** is the data plane (§7.2, the
devices); **what happened** is the audit plane (§7.3, the devices reporting back
to the server).

### 7.1 Pairing (control plane — this is the enforcement point)

A house member pairs two devices in the app. The server then pushes a grant to
**both** devices:

```json
{"id":"esp32-a", "type":"peer_grant", "grant_id":"g-42", "role":"send",
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

#### Who may pair, and what may be granted

Added in revision 2.2; the first draft of this section said what a device does
with a grant and nothing about who may create one.

- **Only a house master, or a member the master has authorised to manage
  devices** (the same right that lets them claim a device, §4.1). Never a child.
  Both devices MUST belong to that member's house and be unblocked.
- **A grant is one-way.** It says *sender* may address *receiver*. The frame each
  device is pushed carries `role`: `"send"` to the device that may transmit and
  `"recv"` to the one that accepts. `scope` always names **the receiver's**
  capability keys, and only the receiver enforces it. Two devices that should talk
  both ways need two grants, because "A may press B's reset" must never come
  free with "B may report to A".
- **Scope is explicit and finite.** Each key MUST be a capability the receiver
  currently declares, writable (`access` `rw` or `w`), and not a reserved `_`
  key. A capability the receiver gains later is **not** in any existing scope —
  the same default-denied rule as §5.10, for the same reason: a firmware update
  must never widen what a peer can reach. A key the receiver later drops stops
  being honoured immediately: the receiver receives its scope afresh at every
  identify and MUST intersect it with what it currently declares.
- **A capability declared `confirm:true` or `agent:"deny"` cannot be in a peer
  scope; the server refuses.** Both mean "a person, or at least not an
  automaton, stands between the request and the action" (§5.4). A peer is
  precisely an automaton with no person present, so allowing it would be a way
  around the control the firmware author asked for. The restriction can be
  relaxed later without breaking anything; tightening it later could not.
- **Re-pairing replaces.** Creating a grant for a (sender, receiver) pair that
  already has an active one revokes the old and issues a new `grant_id` and a new
  key. That is how a key is rotated and a scope changed — there is no edit.

#### The key, and where it lives

`key` is 32 random bytes, generated by the server, standard base64. The server
keeps it (it must re-send it to a device that reconnects) and **never returns it
to an app or any API caller**: the key is only ever sent down a device's own
authenticated WebSocket. It is shared by both ends of one grant and by nobody
else.

`expires` is set by the server, ISO 8601 UTC, **default 30 days, at most 365**. An
expired grant is absent (rule 4) and the server stops pushing it. Re-pairing
renews.

#### Identify carries a MAC

A device that wants to be paired MUST include `"mac":"AA:BB:CC:DD:EE:FF"` — its
WiFi station MAC, upper-case hex — in its identify frame. This is an optional
field (§1 rule 4), so no existing device changes, but the server **refuses to
pair a device whose MAC it does not know**, because the peer's `mac` in the frame
above is what a receiver matches the radio-level source address against (§7.2).

#### Staying in step: a revoke can be missed

A device that is offline when a grant is revoked never receives `peer_revoke`.
So at every identify of a protocol-2 device, after `welcome`, the server sends
one `peer_grant` per active grant that involves it and then a single

```json
{"id":"esp32-a", "type":"peer_sync", "grants":["g-42","g-57"]}
```

listing **every** active grant id for that device, possibly empty. A device MUST
drop any grant it holds that is not in the list. This closes the stale-grant
window of §7.4 at the next reconnect rather than leaving it to `expires`.

### 7.2 Local frame (data plane)

A local frame is a JSON object followed by a dot and a MAC:

```
{"v":2,"from":"esp32-a","grant":"g-42","ep":7,"seq":118,"kind":"set","values":{"speed":60}}.<mac>
```

- **The MAC is HMAC-SHA256 over the exact bytes of the JSON text** (everything
  before the final `.`), keyed with the grant `key`, **truncated to 16 bytes and
  encoded as 22 base64url characters, no padding.** Signing the bytes as sent,
  rather than a re-serialisation, means two implementations can never disagree
  about field order or number formatting — the usual way a MAC check starts
  failing between two firmware versions.
- **A receiver verifies before it believes anything.** It reads `grant` from the
  not-yet-trusted JSON only to find which key to try, checks the MAC, and only
  then looks at `from`, `kind` or `values`. It then also checks that `from` is
  the grant's sender and that the radio-level source MAC matches the peer's `mac`.
  The last check is cheap and spoofable; it is a tripwire, not the defence — the
  MAC is the defence.
- **A frame MUST fit one ESP-NOW payload: 250 bytes including the MAC.** A sender
  that cannot fit a frame refuses to send it and reports `unsupported` locally; it
  does not fragment. `kind:"msg"` payloads are bounded by this, deliberately.
- **Ordering is `(ep, seq)`.** `ep` ("epoch") is a counter the sender persists
  and increments on every boot; `seq` counts frames per (sender, grant) from 1
  within an epoch. A receiver MUST reject any frame whose `(ep, seq)` is not
  greater than the last accepted for that grant. Because `ep` survives reboots, a
  restarted sender is *newer* rather than a replay — the first draft keyed on
  `seq` alone, which made every reboot indistinguishable from an attack.
- **Residual window, stated rather than hidden.** A receiver keeps `seq` in RAM
  and `ep` in flash. After the receiver reboots it accepts the next frame of the
  stored epoch regardless of `seq`, so an attacker who captured traffic could
  replay **one** frame per receiver reboot. This is bounded by `expires`, by
  revocation, and by the capture needing to be within radio range; devices whose
  `set` is not idempotent should say so in their own design.
- `kind` is `set`, `event`, or `msg` (free payload for device-defined chatter).
  A `set` applies the same value rules as §6.2 and is answered with a local
  `kind:"ack"` frame carrying `status` as in §9. There is **no timestamp**: a
  battery device has no clock worth trusting, and ordering is `(ep, seq)`.
- Frames MUST be authenticated. An unauthenticated frame is dropped, not
  processed — and not answered, so a probe learns nothing.

### 7.3 Audit (audit plane)

Local activity is reported to the server **batched, best-effort, and bounded**.
**Both ends report**, because the value of the audit is comparing them:

```json
{"id":"esp32-a", "type":"peer_log", "boot_id":"b-9f3", "dropped":0, "batch":[
  {"grant":"g-42","dir":"out","ep":7,"seq":118,"count":1,"kind":"set","peer":"esp32-b","summary":"speed=60","result":"ok"},
  {"grant":"g-42","dir":"out","ep":7,"seq":119,"count":1,"kind":"set","peer":"esp32-b","result":"not_permitted"}
]}
```

- `dir` is `out` (this device sent) or `in` (this device received). `seq` is the
  **highest** sequence number the entry covers and `count` how many frames it
  stands for (default 1), so an aggregated entry says "frames 200-262, 63 of them".
- **Buffer when offline.** A bounded ring buffer (RECOMMENDED at least 64
  entries) that flushes on reconnect. Without this, visibility disappears exactly
  when the network is broken — which is when it matters most.
- **On overflow, drop oldest and set `"dropped":<n>`** on the next batch. The
  server records a gap. Never let logging block or fail the local data path.
- **Do not log every frame at high rate.** A device exchanging frames faster than
  about 1 Hz MUST aggregate (`count`, last `seq`, last value) rather than emit
  one entry per frame.
- Flush at most every 10 s, or immediately for a `result` other than `ok`.
- **At most 64 entries per frame.** A longer batch is truncated by the server and
  counted as dropped.

Because `seq` is monotonic within an epoch, the server can say "device A claims
118 frames sent on this grant, device B logged 9 received" — silence on either
side is visible as a gap rather than looking like inactivity.

**What the server keeps.** Per (grant, reporter, `dir`, `ep`): the highest `seq`
claimed and the sum of `count` logged; per reporter, the total of `dropped`. The
**unexplained gap** for a side is `claimed − logged`; the reporter's `dropped`
total is shown beside it as the most that buffer overflow could account for —
`dropped` is a property of the batch, not of a grant, because an entry that was
dropped took its grant with it. The server also lines the two ends up per epoch:
the sender's highest claimed `seq` against what the receiver logged. That
difference, minus whatever `dropped` can explain, is a frame that was sent and
never arrived or never admitted. The server
accepts a `peer_log` entry only from a device that is a party to the grant it
names, and ignores the rest. Entries are retained per house up to 5,000, oldest
first out — a device must not be able to fill the database. A device's log rate
is limited like any other frame.

### 7.4 Revocation

Revoking a pairing removes it server-side immediately and pushes
`{"type":"peer_revoke","grant_id":"g-42"}` to both devices. A device that is
offline keeps operating on the stale grant until it reconnects, at which point
`peer_sync` (§7.1) corrects it — an accepted window, and the reason grants carry
`expires`. Keep expiry short (days, not years) for anything sensitive.

Removing a device from a house, or a `factory_reset`, revokes every grant that
involves it.

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

A failing ack MAY carry `failed` — the capability key the status refers to — and
`state` for whatever did apply before it stopped (§6.2). Both are optional
additions to the ack shape and are the only wire change in document revision 2.1.

**An error ack is still an ack.** A server MUST match it to the outstanding
command and answer the caller with it. Letting a failure fall through to the 5 s
timeout turns a precise answer that already arrived into a vague one that did
not.

Server-side outcomes on the control plane: `not_connected` when the device has no
live socket, `timeout` when no ack arrives within 5 s, and `pending` when the
device declares `report_every` and the command was queued for its next check-in
(§5.8). A caller is always told which of the three it got, never left to assume
that silence meant delivery.

---

## 10. Compatibility matrix

| Device \ Server | Server v1 | Server v2 |
|---|---|---|
| **Firmware v1** | works (today) | works — server shims a 3-switch descriptor |
| **Firmware v2** | works — v2 device must still accept v1 command names (§4) | full v2 |

Migration order matters. Build it in this sequence, because each step is useful
on its own and none of them breaks what is already deployed:

1. Server accepts and stores descriptors; shims protocol 1. Nothing else changes.
   — **done 2026-10-10** (`descriptor.py`, `capability_store.py`, the
   `device_capabilities` + `capability_state` tables, and two endpoints;
   `test_descriptor.py` plays both a v1 and a v2 device against the real app).
2. App renders from the descriptor instead of three hardcoded toggles. This is
   where §5.10 (permissions), §5.11 (labels) and §4.1 (claiming creates nothing
   but the device) land: the app cannot render from the descriptor while the
   permission model, the names and the claim shape all still assume three
   relays. The old per-relay permission table and `Relay.name` are converted in
   the same change, not left beside the new ones.
   — **server half done 2026-10-10** (§4.1, §5.10, §5.11, with the per-relay
   permissions migrated onto capability keys and the old table dropped;
   `/api/permissions` kept as a translating facade over the same store).
   **App: the device list and the permission sheet are descriptor-driven; the
   home summary and device-management screens still read the v1 shapes**, which
   keep working through the shim. The Dart was not compiled — no Flutter SDK on
   the machine it was written on.
3. Maya swaps its six fixed tools for a generic `set_capability`, driven by the
   descriptors already in its house context — filtering `agent:"deny"` and
   honouring `confirm` (§5.4) **in the same change**, not as a follow-up.
   — **done 2026-10-10.** Only one of the six (`control_device`) was a relay tool
   and it is the one replaced; the other five are child-data and activity tools
   with nothing to do with capabilities, so "six fixed tools" above overstates
   the change. Both gates are enforced in code and tested against a model
   scripted to misbehave (`test_maya.py`). `confirm` is honoured only for the
   same value, in a later turn than the ask, within five minutes — a
   model-supplied `confirmed:true` is not evidence by itself.
4. **Extract the Arduino library** — by now it only has to implement a written
   protocol, so it is thin and stable.
   — **done 2026-10-10** (`hardware/libraries/Maya`). Two halves, split on
   purpose: `MayaCore` is the protocol with no hardware in it (descriptor,
   `set`/ack/state frames, the §9 errors, the legacy command names), and `Maya`
   is the radio half (BLE provisioning, WiFi, the WebSocket) moved from
   `smartextension.ino` unchanged in behaviour. The split is what makes the
   claim "it implements this document" checkable: `extras/test/test_library.py`
   builds the core on a laptop and has the **server's own** `parse_identify` and
   value rules judge what it says, then runs it against the real app. The
   radio half compiles for ESP32 (core 2.0.17) but **has not been flashed to a
   board**. Not covered yet: peering (§7), device→Maya (§8), `report_every`
   (§5.8).
5. Peering: grants, local link, audit.
   — **spec done 2026-10-10** (revision 2.2, §7). **5a, the server half, done
   the same day** (`peering.py`, `/api/peerings`, `peer_sync`, `peer_log`
   ingest; `test_peering.py`). **5b, the library's side of the link, and the
   ESP-NOW radio itself, are not built**, and the radio cannot be tested
   without two boards.
6. Device to Maya.

Two pieces of this document sit outside that order because they depend on it
rather than on each other: **§5.12 (history)** needs step 2 to have somewhere to
draw a sparkline, and **§12 (the public API v2)** needs step 2's descriptor
surface to expose. Neither blocks anything; both are worth doing before the
first outside integration, because a frozen v1 is only kind to third parties if
there is a v2 to move to.

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

**Revisions of this document**, as distinct from the protocol version: a
clarification or a new section bumps the revision in the header (2.0 → 2.1) and
leaves `proto` alone, because nothing on the wire changed. A new optional field
does the same. Only a rename, a removed field or changed semantics bumps `proto`
and earns a row in §10's matrix. A new entry in the reserved-key table (§5.3) or
the kinds table (§5.2) is a revision on the wire but a change in the app, so it
MUST be planned with the server and app alongside it — those two tables are the
places where "free" stops being free.

---

## 12. The public API surface

Everything above describes the device link. A third party reaches the house
through a house-scoped API key instead, and self-describing devices change what
that API can be: it can no longer be a list of three channels.

**`/api/open/v1/*` is frozen, not deprecated.** It lists devices and switches
channels, and it keeps working through the shim — `ch1`-`ch3` are ordinary
capability keys, so a 3-channel extension answers v1 forever. Nothing is removed;
a working integration in someone else's script is not ours to break.

**`/api/open/v2/*` is the capability surface.** `GET /devices` returns
descriptors and state as §5 defines them, and a single `POST /devices/{id}/set`
takes `values`, with the same validation and the same ack statuses as §6.2. There
is no v2 endpoint per capability kind: the whole point is that a kind is data, not
a route.

A v2 key reaching a v1-only concept, or the reverse, is not a special case —
both speak capabilities underneath.

### 12.1 Scoping a key

A key today grants read and command rights over **every device in its house**.
That is too much for "let my dashboard read the tank level", and it is the open
half of a recorded security finding, so:

- A key MAY be scoped to a list of devices and a list of capability keys. The
  default for a key issued without a scope is the whole house, which is what
  already-issued keys must keep meaning.
- New keys SHOULD be scoped at creation, and the issuing UI SHOULD default to
  read-only.
- Scope is checked on the server, per request, against the descriptor — not
  recorded in the key and trusted. A capability that leaves a device's descriptor
  is unreachable through any key, whatever its scope says.
- **`confirm:true` capabilities are refused on this surface entirely** (§5.4): a
  key is not a person, and no flag can make it one.
- Rate limits are a separate concern and already apply per key.

### 12.2 What a key may never reach

Stated as a list because it is easier to audit than prose, and because the
temptation to add "just one" convenience endpoint here is permanent:

- Anything about children — location, screen time, homework, chat. An integration
  has no business with them, and the surface that cannot reach them cannot leak
  them.
- Pairing and grants (§7): peering two devices is a household decision made by a
  person in the app.
- `factory_reset`, `reboot`, and the provisioning path. A key that can wipe a
  device can erase the house's own hardware.
- House membership, PINs, and other keys.

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

**What step 1 actually did (2026-10-10):** took that advice — `capability_state`
holds typed values as JSON text and `Relay` was left alone. None of the 76
`ch1`/`ch2`/`ch3` sites were removed; every device report now writes *both*
representations, which is what let the server move without the app, the firmware
or Maya changing in the same commit. Removing the duplication is step 2's work.
