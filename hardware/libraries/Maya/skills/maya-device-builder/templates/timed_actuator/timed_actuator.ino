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
//   2. A hard cap on how long it may run, enforced by a hardware timer (esp_timer), NOT by
//      loop(): maya.loop() can block for many seconds (WiFi reconnect) or minutes (Bluetooth
//      setup), and a cutoff that waits for loop() is no cutoff. loop() only reports it.
//   3. A cooldown and a daily total, so repeated "start" requests cannot add up. These live
//      in RAM, so a reboot (brown-out, crash loop, server reboot) resets them: if a reboot
//      loop would be dangerous for your hardware, persist the total (a Preferences
//      namespace of your own) and keep the pump's supply fused.
//   4. The state is reported back, including when the device itself switched it off, and
//      a refusal says why in the "note" text, not only as a bare "bad value".
//   5. addDuration() has a maximum the library enforces (a bigger value is refused before
//      this code runs), and .confirm() makes Maya ask a person first.
//
// Hardware: drive a logic-level N-MOSFET or a transistor from OUT_PIN (never the pump from
// the pin); a flyback diode across the pump; the pump on its own supply with a common
// ground; the supply must not sag the 3.3 V rail when it starts.
//
// Always-on class (it has a writable control), so it needs power all the time. A battery
// pack is fine; deep sleep is not (a sleeping device cannot be told anything, and the
// sleepy class is not implemented).
#include <Maya.h>
#include <esp_timer.h>

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

volatile bool running = false;              // written by the cutoff timer and by loop()
volatile bool timerFired = false;           // the timer switched it off; loop() reports it
unsigned long lastStop = 0;                 // millis() of the end of the last run (cooldown)
uint32_t ranToday = 0;                      // seconds run since dayStart
unsigned long dayStart = 0;
esp_timer_handle_t cutoff = nullptr;

// Runs in the esp_timer task, independent of loop(): the pin goes low no matter what
// maya.loop() is doing. Nothing here may block or call into Maya.
static void onCutoff(void*) {
  digitalWrite(OUT_PIN, LOW);
  running = false;
  timerFired = true;
}

// Called from loop() or a handler (never from the timer): output low, state reported.
void finishRun(const char* why) {
  digitalWrite(OUT_PIN, LOW);
  if (cutoff) esp_timer_stop(cutoff);       // harmless if it is not running
  running = false;
  lastStop = millis();
  maya.setSwitch("running", false);         // tell Maya and the app, also when WE decided
  maya.setNumber("run_for", 0);             // the app should not keep showing "10 s"
  maya.setText("note", why);
  Serial.printf("[pump] off (%s)\n", why);
}

// Asked to run for `seconds`. Returns true only if it actually started (or was a stop).
bool startRun(double seconds) {
  if (millis() - dayStart > 86400000UL) { dayStart = millis(); ranToday = 0; }
  if (seconds <= 0) {                       // a stop request: not a "run", so no cooldown starts
    if (running) finishRun("stopped on request");
    return true;
  }
  if (running) { maya.setText("note", "Already running"); return false; }
  if (lastStop && millis() - lastStop < COOLDOWN_S * 1000UL) {
    char b[48];
    snprintf(b, sizeof b, "Cooling down (%lu s)", (unsigned long)(COOLDOWN_S - (millis() - lastStop) / 1000));
    maya.setText("note", b);
    return false;
  }
  uint32_t s = (uint32_t)seconds;
  if (s > MAX_RUN_S) s = MAX_RUN_S;         // the device's own cap, whatever the app allowed
  if (ranToday + s > MAX_PER_DAY_S) { maya.setText("note", "Daily limit reached"); return false; }
  ranToday += s;
  running = true;
  timerFired = false;
  esp_timer_start_once(cutoff, (uint64_t)s * 1000000ULL);   // the cutoff is armed BEFORE the pin goes high
  digitalWrite(OUT_PIN, HIGH);
  maya.setSwitch("running", true);
  maya.setText("note", "Watering");
  Serial.printf("[pump] on for %u s\n", (unsigned)s);
  return true;
}

void setup() {
  pinMode(OUT_PIN, OUTPUT);
  digitalWrite(OUT_PIN, LOW);               // 1. off before anything else

  const esp_timer_create_args_t args = { onCutoff, nullptr, ESP_TIMER_TASK, "pump_cutoff", true };
  esp_timer_create(&args, &cutoff);

  maya.setName("Plant pump");               // CHANGE
  maya.enableHealth();

  // The one writable control: how long to run, bounded by the library at MAX_RUN_S.
  // confirm(): Maya must ask a person. Not agentDeny(): letting Maya water is the point;
  // remove confirm() only if you trust the caps above completely.
  maya.addDuration("run_for", "Run for", MAX_RUN_S, [](double s) { return startRun(s); }).confirm();
  // A switch with no handler is NOT automatically read-only: say .readOnly() or the app
  // draws it as a control that accepts a value and does nothing.
  maya.addSwitch("running", "Running").readOnly();
  maya.addNumber("moisture", "Soil moisture").readOnly().unit("%").limits(0, 100).history();
  maya.addText("note", "Status", 60).readOnly();

  maya.begin();
  maya.setSwitch("running", false);
  dayStart = millis();
}

void loop() {
  maya.loop();

  if (timerFired) { timerFired = false; finishRun("time is up"); }   // report what the timer did
  // Belt and braces: if the timer somehow did not fire, loop() still ends the run.
  // (It cannot be the ONLY cutoff: see the header.)

  static unsigned long last = 0;
  if (millis() - last >= 5000) {
    last = millis();
    // CHANGE: a real two-point calibration (reading in air = dry, in water = wet) maps this.
    float pct = 100.0f - analogRead(SENSOR_PIN) * 100.0f / 4095.0f;
    maya.setNumber("moisture", pct);
    if (!running) maya.setText("note", pct < 25 ? "Soil is dry" : "Soil is fine");
  }
}
