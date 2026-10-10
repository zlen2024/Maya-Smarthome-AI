# ESP32 firmware

`hardware/smartextension/smartextension.ino` — 618 lines of Arduino C++.
Companion docs: `SETUP.md`, `WIRING.md`.

> **Superseded in intent, not yet in practice.** The provisioning, WiFi and
> WebSocket code on this page now also lives in `hardware/libraries/Maya`, which
> speaks protocol v2 ([Device protocol v2 §Step 4](device-protocol.md#step-4-2026-10-10-the-arduino-library)).
> This sketch stays the shipped firmware until the library's
> `SmartExtension3ch` example has run on a real board. It does **not** build on
> ESP32 core 2.0.17 (BLE `getValue()` returns `std::string` there) and needs the
> Huge APP partition scheme.

> **Not in the graph.** `code2graph index .` admits **0 files** here — `.ino` is
> not a recognised extension, and `build_graph.py` excludes this root by design.
> Everything below was read from source, not queried.
> [known-gaps §5](known-gaps.md#5-esp32-firmware-is-not-indexed-at-all)
>
> To query it anyway, copy to a scratch `.cpp` and index that:
> ```bash
> cp hardware/smartextension/smartextension.ino /tmp/fw/smartextension.cpp
> cd /tmp/fw && code2graph index . && code2graph usages setOutput
> ```

## Outputs

Three relay channels on **GPIO 2, 4, 5** (`OUTPUT_PINS`, line 36; `NUM_OUTPUTS 3`).
GPIO2 is the built-in LED on most ESP32 boards, which the comment at line 32
notes is convenient for testing channel 1 without wiring anything. All outputs
initialise LOW at boot (line 532).

## BLE provisioning

One service, seven characteristics, fixed UUIDs (lines 59–66):

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

The Flutter side is `screens/provision_screen.dart` (1,067 lines).
`sanitizeBleText` (line 40) cleans incoming characteristic strings before use.
Settings persist to ESP32 Preferences (`saveSettings` 124 / `loadSettings` 134),
and `resetPrefsIfNewFirmware` (line 113) clears them when the firmware version
changes so a stale schema can't half-load.

## Connection lifecycle

```
boot → loadSettings → WiFi (connectToWiFiOnce, 20 tries)
     → WebSocket (startWebSocket, 477)
     → loop(): pump WS, heartbeat, reconnect
```

`WIFI_CONNECT_TRIES = 20` (line 83). After
`WIFI_RECONNECT_CYCLES_BEFORE_PROVISION = 6` failed cycles (line 84) the device
**falls back into BLE provisioning** — the recovery path when a household changes
its WiFi password, so the device never becomes permanently unreachable.

`setStatus` (line 100) publishes a short status code over the BLE STATUS
characteristic, which is what the provisioning UI displays.

## Command handling

`webSocketEvent` (line 354) is the message handler. Incoming commands carry a PIN
which is checked before any GPIO is touched. Actuation is `setOutput(channel, state)`
(line 323) and `toggleOutput(channel)` (line 330); `sendAllStatesAck` (line 340)
replies with **all three channel states**, not just the changed one — which is why
the server can keep the whole relay row in sync from a single-channel command.

The device connects to `/ws` or `/` on the server — both routes exist for exactly
this reason ([server backend](server-backend.md#websockets)).
