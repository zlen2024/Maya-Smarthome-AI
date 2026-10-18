// TEMPLATE - a battery sensor that wakes, reads, reports and sleeps (sensor-only class,
// PROTOCOL.md 5.7 / 5.9). Copy this folder, rename the folder AND this file to the same
// name, then change the lines marked CHANGE.
//
// Sensor-only means NOTHING WRITABLE: a sleeping device cannot be told anything. Do not
// declare a switch, a range or a button here. If it needs calibrating, do it in a setup
// mode over Serial (see hardware/smart_jar/smart_jar.ino).
//
// The first power-on needs Bluetooth setup and WiFi once. After that it reports through a
// paired hub over ESP-NOW when it can, and over WiFi when it cannot.
//
// Not measured: the sleeping current. Measure it with a meter before promising a battery life.
#include <Maya.h>

Maya maya("my_sensor", "1.0.0");            // CHANGE

// CHANGE: pins. ADC1 only (WiFi switches ADC2 off): GPIO 0-4 on a C3, 32-39 on an ESP32.
#if CONFIG_IDF_TARGET_ESP32C3
const int SENSOR_PIN = 3;
const int BATT_PIN   = 2;                   // battery divider midpoint, or remove _batt
#else
const int SENSOR_PIN = 34;                  // input only
const int BATT_PIN   = 35;                  // input only
#endif
const uint32_t SLEEP_SECONDS = 300;         // CHANGE: how often it reports

float readSensor() {
  return analogRead(SENSOR_PIN) * 100.0f / 4095.0f;   // CHANGE: your part
}

float readBatteryPercent() {
  // CHANGE: 1 M + 470 k divider into BATT_PIN, with 100 nF across the lower leg.
  // This placeholder only keeps the template compiling.
  return constrain(analogRead(BATT_PIN) * 100.0f / 4095.0f, 0, 100);
}

void setup() {
  maya.setName("My sensor");                // CHANGE
  maya.addNumber("level", "Level").readOnly().unit("%").limits(0, 100).history();
  maya.addReserved("_batt");                // the battery in the card header

  maya.beginSensor();                       // NOT begin(): it does not join WiFi

  maya.setNumber("level", readSensor());
  maya.setNumber("_batt", readBatteryPercent());
  maya.reportNow();                         // the hub if it can, the server if it cannot
  maya.sleepFor(SLEEP_SECONDS);             // deep sleep; does not return
}

void loop() {}
