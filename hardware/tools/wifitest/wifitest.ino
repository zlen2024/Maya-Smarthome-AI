// WiFi bring-up test for an ESP32 / ESP32-C3 board. No Bluetooth, no Maya.
//
// Use it when a board will not join WiFi and you need to know whether the cause is
// the radio, the password or the router. Open the Serial monitor at 115200 with the
// line ending set to "Newline", type the network name, press Enter, type the
// password, press Enter. It then joins, leaves and joins again, forever, printing
// why each attempt ended and a running count. Every few rounds it switches radio
// profile and transmit power. Nothing is stored.
//
// The prompt is repeated every 3 seconds until something is typed, so it does not
// matter when the monitor was opened.

#include <WiFi.h>
#include <esp_wifi.h>

static volatile int lastReason = 0;

static void onDisconnected(WiFiEvent_t, WiFiEventInfo_t info) {
  lastReason = info.wifi_sta_disconnected.reason;
}

// A line from Serial. While waiting, the prompt is printed again every 3 s.
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

struct Power { wifi_power_t level; const char* name; };
static const Power POWERS[] = {
  { WIFI_POWER_8_5dBm,  "8.5 dBm" },
  { WIFI_POWER_13dBm,   "13 dBm"  },
  { WIFI_POWER_19_5dBm, "19.5 dBm (full)" },
};

static String ssid, pass;
static int round_ = 0, ok_ = 0, bad_ = 0;

// "narrow" asks for a 20 MHz channel and 802.11 b/g/n only, which is what many
// routers with a mixed 2.4 GHz band (40 MHz, Wi-Fi 6) cope with best when a C3
// will not associate.
static bool attempt(bool narrow, int powerIndex) {
  WiFi.disconnect(true, true);
  WiFi.mode(WIFI_OFF);
  delay(500);
  WiFi.mode(WIFI_STA);
  WiFi.setTxPower(POWERS[powerIndex].level);
  WiFi.setSleep(false);
  if (narrow) {
    esp_wifi_set_bandwidth(WIFI_IF_STA, WIFI_BW_HT20);
    esp_wifi_set_protocol(WIFI_IF_STA, WIFI_PROTOCOL_11B | WIFI_PROTOCOL_11G | WIFI_PROTOCOL_11N);
  }
  lastReason = 0;
  WiFi.begin(ssid.c_str(), pass.c_str());
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) delay(250);
  return WiFi.status() == WL_CONNECTED;
}

void setup() {
  Serial.begin(115200);
  unsigned long t0 = millis();
  while (!Serial && millis() - t0 < 5000) delay(10);
  WiFi.onEvent(onDisconnected, ARDUINO_EVENT_WIFI_STA_DISCONNECTED);

  ssid = readLine("Network name (2.4 GHz):");
  pass = readLine("Password:");
  Serial.printf("ssid '%s' (%d chars), password %d chars\n", ssid.c_str(), (int)ssid.length(), (int)pass.length());
}

void loop() {
  // Rounds 0-2 use the default profile at each power, rounds 3-5 the narrow one.
  const bool narrow = (round_ / 3) % 2 == 1;
  const int pi = round_ % 3;
  round_++;

  Serial.printf("\n--- round %d: %s, TX power %s ---\n", round_, narrow ? "narrow" : "default", POWERS[pi].name);
  if (attempt(narrow, pi)) {
    ok_++;
    Serial.printf("CONNECTED: ip %s, rssi %d dBm, channel %d   [ok %d / failed %d]\n",
                  WiFi.localIP().toString().c_str(), (int)WiFi.RSSI(), (int)WiFi.channel(), ok_, bad_);
  } else {
    bad_++;
    Serial.printf("FAILED, last reason %d (39 timeout, 2 auth expired, 202 auth fail, 15 handshake timeout, 201 no AP)   [ok %d / failed %d]\n",
                  lastReason, ok_, bad_);
  }
  delay(3000);
}
