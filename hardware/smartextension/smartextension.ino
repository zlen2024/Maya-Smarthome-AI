/*
  Maya Smart Extension — 3 switchable channels.

  This sketch used to carry its own BLE provisioning, WiFi and WebSocket code
  (~650 lines). All of that now lives in the Maya library
  (hardware/libraries/Maya) and speaks the Maya Device Protocol v2
  (PROTOCOL.md). What is left is what is particular to this board: three outputs.

  Install the library first — see SETUP.md. Build with the
  "Huge APP (3MB No OTA/1MB SPIFFS)" partition scheme.

  Behaviour a user or the app can rely on, unchanged from the old firmware:
  - BLE provisioning for WiFi / server URL / PIN when the board has no WiFi saved,
    advertising as "Maya-<device id>"; the same characteristics and status codes.
  - The PIN rules: 4 digits, never 0000/1111/1234; an unclaimed board takes the
    first owner's PIN.
  - Every flash starts clean (saved WiFi and PIN are wiped).
  - All three outputs start OFF.
  - It answers the old protocol-1 commands (output_on/off/toggle, all_on/all_off,
    led_on/led_off/toggle, get_status), so it still works against a server that
    has not been upgraded.

  New: it describes itself to the server (three switches ch1..ch3), so the app
  draws them from that description, and it can be paired with other Maya devices.
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

// The key, and what a person sees until they rename it in the app. Keys are
// permanent: a parent's permissions and a channel's name are filed under them, and
// the old protocol's commands address "ch1".."ch3" — do not change them.
const char* const KEYS[NUM_OUTPUTS]   = {"ch1", "ch2", "ch3"};
const char* const LABELS[NUM_OUTPUTS] = {"Channel 1", "Channel 2", "Channel 3"};

Maya maya("smart_extension_3ch", "2.0.0");

void drive(int channel, bool on) {
  digitalWrite(OUTPUT_PINS[channel], (on != RELAY_ACTIVE_LOW) ? HIGH : LOW);
}

void setup() {
  for (int i = 0; i < NUM_OUTPUTS; i++) {
    pinMode(OUTPUT_PINS[i], OUTPUT);
    drive(i, false);                       // off before anything can ask otherwise

    // The handler runs when the app, Maya, a legacy command or a paired device asks
    // for this channel, and returns true once the pin has been driven.
    maya.addSwitch(KEYS[i], LABELS[i], [i](bool on) { drive(i, on); return true; });

    // Tell the library the pin is off at boot, so the first report is true.
    maya.setSwitch(KEYS[i], false);
  }

  maya.setName("Smart Extension");   // the name for the app to offer (the app prefills the name field with it from app 1.2.0); the owner can still change it
  maya.enableHealth();   // signal strength, uptime and firmware version in the device card
  maya.begin();          // provisioning, WiFi, server link, local link
}

void loop() {
  maya.loop();
}
