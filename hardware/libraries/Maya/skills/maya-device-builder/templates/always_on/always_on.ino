// TEMPLATE - an always-on Maya device (USB or mains). Copy this folder, rename the folder
// AND this file to the same name (Arduino needs them equal), then change the lines marked
// CHANGE. Everything else is the shape every device has.
//
// Compiles for ESP32 and ESP32-C3. See ../../SKILL.md and ../../references/.
#include <Maya.h>

Maya maya("my_device", "1.0.0");            // CHANGE: model (what kind of device), firmware version

// CHANGE: pins. Check references/api-cheatsheet.md for strapping and input-only pins.
#if CONFIG_IDF_TARGET_ESP32C3
const int OUTPUT_PIN = 4;
const int SENSOR_PIN = 3;                   // ADC1: GPIO 0-4 on a C3 (GPIO5 is ADC2: unusable with WiFi)
#else
const int OUTPUT_PIN = 4;
const int SENSOR_PIN = 34;                  // ADC1, input only: 32-39 on an ESP32 (ADC2 dies with WiFi)
#endif

float readSensor() {
  // CHANGE: read your part. Return the value in the unit you declare below.
  // A raw analog read is shown only so the template runs.
  return analogRead(SENSOR_PIN) * 100.0f / 4095.0f;
}

void setup() {
  pinMode(OUTPUT_PIN, OUTPUT);
  digitalWrite(OUTPUT_PIN, LOW);            // a safe state before WiFi comes up

  maya.setName("My device");                // CHANGE: what a person would call it

  // CHANGE: say what this device can do. Keys are permanent: [a-z0-9_], up to 24 chars.
  maya.addSwitch("power", "Power", [](bool on) {
    digitalWrite(OUTPUT_PIN, on ? HIGH : LOW);
    return true;                            // true only if the hardware did it
  });
  maya.addNumber("level", "Level").readOnly().unit("%").limits(0, 100).history();
  maya.addText("note", "Status", 60).readOnly();   // the device's own sentence about itself
  maya.enableHealth();                      // signal strength, uptime, firmware in the card

  maya.begin();                             // Bluetooth setup, WiFi, server link
}

void loop() {
  maya.loop();                              // keep this fast; never delay() for seconds

  static unsigned long last = 0;
  static float lastReported = -1000;
  if (millis() - last >= 2000) {            // read on a timer
    last = millis();
    float v = readSensor();
    if (fabsf(v - lastReported) >= 1.0f) {  // a deadband: do not report noise
      lastReported = v;
      maya.setNumber("level", v);
      maya.setText("note", v < 10 ? "Running low" : "All good");
    }
  }
}
