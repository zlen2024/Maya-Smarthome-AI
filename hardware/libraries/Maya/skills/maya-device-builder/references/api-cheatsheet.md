# Maya API cheat sheet

## Skeleton

```cpp
#include <Maya.h>
Maya maya("my_model", "1.0.0");          // model = what kind of device; fw = this sketch's version

void setup() {
  maya.setName("Hall lamp");              // the name for an app to offer (<= 32 bytes)
  maya.enableHealth();                    // optional: _rssi, _uptime, _fw
  maya.addSwitch("lamp", "Lamp", [](bool on) { digitalWrite(2, on); return true; });
  maya.begin();                           // always-on.  Sensor: maya.beginSensor()
}
void loop() { maya.loop(); }              // sensor: empty, you sleep instead
```

## Declare (before `begin()`)

| Call | Kind | Handler |
|---|---|---|
| `addSwitch(key, label[, fn(bool)])` | switch | on/off. **No `fn` does NOT make it read-only**: add `.readOnly()` for a state, or the app draws a control that accepts a value and does nothing |
| `addRange(key, label, min, max, step, fn(double))` | range | number |
| `addNumber(key, label[, fn(double)])` | number | none = read-only |
| `addText(key, label, maxChars[, fn(const char*)])` | text | string |
| `addEnum(key, label, options, n[, fn(const char*)])` | enum | one option |
| `addButton(key, label, fn())` | button | none |
| `addColor(key, label[, fn(const char*)])` | color | "#rrggbb" |
| `addTime(key, label[, fn(const char*)])` | time | "HH:MM" |
| `addDuration(key, label, maxSeconds[, fn(double)])` | duration | seconds |
| `addLocation(key, label)` | location | report with `setLocation` |
| `addReserved("_batt")` | battery % | you report it |

Modifiers chain off any of them: `.unit("g")` `.group("Setup")` `.readOnly()` `.writeOnly()`
`.history()` `.limits(lo, hi)` `.confirm()` `.agentDeny()`.

## Report (any time after `begin()`)

`setSwitch(key, bool)` `setNumber(key, double)` `setText(key, const char*)` `setLocation(...)`.
An unchanged value is never re-sent, so calling them every `loop()` is fine. Each returns
`false` for an unknown key or the wrong kind, and `setNumber` also for **NaN or infinity**
(a failed sensor read): the last good value stays. Check the return.

## Library facts and settings

| Call | What |
|---|---|
| `Maya::libraryVersion()` | "0.3.0" |
| `maya.builtAt()` | when this sketch was compiled ("Oct 18 2026 01:23:45") |
| `maya.printInfo()` | the banner line(s) on Serial, on demand |
| `maya.id()`, `maya.connected()` | device id, server link up |
| `maya.setWifiTxPower(WIFI_POWER_11dBm)` | before `begin()`; C3 defaults to 8.5 dBm |
| `maya.factoryReset()` | wipe WiFi + PIN, reboot into setup (wire to a button; `.agentDeny()` any app button) |

## Other roles

- Hub: `maya.enableHub()` before `begin()`.
- Battery sensor: `beginSensor()` -> `setNumber(...)` -> `reportNow()` -> `sleepFor(seconds)`.
- Local link: `peerSetNumber(peerId, key, value)`, `onPeerAck(...)`.
- Ask Maya: `askMaya("text", callback)`.

## Pins

| Board | Avoid / know |
|---|---|
| ESP32 (classic) | GPIO 6-11 are the flash. 0, 2, 12, 15 are strapping (boot state matters; 12 high at reset = 1.8 V flash, board will not boot). 34-39 are input only, no pull-ups. ADC2 pins do not work while WiFi is on: read analog on ADC1 (32-39). GPIO 2 is the on-board LED. |
| ESP32-C3 | GPIO 0-5 are the only deep-sleep wake pins; GPIO 0-4 are ADC1 (GPIO5 is ADC2, which does not work while WiFi is on). 2, 8 and 9 are strapping (GPIO 2 must not be pulled low at reset); **GPIO 9 low at reset = download mode** (the BOOT button). 18/19 are the USB; 20/21 the UART. No ext0/ext1, no ULP. |

Logic is 3.3 V; a pin sources a few mA, not a relay coil or a bridge of strain gauges
(use a transistor or load switch past ~10 mA). Power a 5 V relay module from VIN, not 3V3.
**Most relay modules switch ON when their input is LOW** (active-low): set the polarity before
connecting a load, and make the boot state OFF in that polarity (`templates/always_on`).
A 5 V active-LOW module often does **not release** from a 3.3 V "off" (the optocoupler LED still
conducts through VCC minus 3.3 V): use a module rated for 3.3 V logic, JD-VCC separation or a
transistor stage, and test that it really switches off. Set the output level before
`pinMode(OUTPUT)` so the pin never glitches to the ON level at boot.
Mains: fused supply, enclosed relay and terminals, never live on a breadboard.

## Limits

32 capabilities, 4 KB descriptor, local-link frames 250 bytes, `askMaya` text 280 bytes,
one device name <= 32 bytes. A device-side `delay()` over ~a second in a handler can drop the
server link.
