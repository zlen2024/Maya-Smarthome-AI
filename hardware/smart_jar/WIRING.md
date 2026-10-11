# Smart Jar — Wiring

A jar on a load cell. The ESP32-C3 reads the cell through an HX711 and reports **weight
(g)** and **level (%)** to Maya.

> **Status:** the firmware compiles for the ESP32-C3. **Nothing here has been wired or run
> on a board.** Wire it on a breadboard first and check each item in the checklist.

## Parts

| Part | Notes |
|---|---|
| ESP32-C3 board | A "SuperMini" or any C3 dev board with GPIO 3, 6, 7, 10 and 20 exposed |
| HX711 module | The usual green/red breakout with 4 load-cell terminals and 4 header pins |
| 5 kg bar load cell | The strain-gauge bar with 4 wires and a hole at each end |
| Push button | Only for the battery build (setup mode) |
| 1 MΩ + 470 kΩ resistors, 100 nF capacitor | Only for the battery build (battery divider) |
| 3 × AA cells + holder | Only for the battery build |
| Jumper wires, breadboard | |

## Pin assignment (ESP32-C3)

| Signal | C3 GPIO | Goes to |
|---|---|---|
| HX711 DT (data) | **6** | HX711 `DT` |
| HX711 SCK (clock) | **7** | HX711 `SCK` |
| HX711 power switch | **10** | HX711 `VCC` (see Power) |
| Ground | `GND` | HX711 `GND` |
| Battery sense | **3** | Divider midpoint (battery build) |
| Setup button | **20** | One leg of the button; the other leg to `GND` (battery build) |

Why these pins: GPIO 0–5 are the only pins that can wake a C3 from deep sleep, and they are
left free for the wake-up radio planned in [`ITERATION_4_1.md`](../../ITERATION_4_1.md).
GPIO 9 is **not** used for the button on purpose — held low at reset it puts the chip in
download mode.

To change a pin, edit the constants at the top of `smart_jar.ino`.

## The load cell → HX711

A 5 kg bar cell has four wires. The **common** colour code is below, but **it is not
universal — check the sheet that came with yours.**

| Load-cell wire | HX711 terminal |
|---|---|
| Red | `E+` |
| Black | `E−` |
| White | `A−` |
| Green | `A+` |

If the reading goes **down** when you press on the cell, swap the white and green wires
(`A+` / `A−`). Nothing is damaged by trying it the wrong way round.

## The whole thing

Both builds:

```
  ┌─────────────┐           ┌─────────────────────────┐           ┌──────────────┐
  │  5 kg load  │           │          HX711          │           │   ESP32-C3   │
  │    cell     │           │                         │           │              │
  │         red ├───────────┤ E+                  VCC ├───────────┤ GPIO10       │  switched 3.3 V  (C3 → HX711)
  │       black ├───────────┤ E−                   DT ├───────────┤ GPIO6        │  data            (HX711 → C3)
  │       white ├───────────┤ A−                  SCK ├───────────┤ GPIO7        │  clock           (C3 → HX711)
  │       green ├───────────┤ A+                  GND ├───────────┤ GND          │
  │             │           │                         │           │              │
  └─────────────┘           └─────────────────────────┘           └──────────────┘
```

Battery build only, in addition:

```
                                                       ┌──────────────┐
  3 × AA  (+) ──────┬──────────────────────────────────┤ 5V / VIN     │
    4.5 V           │                                  │              │
                   ┌┴┐                                 │              │
                   │ │  1 MΩ                           │              │
                   └┬┘                                 │              │
                    ●──────────────┬───────────────────┤ GPIO3        │  battery sense
                   ┌┴┐             │                   │              │
                   │ │  470 kΩ   ──┴──                 │   ESP32-C3   │
                   └┬┘           ──┬──  100 nF         │              │
                    │              │                   │              │
  3 × AA  (−) ──────┴──────────────┴──┬────────────────┤ GND          │
                                      │                │              │
                                      │  setup button  │              │
                                      └──o    o────────┤ GPIO20       │
                                                       └──────────────┘
```

The setup button joins GPIO20 to GND while it is held; hold it while switching on.

HX711 `VCC` comes from **GPIO10**, not straight from 3.3 V. That lets the sketch switch the
HX711 and the load cell off while the board sleeps, because a load-cell bridge draws current
the whole time it is powered. If you would rather power it from the 3.3 V pin, move the red
`VCC` wire there and set `hxPower()` to do nothing.

## Power

### USB / mains build (`JAR_BATTERY 0`, the default)

Power the board over USB. Nothing else is needed. It is always on and reports every few
seconds when the weight changes by 2 g or more.

### Battery build (`JAR_BATTERY 1`)

- **Three AA cells in series** (4.5 V fresh) into the board's `5V`/`VIN` pin and `GND`, so
  the board's own regulator makes 3.3 V. Do not connect them to the `3V3` pin, and do not
  charge alkaline cells. Check your board has a regulator on that pin; some do not.
- The regulator stops holding 3.3 V when the cells fall to about 3.5 V, so the sketch calls
  **3.4 V empty and 4.5 V full**. An alkaline AA is flat for most of its life, so this is a
  rough gauge, not a fuel gauge.
- Battery sense: **1 MΩ** from battery `+` to GPIO3 and **470 kΩ** from GPIO3 to `GND`, with
  a **100 nF** capacitor across the 470 kΩ. The high values keep the divider's own drain to
  about 3 µA (a 100 kΩ pair would drain over 20 µA, which is large next to deep sleep), and
  the capacitor gives the ADC a steady source despite them. 4.8 V fresh reads 1.5 V, inside
  the ADC's range.
- **Do not trust the battery life until you measure it.** A dev board's LDO and power LED
  can draw far more than the C3 does in deep sleep. Remove the power LED (or choose a board
  without one) and measure the sleeping current with a meter. The library notes the same
  for any battery sensor (`PROTOCOL.md` §5.9).
- **Check the GPIO current:** GPIO10 powers the HX711 and the bridge. A 1 kΩ bar cell at 3.3 V
  draws about 3 mA and the HX711 about 1.5 mA — within what a pin can give — but measure
  yours. A 350 Ω cell draws about 9 mA, and then a transistor or load switch is the safer
  choice.

## Mounting the load cell

The bar flexes; that flex is what is measured. It only works if one end is fixed and the
other end is free.

From the top down — the load passes through the bar, never around it:

```
                                        │ load
                                        ▼
                                 ┌─────────────┐
                                 │     jar     │
              ┌──────────────────┴─────────────┴──────────────────┐
              │                     platform                      │  ← touches nothing else
              └─────────────────────────────────────┬────────┬────┘
                                                    │ spacer │
      ┌─────────────────────────────────────────────┴────────┴────┐
      │                load cell bar      (its arrow ↓)           │  ← this bar bends
      └────┬────────┬─────────────────────────────────────────────┘
           │ spacer │
  ─────────┴────────┴──────────────────────────────────────────────────  base, fixed to the table

          FIXED end                                      FREE end
```

- Fix **one end** to the base with a spacer (a nut or washer) so the other end is free to
  move down. Put the platform on the **other** end, also on a spacer.
- The platform must not touch the base, or anything else, when loaded. A touch is the most
  common reason for readings that drift.
- The arrow printed on the cell points in the direction of the load.
- **Limit:** the cell is rated 5 kg. Keep jar + contents + platform **under about 3.5 kg**.
  Pushing past 5 kg can permanently damage the cell.

## Checklist before powering on

- [ ] Load-cell wires are in the right terminals (red `E+`, black `E−`, white `A−`, green `A+`) — or whatever *your* sheet says
- [ ] HX711 `VCC` goes to **GPIO10**, `GND` to `GND`, `DT` to GPIO6, `SCK` to GPIO7
- [ ] The cell has one fixed end and one free end, and the platform touches nothing
- [ ] Jar + contents will stay under 3.5 kg
- [ ] (Battery build) the divider and button are wired, and the power LED is removed

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Serial log: `HX711 not answering` | `DT`/`SCK` swapped, no power, loose wire | Check GPIO6 → `DT`, GPIO7 → `SCK`, and that GPIO10 is driving `VCC` |
| Reading goes down when you press | `A+` / `A−` swapped | Swap the white and green wires |
| Reading drifts steadily | The platform is touching something, or the cell is warming up | Free the platform; wait a few minutes after power-on |
| Reading jumps around by many grams | Loose wire, long leads, noisy USB supply | Shorten the leads; keep them away from the antenna; try another supply |
| `calibrate refused` | The known weight is not on the jar, or you did not tare first | Tare with the jar empty, then put the known weight on |
| Weight is right but level is wrong | "Full at" is not what the full jar weighs | Set **Full at** to the contents' weight when the jar is 100 % full |
| Board does not run my sketch when I hold the button | You used the BOOT button (GPIO9) | Use a button on GPIO20 instead |
