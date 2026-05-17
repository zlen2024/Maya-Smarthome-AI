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

> **To change pins** — edit these lines in `smartextension.ino`:
> ```cpp
> const int OUTPUT_PINS[NUM_OUTPUTS] = {2, 4, 5};
> ```

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
If your relay behaves inverted, change the logic in the firmware:

```cpp
// In setOutput() — invert for active-LOW relay modules
digitalWrite(OUTPUT_PINS[channel - 1], state ? LOW : HIGH);
```

---

## Power Considerations

| Scenario | Recommended Power |
|----------|------------------|
| LED testing only | USB (any 5V) |
| 1–3 relay modules (5V coil) | USB 5V ≥ 1A (phone charger) |
| 3 relays + high-load appliances | Dedicated 5V 2A power supply |

> ⚡ Do **not** power relay modules from the ESP32 `3.3V` pin — relay coils draw too much current and will brown-out the ESP32.

---

## WebSocket Command Reference

Commands are sent as JSON over WebSocket to the server, which routes them to the device.

### Channel-specific commands

```json
{ "id": "esp32-9f83b1c1", "cmd": "output_on",     "channel": 1 }
{ "id": "esp32-9f83b1c1", "cmd": "output_off",    "channel": 2 }
{ "id": "esp32-9f83b1c1", "cmd": "output_toggle", "channel": 3 }
```

| Field | Values | Notes |
|-------|--------|-------|
| `cmd` | `output_on` / `output_off` / `output_toggle` | |
| `channel` | `1`, `2`, `3` | Defaults to `1` if omitted |

### All-channel commands

```json
{ "id": "esp32-9f83b1c1", "cmd": "all_on"  }
{ "id": "esp32-9f83b1c1", "cmd": "all_off" }
```

### Status & Utility

```json
{ "id": "esp32-9f83b1c1", "cmd": "get_status" }
{ "id": "esp32-9f83b1c1", "cmd": "reboot" }
```

### Ack Response Format

Every command returns an ack with all channel states:

```json
{
  "id": "esp32-9f83b1c1",
  "status": "ok",
  "ch1": "on",
  "ch2": "off",
  "ch3": "off"
}
```

### Backward-Compatible Commands (Channel 1 only)

```json
{ "id": "esp32-9f83b1c1", "cmd": "led_on"  }
{ "id": "esp32-9f83b1c1", "cmd": "led_off" }
{ "id": "esp32-9f83b1c1", "cmd": "toggle"  }
```

---

## Heartbeat Payload

Every 30 seconds the device sends all channel states:

```json
{
  "id": "esp32-9f83b1c1",
  "type": "heartbeat",
  "uptime_ms": 120000,
  "ch1": "on",
  "ch2": "off",
  "ch3": "off"
}
```

---

## Quick Checklist Before Flashing

- [ ] Arduino IDE has **ESP32 board package** installed  
- [ ] Libraries installed: `WebSocketsClient`, `ArduinoJson`, `BLE` (built-in ESP32)  
- [ ] Board set to `ESP32 Dev Module` (or your specific variant)  
- [ ] Baud rate: `115200`  
- [ ] Correct COM port selected  
- [ ] GPIO 2, 4, 5 are free (not used by other shields/peripherals)

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Only CH1 works | Wiring issue on CH2/CH3 | Check GPIO 4 & 5 connections |
| Relay clicks but load stays on | Active-LOW relay | Invert logic in firmware |
| Relay doesn't click | Wrong VCC (using 3.3V) | Connect relay VCC to ESP32 VIN (5V) |
| Device keeps rebooting | Power brownout | Use dedicated 5V 2A supply |
| GPIO 2 glitches on boot | Boot strapping pin | Normal — use GPIO 4/5 for relays if critical |
