// The 3-channel smart extension that is also a hub.
//
// It switches three outputs like SmartExtension3ch, and in addition carries the
// readings of battery sensors (HubSensor) to the server over ESP-NOW. One line
// makes the difference: maya.enableHub().
//
// A hub is an optimisation, never a requirement (PROTOCOL.md 5.9): a house without
// one still works, more slowly. Put it where it has mains power and a clear path to
// the sensors - range is measured to the hub, not to the router.
//
// It holds no key for its sensors, so it cannot read or alter what it carries; the
// server checks every frame. It does queue up to 32 frames, takes at most 12 a minute
// from one sensor, and tells the server which WiFi channel it is on.
#include <Maya.h>

Maya maya("smart_extension_hub", "1.0.0");

const int PINS[3] = {2, 4, 5};   // GPIO2 is the on-board LED on most ESP32 boards

void setup() {
  for (int i = 0; i < 3; i++) {
    pinMode(PINS[i], OUTPUT);
    digitalWrite(PINS[i], LOW);
  }

  maya.addSwitch("ch1", "Channel 1", [](bool on) { digitalWrite(PINS[0], on); return true; });
  maya.addSwitch("ch2", "Channel 2", [](bool on) { digitalWrite(PINS[1], on); return true; });
  maya.addSwitch("ch3", "Channel 3", [](bool on) { digitalWrite(PINS[2], on); return true; });
  for (int i = 0; i < 3; i++) {
    char key[4] = {'c', 'h', (char)('1' + i), 0};
    maya.setSwitch(key, false);
  }

  maya.enableHealth();
  maya.enableHub();      // before begin(): identify then says "hub", and the queue is allocated
  maya.begin();
}

void loop() {
  maya.loop();
}
