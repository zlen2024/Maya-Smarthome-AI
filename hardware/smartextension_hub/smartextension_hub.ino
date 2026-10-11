/*
  Maya Smart Extension Hub — 3 switchable channels, and a hub for other ESP32s.

  The same board as hardware/smartextension, with one addition: it carries the
  readings of battery sensors (see the HubSensor example in hardware/libraries/Maya)
  to the server over ESP-NOW. A sensor that reports through a hub lasts roughly three
  times as long on its batteries as one that joins WiFi every time (PROTOCOL.md 5.9).

  A hub is an optimisation, never a requirement: a house without one still works,
  more slowly. So this board behaves exactly like the plain extension if no sensor is
  ever paired to it.

  What it does for a sensor, and what it cannot do:
  - It takes frames from the sensors a person has paired to it, and forwards them to
    the server byte for byte. It queues up to 32, takes at most 12 a minute from one
    sensor, and drops anything malformed.
  - It holds NO key for its sensors (PROTOCOL.md 7.5). It cannot read, alter, forge or
    replay what it carries; the server checks every frame itself. It can only delay or
    drop frames, and the audit in the app shows when it has.
  - It tells the server which WiFi channel it is on, so a router that moves does not
    silently strand every sensor.

  Install the library first — see SETUP.md. Build with the
  "Huge APP (3MB No OTA/1MB SPIFFS)" partition scheme.

  Everything the plain extension promises still holds: BLE provisioning advertising
  as "Maya-<device id>", the PIN rules, every flash starting clean, all outputs OFF at
  boot, and the protocol-1 commands still answered.
*/
#include <Maya.h>

// ─── Outputs ─────────────────────────────────────────────────
// GPIO2 is the built-in LED on most ESP32 boards, so channel 1 can be tested
// without wiring anything. Swap the pins for your relay IN pins.
#define NUM_OUTPUTS 3
const int OUTPUT_PINS[NUM_OUTPUTS] = {2, 4, 5};

// Many relay modules energise when their input is LOW. Set this to true if yours
// does: "on" then drives the pin LOW, and the pin idles HIGH so nothing clicks on
// at boot. (Leave false for LEDs and active-HIGH modules.)
const bool RELAY_ACTIVE_LOW = false;

// Keys are permanent: a parent's permissions and a channel's name are filed under
// them, and the old protocol's commands address "ch1".."ch3" — do not change them.
const char* const KEYS[NUM_OUTPUTS]   = {"ch1", "ch2", "ch3"};
const char* const LABELS[NUM_OUTPUTS] = {"Channel 1", "Channel 2", "Channel 3"};

Maya maya("smart_extension_hub", "1.0.0");

void drive(int channel, bool on) {
  digitalWrite(OUTPUT_PINS[channel], (on != RELAY_ACTIVE_LOW) ? HIGH : LOW);
}

void setup() {
  for (int i = 0; i < NUM_OUTPUTS; i++) {
    pinMode(OUTPUT_PINS[i], OUTPUT);
    drive(i, false);                       // off before anything can ask otherwise
    maya.addSwitch(KEYS[i], LABELS[i], [i](bool on) { drive(i, on); return true; });
    maya.setSwitch(KEYS[i], false);
  }

  maya.enableHealth();   // signal strength, uptime and firmware version in the device card
  maya.enableHub();      // before begin(): identify then says "hub", and the queue is allocated
  maya.begin();          // provisioning, WiFi, server link, local link
}

void loop() {
  maya.loop();
}
