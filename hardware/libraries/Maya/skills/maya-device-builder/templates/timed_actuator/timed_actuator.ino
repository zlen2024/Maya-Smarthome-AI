// TEMPLATE - something Maya or a person may switch on for a limited time: a pump, a valve,
// a heater, a lock. Copy this folder, rename the folder AND this file to the same name,
// then change the lines marked CHANGE.
//
// The point of this template is the SAFETY THAT LIVES ON THE DEVICE. The app and Maya the
// assistant are not the last line of defence; the firmware is, because it is the only part
// that is still there when WiFi drops, the server restarts, or an agent asks twice.
//
//   1. OFF at boot, and before WiFi is up (pins float while the chip resets and flashes:
//      fit a ~10 k pull-down from the transistor gate to GND).
//   2. A hard cap on how long it may run, enforced here with millis(), whatever was asked.
//   3. A cooldown and a daily total, so repeated "start" requests cannot add up.
//   4. The state is reported back, including when the device itself switched it off.
//   5. addDuration() has a maximum the library enforces (a bigger value is refused as
//      bad_value), and .confirm() makes Maya ask a person first.
//
// Hardware: drive a logic-level N-MOSFET or a transistor from OUT_PIN (never the pump from
// the pin); a flyback diode across the pump; the pump on its own supply with a common
// ground; the supply must not sag the 3.3 V rail when it starts.
//
// Always-on class (it has a writable control), so it needs power all the time. A battery
// pack is fine; deep sleep is not (a sleeping device cannot be told anything, and the
// sleepy class is not implemented).
#include <Maya.h>

Maya maya("my_pump", "1.0.0");              // CHANGE

#if CONFIG_IDF_TARGET_ESP32C3
const int OUT_PIN    = 4;                   // CHANGE: drives the transistor gate
const int SENSOR_PIN = 3;                   // CHANGE: an ADC1 pin (GPIO 0-4 on a C3)
#else
const int OUT_PIN    = 4;                   // CHANGE
const int SENSOR_PIN = 34;                  // CHANGE: ADC1, input only (32-39); ADC2 dies with WiFi
#endif

// CHANGE: the limits of THIS hardware, not of the UI.
const uint32_t MAX_RUN_S      = 10;         // never longer than this, in one go
const uint32_t COOLDOWN_S     = 60;         // rest between runs
const uint32_t MAX_PER_DAY_S  = 120;        // total per 24 hours

unsigned long runUntil = 0;                 // millis() when the current run must stop; 0 = off
unsigned long lastStop = 0;                 // millis() of the last stop (cooldown)
uint32_t ranToday = 0;                      // seconds run since dayStart
unsigned long dayStart = 0;

void outputOff(const char* why) {
  digitalWrite(OUT_PIN, LOW);
  runUntil = 0;
  lastStop = millis();
  maya.setSwitch("running", false);         // tell Maya and the app, also when WE decided
  Serial.printf("[pump] off (%s)\n", why);
}

// Asked to run for `seconds`. Returns true only if it actually started.
bool startRun(double seconds) {
  if (millis() - dayStart > 86400000UL) { dayStart = millis(); ranToday = 0; }
  if (seconds <= 0) { outputOff("asked to stop"); return true; }
  if (runUntil) { Serial.println("[pump] already running"); return false; }
  if (lastStop && millis() - lastStop < COOLDOWN_S * 1000UL) { Serial.println("[pump] cooling down"); return false; }
  uint32_t s = (uint32_t)seconds;
  if (s > MAX_RUN_S) s = MAX_RUN_S;         // the device's own cap, whatever the app allowed
  if (ranToday + s > MAX_PER_DAY_S) { Serial.println("[pump] daily limit reached"); return false; }
  ranToday += s;
  runUntil = millis() + s * 1000UL;
  digitalWrite(OUT_PIN, HIGH);
  maya.setSwitch("running", true);
  Serial.printf("[pump] on for %u s\n", (unsigned)s);
  return true;
}

void setup() {
  pinMode(OUT_PIN, OUTPUT);
  digitalWrite(OUT_PIN, LOW);               // 1. off before anything else

  maya.setName("Plant pump");               // CHANGE
  maya.enableHealth();

  // The one writable control: how long to run, bounded by the library at MAX_RUN_S.
  // confirm(): Maya must ask a person. Not agentDeny(): letting Maya water is the point;
  // remove confirm() only if you trust the caps above completely.
  maya.addDuration("run_for", "Run for", MAX_RUN_S, [](double s) { return startRun(s); }).confirm();
  maya.addSwitch("running", "Running").readOnly();       // the state, not a control
  maya.addNumber("moisture", "Soil moisture").readOnly().unit("%").limits(0, 100).history();
  maya.addText("note", "Status", 60).readOnly();

  maya.begin();
  maya.setSwitch("running", false);
  dayStart = millis();
}

void loop() {
  maya.loop();

  // 2. The hard stop, independent of anyone's request.
  if (runUntil && (long)(millis() - runUntil) >= 0) outputOff("time is up");

  static unsigned long last = 0;
  if (millis() - last >= 5000) {
    last = millis();
    // CHANGE: a real two-point calibration (reading in air = dry, in water = wet) maps this.
    float pct = 100.0f - analogRead(SENSOR_PIN) * 100.0f / 4095.0f;
    maya.setNumber("moisture", pct);
    maya.setText("note", runUntil ? "Watering" : (pct < 25 ? "Soil is dry" : "Soil is fine"));
  }
}
