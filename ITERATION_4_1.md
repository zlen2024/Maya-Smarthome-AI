# Iteration 4.1 — wake-up radio for sleepy devices

Branch base: `dev-itteration-4` (protocol v2, spec rev 2.5).
Status: **plan only.** Nothing below is built, and nothing has run on hardware.

## The problem

A sleepy device (§7, battery, deep sleep) cannot be woken by ESP-NOW: in deep sleep
the ESP32's radio is off, so it hears nothing. Today it only learns about a command
when it wakes on its own timer and **polls** the hub, so command latency equals the
poll interval (5 min ≈ 1 year on 3×AA).

## The feature

Give a sleepy device a second, tiny, always-listening receiver. The hub sends a
"wake" signal on that radio; the receiver pulls a GPIO pin; the pin wakes the ESP32
from deep sleep; the ESP32 then does the normal ESP-NOW poll.

```
Hub ──("wake" signal, 433 MHz)──> [small receiver, µA, always listening]
                                      │ raises a pin
                                      ▼
                                GPIO (ext0/ext1 wake) ──> ESP32 wakes from deep sleep
                                      │
                                      ▼
                          ESP-NOW to hub: "anything for me?"  (existing §7 poll)
```

Only the *wake* is new. The command still travels as a signed ESP-NOW frame from
the hub's queue, so nothing in the trust model changes.

## Design rules

1. **The wake signal carries no command and no authority.** It means "poll now" and
   nothing else. A forged or replayed wake can only cost battery, never control a device.
2. **The command path is unchanged**: signed frame, `(ep,seq)` replay protection, the
   hub never holds the device key (§7.5).
3. **Optional per device.** No wake radio → the device polls on its timer exactly as
   before. Wake is an addition to sleepy, not a replacement.
4. **Latency target:** a few hundred ms from queued command to the device acting.
5. **Fail safe:** if the wake is missed, the timer poll still delivers the command.

## Work

### Spec
- [ ] New §7.x "Wake-up radio": signal meaning, per-device addressing, rate limit, what a missed or spoofed wake does.
- [ ] Descriptor/announce flag so the server knows a sleepy device is wakeable (e.g. `wake:"433"`), and the hub knows which wake address to send.
- [ ] Battery table for the wake path, from **measurements** rather than the estimates used so far.

### Hub
- [ ] Transmitter module on the hub (433 MHz OOK to start; LoRa/nRF only if range or addressing demands it).
- [ ] When a command is queued for a wakeable sleepy device: send the wake, keep the command queued, serve it when the poll arrives.
- [ ] Repeat the wake a few times; stop on poll, give up after a limit and rely on the timer poll.
- [ ] Rate limit wakes per device so a flood of commands cannot drain a battery.

### Library (`hardware/libraries/Maya`)
- [ ] `wakePin` / wake-source option: configure GPIO wake from the receiver pin (`ext0`/`ext1` on classic ESP32; `esp_deep_sleep_enable_gpio_wakeup` on ESP32-C3, see Hardware on hand).
- [ ] On wake-by-pin: run the poll immediately instead of waiting for the timer.
- [ ] Example `SleepyValve` (or similar) with the receiver wired up.

### Server
- [ ] Surface "queued, waking device" vs "queued, next poll" so Maya and the app report honestly instead of "done".
- [ ] Persist the wake address per device.

### Tests (existing style: TestClient + host driver, with mutation checks)
- [ ] Wake does not change what a command may do (same MAC, same replay checks).
- [ ] Missed wake → timer poll still delivers.
- [ ] Wake rate limit holds.
- [ ] Deliberate bugs (ignore the limit, accept an unsigned command on wake) must each fail a test.

### Bench (the part that decides if this is worth keeping)
- [ ] Measure idle current with the receiver attached (datasheet µA figures are not the same as a real board).
- [ ] Measure wake-to-action latency and wake range through a wall.
- [ ] Measure false wakes per day (433 MHz is noisy); each one costs a poll.

## Hardware on hand

Owner has ESP32-C3 boards and a radio module with an antenna (aerial). Which module
it is (433 MHz receiver, LoRa, other) is **not yet recorded** — confirm before building.

- **ESP32-C3 as the sleepy device: works, but the wake API differs.** The C3 has no `ext0`/`ext1`. It wakes from deep sleep on GPIO0–GPIO5 via `esp_deep_sleep_enable_gpio_wakeup()`, so the receiver's output pin must be wired to one of those. It has no ULP coprocessor, so nothing can "watch" the pin while the CPU is off except the wake logic itself.
- **ESP32-C3 supports ESP-NOW**, so the poll after wake is unchanged.
- **The antenna helps the wake radio, not the ESP-NOW link.** A proper antenna on the wake receiver raises its sensitivity and range (a quarter-wave wire for 433 MHz is about 17 cm). It also hears more noise, so false wakes can go up, not down. Measure both (see Bench).
- **An external antenna on the C3's own WiFi** improves ESP-NOW range, but it cannot wake a device in deep sleep.
- **Hub side:** the transmitter needs its own antenna too; range is limited by the weaker end.

Status: untested. Nothing here has been wired or measured yet.

## Open questions

- Which receiver? A simple 433 MHz OOK module is cheap but noisy and addressless; LoRa or nRF is addressed and longer range but costs more idle current and parts.
- How is one device addressed without waking all of them? A short per-device code in the signal, or one receiver per device pair?
- Does a false-wake rate low enough exist at 433 MHz, or does the idle-current saving vanish once false wakes are counted?
- Which GPIO (0–5) on the C3 board is free for the receiver pin once the board's own pins are accounted for?
- Hub cost and complexity: is a second radio on the hub acceptable, or should this be a separate "wake beacon" board?

## Not in scope

Light sleep with an ESP-NOW wake window (another way to cut latency) and a general
`listening` class. Both are alternatives to this feature, not part of it.

## Done when

A queued command reaches a battery device in deep sleep within about a second on
real boards, with measured idle current and false-wake rate written into the spec,
and the tests above passing with their mutations caught.

## Test device: the Smart Jar

`hardware/smart_jar/` (ESP32-C3 + HX711 + 5 kg load cell) is a battery sensor and is the
natural first device for this feature. Its battery build already sleeps and reports every
five minutes; a wake radio would let a person force a fresh weigh on demand. Its firmware
compiles; none of it has run on a board. See its `WIRING.md` and `SETUP.md`.
