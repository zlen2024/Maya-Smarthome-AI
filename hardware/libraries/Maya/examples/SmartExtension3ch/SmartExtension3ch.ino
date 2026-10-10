// The 3-channel smart extension, on the library.
//
// This is hardware/smartextension/smartextension.ino without the 650 lines of
// provisioning, WiFi and WebSocket plumbing: the library owns those. What is left
// is what is particular to this board - three outputs.
//
// Swap the LED pins for relay IN pins when you wire the real thing.
#include <Maya.h>

Maya maya("smart_extension_3ch", "2.0.0");

const int PINS[3] = {2, 4, 5};   // GPIO2 is the on-board LED on most ESP32 boards

void setup() {
  for (int i = 0; i < 3; i++) {
    pinMode(PINS[i], OUTPUT);
    digitalWrite(PINS[i], LOW);
  }

  // Keys ch1..ch3 are what a protocol-1 server's legacy commands address, so the
  // board keeps working against a server that has not been upgraded yet.
  maya.addSwitch("ch1", "Channel 1", [](bool on) { digitalWrite(PINS[0], on); return true; });
  maya.addSwitch("ch2", "Channel 2", [](bool on) { digitalWrite(PINS[1], on); return true; });
  maya.addSwitch("ch3", "Channel 3", [](bool on) { digitalWrite(PINS[2], on); return true; });

  // Tell the library what the pins are at boot, so identify reports them.
  for (int i = 0; i < 3; i++) {
    char key[4] = {'c', 'h', (char)('1' + i), 0};
    maya.setSwitch(key, false);
  }

  maya.enableHealth();   // signal strength, uptime and firmware version in the card header
  maya.begin();
}

void loop() {
  maya.loop();
}
