// Smart Jar - a jar that knows how full it is.
//
// ESP32-C3 + HX711 + a 5 kg bar load cell. The jar sits on the cell; the sketch turns the
// HX711's raw count into grams and a fill level, and the Maya library does everything
// else (BLE provisioning, WiFi, the server link, the descriptor the app and Maya read).
//
// Two builds, one file, two device classes (PROTOCOL.md 5.7):
//
//   JAR_BATTERY 0 (default)  ALWAYS-ON. USB/mains powered, reports every few seconds.
//                            Tare, calibration and "full at" are controls in the app.
//
//   JAR_BATTERY 1            SENSOR-ONLY. 3xAA: wakes, weighs, reports through a hub (or
//                            WiFi), sleeps. It declares readings only - nothing writable -
//                            because a sleeping device cannot be told anything. Tare,
//                            calibration and "full at" are typed into the Serial monitor
//                            in SETUP MODE, which it enters when the setup button (GPIO20
//                            to GND) is held at power-on, or when it has never been
//                            calibrated. See SETUP.md.
//
// Status: compiled for the ESP32-C3, never run on a board. WIRING.md and SETUP.md say
// what to check first.
#include <Maya.h>
#include <Preferences.h>

#ifndef JAR_BATTERY
#define JAR_BATTERY 0
#endif

// -- pins (ESP32-C3; see WIRING.md) ------------------------------------------
const int HX_DT   = 6;     // HX711 DT  (data out)
const int HX_SCK  = 7;     // HX711 SCK (clock in)
const int HX_PWR  = 10;    // powers the HX711 + load cell, so they can be switched off asleep
const int BATT_PIN = 3;    // 3xAA through a 1M / 470k divider (battery build only)
const int CFG_PIN  = 20;   // a button to GND: hold at power-on to enter setup mode (not BOOT/GPIO9: low at reset = download mode)

const unsigned long REPORT_EVERY_MS = 5000;     // always-on build
const uint32_t SLEEP_SECONDS = 300;             // battery build: five minutes between weighs
const unsigned long SETUP_MODE_MS = 600000UL;   // battery build: how long setup mode waits for you
const float MIN_STEP_G = 2.0;                   // ignore changes smaller than this (load cell noise)

Maya maya("smart_jar", "1.0.0");
Preferences prefs;

// What survives a reboot: where zero is, how many counts make a gram, and the two numbers
// a person sets.
long  zeroRaw  = 0;
float countsPerGram = 0;      // 0 = not calibrated yet
float fullGrams = 1000;       // the contents' weight at 100 %
float calGrams  = 200;        // the known weight used to calibrate

void loadCalibration() {
  prefs.begin("jar", true);
  zeroRaw = prefs.getLong("zero", 0);
  countsPerGram = prefs.getFloat("scale", 0);
  fullGrams = prefs.getFloat("full", 1000);
  calGrams = prefs.getFloat("calw", 200);
  prefs.end();
}

void saveFloat(const char* key, float v) {
  prefs.begin("jar", false);
  prefs.putFloat(key, v);
  prefs.end();
}

// -- the HX711, with no library ----------------------------------------------
// 24 bits clocked out MSB first, then one extra pulse to pick channel A at gain 128.
// SCK held HIGH for 60 us or more powers the chip down, so every pulse here is short.
bool hxRead(long& out) {
  uint32_t t = millis();
  while (digitalRead(HX_DT) == HIGH) {            // DT goes LOW when a conversion is ready
    if (millis() - t > 1000) return false;
    delay(1);
  }
  uint32_t v = 0;
  noInterrupts();
  for (int i = 0; i < 24; i++) {
    digitalWrite(HX_SCK, HIGH);
    delayMicroseconds(1);
    v = (v << 1) | (uint32_t)digitalRead(HX_DT);
    digitalWrite(HX_SCK, LOW);
    delayMicroseconds(1);
  }
  digitalWrite(HX_SCK, HIGH);                     // 25th pulse: channel A, gain 128
  delayMicroseconds(1);
  digitalWrite(HX_SCK, LOW);
  interrupts();
  if (v & 0x800000UL) v |= 0xFF000000UL;          // sign-extend the 24-bit two's complement
  out = (int32_t)v;
  return true;
}

// The median of a handful of reads: one bad sample (a knock, a radio burst) cannot move it.
bool hxMedian(long& out, int n = 7) {
  long s[15];
  if (n > 15) n = 15;
  long stale;
  hxRead(stale);                                  // the first read after power-up is stale
  for (int i = 0; i < n; i++) {
    if (!hxRead(s[i])) return false;
  }
  for (int i = 1; i < n; i++) {                   // insertion sort, n is tiny
    long k = s[i];
    int j = i - 1;
    while (j >= 0 && s[j] > k) { s[j + 1] = s[j]; j--; }
    s[j + 1] = k;
  }
  out = s[n / 2];
  return true;
}

void hxPower(bool on) {
  digitalWrite(HX_PWR, on ? HIGH : LOW);
  if (on) delay(500);                             // the HX711 needs ~400 ms to settle at 10 Hz
}

// -- what the sketch reports -------------------------------------------------
float lastGrams = -1e9;

// Weighs, and tells Maya. Returns false while uncalibrated or if the HX711 is not answering.
// measure() runs every few seconds for as long as the jar lives, so a standing problem must not print every time
// (it buried the Serial log, and everything useful in it, under thousands of identical lines).
static void sayEvery(unsigned long ms, const char* msg) {
  static unsigned long lastSaid = 0;
  static const char* lastMsg = nullptr;
  if (msg != lastMsg || millis() - lastSaid >= ms) {
    lastSaid = millis();
    lastMsg = msg;
    Serial.println(msg);
  }
}

bool measure(bool force) {
  if (countsPerGram == 0) {
    sayEvery(30000, "[jar] not calibrated: tare with the jar empty, then calibrate with a known weight");
    return false;
  }
  long raw;
  if (!hxMedian(raw)) {
    sayEvery(30000, "[jar] HX711 not answering: check DT/SCK/power (WIRING.md)");
    return false;
  }
  float g = (raw - zeroRaw) / countsPerGram;
  if (g < 0 && g > -MIN_STEP_G) g = 0;
  if (!force && fabsf(g - lastGrams) < MIN_STEP_G) return true;
  lastGrams = g;
  float pct = fullGrams > 0 ? g * 100.0f / fullGrams : 0;
  if (pct < 0) pct = 0;
  if (pct > 100) pct = 100;
  maya.setNumber("weight_g", roundf(g));
  maya.setNumber("level", roundf(pct));
  return true;
}

#if JAR_BATTERY
// Three AA cells, 4.5 V fresh. The board's regulator stops holding 3.3 V somewhere near
// 3.5 V, so 3.4 V is called empty. Alkaline cells are flat for most of their life, so this
// is a rough gauge, not a fuel gauge. The divider is 1M over 470k: 4.8 V reads 1.5 V.
float batteryPercent() {
  uint32_t mv = 0;
  for (int i = 0; i < 8; i++) { mv += analogReadMilliVolts(BATT_PIN); delay(2); }
  float volts = (mv / 8.0f) * (1000000.0f + 470000.0f) / 470000.0f / 1000.0f;
  float pct = (volts - 3.4f) * 100.0f / (4.5f - 3.4f);
  return pct < 0 ? 0 : (pct > 100 ? 100 : pct);
}
#endif

// -- tare and calibration ----------------------------------------------------
void tare() {
  long raw;
  if (!hxMedian(raw, 15)) { Serial.println("[jar] tare failed: HX711 not answering"); return; }
  zeroRaw = raw;
  prefs.begin("jar", false);
  prefs.putLong("zero", zeroRaw);
  prefs.end();
  Serial.printf("[jar] tared at %ld\n", zeroRaw);
  lastGrams = -1e9;
  measure(true);
}

void calibrateWith(float grams) {
  long raw;
  if (grams <= 0) { Serial.println("[jar] calibrate refused: the known weight must be above 0 g"); return; }
  if (!hxMedian(raw, 15)) { Serial.println("[jar] calibrate failed: HX711 not answering"); return; }
  long delta = raw - zeroRaw;
  if (labs(delta) < 1000) {
    Serial.println("[jar] calibrate refused: the known weight barely moved the count. Is it on the jar? Did you tare first?");
    return;
  }
  countsPerGram = (float)delta / grams;
  saveFloat("scale", countsPerGram);
  Serial.printf("[jar] calibrated: %.3f counts per gram\n", countsPerGram);
  lastGrams = -1e9;
  measure(true);
}

void setFull(float grams) {
  if (grams <= 0) { Serial.println("[jar] full refused: must be above 0 g"); return; }
  fullGrams = grams;
  saveFloat("full", fullGrams);
  Serial.printf("[jar] full = %.0f g\n", fullGrams);
  lastGrams = -1e9;
}

#if JAR_BATTERY
// SETUP MODE (battery build): the Serial monitor is the interface. 115200 baud, newline.
//   tare            zero the scale with the jar empty
//   cal <grams>     calibrate with that known weight on the jar
//   full <grams>    the contents' weight at 100 %
//   show            print the current weight and settings
//   done            leave setup mode and go to the normal wake-weigh-sleep routine
void setupConsole() {
  Serial.println("[jar] SETUP MODE. Commands: tare | cal <grams> | full <grams> | show | done");
  unsigned long start = millis();
  String line;
  while (millis() - start < SETUP_MODE_MS) {
    while (Serial.available()) {
      char c = (char)Serial.read();
      if (c != '\n' && c != '\r') { line += c; continue; }
      line.trim();
      if (line == "tare") tare();
      else if (line.startsWith("cal ")) calibrateWith(line.substring(4).toFloat());
      else if (line.startsWith("full ")) setFull(line.substring(5).toFloat());
      else if (line == "show") {
        long raw;
        if (hxMedian(raw)) Serial.printf("[jar] raw=%ld zero=%ld counts/g=%.3f full=%.0f g\n", raw, zeroRaw, countsPerGram, fullGrams);
        else Serial.println("[jar] HX711 not answering");
      }
      else if (line == "done") { Serial.println("[jar] leaving setup mode"); return; }
      else if (line.length()) Serial.println("[jar] ? tare | cal <grams> | full <grams> | show | done");
      line = "";
    }
    delay(10);
  }
  Serial.println("[jar] setup mode timed out");
}
#endif

// -- what the device declares ------------------------------------------------
void declare() {
  maya.addNumber("weight_g", "Weight").readOnly().unit("g").history();
  maya.addNumber("level", "Level").readOnly().unit("%").history();

#if JAR_BATTERY
  // Sensor-only (5.7): nothing writable. A sleeping device cannot be told anything, so
  // tare and calibration live in the Serial monitor (setup mode), not in the app.
  maya.addReserved("_batt");
#else
  maya.addRange("full_g", "Full at", 100, 4000, 50, [](double g) {
    setFull((float)g);
    return true;
  }).unit("g").group("Setup");

  maya.addRange("cal_g", "Known weight", 50, 3000, 10, [](double g) {
    calGrams = (float)g;
    saveFloat("calw", calGrams);
    return true;
  }).unit("g").group("Setup");

  // Both change what every later reading means, so a person confirms them. Calibrate is
  // also invisible to Maya: she must never be the one to decide what a gram is.
  maya.addButton("tare", "Tare (jar empty)", tare).confirm().group("Setup");
  maya.addButton("calibrate", "Calibrate with known weight", []() { calibrateWith(calGrams); })
      .confirm().agentDeny().group("Setup");
#endif
}

unsigned long modeStart = 0;

void setup() {
  pinMode(HX_PWR, OUTPUT);
  pinMode(HX_SCK, OUTPUT);
  digitalWrite(HX_SCK, LOW);
  pinMode(HX_DT, INPUT);
  pinMode(CFG_PIN, INPUT_PULLUP);
  hxPower(true);

  loadCalibration();
  declare();
  maya.setName("Smart Jar");                      // the name for the app to offer (the app prefills the name field with it from app 1.2.0); the owner can still change it

#if JAR_BATTERY
  bool setupMode = digitalRead(CFG_PIN) == LOW || countsPerGram == 0;
  maya.beginSensor();                             // not begin(): it does not join WiFi. Provisions over BLE the first time.
  if (setupMode) {
    setupConsole();
    loadCalibration();
  }
  if (measure(true)) {
    maya.setNumber("_batt", roundf(batteryPercent()));
    maya.reportNow();                             // the hub if it can, the server if it cannot
  }
  hxPower(false);                                 // load cell and HX711 off while asleep
  maya.sleepFor(SLEEP_SECONDS);                   // does not return
#else
  maya.setNumber("full_g", fullGrams);
  maya.setNumber("cal_g", calGrams);
  modeStart = millis();
  maya.begin();
#endif
}

void loop() {
#if !JAR_BATTERY
  maya.loop();
  static unsigned long last = 0;
  if (millis() - last >= REPORT_EVERY_MS) {
    last = millis();
    measure(false);
  }
#endif
}
