// A battery sensor that reports through a hub.
//
// It wakes, reads, hands the reading to a hub over ESP-NOW (no WiFi, no TLS: a few
// hundred milliseconds), and sleeps. That is what makes a coin-cell or 3xAA sensor
// last years instead of months (PROTOCOL.md 5.9).
//
// Setup, once:
//   1. Flash it and provision it like any Maya device. It needs WiFi and the server
//      one time, to be claimed and to be paired.
//   2. In the app, pair it to a hub (a device running enableHub(), such as the
//      SmartExtensionHub example) with a *relay* pairing, and tick the keys the hub
//      may carry: "salt" and the battery.
//   3. From then on it reports through the hub, and visits WiFi about once a day to
//      refresh its pairing and learn the hub's channel.
//
// If the hub does not answer three times in a row, it reports through the server
// instead and the server tells the family which hub to check. If both are down, it
// keeps the last 16 readings and sends them when either comes back.
//
// Use a bare ESP32 module, not a DevKit: a DevKit's USB chip draws more asleep than
// this whole design budget. A load cell bridge also draws continuously while powered -
// switch it off between reads.
#include <Maya.h>

Maya maya("salt_jar", "1.0.0");

const int SALT_PIN = 34;      // swap for your HX711 / ultrasonic / whatever reads the level
const int BATT_PIN = 35;      // battery through a divider

float readSalt() { return analogRead(SALT_PIN) * 100.0 / 4095.0; }
float readBattery() { return analogRead(BATT_PIN) * 100.0 / 4095.0; }

void setup() {
  maya.setName("Salt jar");
  maya.addNumber("salt", "Salt left").readOnly().unit("%").history();
  maya.addReserved("_batt");          // the battery, in the card header (5.3)

  maya.beginSensor();                 // not begin(): it does not join WiFi

  maya.setNumber("salt", readSalt());
  maya.setNumber("_batt", readBattery());
  maya.reportNow();                   // the hub if it can, the server if it cannot

  maya.sleepFor(300);                 // five minutes; does not return
}

void loop() {}
