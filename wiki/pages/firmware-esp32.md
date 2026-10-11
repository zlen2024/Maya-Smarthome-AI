# ESP32 firmware

Two layers, since 2026-10-10:

- `hardware/smartextension/smartextension.ino` — **~70 lines**: three outputs on GPIO
  2, 4, 5 declared as switches `ch1`..`ch3`, plus a `RELAY_ACTIVE_LOW` option.
  Companion docs: `SETUP.md`, `WIRING.md`.
- `hardware/libraries/Maya` — everything else: BLE provisioning, WiFi, the server
  link, the capability descriptor, the local link, asking Maya. See
  [Device protocol v2 §Step 4](device-protocol.md#step-4-2026-10-10-the-arduino-library).

Until 2026-10-10 the sketch was a single 618-line file that carried all of it. That
version is in git: `git show 76e0061:hardware/smartextension/smartextension.ino`.

> **Not verified on hardware.** The new sketch compiles for ESP32 (core 2.0.17, Huge
> APP partition, both relay polarities) and the library's protocol behaviour is tested
> on a laptop against the real server — but **no board has been flashed with this
> build**. The BLE, WiFi and TLS code is the old sketch's, moved; the first flash is its
> first run in this arrangement. The old sketch did **not** build on core 2.0.17 at all
> (BLE `getValue()` returns `std::string` there), so the previous firmware could not
> have been rebuilt on the toolchain this was verified against.

> **Not in the graph.** `code2graph index .` admits **0 files** here — `.ino` is not a
> recognised extension, and `build_graph.py` excludes this root (and the library) by
> design. [known-gaps §5](known-gaps.md#5-esp32-firmware-is-not-indexed-at-all).
> Everything below was read from source, not queried.

## Outputs

Three channels on **GPIO 2, 4, 5**; GPIO2 is the built-in LED on most boards, so
channel 1 can be tested without wiring. All outputs are driven off before anything
else runs. `RELAY_ACTIVE_LOW` flips the polarity and makes every pin idle HIGH, so an
active-LOW relay module does not click on at boot — before, this was a hand-edit
described in `WIRING.md`.

The keys `ch1`..`ch3` are permanent: a parent's permissions, the names a household has
given the channels, and the old protocol's commands are all filed under them.

## BLE provisioning

Unchanged from the old firmware, because the app is written against it. One service,
seven characteristics, fixed UUIDs (`Maya.cpp`):

| Characteristic | UUID suffix | Purpose |
|---|---|---|
| `SERVICE` | `...789000` | The setup service |
| `SSID` | `...789001` | WiFi SSID |
| `PASS` | `...789002` | WiFi password |
| `PIN` | `...789003` | Current security PIN (required) |
| `WSURL` | `...789004` | Backend WebSocket URL |
| `CMD` | `...789005` | Commands over BLE |
| `STATUS` | `...789006` | Status readback to the app |
| `NEWPIN` | `...789007` | **Optional** — rotate the PIN; current PIN still required |

The board advertises as `Maya-<device id>` (the earlier docs said `Maya-Setup`, which
was never what the code did). Status codes the app reads: `1` PIN verified, `2` WiFi
connected, `4` WiFi failed, `6` PIN mismatch, `8` saved and rebooting, `9` weak PIN
refused. The Flutter side is `screens/provision_screen.dart`.

Settings persist to NVS under one namespace. **Every flash starts clean**: the library
keys the wipe on the running sketch's MD5 (`ESP.getSketchMD5()`), not on a compile-time
date, because a date inside a library is baked in when *the library* is compiled and a
cached object would never notice a new sketch.

## Connection lifecycle

```
boot → load settings → (no WiFi? BLE provisioning) → WiFi (20 tries)
     → WebSocket (identify with the descriptor) → loop(): pump WS, report changes,
       full report every 30 s, reconnect
```

After `WIFI_RECONNECT_CYCLES_BEFORE_PROVISION = 6` failed cycles the device **falls back
into BLE provisioning** — the recovery path when a household changes its WiFi password,
so the device never becomes permanently unreachable. A ping every 15 s plus a 3-minute
silence watchdog catch half-open sockets; the watchdog reconnects rather than rebooting,
because a reboot would drop every output.

## Command handling

The server's `set` frames and the old `cmd` frames both end at the channel handler in the
sketch. A legacy command is answered the old way (all three channels, no request id) so a
server that has not been upgraded still works. The PIN is checked once, at identify, by the server;
there is no per-command PIN (the previous version of this page said commands carry one;
the code never did). Details of both vocabularies: `WIRING.md`.

The device connects to `/ws` or `/` on the server — both routes exist for exactly this
reason ([server backend](server-backend.md#websockets)).
