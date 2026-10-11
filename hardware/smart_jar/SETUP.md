# Smart Jar — Setup

This is a [Maya](../libraries/Maya/README.md) device: a jar on a load cell that tells the
app and Maya how much is in it. Wire it first ([WIRING.md](WIRING.md)), then follow this.

> **Status:** compiled for the ESP32-C3 with the Maya library; never run on a board.

## 1. Toolchain

- Arduino IDE or `arduino-cli`, with the **esp32** core (tested with **2.0.17**).
- Libraries: **Maya** (copy `hardware/libraries/Maya` into your Arduino libraries folder),
  **ArduinoJson 6.x**, **WebSockets (links2004) 2.4+**.
- Board: **ESP32C3 Dev Module**.
- **Partition scheme: Huge APP.** BLE + TLS + WiFi does not fit the default partition.
- If your board uses the C3's built-in USB for Serial, enable **USB CDC On Boot** or you
  will see no log.

With `arduino-cli`:

```
arduino-cli compile --fqbn esp32:esp32:esp32c3:PartitionScheme=huge_app \
  --libraries hardware/libraries hardware/smart_jar
```

For the battery build add `--build-property "compiler.cpp.extra_flags=-DJAR_BATTERY=1"`, or
put `#define JAR_BATTERY 1` at the top of `smart_jar.ino`.

## 2. Choose a build

| | Always-on (`JAR_BATTERY 0`) | Battery (`JAR_BATTERY 1`) |
|---|---|---|
| Power | USB / mains | 3 × AA cells |
| Reports | every 5 s when the weight changes ≥ 2 g | every 5 minutes, then deep sleep |
| Reaches Maya | over WiFi | through a hub if paired, else over WiFi |
| Class (spec 5.7) | always-on | **sensor-only**: readings only, nothing writable |
| Tare / calibrate | any time, from the app | **setup mode**, typed in the Serial monitor |
| Start with | this one | after the always-on one works |

Start with the always-on build and its app buttons. Move to battery once weighing works.

## 3. Add it to Maya

1. Flash the sketch. Open the Serial monitor at 115200.
2. The board advertises over Bluetooth as `Maya-<device id>`. In the app, add the device and
   give it your WiFi.
3. It appears as a **Smart Jar** with **Weight** and **Level** (and, in the always-on build only, a **Setup** group
   with **Full at**, **Known weight**, **Tare** and **Calibrate**).
4. The readings stay empty until you calibrate (next step); the Serial log says so.

## 4. Calibrate (once; the steps below are the always-on build, section 5 has the battery build)

The HX711 gives a raw count. It means nothing until you say where zero is and how many counts
make a gram.

1. **Tare:** put the **empty jar** (and lid) on the platform, wait a few seconds so it settles,
   then press **Tare** and confirm.
2. **Pick a known weight:** something whose weight you know — a bag of sugar, a 500 g
   packet, a kitchen-scale-checked item. Set **Known weight** to its weight in grams.
3. **Calibrate:** put that weight **on the jar**, wait, press **Calibrate** and confirm.
   The Serial log prints `calibrated: … counts per gram`. If it says `calibrate refused`, the
   count barely moved: the weight is not on, or you skipped the tare.
4. **Check it:** take the weight off and put it back; you should see the number follow. Try a
   second known item and see whether it reads right. If the numbers are off by a steady
   ratio, calibrate again with a **heavier** known weight — more weight gives a better
   calibration.
5. **Full at:** fill the jar the way you mean to keep it and set **Full at** to the weight of
   the *contents* at 100 %. Level is then `weight ÷ full × 100`.

Tare, calibration, and both numbers are stored in the board's flash and survive a reboot.
They are not backed up anywhere: re-flashing with the flash erased means doing it again.

> **Why Tare and Calibrate ask you to confirm, and why Maya cannot press Calibrate.**
> Both change what every later reading means. Tare needs a person to confirm
> (`confirm()`); Calibrate also carries `agentDeny()`, so Maya never sees it and cannot
> run it. See `PROTOCOL.md` §5.4.

## 5. The battery build

The battery build is a **sensor-only** device (`PROTOCOL.md` §5.7): it declares readings
(`weight_g`, `level`, battery) and **nothing writable**, because a sleeping device cannot be
told anything. So there are no Tare or Calibrate buttons in the app for this build. You do
those once, in **setup mode**, from the Serial monitor.

1. Flash the battery build (`JAR_BATTERY 1`). On first start it provisions over Bluetooth
   like any Maya device (section 3), then enters **setup mode** because it has never been
   calibrated. Later, hold the **setup button** (GPIO20 to GND) while switching on to come
   back to it.
2. Open the Serial monitor at **115200 baud, newline**. Setup mode waits up to 10 minutes and
   understands:

   ```
   tare            zero the scale with the jar empty
   cal <grams>     calibrate with that known weight on the jar, e.g.  cal 500
   full <grams>    the contents' weight at 100 %, e.g.  full 1000
   show            print the raw count, zero, counts per gram and full
   done            leave setup mode
   ```
3. Do it in the order of section 4: empty jar → `tare`; known weight on → `cal <grams>`;
   fill the jar the way you keep it → `full <grams>`; then `done`.
4. In normal use it wakes every 5 minutes, powers the HX711, takes seven readings, takes the
   median, reports, powers the HX711 off and sleeps.
5. To reach Maya through a hub instead of WiFi, pair it to a hub as the library's
   [`HubSensor`](../libraries/Maya/examples/HubSensor/HubSensor.ino) example describes: the
   app's relay pairing, ticking `weight_g`, `level` and the battery.
6. If you would rather use the app's buttons, calibrate with the always-on build first: the
   calibration is stored in flash and the battery build reads the same values. (Erase the
   flash and you do it again.)
7. **Measure the sleeping current.** The sketch does not know how long three AA cells last
   and neither does this guide.

## 6. What the library does, and what you wrote

**The library handles:** Bluetooth provisioning, WiFi, the server link, building the
descriptor from what you declared, answering `set`, the `confirm` and `agent:"deny"` safety
fields, ESP-NOW to a hub and WiFi fallback, deep sleep bookkeeping, and the health values.

**The sketch handles:** reading the HX711 (it is 40 lines; there is no HX711 library), turning
counts into grams, the calibration and where it is stored, and what to declare. A new device
of this kind is the same shape: declare capabilities, read your hardware, call
`setNumber()`.

**What the library cannot do for you:** it has no idea what a load cell is. If you build a
device of another kind it will take whatever capabilities you declare, but the driver for
the part itself — and its calibration — is yours.

## 7. Limits worth knowing

- **5 kg cell:** keep jar + contents + platform under about 3.5 kg.
- **Accuracy:** a bar cell and an HX711 on a breadboard give roughly gram-level readings
  after calibration. Temperature, wiring and mounting move them. This build ignores changes
  under 2 g so the number does not flicker.
- **Calibration is one point plus zero.** A cell that is not linear over its range will be
  slightly off away from the calibration weight.
- **Slow changes are not seen:** it reports every 5 s (always-on) or 5 minutes (battery).
  Taking a spoon of salt out is seen on the next report.
- **Not checked:** the HX711 reading code, the calibration maths, and the battery current have
  not run on real hardware.

## Troubleshooting

See the table in [WIRING.md](WIRING.md#troubleshooting). For app and server problems see the
[Smart Extension's SETUP.md](../smartextension/SETUP.md).
