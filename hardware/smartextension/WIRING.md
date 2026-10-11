# Maya Smart Extension — Hardware Setup & Wiring Guide

## Overview

The ESP32 controls **3 output channels** — wired to LEDs (for prototyping) or relay modules (for mains-powered appliances). Each channel is independently controllable via WebSocket commands.

---

## Pin Assignment

| Channel | GPIO | Label  | Use Case |
|---------|------|--------|----------|
| CH1     | 2    | `ch1`  | Built-in LED (test) / Relay 1 |
| CH2     | 4    | `ch2`  | External LED / Relay 2 |
| CH3     | 5    | `ch3`  | External LED / Relay 3 |

> **To change pins** — edit this line in `smartextension.ino`:
> ```cpp
> const int OUTPUT_PINS[NUM_OUTPUTS] = {2, 4, 5};
> ```
> Do **not** rename the keys (`ch1`, `ch2`, `ch3`): permissions and the names a household has given each channel are filed under them.

---

## Prototype Wiring — 3 LEDs (Testing)

```
ESP32 Board
┌─────────────────────────────────┐
│  GPIO 2 ──┬── [220Ω] ──┤► GND  │  ← CH1 (also built-in LED)
│  GPIO 4 ──┼── [220Ω] ──┤► GND  │  ← CH2
│  GPIO 5 ──┴── [220Ω] ──┤► GND  │  ← CH3
│  GND    ──────────────────────  │
│  VIN/3.3V (for power)           │
└─────────────────────────────────┘
```

### Step-by-step (Breadboard)

1. Insert the ESP32 into the breadboard straddling the centre gap.
2. For **each LED channel**:
   - Connect the **anode (+, longer leg)** of the LED to a `220 Ω` resistor.
   - Connect the other resistor leg to the respective GPIO pin.
   - Connect the **cathode (-, shorter leg)** to the **GND rail**.
3. Connect the ESP32 `GND` pin to the breadboard GND rail.
4. Power via USB.

> ⚠️ **Always use a resistor** (220–470 Ω) in series with each LED. Direct GPIO → LED → GND will damage the ESP32 over time.

---

## Relay Module Wiring (Mains Control)

> ⚠️ **WARNING — MAINS VOLTAGE IS DANGEROUS.**  
> Only attempt mains wiring if you are qualified to do so. Use an enclosure. Double-check all connections before powering on.

### Relay Module Pinout

Most 5V relay modules have 3 control pins:

| Relay Pin | Connect To |
|-----------|-----------|
| `VCC`     | ESP32 `VIN` (5V from USB) |
| `GND`     | ESP32 `GND` |
| `IN1`     | ESP32 `GPIO 2` (CH1) |
| `IN2`     | ESP32 `GPIO 4` (CH2) |
| `IN3`     | ESP32 `GPIO 5` (CH3) |

### Relay Wiring Diagram

```
                  ┌─────────────────────────────┐
                  │     5V Relay Module          │
                  │                              │
ESP32 GPIO2 ─────►│ IN1   [RELAY 1] ──► Load 1  │
ESP32 GPIO4 ─────►│ IN2   [RELAY 2] ──► Load 2  │
ESP32 GPIO5 ─────►│ IN3   [RELAY 3] ──► Load 3  │
ESP32 VIN   ─────►│ VCC                          │
ESP32 GND   ─────►│ GND                          │
                  └─────────────────────────────┘

Relay contacts (per channel):
    COM ──── Live (Mains)
    NO  ──── Load Live In    (Normally Open — load OFF when ESP32 LOW)
    NC  ──── (not used)
    Load Neutral ──── Mains Neutral
```

### Active-LOW vs Active-HIGH Relays

Many relay modules are **active-LOW** (relay energises when GPIO is LOW).
If your relay behaves inverted, set this one constant in `smartextension.ino`:

```cpp
const bool RELAY_ACTIVE_LOW = true;
```

"On" then drives the pin LOW, and every pin idles HIGH, so no relay clicks on while the board boots.

---

## Power Considerations

| Scenario | Recommended Power |
|----------|------------------|
| LED testing only | USB (any 5V) |
| 1–3 relay modules (5V coil) | USB 5V ≥ 1A (phone charger) |
| 3 relays + high-load appliances | Dedicated 5V 2A power supply |

> ⚡ Do **not** power relay modules from the ESP32 `3.3V` pin — relay coils draw too much current and will brown-out the ESP32.

---

## Command Reference

The server talks to the board over a WebSocket. The board speaks the **Maya Device
Protocol v2** (`PROTOCOL.md`) and still answers the old protocol-1 commands, so it
works against a server that has not been upgraded.

### What the board says about itself

On connecting, it sends a description of what it can do — three switches — and their
current values. The app draws its controls from this, rather than knowing about this
board in advance:

```json
{ "id": "esp32-9f83b1c1", "proto": 2, "status": "online", "pin": "****", "ip": "192.168.0.42",
  "mac": "24:6F:28:AA:BB:01", "model": "smart_extension_3ch", "fw": "2.0.0",
  "capabilities": [
    { "key": "ch1", "kind": "switch", "label": "Channel 1" },
    { "key": "ch2", "kind": "switch", "label": "Channel 2" },
    { "key": "ch3", "kind": "switch", "label": "Channel 3" },
    { "key": "_rssi", "kind": "number", "access": "r", "unit": "dBm" },
    { "key": "_uptime", "kind": "number", "access": "r", "unit": "s" },
    { "key": "_fw", "kind": "text", "access": "r" } ],
  "state": { "ch1": "off", "ch2": "off", "ch3": "off", "_fw": "2.0.0" } }
```

### Switching a channel (protocol 2)

```json
{ "id": "esp32-9f83b1c1", "type": "set", "req": "c-8123", "values": { "ch1": "on", "ch3": "off" } }
```

The board applies the keys in order and answers with what it actually did:

```json
{ "id": "esp32-9f83b1c1", "type": "ack", "req": "c-8123", "status": "ok",
  "state": { "ch1": "on", "ch3": "off" } }
```

If something fails the ack says which key and what happened before it
(`"status": "bad_value", "failed": "ch3", "state": { "ch1": "on" }`); nothing is
rolled back. Status values are listed in `PROTOCOL.md` §9.

### Legacy commands (protocol 1, still answered)

```json
{ "id": "esp32-9f83b1c1", "cmd": "output_on",     "channel": 1 }
{ "id": "esp32-9f83b1c1", "cmd": "output_off",    "channel": 2 }
{ "id": "esp32-9f83b1c1", "cmd": "output_toggle", "channel": 3 }
{ "id": "esp32-9f83b1c1", "cmd": "all_on" }
{ "id": "esp32-9f83b1c1", "cmd": "all_off" }
{ "id": "esp32-9f83b1c1", "cmd": "get_status" }
{ "id": "esp32-9f83b1c1", "cmd": "led_on" }
```

`channel` defaults to `1`. `led_on`, `led_off` and `toggle` address channel 1 only. A
legacy command is answered the old way — all three channels, no request id:

```json
{ "id": "esp32-9f83b1c1", "status": "ok", "ch1": "on", "ch2": "off", "ch3": "off" }
```

An out-of-range channel is answered `{"status": "invalid_channel"}`.

### Reboot and factory reset

```json
{ "id": "esp32-9f83b1c1", "type": "reboot" }
{ "id": "esp32-9f83b1c1", "type": "factory_reset" }
```

A factory reset wipes Wi-Fi, the server URL, the PIN and any pairings, and reboots into
provisioning. The server sends it when a device is removed from a house.

---

## Reports

Whenever a channel changes the board reports it (within a quarter of a second), and
every 30 seconds it sends a full report, which doubles as the keep-alive:

```json
{ "id": "esp32-9f83b1c1", "type": "state", "uptime_ms": 120000,
  "state": { "ch1": "on", "ch2": "off", "ch3": "off", "_rssi": -61, "_uptime": 120 } }
```

---

## Pairing with other Maya devices

A person can let this board's channels be driven directly by another Maya device (a
button, a sensor) over the local radio link, without going through the server: in the
app, "this device may address that one, and only these channels". `PROTOCOL.md` §7
defines it. Nothing needs configuring on the board, and a channel can never be driven
this way unless a person granted that exact channel. **This part has not yet been run
on two real boards.**

---

## Quick Checklist Before Flashing

- [ ] Arduino IDE has **ESP32 board package** installed  
- [ ] Libraries installed: **Maya** (copied from `hardware/libraries/Maya`), `WebSockets`, `ArduinoJson` **6.x**  
- [ ] **Tools > Partition Scheme = Huge APP** (otherwise the build stops with "Sketch too big")  
- [ ] Board set to `ESP32 Dev Module` (or your specific variant)  
- [ ] Baud rate: `115200`  
- [ ] Correct COM port selected  
- [ ] GPIO 2, 4, 5 are free (not used by other shields/peripherals)

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Only CH1 works | Wiring issue on CH2/CH3 | Check GPIO 4 & 5 connections |
| Relay clicks but load stays on | Active-LOW relay | Set `RELAY_ACTIVE_LOW = true` in the sketch |
| Relay doesn't click | Wrong VCC (using 3.3V) | Connect relay VCC to ESP32 VIN (5V) |
| Device keeps rebooting | Power brownout | Use dedicated 5V 2A supply |
| Build stops with `Sketch too big` | Default partition scheme | Tools > Partition Scheme > Huge APP |
| Build stops with `Maya.h: No such file` | Library not installed | Copy `hardware/libraries/Maya` into your Arduino libraries folder (see `SETUP.md`) |
| GPIO 2 glitches on boot | Boot strapping pin | Normal — use GPIO 4/5 for relays if critical |
