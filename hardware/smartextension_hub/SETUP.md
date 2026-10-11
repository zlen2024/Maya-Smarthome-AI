# Smart Extension Hub — Setup

This is the [Smart Extension](../smartextension/SETUP.md) with one addition: it also
carries the readings of battery-powered ESP32 sensors to the server over ESP-NOW.
**Follow the Smart Extension's `SETUP.md` for everything about the toolchain** — the
Arduino IDE, the ESP32 core (tested with 2.0.17), the libraries (Maya, WebSockets,
ArduinoJson **6.x**), the **Huge APP** partition scheme, and flashing. Open
`hardware/smartextension_hub/smartextension_hub.ino` instead of `smartextension.ino`.

What follows is only what is different.

## What a hub is for

A battery sensor that joins WiFi, does TLS and talks to the server every time it wakes
uses about 0.17 mAh a wake. The same report over ESP-NOW to a hub nearby uses about
0.012 mAh — roughly three times the battery life, and the only way some battery devices
can be reached at all. The hub is the mains-powered part that holds the server
connection so the sensors do not have to.

A hub is **an optimisation, never a requirement** (`PROTOCOL.md` §5.9): a house without
one still works, more slowly, and this board is a perfectly ordinary Smart Extension
until a sensor is paired to it.

## Placing it

- It must be **mains-powered and always on**. It listens for sensors continuously.
- **Range is measured to the hub, not to the router.** ESP-NOW reaches hundreds of
  metres in the open at low rates and a room or two through walls. A hub in a cupboard
  or a metal enclosure can be worse than the WiFi you already have. Put it where the
  sensors can see it.
- It uses the **same WiFi channel as your router**. If the router moves channel the
  hub notices and tells the server; sensors learn the new one the next time they visit
  WiFi (about daily) or when the server tells them.

## Setting it up in the app

1. Provision the hub like any Maya device: it advertises as `Maya-<device id>`.
   In the app it appears as a normal device with three switches.
2. Provision each battery sensor the same way. (A sensor needs WiFi and the server once,
   to be claimed and to be handed its pairing.)
3. In the app, pair the sensor to the hub with a **relay** pairing, and choose which of
   the sensor's readings the hub may carry. *(The app does not have this screen yet. Today
   it is `POST /api/peerings` with `"purpose":"relay"`; see `PROTOCOL.md` §7.5.)*
4. From then on the sensor reports through the hub, and the app shows its readings as the
   sensor's own.

## Limits worth knowing

| | |
|---|---|
| Sensors per hub | up to 8 pairings (`MAYA_MAX_PEERS` in the library); each sensor is one pairing |
| Frames held waiting for the server | 32. When full it drops the **newest** and says so in the audit |
| Frames taken from one sensor | 12 a minute; a burst after a sensor flushes its buffer fits |
| Frames per message to the server | 16 |

## What a hub cannot do

It holds **no key** for its sensors. It cannot read their readings' authenticity, alter
them, forge one, or replay an old one — the server checks every frame itself. What it
*can* do is delay or drop frames; the audit shows when it has (the sensor's count of what
it sent against what the hub says it received). If a hub dies, the sensors notice after
three missed acknowledgements, switch to reporting through the server, and the app tells
the family which hub to check.

> **Not yet run on real boards.** Everything here is built, compiled for the ESP32 and
> tested against the real server with the radio simulated — no frame has crossed a real
> ESP-NOW link. The first test is one hub and one sensor on a bench.
