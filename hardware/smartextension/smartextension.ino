/*
  ESP32 BLE Provisioning + WebSocket client
  DEVICE_ID derived from chip MAC at boot (e.g. "esp32-9f83b1c1") — unique per board

  Features:
  - BLE provisioning for SSID / PASS / WS_URL / BLE_PIN
  - BLE PIN protection (default "0000"; also verified server-side at WS identify)
  - Save settings to Preferences (committed once WiFi verifies; server
    reachability is then confirmed after an automatic reboot, BLE off)
  - WiFi auto-reconnect; BLE provisioning re-opens on boot/persistent WiFi failure
  - WebSocket client with background retry (never falls back to old WiFi)
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
// Derived from the chip's factory MAC in setup() — unique per board,
// so multiple extensions can coexist on one server.
String DEVICE_ID;

// ─── BLE UUIDs ───────────────────────────────────────────────
#define SERVICE_UUID  "12345678-1234-1234-1234-123456789000"
#define SSID_UUID     "12345678-1234-1234-1234-123456789001"
#define PASS_UUID     "12345678-1234-1234-1234-123456789002"
#define WSURL_UUID    "12345678-1234-1234-1234-123456789004"
#define PIN_UUID      "12345678-1234-1234-1234-123456789003"
#define CMD_UUID      "12345678-1234-1234-1234-123456789005"
#define STATUS_UUID   "12345678-1234-1234-1234-123456789006"
#define NEWPIN_UUID   "12345678-1234-1234-1234-123456789007" // optional: change PIN (current PIN still required)

// ─── Runtime Settings ─────────────────────────────────────────
String wifi_ssid = "";
String wifi_pass = "";
String ws_url    = "";
String ble_pin   = "";

// ─── Provisioning Buffers ────────────────────────────────────
String recvSSID = "", recvPASS = "", recvWS = "", recvPIN = "";
String recvNEWPIN = ""; // optional — only sent when the owner wants to change the PIN
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
BLECharacteristic* newpinChar;
BLECharacteristic* cmdChar;
BLECharacteristic* statusChar;

// Helper to update and notify status over BLE
void setStatus(const char* code) {
  if (statusChar) {
    statusChar->setValue(code);
    statusChar->notify();
    Serial.printf("Status update sent to BLE: %s\n", code);
  }
}

// ─── Settings Persistence ────────────────────────────────────
// NVS Preferences survive sketch uploads, so a reflashed (or factory-fresh)
// board could keep an old owner's PIN/WiFi. Wipe everything whenever the
// firmware build fingerprint changes — every flash starts clean: PIN "0000",
// no WiFi, BLE provisioning mode.
void resetPrefsIfNewFirmware() {
  const String buildTag = String(__DATE__) + " " + String(__TIME__);
  prefs.begin("iotdata", false);
  if (prefs.getString("build", "") != buildTag) {
    prefs.clear();
    prefs.putString("build", buildTag);
    Serial.println("New firmware build detected. Settings wiped: PIN=0000, no WiFi config.");
  }
  prefs.end();
}

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
      else if (uuid == NEWPIN_UUID){ recvNEWPIN = s;               Serial.printf("BLE NEW PIN (len=%d)\n", (int)s.length()); }
      else if (uuid == CMD_UUID)   { Serial.printf("BLE CMD: %s\n", s.c_str()); }
    }
};

// ─── BLE Provisioning ────────────────────────────────────────
void startBLEProvisioning() {
  String advName = "Maya-" + String(DEVICE_ID);
  Serial.printf("Starting BLE provisioning mode. Advertising as '%s'...\n", advName.c_str());
  Serial.printf("PIN protection: %s\n", (ble_pin == "" || ble_pin == "0000") ? "default (unset)" : "enabled");

  BLEDevice::setMTU(517);
  BLEDevice::init(advName.c_str());
  pServer  = BLEDevice::createServer();
  pService = pServer->createService(SERVICE_UUID);

  ssidChar   = pService->createCharacteristic(SSID_UUID,   BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  passChar   = pService->createCharacteristic(PASS_UUID,   BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  wsChar     = pService->createCharacteristic(WSURL_UUID,  BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  pinChar    = pService->createCharacteristic(PIN_UUID,    BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  newpinChar = pService->createCharacteristic(NEWPIN_UUID, BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  cmdChar    = pService->createCharacteristic(CMD_UUID,    BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  statusChar = pService->createCharacteristic(STATUS_UUID, BLECharacteristic::PROPERTY_READ  | BLECharacteristic::PROPERTY_NOTIFY);

  GenericWriteCallback* cb = new GenericWriteCallback();
  ssidChar->setCallbacks(cb); passChar->setCallbacks(cb);
  wsChar->setCallbacks(cb);   pinChar->setCallbacks(cb);
  newpinChar->setCallbacks(cb); cmdChar->setCallbacks(cb);

  ssidChar->addDescriptor(new BLE2902()); passChar->addDescriptor(new BLE2902());
  wsChar->addDescriptor(new BLE2902());   pinChar->addDescriptor(new BLE2902());
  statusChar->addDescriptor(new BLE2902());

  statusChar->setValue("0"); // Idle/Waiting

  pService->start();
  BLEDevice::startAdvertising();
  Serial.println("BLE advertising started. Waiting for SSID, PASS, WSURL, PIN...");

  unsigned long start   = millis();
  unsigned long timeout = 5UL * 60 * 1000; // 5 min
  while (millis() - start < timeout) {
    if (haveSSID && havePASS && haveWS && havePIN) {
      Serial.println("All provisioning values received.");

      // PIN validation (no dev override — server also verifies this PIN on WS identify)
      if (ble_pin != "" && ble_pin != "0000" && recvPIN != ble_pin) {
        Serial.println("PIN mismatch. Rejecting.");
        setStatus("6"); // PIN mismatch code
        havePIN = haveSSID = havePASS = haveWS = false;
        recvPIN = recvSSID = recvPASS = recvWS = recvNEWPIN = "";
        continue;
      }

      setStatus("1"); // PIN verified, connecting to WiFi
      delay(200);

      // Test new WiFi credentials WITHOUT overwriting live vars until everything succeeds
      bool wifiOk = false;
      int connectRetries = 3;
      for (int r = 0; r < connectRetries; r++) {
        Serial.printf("Attempting WiFi connect to '%s' (try %d/%d)...\n", recvSSID.c_str(), r + 1, connectRetries);
        WiFi.persistent(false);
        WiFi.mode(WIFI_STA);
        WiFi.disconnect(true);
        delay(150);
        WiFi.begin(recvSSID.c_str(), recvPASS.c_str());

        int attempts = 0;
        while (attempts < WIFI_CONNECT_TRIES) {
          delay(500);
          if (WiFi.status() == WL_CONNECTED) {
            wifiOk = true;
            break;
          }
          attempts++;
        }
        if (wifiOk) break;
        Serial.println("WiFi connect attempt failed.");
      }

      if (!wifiOk) {
        Serial.println("WiFi connection failed during BLE setup.");
        setStatus("4"); // WiFi failed
        WiFi.disconnect(true);
        delay(1000);
        haveSSID = havePASS = haveWS = havePIN = false;
        recvPIN = recvSSID = recvPASS = recvWS = recvNEWPIN = "";
        start = millis(); // Reset timeout so user can try again
        continue;
      }

      setStatus("2"); // WiFi connected
      Serial.println("WiFi connected during provisioning.");

      // ── Commit credentials, then reboot to reach the server ──────
      // We deliberately do NOT open the TLS WebSocket while BLE is still up.
      // The ESP32 has a single 2.4GHz radio shared between WiFi and the live
      // BLE link to the phone; a TLS handshake (Fly's multi-KB certificate
      // chain) gets corrupted under that coexistence, and Bluedroid + mbedTLS
      // also compete for heap — both make an in-BLE handshake unreliable.
      // Instead we save the freshly-verified WiFi credentials, tell the app to
      // confirm the device via the server, then reboot into a clean WiFi-only
      // state where the WebSocket connects reliably with full heap and radio.
      // If the owner supplied a NEW PIN (current PIN already validated above),
      // it takes effect here — this is the PIN-change path.
      wifi_ssid = recvSSID;
      wifi_pass = recvPASS;
      ws_url    = recvWS;
      ble_pin   = recvNEWPIN.length() > 0 ? recvNEWPIN : recvPIN;
      saveSettings();
      wifiFailCycles = 0;
      wsFailCycles   = 0;
      wifiConnected  = true;

      setStatus("8"); // Saved — BLE shutting down; app confirms device online via server
      Serial.println("Credentials saved. Rebooting to connect to the server with BLE off.");
      delay(1500); // let the phone receive status 8 and switch to server polling

      BLEDevice::stopAdvertising();
      delay(100);
      ESP.restart(); // clean boot → connectToWiFiOnce() + startWebSocket() (full heap/radio)
    }
    delay(200);
  }

  Serial.println("Provisioning timed out.");
  BLEDevice::stopAdvertising();
  BLEDevice::deinit();
  statusChar = ssidChar = passChar = wsChar = pinChar = newpinChar = cmdChar = nullptr;
}

// ─── WiFi ─────────────────────────────────────────────────────
bool connectToWiFiOnce() {
  if (WiFi.status() == WL_CONNECTED) { wifiConnected = true; return true; } // already online (e.g. just provisioned)
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
unsigned long lastServerContact = 0; // millis of last frame heard from the server

void webSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
  switch (type) {
    case WStype_DISCONNECTED:
      Serial.println("[WS] Disconnected");
      wsConnected = false;
      wsFailCycles++;
      break;

    case WStype_PONG:
      lastServerContact = millis();
      break;

    case WStype_CONNECTED: {
      Serial.println("[WS] Connected");
      wsConnected  = true;
      wsFailCycles = 0;
      lastServerContact = millis();

      // Send identify + all output states; PIN verified by server at identify
      StaticJsonDocument<384> doc;
      doc["id"]     = DEVICE_ID;
      doc["status"] = "online";
      doc["pin"]    = ble_pin;
      doc["ip"]     = WiFi.localIP().toString();
      for (int i = 0; i < NUM_OUTPUTS; i++) {
        doc[OUTPUT_NAMES[i]] = pinStateStr(OUTPUT_PINS[i]);
      }
      char buf[384]; size_t n = serializeJson(doc, buf);
      webSocket.sendTXT(buf, n);
      break;
    }

    case WStype_TEXT: {
      lastServerContact = millis();
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

      // No per-command PIN check: commands are authorized server-side (JWT +
      // child permissions), and this connection was PIN-verified at identify.

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

      // ── Factory reset (device removed from house) ──────
      } else if (cmd.equalsIgnoreCase("factory_reset")) {
        StaticJsonDocument<128> ack;
        ack["id"] = DEVICE_ID; ack["status"] = "factory_reset";
        char b[128]; size_t s = serializeJson(ack, b); webSocket.sendTXT(b, s);
        Serial.println("[WS] Factory reset requested. Wiping settings and rebooting.");
        delay(300);
        prefs.begin("iotdata", false);
        prefs.clear(); // wipes WiFi, WS URL, PIN, and build tag — boots fresh into BLE provisioning
        prefs.end();
        ESP.restart();

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
  if (wsConnected) return; // already connected (e.g. verified during provisioning)
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

  if (useSSL) {
    // beginSSL with no CA cert/fingerprint skips cert verification
    // (library calls setInsecure() internally) — needed for Fly.io TLS
    webSocket.beginSSL(host.c_str(), port, path.c_str());
  } else {
    webSocket.begin(host.c_str(), port, path.c_str());
  }

  webSocket.onEvent(webSocketEvent);
  webSocket.setReconnectInterval(5000);
  // Protocol-level ping/pong: detects half-open ("zombie") sockets the TCP
  // stack never reports — e.g. server stopped (Fly scale-to-zero) or NAT
  // mapping silently dropped. Ping every 15s; 2 missed pongs (3s timeout
  // each) → library fires WStype_DISCONNECTED → auto-reconnect kicks in.
  webSocket.enableHeartbeat(15000, 3000, 2);
  // Required for ngrok free tier to bypass browser warning interstitial
  webSocket.setExtraHeaders("ngrok-skip-browser-warning: true");
}

// ─── Setup ────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);

  // Unique per-board ID from the factory MAC (lower 32 bits)
  DEVICE_ID = "esp32-" + String((uint32_t)ESP.getEfuseMac(), HEX);
  Serial.printf("Device ID: %s\n", DEVICE_ID.c_str());

  resetPrefsIfNewFirmware();

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
    // Saved credentials exist but WiFi failed on boot — open BLE for reprovisioning
    Serial.println("Boot WiFi failed. Entering BLE provisioning for re-setup.");
    startBLEProvisioning();
    loadSettings();
    connectToWiFiOnce();
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

  // Zombie-link watchdog: with pings every 15s the server should never be
  // silent for long while "connected". If it is, the link is dead in a way
  // even ping/pong missed — force a disconnect so the reconnect timer takes
  // over. Deliberately NOT ESP.restart(): that would flip all outputs LOW.
  if (wsConnected && millis() - lastServerContact > 180000) {
    Serial.println("[WS] No server contact for 3 min. Forcing reconnect.");
    wsConnected = false;
    webSocket.disconnect();
  }

  // WS failure warning — print info but do not enter blocking BLE provisioning
  if (wsFailCycles >= 5) {
    static unsigned long lastWarning = 0;
    if (millis() - lastWarning > 30000) {
      Serial.println("Warning: Multiple WebSocket connection failures. Retrying in background...");
      lastWarning = millis();
    }
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
