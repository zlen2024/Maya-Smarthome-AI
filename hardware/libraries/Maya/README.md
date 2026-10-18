# Maya — the Arduino library

**Version 0.3.0** ([CHANGELOG](CHANGELOG.md)). Make an ESP32 board a Maya device. You say what the hardware can do; the library
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

Flash it, provision it from the app, and the three controls appear. Complete
sketches are in `examples/`: `MinimalSensor` (the one to copy), `SmartExtension3ch`
(the existing 3-relay board, on the library), `PeerButton` (a button that drives another
device directly), `SmartExtensionHub` (the same board, also carrying other devices'
readings) and `HubSensor` (a battery sensor that reports through a hub). A complete device built on the library, with its own driver and calibration, is `hardware/smart_jar/`.

## Building your own device, with or without an AI agent

`skills/` has two skills written for an agent and readable by a person:
[`maya-device-builder`](skills/maya-device-builder/SKILL.md) (build any hardware on this
library: API cheat sheet, driver patterns, a troubleshooting table, three
templates: always-on, battery sensor, timed actuator) and [`maya-library-maintainer`](skills/maya-library-maintainer/SKILL.md) (change
the library without breaking the app, the server or devices already flashed).
See [`skills/README.md`](skills/README.md).

## Name, version and build time

```cpp
maya.setName("Smart Jar");        // the name for an app to offer; the owner can change it
```

On every boot Serial (115200) shows which library and sketch you are running:

```
[Maya] library 0.3.0 | model smart_jar | fw 1.0.0
[Maya] name 'Smart Jar' | id esp32-9fc13de8
[Maya] sketch built Oct 18 2026 01:23:45 | binary 3f9a1c2e | chip ESP32-C3 rev 4 | free heap 214532
```

- **library** is `MAYA_LIB_VERSION` (`Maya::libraryVersion()`), kept equal to `library.properties`.
- **sketch built** is when *your sketch* was compiled, not when the library was. There is no
  clock on the board that survives a reset, so this is the closest honest answer to "when was
  this flashed": it is when the code you flashed was compiled. **binary** is the first 8
  characters of the running firmware's MD5 and names the exact image (the build time can lag if
  only the library changed, because the sketch file is not recompiled). `maya.builtAt()` returns it;
  `maya.printInfo()` prints the banner on demand.
- On a board whose Serial is its USB port (ESP32-C3/S3), `begin()` waits up to 2.5 s for a
  serial monitor before printing, so opening the monitor a moment late no longer looks like a
  dead board. A battery sensor skips that wait on a timer wake.
- The same facts are in a read-only Bluetooth characteristic (`...9008`) as JSON, for an app to
  read before the person has typed anything. No WiFi password and no PIN are in it.

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

## Being a hub, and reporting through one

A **hub** is a mains-powered device that carries other devices' readings to the server
over ESP-NOW, so a battery sensor does not have to join WiFi every time it wakes
(PROTOCOL.md 5.9: roughly three times the battery life).

```cpp
maya.enableHub();      // before begin() - that is all a hub sketch does
```

The library then says `hub:true` at identify, takes the reports of the sensors a person has
paired to it, forwards them to the server byte for byte, and tells the server its WiFi
channel. `examples/SmartExtensionHub` is the 3-channel extension with that one line added;
`hardware/smartextension_hub` is the shipped firmware.

**A hub holds no key for its sensors** (PROTOCOL.md 7.5), so it cannot check a frame's MAC
and does not pretend to: it checks what it can without a key (the radio address is a sensor
it was paired with, the frame is well-formed text under 250 bytes, the sender is within 12
frames a minute, its queue of 32 is not full) and the server does the authenticating. The
point is that a compromised hub still cannot forge, alter or replay a reading. It can only
withhold or delay, and the app's audit shows that.

A **sensor** that sleeps between readings:

```cpp
void setup() {
  maya.addNumber("salt", "Salt left").readOnly().unit("%");
  maya.addReserved("_batt");
  maya.beginSensor();                 // not begin(): it does not join WiFi
  maya.setNumber("salt", readSalt());
  maya.setNumber("_batt", readBattery());
  maya.reportNow();                   // the hub if it can, the server if it cannot
  maya.sleepFor(300);                 // deep sleep; does not return
}
void loop() {}
```

`reportNow()` hands what changed to the hub (ESP-NOW, no WiFi), oldest first, each reading
carrying how old it is. A frame the hub's radio does not acknowledge is kept and spends no
sequence number. After three failures in a row the sensor stops using the air on it, reports
through the server instead (the latest value of each key), and the first such report says
`hub_failed` so the app can tell the family which hub to check, once. It tries the hub again
every half hour. With both down it keeps the last 16 readings. It visits WiFi about once a day
to refresh its pairing and learn the hub's channel. The first time it is switched on it needs
WiFi and the server, like any Maya device.

Use a bare ESP32 module, not a DevKit: a DevKit's USB chip draws more asleep than the design
budget. `core.report()` / `hubUsable()` / `fallBackToServer()` are the platform-free pieces
`reportNow()` is made of, if you need a different wake loop.

## Asking Maya for help

```cpp
maya.askMaya("someone is at the front door", [](const char* status, const char* text, uint32_t retryAfter) {
  if (!strcmp(status, "ok")) showOnDisplay(text);        // "I've told the family."
});
```

The reply arrives in the callback during `loop()`. `status` is `ok`, `not_permitted`,
`rate_limited` (see `retryAfter`), `busy`, `bad_value` or `unavailable`; treat anything
else as failure. `askMaya` itself returns `false` if the device is offline, a request is
already waiting (one at a time), or the text is empty or over 280 bytes.

**A person has to allow it first**, in the app (until then the status is
`not_permitted`), and what Maya may *do* for the device is exactly what it could already
do over the local link: the controls named in its `send` grants, nothing more. She can
also post a short message to the family chat, always labelled with the device's name.
The device's text is treated as data, not instructions. Limits: 6 requests an hour and
30 a day per device, 100 a day per house. Give up after 45 s if no reply comes (the
library does this for you and reports `unavailable`).

## Reporting

`setSwitch`, `setNumber`, `setText`, `setLocation` tell the library what the
hardware now reads. A changed value goes out within 250 ms; an unchanged one is
never re-sent, so calling them every `loop()` is fine. Each returns `false` for an
unknown key or the wrong kind rather than guessing.

## Joining WiFi, and when it does not

Bluetooth setup is the original flow, unchanged on the wire: the app writes the network,
password, server URL and PIN, and reads status codes back. What the library does now to make
the join dependable, and says on Serial:

- It scans first and logs whether the network was **heard at all** (`'name' heard at -64 dBm
  on channel 11`, or `NOT heard among 23 networks`). A network that is not heard cannot be
  fixed with a password.
- Every failure prints the router's reason in words (`WiFi: not joined, reason 202 -
  authentication failed (usually a wrong password)`).
- WiFi is brought up once and retried (not torn down for every try), and just before the join
  the phone link is relaxed to 60-100 ms, because WiFi and Bluetooth share one radio.
- The station asks for a 20 MHz channel. On an ESP32-C3 the transmit power defaults to 8.5 dBm
  (many SuperMini clones cannot drive their antenna at full power); `setWifiTxPower()` changes
  it. The core only accepts a power once the station has started, so the library waits for that
  and prints `WiFi radio: HT20, TX power 8.5 dBm` (or says it could not set it).
  (The 0.2.0 code asked too early and the request was silently ignored.)
- The Bluetooth service now reserves 40 attribute handles instead of the default 15; it needs
  about 22, and with too few the stack can leave the last-registered characteristics out.
- If a phone disconnects, advertising restarts (core 2.0.x does not do this by itself).

**These changes compile and are unverified on a board.** In one bench session a C3 failed to
join a 2.4 GHz router while a phone was connected over Bluetooth and joined first try in a bare
WiFi sketch, which points at the shared radio; the changes above are the mitigation, not a
proven fix. If your board still fails, the Serial line says which of the causes it is
(`skills/maya-device-builder/references/troubleshooting.md`), and
[`SOFTWARE_TICKETS.md`](../../../SOFTWARE_TICKETS.md) T-5 describes the app-side fix.

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
python extras/test/test_relay_link.py   # a hub and a sensor, then both through the real server
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
- `askMaya` is tested for its frames, one-at-a-time rule, every reply status, the 280-byte
  limit and the 45 s timeout, and once end to end against the real server. The model on the
  other end was scripted, not real.
- **The hub and sensor halves** are tested by `extras/test/test_relay_link.py` (12 checks): a
  hub fed frames by a script (forwarded byte for byte whatever their tag, because it cannot
  check one; dropped for every defect it *can* see; rate and queue bounds; what the server's
  answer causes to be logged), a sensor judged with Python's `hmac` (numbering, age, a dead
  hub, the buffer, the fallback, `hub_failed` once), and then both through the real server:
  a reading crosses as the sensor's own, a replay and a forgery are refused, a dead hub is
  reported, revoking leaves the sensor nowhere to report. Twenty deliberate bugs each fail
  it. It found one real bug: the JSON pool for incoming frames was too small for a
  `relay_ack` with 16 results, which would have been dropped without a word.
- **Version 0.3.0 additions are compiled and unrun on a board:** the Bluetooth INFO
  characteristic, the advertising restart and connection-parameter request, the WiFi
  tuning (20 MHz, C3 transmit power), the retry-on-one-radio-session change, and the
  serial-monitor wait. The version, `setName`, and banner logic have no hardware
  dependency beyond Serial. `extras/test/check_version.py` checks the three version strings.
- **ESP-NOW acknowledgement and deep sleep are untested.** `Maya.cpp`'s `radioSend` (the
  MAC layer's acknowledgement is what makes a sensor give up on a hub), `beginSensor`,
  `reportNow` and `sleepFor` compile for ESP32 and have never run: they need a hub and a
  sensor on a bench, and a bare module to measure the sleep current.
- Not implemented yet: the sleepy class's `pending` queue (§5.9) and `report_every` (§5.8).
- Cost: the local link adds ~18 KB of RAM (grant tables, the 64-entry audit buffer,
  the receive queue) and ~25 KB of flash. A hub allocates ~9 KB for its queue, only when
  `enableHub()` is called; a sensor ~2 KB for its buffer, on first use.
