---
name: maya-device-builder
description: Build a new Maya hardware device (an ESP32 or ESP32-C3 sketch) on the Maya Arduino library - lamp, sensor, scale, valve, anything - so the Maya app and Maya the assistant can see and control it with no change to the app or server. Use when asked to create, port, wire, flash or debug a Maya device, to add a sensor or actuator to one, or to choose pins, power or a battery design for one.
---

# Building a Maya device

You write the hardware half. The library speaks the protocol: Bluetooth setup, WiFi, the
server link, the capability descriptor, `set`/`state`/`ack`, safety fields, ESP-NOW to a
hub. **Never edit `software/` (the app and server) to make a device work.** If something
cannot be done without a change there, write a ticket (last section).

Read first, in this order, and only as much as the task needs:

1. `../../README.md` - the API and the rules. 2. `references/api-cheatsheet.md` - the
calls on one page. 3. `references/driver-patterns.md` - how to read a part, calibrate
it, store settings. 4. `references/troubleshooting.md` - Serial line to cause.
5. `../../../../../PROTOCOL.md` (repository root) section 5 (capabilities) only when a rule is unclear.
Working examples: `../../examples/` and `hardware/smart_jar/` (a full device: its own
driver, calibration, two power builds).

## The rules that cost people hours

- **Keys are permanent.** `[a-z0-9_]`, 1-24 chars. Permissions and history are filed under
  them. Pick them once, for what the thing *is* (`weight_g`), not how it looks today.
- **Pass string literals** for keys, labels, units and enum options. The library keeps the
  pointers; a `String` that goes out of scope becomes garbage in the descriptor.
- **Handlers run inside `maya.loop()`.** Never `delay()` for seconds in one, never block
  `loop()`. Read slow parts on a timer (`millis()`), not in a handler.
- **A handler returns `true` only if the hardware did it.** `false` tells the app `bad_value`.
- **Anything destructive or irreversible: `.agentDeny()`** (Maya cannot see it) and usually
  `.confirm()` (a person must approve). Tare, calibrate, factory reset, a valve, a lock.
- **At most 32 capabilities and 4 KB of descriptor.** `begin()` prints why if refused.
- **Anything that moves, heats, pumps, locks or floods needs safety ON THE DEVICE**, not in
  the app: off at boot (and a pull resistor to the OFF level on the driver's input: pins float while the chip
  resets or is flashed), a hard maximum run time enforced by an **`esp_timer` (its own high-priority task), not by `loop()`** (which can block for
  minutes) whatever was asked,
  a cooldown and a daily total, and the state reported back (also when the device itself
  switched off). Use `addDuration(key, label, maxSeconds, fn)` so the library refuses a
  longer request, and `.confirm()` so Maya asks a person. Start from
  `templates/timed_actuator`, and read "Timed actuators" in `references/driver-patterns.md`.
- **A failed read is a fault, not a number.** A DHT22 returns NaN when a read fails. The library
  refuses a non-finite `setNumber` (returns `false`, keeps the last good value); check the
  return, count consecutive failures, and say what is wrong in a `note` text ("sensor not
  answering"). Never push a made-up number to hide a failure.
- **Relay modules are usually active-LOW.** Most cheap relay boards energise when the input is
  LOW, so "off at boot" must drive HIGH and every command inverts. Use a `RELAY_ON` constant
  (see `templates/always_on`) and test with the load disconnected. Mains work: fused supply,
  relay and terminals in an enclosure, nothing live on a breadboard, and only if you are
  qualified to do it.
- **Third-party part libraries** (DHT, OneWire, HX711...) are installed for the build you use:
  `arduino-cli lib install "DHT sensor library"` (it also needs "Adafruit Unified Sensor"),
  or the IDE's Library Manager for the IDE. A part that disables interrupts while it reads (the
  DHT22 for ~5 ms) must be read no more often than its datasheet says (every 2 s for a DHT22)
  and will occasionally fail while WiFi is busy: treat that as the fault case above.
- **Do not use `_`-prefixed keys** except through `enableHealth()` / `addReserved("_batt")`.
- **Every flash wipes WiFi and the PIN** (by design: the first owner sets a new PIN, 4 digits,
  not 0000/1111/1234). Re-provision after each upload. Keep your own settings (calibration)
  in a **separate Preferences namespace** (not `"iotdata"`), or they are lost too.
- **Huge APP partition.** BLE + WiFi + TLS is ~1.6 MB. Default partition = "Sketch too big".
- **esp32 core 2.0.17.** It is what the library is built and tested on. Core 3.x is untested.

## Workflow

1. **Say what it is, as capabilities.** For each thing a person or Maya would read or do:
   a kind (switch, range, number, text, enum, button, color, time, duration, location), a
   key, a label, a unit. Reading only -> `addNumber(...).readOnly()`. Give a read-only number
   `.limits(lo, hi)` so the app can draw a gauge. Add `.history()` for a trend.
2. **Pick the device class** - it decides power and what may be writable:
   | Class | Power | Writable? | Calls |
   |---|---|---|---|
   | always-on | USB/mains | yes | `begin()` + `loop()` |
   | sensor-only (battery) | cells, deep sleep | **no** (only `_` keys) | `beginSensor()`, `reportNow()`, `sleepFor()` |
   | hub | mains | yes + carries sensors | `enableHub()` before `begin()` |
   A sleeping device cannot be told anything, so declaring a control on one is a design
   error. Calibrate it through Serial "setup mode" instead (see `hardware/smart_jar`).
   **A device that must be commanded (a pump, a valve) on batteries is not a sensor-only
   device:** run the always-on build from a battery pack or mains and do not deep-sleep it.
   The sleepy class (a writable device that sleeps and polls) is not implemented.
3. **Choose pins** with `references/api-cheatsheet.md` (board table). Check strapping and
   input-only pins before wiring, not after.
4. **Copy a template** from `templates/` (`always_on`, `battery_sensor`, `timed_actuator`) and fill in. Set the display name:
   `maya.setName("Hall lamp");` - it is the name an app can offer to start from, and it is printed in the Serial banner. The phone app (1.2.0 and later) puts it in the name field when adding the device; older app versions show a fixed "Maya Device XXXX". The owner can always type another name.
5. **Write the driver** (`references/driver-patterns.md`): non-blocking, filtered, with a
   deadband so a noisy reading does not flood the link.
6. **Compile** with arduino-cli (below). Fix warnings in your own file.
7. **Flash, provision, check Serial** against the table in `references/troubleshooting.md`.
8. **Verify on the app**: card appears with the right labels; each control does what it says;
   unplug and re-power; check it comes back.

## Compile and flash

```
arduino-cli compile --fqbn esp32:esp32:esp32:PartitionScheme=huge_app   --libraries hardware/libraries <sketch_dir>   # ESP32
arduino-cli compile --fqbn esp32:esp32:esp32c3:PartitionScheme=huge_app,CDCOnBoot=cdc --libraries hardware/libraries <sketch_dir>   # ESP32-C3
```

- C3 over its own USB: `CDCOnBoot=cdc` or Serial prints nothing. To flash a stuck C3: hold
  BOOT, tap RESET, release BOOT (or unplug, hold BOOT, plug in).
- Add a build flag **without** breaking the core's: `--build-property "compiler.cpp.extra_flags=-DMY_FLAG=1"`.
  Do not override `build.extra_flags`.
- A long Windows user name can push the toolchain past the 260-character path limit
  ("bits/error_constants.h: No such file"). Point arduino-cli's data folder at a short path
  such as `C:\mac\data`.

## What a good device prints on Serial

The boot banner (library version, model, firmware, **name**, id, **build time**), then
`Starting BLE provisioning...` on a fresh board, then `[WS] Connected`. If it does not,
`references/troubleshooting.md`. The library cannot know your hardware works: print your own
`[mydevice] ...` lines for readings, calibration and faults.

## Do not

- Do not edit `software/mobile` or `software/server`, or the library, to suit one device.
- Do not invent capability kinds, `_` keys, BLE characteristics or status codes.
- Do not claim it works until it has run on a board. Say "compiles" when that is all.
- Do not commit calibration values, WiFi names or passwords, or PINs.

## When the app or server must change

Write a short ticket in `SOFTWARE_TICKETS.md` at the repository root (what is wrong, what
the device already sends, the smallest change that fixes it) and carry on. Do not change
`software/` yourself.
