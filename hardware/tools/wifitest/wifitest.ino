// WiFi bring-up EXPERIMENT for an ESP32 / ESP32-C3 board. No Bluetooth, no Maya.
//
// Use it when a board joins WiFi sometimes and not others and you need DATA, not guesses.
// It joins the same network with several radio settings, several times each, and prints a
// table of how many joins worked and why the others failed.
//
// How to use: open the Serial monitor at 115200 with the line ending set to "Newline".
// Type the network name, press Enter, type the password, press Enter. Nothing is stored.
// It takes about 6-8 minutes and repeats the summary every 30 s afterwards, so it does
// not matter when the monitor was opened. Read the SUMMARY, not the individual lines.
//
// What it varies (each in its own configuration, see CFGS):
//   teardown   WiFi is switched off and on again before each attempt (what Maya's boot path does)
//   scan first the network is scanned before WiFi.begin()
//   TX power   8.5, 11, 13 dBm (a C3 SuperMini often cannot drive its antenna at 19.5)
//   sleep off  WiFi modem sleep disabled
// The first configuration is run again at the end: if its result changed, the board is
// drifting (supply, temperature, router) and one run proves little.

#include <WiFi.h>
#include <esp_wifi.h>

static volatile int lastReason = 0;
static String ssid, pass;

static void onDisconnected(WiFiEvent_t, WiFiEventInfo_t info) {
  int r = info.wifi_sta_disconnected.reason;
  if (r != 8 || lastReason == 0) lastReason = r;   // 8 is our own disconnect between tries
}

// A line from Serial. The prompt repeats every 3 s until something is typed.
static String readLine(const char* prompt) {
  String s;
  unsigned long lastPrompt = 0;
  bool first = true;
  while (true) {
    if (first || (s.length() == 0 && millis() - lastPrompt > 3000)) {
      Serial.println(prompt);
      lastPrompt = millis();
      first = false;
    }
    while (Serial.available()) {
      char c = (char)Serial.read();
      if (c == '\n') return s;
      if (c != '\r') s += c;
    }
    delay(20);
  }
}

struct Cfg {
  const char* name;
  bool teardown;
  bool scanFirst;
  wifi_power_t power;
  bool sleepOff;
};

static const Cfg CFGS[] = {
  {"A  teardown,   8.5 dBm",                 true,  false, WIFI_POWER_8_5dBm, false},
  {"B  no teardown, 8.5 dBm",                false, false, WIFI_POWER_8_5dBm, false},
  {"C  scan first, 8.5 dBm",                 false, true,  WIFI_POWER_8_5dBm, false},
  {"D  no teardown, 11 dBm",                 false, false, WIFI_POWER_11dBm,  false},
  {"E  no teardown, 13 dBm",                 false, false, WIFI_POWER_13dBm,  false},
  {"F  no teardown, 8.5 dBm, sleep off",     false, false, WIFI_POWER_8_5dBm, true},
  {"G  scan first, 11 dBm, sleep off",       false, true,  WIFI_POWER_11dBm,  true},
  {"H  teardown,   11 dBm, sleep off",       true,  false, WIFI_POWER_11dBm,  true},
  {"A  teardown,   8.5 dBm  (again)",        true,  false, WIFI_POWER_8_5dBm, false},
};
static const int NCFG = sizeof(CFGS) / sizeof(CFGS[0]);
static const int TRIES = 4;

static int okCount[NCFG], failCount[NCFG];
static unsigned long msSum[NCFG];
static int reasonSeen[NCFG][4];     // the first few failure reasons
static int done = 0;

static bool stationUp = false;

static bool attempt(int idx, unsigned long& ms) {
  const Cfg& c = CFGS[idx];
  if (c.teardown) {
    WiFi.persistent(false);
    WiFi.mode(WIFI_STA);
    WiFi.disconnect(true);
    delay(150);
    WiFi.mode(WIFI_STA);
    stationUp = true;
  } else {
    if (!stationUp) { WiFi.persistent(false); WiFi.mode(WIFI_STA); stationUp = true; }
    WiFi.disconnect(false);
    delay(300);
  }
  // The core only accepts a TX power once the station has started.
  unsigned long t0 = millis();
  while (!WiFi.setTxPower(c.power) && millis() - t0 < 1500) delay(10);
  esp_wifi_set_bandwidth(WIFI_IF_STA, WIFI_BW_HT20);
  WiFi.setSleep(!c.sleepOff);
  if (c.scanFirst) { WiFi.scanNetworks(false, true); WiFi.scanDelete(); }

  lastReason = 0;
  unsigned long start = millis();
  WiFi.begin(ssid.c_str(), pass.c_str());
  while (WiFi.status() != WL_CONNECTED && millis() - start < 12000) delay(100);
  ms = millis() - start;
  return WiFi.status() == WL_CONNECTED;
}

static void summary() {
  Serial.println();
  Serial.println("================ SUMMARY (joins that worked / tries) ================");
  for (int i = 0; i < NCFG; i++) {
    int n = okCount[i] + failCount[i];
    if (n == 0) { Serial.printf("  %-40s  not run yet\n", CFGS[i].name); continue; }
    Serial.printf("  %-40s  %d/%d", CFGS[i].name, okCount[i], n);
    if (okCount[i]) Serial.printf("   avg %lu ms", msSum[i] / okCount[i]);
    if (failCount[i]) {
      Serial.print("   fail reasons:");
      for (int k = 0; k < 4 && k < failCount[i]; k++) Serial.printf(" %d", reasonSeen[i][k]);
    }
    Serial.println();
  }
  Serial.println("  reasons: 2 auth expired, 15/204 handshake timeout, 39 timeout, 201 not found, 202 auth failed");
  Serial.println("=====================================================================");
}

void setup() {
  Serial.begin(115200);
  unsigned long t0 = millis();
  while (!Serial && millis() - t0 < 5000) delay(10);
  WiFi.onEvent(onDisconnected, ARDUINO_EVENT_WIFI_STA_DISCONNECTED);

  ssid = readLine("Network name (2.4 GHz):");
  pass = readLine("Password:");
  Serial.printf("ssid '%s' (%d chars), password %d chars\n", ssid.c_str(), (int)ssid.length(), (int)pass.length());
  Serial.printf("Running %d configurations x %d tries. Read the SUMMARY at the end.\n", NCFG, TRIES);
}

void loop() {
  if (done < NCFG) {
    const Cfg& c = CFGS[done];
    Serial.printf("\n--- %s ---\n", c.name);
    // Start each configuration from a radio that is off, so one cannot inherit another's state.
    WiFi.disconnect(true, true);
    WiFi.mode(WIFI_OFF);
    stationUp = false;
    delay(1500);
    for (int t = 1; t <= TRIES; t++) {
      unsigned long ms = 0;
      if (attempt(done, ms)) {
        okCount[done]++;
        msSum[done] += ms;
        Serial.printf("  try %d: OK in %lu ms, rssi %d dBm, channel %d\n", t, ms, (int)WiFi.RSSI(), (int)WiFi.channel());
      } else {
        if (failCount[done] < 4) reasonSeen[done][failCount[done]] = lastReason;
        failCount[done]++;
        Serial.printf("  try %d: FAILED, reason %d\n", t, lastReason);
      }
      delay(1000);
    }
    done++;
    if (done == NCFG) summary();
  } else {
    delay(30000);
    summary();
  }
}
