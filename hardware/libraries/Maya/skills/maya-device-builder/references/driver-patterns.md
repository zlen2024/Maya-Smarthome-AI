# Driver patterns

The library has no idea what your part is. These are the patterns that keep a driver from
fighting it. `hardware/smart_jar/smart_jar.ino` is a complete worked example (HX711 load
cell: bit-banged read, median filter, one-point-plus-zero calibration, two power builds).

## Read on a timer, never in a handler

```cpp
static unsigned long last = 0;
if (millis() - last >= 1000) { last = millis(); readAndReport(); }
```

`loop()` must return quickly: `maya.loop()` keeps WiFi and the server link alive.

## Filter, then deadband

Take several samples, use the **median** (a spike cannot move it), and only call
`setNumber` when the value moved more than the noise:

```cpp
if (fabsf(v - lastReported) >= 2.0f) { maya.setNumber("weight_g", v); lastReported = v; }
```

The library already skips an unchanged value, but a value that jitters by 0.1 changes every
pass and would send four frames a second.

## Settings that must survive a reflash

The library wipes the `"iotdata"` Preferences namespace on every new build (WiFi, PIN).
Anything the user did on purpose (calibration, schedules) goes in **your own namespace**:

```cpp
Preferences p; p.begin("mydevice", false); p.putFloat("scale", s); p.end();
```

Say in the README that erasing the whole flash (an "Erase All Flash" upload) loses it.

## Calibration is a control, so protect it

Anything that changes what later readings mean: `.confirm()` so a person approves, and
`.agentDeny()` so Maya cannot press it. On a battery (sensor-only) build there are no
controls, so offer a **setup mode** over Serial (a held button at power-on, a 10-minute
timeout) and say how to enter it. Print what was stored.

## Power a hungry part only while reading

A load-cell bridge or a sensor heater draws current the whole time it has power. Switch it
from a GPIO (if it needs less than ~10 mA, else a transistor/load switch), read, switch off
before `sleepFor()`. Let it settle after switching on (an HX711 needs ~400 ms).

## Battery

Report `_batt` (`addReserved("_batt")`, `setNumber("_batt", pct)`). Divide the cell voltage to
the ADC with a **high-value divider** (1 M + 470 k) plus a 100 nF capacitor across the lower
leg, or the divider itself drains more than deep sleep. Convert voltage to percent with the
*regulator's* dropout in mind: 3 x AA gives ~4.5 V, a 3.3 V regulator quits near 3.5 V.
**Measure the sleeping current with a meter** before claiming a battery life: a dev board's
regulator and power LED can draw 100 times the chip.

## Timed actuators (pumps, valves, heaters, locks)

Whatever can hurt something gets its limits in firmware, because the firmware is the only
part still running when WiFi drops or an agent asks twice. `templates/timed_actuator` does all
of this; the rules, in order of how much damage skipping them does:

1. **Off at boot**, in `setup()` before anything else, and a ~10 k resistor from the driver's
   gate/base to GND so the output stays off while the chip resets or is being flashed.
2. **A hard cap on one run**, checked in `loop()` with `millis()` (never `delay()` the run). The
   cap is a constant of the *hardware*; the declared `addDuration` maximum should equal it.
3. **A cooldown and a daily total**, or ten polite 10-second requests are a flood.
4. **Report the state back**, including when the device ended the run itself (`setSwitch`).
5. **`.confirm()`** on the control so Maya asks a person; **`.agentDeny()`** if no automation
   should ever start it.
6. **Electrical:** a logic-level MOSFET or transistor (the pin drives the gate, never the load);
   a flyback diode across any motor, pump or coil; a separate supply for the load with a common
   ground; check the 3.3 V rail does not sag when the load starts (that is a brown-out reset
   mid-run, with the output left however it was).
7. A moisture or level sensor is an input, not a safeguard: a stuck sensor must not be able to
   extend the cap.

## Faults are a capability too

A broken sensor is information. Add a read-only text key (`note`) and say it in words:
"HX711 not answering - check wiring". The device speaks for itself; nothing else parses it.
Print the same line on Serial with a `[mydevice]` prefix.

## Do not

- Use `String` concatenation in a hot loop (heap fragmentation on a board that runs for months).
- Call `delay()` for more than ~100 ms in `loop()` on an always-on device.
- Write to flash (Preferences) every pass; wear it only when a value changed.
- Print a reading every pass; every few seconds is plenty.
