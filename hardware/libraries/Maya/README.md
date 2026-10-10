# Maya — the Arduino library

Make an ESP32 board a Maya device. You say what the hardware can do; the library
speaks [the Maya Device Protocol v2](../../../PROTOCOL.md) for you — BLE
provisioning, WiFi, the server link, the capability descriptor, and the answers
to `set` — and the app and Maya draw and control it **without anyone editing
`software/`**.

```cpp
#include <Maya.h>

Maya maya("my_lamp", "1.0.0");

void setup() {
  maya.addSwitch("lamp", "Lamp", [](bool on) { digitalWrite(2, on); return true; });
  maya.addRange("dim", "Brightness", 0, 255, 5, [](double v) { dacWrite(25, (uint8_t)v); return true; });
  maya.addNumber("temp", "Temperature").unit("C").history();   // a sensor: no handler
  maya.begin();
}

void loop() {
  maya.loop();
  maya.setNumber("temp", readTemperature());   // unchanged values are not re-sent
}
```

Flash it, provision it from the app, and the three controls appear. Two complete
sketches are in `examples/`: `MinimalSensor` (the one to copy) and
`SmartExtension3ch` (the existing 3-relay board, on the library).

## Install

Copy this folder to your Arduino libraries folder (`Documents/Arduino/libraries/Maya`),
or point arduino-cli at it with `--library hardware/libraries/Maya`. It needs
**ArduinoJson 6.x** and **WebSockets (links2004) 2.4+**.

**Choose the "Huge APP" partition scheme** (`PartitionScheme=huge_app`). BLE plus
TLS plus WiFi is about 1.7 MB, which does not fit the default 1.2 MB app
partition; the build stops with "Sketch too big". The existing firmware has the
same requirement.

Built and tested against `esp32:esp32` core **2.0.17**. Core 3.x should work but
has not been built.

## Declaring capabilities

| Call | Kind | Handler gets |
|---|---|---|
| `addSwitch(key, label, fn(bool))` | `switch` | on/off |
| `addRange(key, label, min, max, step, fn(double))` | `range` | the number |
| `addNumber(key, label[, fn(double)])` | `number` | the number (read-only without `fn`) |
| `addText(key, label, maxChars[, fn(const char*)])` | `text` | the string |
| `addEnum(key, label, options, n[, fn(const char*)])` | `enum` | one of `options` |
| `addButton(key, label, fn())` | `button` | nothing |
| `addColor(key, label[, fn(const char*)])` | `color` | `"#rrggbb"` |
| `addTime(key, label[, fn(const char*)])` | `time` | `"HH:MM"` |
| `addDuration(key, label, maxSeconds[, fn(double)])` | `duration` | seconds |
| `addLocation(key, label)` | `location` | — (report with `setLocation`) |

A handler returns `true` when the hardware did what was asked. `false` answers
`bad_value`. The library has already checked the value against what you declared
(range limits, enum options, text length, colour and time format), so a handler
only sees values it can act on.

Chain modifiers off any of them: `.unit("C")`, `.group("Kitchen")`,
`.readOnly()`, `.writeOnly()`, `.history()`, `.limits(lo, hi)`,
**`.confirm()`** (Maya must ask the user first) and **`.agentDeny()`** (Maya
never sees it). Put `.agentDeny()` on anything destructive — a factory reset, a
valve that floods a room. The app still shows it; Maya cannot reach it, and the
server refuses even if a model names it anyway.

`maya.enableHealth()` adds signal strength, uptime and firmware version to the
device card. Report `_batt` yourself with `maya.addReserved("_batt")` and
`setNumber("_batt", pct)`. Nothing else starting with `_` is allowed; that
namespace belongs to the protocol.

## Talking to another device (the local link)

A person pairs two devices in the app — "this one may address that one, and only
these controls" — and the server pushes a key to both. From then on the sender can
act on the receiver directly over ESP-NOW, with no round trip through the server:

```cpp
maya.peerSetNumber("esp32-9f83b1c1", "fan", 60);   // false: no grant, expired, outside scope, or too big
maya.onPeerAck([](const char* peer, const char* status, const char* failed) { ... });
```

The receiving side needs no code: a peer's `set` goes through the same handlers
as one from the app, limited to the grant's scope. `examples/PeerButton` is a
button that drives a fan this way.

What the library does for you: checks every frame's HMAC before reading it,
refuses replays, enforces the scope — and refuses anything `confirm()`,
`agentDeny()`, reserved or read-only *even if a scope names it* — and reports what
the link did to the server, so the app can show where the two ends disagree. A
forged frame is dropped without a reply and without a log line.

Things to know: frames are limited to 250 bytes and are never fragmented; the
device must hear the time from SNTP for a grant to expire, and without it a grant
lasts until it is revoked; a frame can only reach a peer on the same WiFi channel,
which a device in station mode on the same router is.

## Reporting

`setSwitch`, `setNumber`, `setText`, `setLocation` tell the library what the
hardware now reads. A changed value goes out within 250 ms; an unchanged one is
never re-sent, so calling them every `loop()` is fine. Each returns `false` for an
unknown key or the wrong kind rather than guessing.

## Rules worth knowing

- **Keys are permanent.** `[a-z0-9_]`, 1–24 characters. The key is what a parent's
  permission and a sensor's history are filed under; renaming it orphans both.
- **Pass string literals** for keys, labels, units and option lists. The library
  keeps the pointers.
- **Handlers run in `loop()`**, inside `maya.loop()`. Keep them short; do not
  `delay()` for seconds.
- **At most 32 capabilities and 4 KB of descriptor.** A declaration the server
  would reject is refused here instead, and `begin()` prints why on Serial.
- **`maya` is free as a variable name:** the library's namespace is
  `mayalib`, deliberately, so the obvious name does not collide.
- Every flash starts clean: the library wipes saved WiFi and PIN when the sketch
  changes, and the first owner sets a PIN (4 digits, not `0000`/`1111`/`1234`).
  Same rule as the original firmware, kept on purpose.

## Testing without a board

`extras/test/` builds the protocol core on a laptop and checks it against the
**real server**:

```
python extras/test/test_library.py      # the protocol core against the real server
python extras/test/test_peer_link.py    # the local link
```

It declares a 16-capability device, runs it through the server's own
`parse_identify`, plays every kind of `set` (including a refused one, a partial
failure and a button press), and then connects the same code to the real app
over a WebSocket. It needs a C++ compiler (`g++`, or `pip install ziglang`),
ArduinoJson's headers (`ARDUINOJSON_DIR`), and the server's test dependencies
(`fastapi`, `sqlalchemy`, `httpx<0.28`). Exit `0` is a pass; exit `3` means it
could not build the driver, which is **not** a pass.

## What is and is not verified

- Both examples **compile for ESP32** (core 2.0.17, ArduinoJson 6.21.5, WebSockets
  2.4.1). Nothing has been **flashed to a board**. The BLE/WiFi/WebSocket half
  (`Maya.cpp`) is the original firmware's code moved, but it has only been
  compiled, not run.
- The protocol half (`MayaCore.*`) is tested for real, by the script above.
- The local link's **decisions** are tested for real by `extras/test/test_peer_link.py`
  (11 checks): an independent peer written in Python signs frames with its own
  `hmac`, and the device must accept, refuse and answer correctly; then two library
  devices pair through the real server and the audit lines up. Three deliberate bugs
  (accept any MAC, no replay check, trust the scope blindly) each failed the run.
- **The ESP-NOW radio has not run.** `Maya.cpp`'s radio glue compiles for ESP32 but
  was never put on the air; frames in the tests travel through Python. Two boards
  are the first real test.
- Not implemented yet: device→Maya (§8), the hub relay (§5.9), and sleeping devices
  (`report_every`, §5.8).
- Cost: the local link adds ~18 KB of RAM (grant tables, the 64-entry audit buffer,
  the receive queue) and ~25 KB of flash.
