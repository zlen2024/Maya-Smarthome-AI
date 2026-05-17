/*
  ESP32 BLE Provisioning + WebSocket client
  DEVICE_ID hardcoded: "esp32-9f83b1c1"

  Features:
  - BLE provisioning for SSID / PASS / WS_URL / BLE_PIN
  - BLE PIN protection (default "0000", dev override "9999")
  - Save settings to Preferences
  - WiFi auto-reconnect with BLE fallback
  - WebSocket client (5-failure fallback to BLE re-provisioning)
  - 3-channel output control (LED1/LED2/LED3 — can be swapped for relays)
  - Commands: output_on / output_off / output_toggle (with "channel": 1|2|3)
  - Backward compat: led_on/led_off/toggle → channel 1
  - Heartbeat every 30s with all channel states
  - Device identifies to server with DEVICE_ID on connect
*/

#include <WiFi.h>
#include <Preferences.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>

Preferences prefs;
WebSocketsClient webSocket;

// ─── Output Pins (swap for relay IN pins later) ──────────────
// GPIO2  = built-in LED on most ESP32 boards (good for testing ch1)
// GPIO4  = channel 2
// GPIO5  = channel 3
#define NUM_OUTPUTS 3
const int OUTPUT_PINS[NUM_OUTPUTS] = {2, 4, 5};
const char* OUTPUT_NAMES[NUM_OUTPUTS] = {"ch1", "ch2", "ch3"};

// ─── Helpers ─────────────────────────────────────────────────
String sanitizeBleText(String s) {
  s.replace("\r", "");
  s.replace("\n", "");
  s.replace("\0", "");
  s.trim();
  return s;
}

// Returns "on"/"off" string for a pin state
const char* pinStateStr(int pin) {
  return digitalRead(pin) ? "on" : "off";
}

// ─── Device ID ───────────────────────────────────────────────
const char* DEVICE_ID = "esp32-9f83b1c1";

// ─── BLE UUIDs ───────────────────────────────────────────────
#define SERVICE_UUID  "12345678-1234-1234-1234-123456789000"
#define SSID_UUID     "12345678-1234-1234-1234-123456789001"
#define PASS_UUID     "12345678-1234-1234-1234-123456789002"
#define WSURL_UUID    "12345678-1234-1234-1234-123456789004"
#define PIN_UUID      "12345678-1234-1234-1234-123456789003"
#define CMD_UUID      "12345678-1234-1234-1234-123456789005"

// ─── Runtime Settings ─────────────────────────────────────────
String wifi_ssid = "";
String wifi_pass = "";
String ws_url    = "";
String ble_pin   = "";

// ─── Provisioning Buffers ────────────────────────────────────
String recvSSID = "", recvPASS = "", recvWS = "", recvPIN = "";
bool haveSSID = false, havePASS = false, haveWS = false, havePIN = false;

// ─── Connection State ─────────────────────────────────────────
bool wifiConnected = false;
bool wsConnected   = false;

const int WIFI_CONNECT_TRIES = 20;
const int WIFI_RECONNECT_CYCLES_BEFORE_PROVISION = 6;
int wifiFailCycles = 0;
int wsFailCycles   = 0;

// ─── BLE Globals ─────────────────────────────────────────────
BLEServer*         pServer  = nullptr;
BLEService*        pService = nullptr;
BLECharacteristic* ssidChar;
BLECharacteristic* passChar;
BLECharacteristic* wsChar;
BLECharacteristic* pinChar;
BLECharacteristic* cmdChar;

// ─── Settings Persistence ────────────────────────────────────
void saveSettings() {
  prefs.begin("iotdata", false);
  prefs.putString("ssid", wifi_ssid);
  prefs.putString("pass", wifi_pass);
  prefs.putString("ws",   ws_url);
  prefs.putString("pin",  ble_pin);
  prefs.end();
  Serial.println("Settings saved to Preferences.");
}

void loadSettings() {
  prefs.begin("iotdata", true);
  wifi_ssid = prefs.getString("ssid", "");
  wifi_pass = prefs.getString("pass", "");
  ws_url    = prefs.getString("ws",   "");
  ble_pin   = prefs.getString("pin",  "0000");
  prefs.end();
  wifi_ssid = sanitizeBleText(wifi_ssid);
  wifi_pass = sanitizeBleText(wifi_pass);
  ws_url    = sanitizeBleText(ws_url);
  ble_pin   = sanitizeBleText(ble_pin);
  Serial.printf("Loaded: ssid='%s', ws='%s', pin_len=%d\n",
    wifi_ssid.c_str(), ws_url.c_str(), (int)ble_pin.length());
}

// ─── BLE Callbacks ───────────────────────────────────────────
class GenericWriteCallback : public BLECharacteristicCallbacks {
  public:
    void onWrite(BLECharacteristic *pChar) {
      String s = pChar->getValue();
      s = sanitizeBleText(s);
      String uuid = pChar->getUUID().toString().c_str();
      Serial.printf("BLE write UUID: %s = %s\n", uuid.c_str(), s.c_str());

      if      (uuid == SSID_UUID)  { recvSSID = s; haveSSID = true; Serial.printf("BLE SSID: %s\n", s.c_str()); }
      else if (uuid == PASS_UUID)  { recvPASS = s; havePASS = true; Serial.printf("BLE PASS (len=%d)\n", (int)s.length()); }
      else if (uuid == WSURL_UUID) { recvWS   = s; haveWS   = true; Serial.printf("BLE WSURL: %s\n", s.c_str()); }
      else if (uuid == PIN_UUID)   { recvPIN  = s; havePIN  = true; Serial.printf("BLE PIN (len=%d)\n", (int)s.length()); }
      else if (uuid == CMD_UUID)   { Serial.printf("BLE CMD: %s\n", s.c_str()); }
    }
};

// ─── BLE Provisioning ────────────────────────────────────────
void startBLEProvisioning() {
  Serial.println("Starting BLE provisioning mode. Advertising as 'Maya-Setup'...");
  Serial.printf("Dev Note: Stored PIN='%s' | Override PIN='9999'\n", ble_pin.c_str());

  BLEDevice::setMTU(517);
  BLEDevice::init("Maya-Setup");
  pServer  = BLEDevice::createServer();
  pService = pServer->createService(SERVICE_UUID);

  ssidChar = pService->createCharacteristic(SSID_UUID,  BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  passChar = pService->createCharacteristic(PASS_UUID,  BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  wsChar   = pService->createCharacteristic(WSURL_UUID, BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  pinChar  = pService->createCharacteristic(PIN_UUID,   BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  cmdChar  = pService->createCharacteristic(CMD_UUID,   BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);

  GenericWriteCallback* cb = new GenericWriteCallback();
  ssidChar->setCallbacks(cb); passChar->setCallbacks(cb);
  wsChar->setCallbacks(cb);   pinChar->setCallbacks(cb); cmdChar->setCallbacks(cb);

  ssidChar->addDescriptor(new BLE2902()); passChar->addDescriptor(new BLE2902());
  wsChar->addDescriptor(new BLE2902());   pinChar->addDescriptor(new BLE2902());

  pService->start();
  BLEDevice::startAdvertising();
  Serial.println("BLE advertising started. Waiting for SSID, PASS, WSURL, PIN...");

  unsigned long start   = millis();
  unsigned long timeout = 5UL * 60 * 1000; // 5 min
  while (millis() - start < timeout) {
    if (haveSSID && havePASS && haveWS && havePIN) {
      Serial.println("All provisioning values received.");

      // PIN validation
      if (ble_pin == "" || ble_pin == "0000") {
        if (recvPIN.length() > 0) { ble_pin = recvPIN; Serial.printf("First-time PIN set (len=%d)\n", (int)ble_pin.length()); }
      } else {
        if (recvPIN != ble_pin && recvPIN != "9999") {
          Serial.println("PIN mismatch. Rejecting.");
          havePIN = haveSSID = havePASS = haveWS = false;
          recvPIN = recvSSID = recvPASS = recvWS = "";
          continue;
        }
      }

      wifi_ssid = recvSSID;
      wifi_pass = recvPASS;
      ws_url    = recvWS;
      Serial.printf("Provisioning accepted. SSID=%s URL=%s\n", wifi_ssid.c_str(), ws_url.c_str());
      saveSettings();
      wifiFailCycles = 0;

      BLEDevice::stopAdvertising();
      delay(100);
      BLEDevice::deinit();
      haveSSID = havePASS = haveWS = havePIN = false;
      recvPIN = recvSSID = recvPASS = recvWS = "";
      return;
    }
    delay(200);
  }

  Serial.println("Provisioning timed out.");
  BLEDevice::stopAdvertising();
  BLEDevice::deinit();
}

// ─── WiFi ─────────────────────────────────────────────────────
bool connectToWiFiOnce() {
  if (wifi_ssid.length() == 0) { Serial.println("No SSID saved."); return false; }
  wifi_ssid = sanitizeBleText(wifi_ssid);
  wifi_pass = sanitizeBleText(wifi_pass);
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.disconnect(true);
  delay(150);
  Serial.printf("Connecting to WiFi '%s'...\n", wifi_ssid.c_str());
  WiFi.begin(wifi_ssid.c_str(), wifi_pass.c_str());

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < WIFI_CONNECT_TRIES) {
    delay(500); Serial.print("."); attempts++;
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("WiFi connected. IP=%s\n", WiFi.localIP().toString().c_str());
    wifiConnected = true; wifiFailCycles = 0; return true;
  }
  Serial.printf("WiFi failed. status=%d\n", (int)WiFi.status());
  wifiConnected = false; return false;
}

// ─── Output Helpers ──────────────────────────────────────────
// Sets output channel (1-based). Returns true if valid channel.
bool setOutput(int channel, bool state) {
  if (channel < 1 || channel > NUM_OUTPUTS) return false;
  digitalWrite(OUTPUT_PINS[channel - 1], state ? HIGH : LOW);
  Serial.printf("Output %d (%s) -> %s\n", channel, OUTPUT_NAMES[channel-1], state ? "ON" : "OFF");
  return true;
}

bool toggleOutput(int channel) {
  if (channel < 1 || channel > NUM_OUTPUTS) return false;
  int pin = OUTPUT_PINS[channel - 1];
  bool newState = !digitalRead(pin);
  digitalWrite(pin, newState ? HIGH : LOW);
  Serial.printf("Output %d (%s) toggled -> %s\n", channel, OUTPUT_NAMES[channel-1], newState ? "ON" : "OFF");
  return true;
}

// Build a JSON ack with all channel states
void sendAllStatesAck(const char* status = "ok") {
  StaticJsonDocument<256> ack;
  ack["id"]     = DEVICE_ID;
  ack["status"] = status;
  for (int i = 0; i < NUM_OUTPUTS; i++) {
    ack[OUTPUT_NAMES[i]] = pinStateStr(OUTPUT_PINS[i]);
  }
  char buf[256]; size_t n = serializeJson(ack, buf);
  webSocket.sendTXT(buf, n);
}

// ─── WebSocket Event Handler ──────────────────────────────────
void webSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
  switch (type) {
    case WStype_DISCONNECTED:
      Serial.println("[WS] Disconnected");
      wsConnected = false;
      wsFailCycles++;
      break;

    case WStype_CONNECTED: {
      Serial.println("[WS] Connected");
      wsConnected  = true;
      wsFailCycles = 0;

      // Send identify + all output states
      StaticJsonDocument<384> doc;
      doc["id"]     = DEVICE_ID;
      doc["status"] = "online";
      doc["ip"]     = WiFi.localIP().toString();
      for (int i = 0; i < NUM_OUTPUTS; i++) {
        doc[OUTPUT_NAMES[i]] = pinStateStr(OUTPUT_PINS[i]);
      }
      char buf[384]; size_t n = serializeJson(doc, buf);
      webSocket.sendTXT(buf, n);
      break;
    }

    case WStype_TEXT: {
      String msg((char*)payload, length);
      Serial.printf("[WS] Message: %s\n", msg.c_str());

      StaticJsonDocument<512> root;
      DeserializationError err = deserializeJson(root, msg);
      if (err) { Serial.println("[WS] JSON parse error"); return; }

      // Check device target
      if (root.containsKey("id")) {
        String target = root["id"].as<const char*>();
        if (target != DEVICE_ID) {
          Serial.printf("[WS] Ignored msg for '%s'\n", target.c_str());
          return;
        }
      }

      if (!root.containsKey("cmd")) return;

      // PIN check
      if (root.containsKey("pin")) {
        String providedPin = root["pin"].as<const char*>();
        if (providedPin != ble_pin && providedPin != "" ) {
          // Only reject if a non-empty PIN was provided and it doesn't match
          if (providedPin != ble_pin) {
            Serial.println("[WS] PIN mismatch! Rejecting.");
            StaticJsonDocument<256> er;
            er["id"] = DEVICE_ID; er["status"] = "pin_mismatch";
            char b[256]; size_t s = serializeJson(er, b); webSocket.sendTXT(b, s);
            return;
          }
        }
      }

      String cmd = root["cmd"].as<const char*>();
      // Channel defaults to 1 if not specified
      int channel = root.containsKey("channel") ? root["channel"].as<int>() : 1;

      // ── Multi-channel commands ───────────────────────────
      if (cmd.equalsIgnoreCase("output_on")) {
        if (setOutput(channel, true)) sendAllStatesAck();
        else { StaticJsonDocument<128> er; er["id"]=DEVICE_ID; er["status"]="invalid_channel"; char b[128]; size_t s=serializeJson(er,b); webSocket.sendTXT(b,s); }

      } else if (cmd.equalsIgnoreCase("output_off")) {
        if (setOutput(channel, false)) sendAllStatesAck();
        else { StaticJsonDocument<128> er; er["id"]=DEVICE_ID; er["status"]="invalid_channel"; char b[128]; size_t s=serializeJson(er,b); webSocket.sendTXT(b,s); }

      } else if (cmd.equalsIgnoreCase("output_toggle")) {
        if (toggleOutput(channel)) sendAllStatesAck();

      // ── All-outputs at once ──────────────────────────────
      } else if (cmd.equalsIgnoreCase("all_on")) {
        for (int i = 1; i <= NUM_OUTPUTS; i++) setOutput(i, true);
        sendAllStatesAck();

      } else if (cmd.equalsIgnoreCase("all_off")) {
        for (int i = 1; i <= NUM_OUTPUTS; i++) setOutput(i, false);
        sendAllStatesAck();

      // ── Status query ────────────────────────────────────
      } else if (cmd.equalsIgnoreCase("get_status")) {
        sendAllStatesAck();

      // ── Backward-compat (channel 1) ─────────────────────
      } else if (cmd.equalsIgnoreCase("led_on")) {
        setOutput(1, true);  sendAllStatesAck();
      } else if (cmd.equalsIgnoreCase("led_off")) {
        setOutput(1, false); sendAllStatesAck();
      } else if (cmd.equalsIgnoreCase("toggle")) {
        toggleOutput(1);     sendAllStatesAck();

      // ── Reboot ─────────────────────────────────────────
      } else if (cmd.equalsIgnoreCase("reboot")) {
        StaticJsonDocument<128> ack;
        ack["id"] = DEVICE_ID; ack["status"] = "rebooting";
        char b[128]; size_t s = serializeJson(ack, b); webSocket.sendTXT(b, s);
        delay(200);
        ESP.restart();

      } else {
        Serial.printf("[WS] Unknown command '%s'\n", cmd.c_str());
      }
      break;
    }

    default: break;
  }
}

// ─── WebSocket Init ───────────────────────────────────────────
void startWebSocket() {
  if (ws_url.length() == 0) { Serial.println("No WS URL configured."); return; }

  bool useSSL = false;
  String url  = ws_url;
  // Check wss:// BEFORE ws:// — "wss://" also startsWith("ws://")
  if (url.startsWith("wss://")) { useSSL = true; url = url.substring(6); }
  else if (url.startsWith("ws://"))               { url = url.substring(5); }

  String host = url;
  String path = "/";
  int slashPos = url.indexOf('/');
  if (slashPos != -1) { host = url.substring(0, slashPos); path = url.substring(slashPos); }

  int port = useSSL ? 443 : 80;
  int colonIdx = host.indexOf(':');
  if (colonIdx != -1) { port = host.substring(colonIdx + 1).toInt(); host = host.substring(0, colonIdx); }

  Serial.printf("Starting WebSocket: host='%s', port=%d, path='%s', ssl=%d\n",
    host.c_str(), port, path.c_str(), useSSL);

  if (useSSL) webSocket.beginSSL(host.c_str(), port, path.c_str());
  else        webSocket.begin(host.c_str(), port, path.c_str());

  webSocket.onEvent(webSocketEvent);
  webSocket.setReconnectInterval(5000);
  // Required for ngrok free tier to bypass browser warning interstitial
  webSocket.setExtraHeaders("ngrok-skip-browser-warning: true");
}

// ─── Setup ────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);

  // Initialise all outputs LOW
  for (int i = 0; i < NUM_OUTPUTS; i++) {
    pinMode(OUTPUT_PINS[i], OUTPUT);
    digitalWrite(OUTPUT_PINS[i], LOW);
    Serial.printf("Output %d (%s) on GPIO%d initialised LOW\n", i+1, OUTPUT_NAMES[i], OUTPUT_PINS[i]);
  }

  loadSettings();

  if (wifi_ssid.length() == 0) {
    Serial.println("No WiFi config. Entering BLE provisioning.");
    startBLEProvisioning();
    loadSettings();
  }

  if (!connectToWiFiOnce()) {
    wifiFailCycles++;
    if (wifiFailCycles >= WIFI_RECONNECT_CYCLES_BEFORE_PROVISION) {
      Serial.println("Repeated WiFi failures. BLE provisioning.");
      startBLEProvisioning();
      loadSettings();
      connectToWiFiOnce();
    }
  } else {
    startWebSocket();
  }
}

// ─── Loop ─────────────────────────────────────────────────────
unsigned long lastWiFiCheck = 0;

void loop() {
  // WiFi watchdog — check every 3s
  if (millis() - lastWiFiCheck > 3000) {
    lastWiFiCheck = millis();
    if (WiFi.status() != WL_CONNECTED) {
      wifiConnected = false;
      Serial.println("WiFi lost. Reconnecting...");
      if (!connectToWiFiOnce()) {
        wifiFailCycles++;
        if (wifiFailCycles >= WIFI_RECONNECT_CYCLES_BEFORE_PROVISION) {
          Serial.println("Too many WiFi failures. BLE provisioning.");
          startBLEProvisioning();
          loadSettings();
          connectToWiFiOnce();
        }
      } else {
        startWebSocket();
      }
    } else {
      wifiConnected = true;
    }
  }

  // WebSocket loop
  webSocket.loop();

  // WS failure fallback after 5 disconnects
  if (wsFailCycles >= 5) {
    Serial.println("Too many WS failures. BLE provisioning.");
    webSocket.disconnect();
    wsFailCycles = 0;
    startBLEProvisioning();
    loadSettings();
    if (connectToWiFiOnce()) startWebSocket();
  }

  // Heartbeat every 30s — includes all channel states
  static unsigned long lastHeartbeat = 0;
  if (millis() - lastHeartbeat > 30000 && wsConnected) {
    lastHeartbeat = millis();
    StaticJsonDocument<256> hb;
    hb["id"]        = DEVICE_ID;
    hb["type"]      = "heartbeat";
    hb["uptime_ms"] = (uint32_t)millis();
    for (int i = 0; i < NUM_OUTPUTS; i++) {
      hb[OUTPUT_NAMES[i]] = pinStateStr(OUTPUT_PINS[i]);
    }
    char buf[256]; size_t n = serializeJson(hb, buf);
    webSocket.sendTXT(buf, n);
  }

  delay(10);
}
