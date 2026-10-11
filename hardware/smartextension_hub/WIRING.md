# Smart Extension Hub — Wiring

**The wiring is the [Smart Extension's](../smartextension/WIRING.md), unchanged:** three
outputs on GPIO 2, 4 and 5, LEDs for prototyping or relay modules for mains, and the
`RELAY_ACTIVE_LOW` constant in the sketch for active-LOW modules. Read that guide for the
pin table, the relay diagrams, power, and the command reference — all of it applies.

The hub needs **no extra hardware**. ESP-NOW is part of the ESP32's own radio, so there is
no module to add and no pin it uses.

## What is different

| | Smart Extension | Smart Extension Hub |
|---|---|---|
| Sketch | `hardware/smartextension/smartextension.ino` | `hardware/smartextension_hub/smartextension_hub.ino` |
| Says `hub:true` at identify | no | yes |
| Carries other devices' readings | no | yes, after a person pairs a sensor to it |
| Model reported to the server | `smart_extension_3ch` | `smart_extension_hub` |
| RAM | baseline | about 9 KB more once the queue is allocated (32 frames of up to 250 bytes) |

Its protocol-2 and protocol-1 commands, reboot, factory reset, state reports and
pairing with other devices are identical.

## What the hub says to the server

In addition to the Smart Extension's frames:

```json
{"id":"esp32-9f83b1c1","type":"hub_status","channel":6}
{"id":"esp32-9f83b1c1","type":"relay","frames":["{\"v\":2,\"from\":\"esp32-ab12cd34\",...}.<mac>"]}
```

`hub_status` goes out after every connection and whenever the WiFi channel changes. `relay`
carries up to 16 sensor frames exactly as they arrived. The server answers with a
`relay_ack` giving one result per frame. `PROTOCOL.md` §7.5 defines both.

## Checklist before flashing

- [ ] Everything in the Smart Extension's checklist (libraries, **Huge APP**, board, port)
- [ ] `RELAY_ACTIVE_LOW` set correctly for your relay modules
- [ ] The hub will be **mains-powered and always on**, and within radio range of its sensors

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Hub works as an extension but the app offers no relay pairing | The device did not say `hub:true` | Flash `smartextension_hub.ino`, not `smartextension.ino` |
| A paired sensor's readings never arrive | Different WiFi channel | Check the hub's channel in the Serial log; the sensor learns it on its next WiFi visit |
| Sensor readings arrive late or in bursts | Hub out of range for the sensor, retries | Move the hub closer; the sensor buffers up to 16 readings and sends them when it can |
| The app says a sensor could not reach its hub | Three missed acknowledgements | Check the hub is powered and in range; the sensor reports through the server meanwhile |
| Audit shows frames sent but not received | Hub dropped them (queue full, rate limit) or never heard them | Fewer sensors per hub, or a second hub |
| Everything from the Smart Extension's troubleshooting table | — | See [its WIRING.md](../smartextension/WIRING.md#troubleshooting) |
