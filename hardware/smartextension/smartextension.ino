/*
  ESP32 BLE Provisioning + WebSocket client example
  DEVICE_ID hardcoded: "esp32-9f83b1c1"

  Features:
  - BLE characteristics for SSID / PASS / WS_URL / BLE_PIN
  - BLE PIN protection (default "0000")
  - Save to Preferences
  - Connect to WiFi, auto-reconnect
  - WebSocket client (auto reconnect)
  - Device identifies to server with DEVICE_ID
  - Accepts JSON commands like { "id": "esp32-9f83b1c1", "cmd": "led_on" }
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

#define LED_PIN 2

// Hardcoded device id option A
const char* DEVICE_ID = "esp32-9f83b1c1";

// BLE UUIDs
#define SERVICE_UUID        "12345678-1234-1234-1234-123456789000"
#define SSID_UUID           "12345678-1234-1234-1234-123456789001"
#define PASS_UUID           "12345678-1234-1234-123456789002"
#define WSURL_UUID          "12345678-1234-1234-1234-123456789003"
#define PIN_UUID            "12345678-1234-1234-1234-123456789004"
#define CMD_UUID            "12345678-1234-1234-1234-123456789005" // optional ack

// runtime settings (loaded/saved)
String wifi_ssid = "";
String wifi_pass = "";
String ws_url   = "";
String ble_pin  = ""; // provisioning pin

// provisioning buffers & flags
String recvSSID = "";
String recvPASS = "";
String recvWS   = "";
String recvPIN  = "";

bool haveSSID = false;
bool havePASS = false;
bool haveWS   = false;
bool havePIN  = false;

// runtime connection state
bool wifiConnected = false;
bool wsConnected = false;

unsigned long lastWsReconnectAttempt = 0;
unsigned long wsReconnectInterval = 5000; // ms

// reconnect attempts before fallback to BLE provisioning
const int WIFI_CONNECT_TRIES = 20;   // ~10 seconds
const int WIFI_RECONNECT_CYCLES_BEFORE_PROVISION = 6; // try many cycles before enabling BLE (6 * WIFI_CONNECT_TRIES)

// internal counters
int wifiFailCycles = 0;

// BLE server global pointer (so we can stop advertising)
BLEServer* pServer = nullptr;
BLEService* pService = nullptr;
BLECharacteristic* ssidChar;
BLECharacteristic* passChar;
BLECharacteristic* wsChar;
BLECharacteristic* pinChar;
BLECharacteristic* cmdChar;

void saveSettings() {
  prefs.begin("iotdata", false);
  prefs.putString("ssid", wifi_ssid);
  prefs.putString("pass", wifi_pass);
  prefs.putString("ws", ws_url);
  prefs.putString("pin", ble_pin);
  prefs.end();
  Serial.println("Settings saved to Preferences.");
}

void loadSettings() {
  prefs.begin("iotdata", true);
  wifi_ssid = prefs.getString("ssid", "");
  wifi_pass = prefs.getString("pass", "");
  ws_url = prefs.getString("ws", "");
  ble_pin = prefs.getString("pin", "0000"); // default PIN
  prefs.end();
  Serial.printf("Loaded settings: ssid='%s', ws='%s', pin='%s'\n", wifi_ssid.c_str(), ws_url.c_str(), ble_pin.c_str());
}

// BLE callbacks to collect written values
class GenericWriteCallback : public BLECharacteristicCallbacks {
  public:
    void onWrite(BLECharacteristic *pChar) {
      std::string val = pChar->getValue();
      String s = String(val.c_str());
      String uuid = pChar->getUUID().toString().c_str();
      if (pChar == ssidChar) {
        recvSSID = s; haveSSID = true;
        Serial.printf("BLE got SSID: %s\n", recvSSID.c_str());
      } else if (pChar == passChar) {
        recvPASS = s; havePASS = true;
        Serial.printf("BLE got PASS: %s\n", recvPASS.c_str());
      } else if (pChar == wsChar) {
        recvWS = s; haveWS = true;
        Serial.printf("BLE got WSURL: %s\n", recvWS.c_str());
      } else if (pChar == pinChar) {
        recvPIN = s; havePIN = true;
        Serial.printf("BLE got PIN: %s\n", recvPIN.c_str());
      } else if (pChar == cmdChar) {
        Serial.printf("BLE CMD char written: %s\n", s.c_str());
      }
    }
};

// Start BLE advertising and wait for provisioning data
void startBLEProvisioning() {
  Serial.println("Starting BLE provisioning mode. Advertising as 'MyIoT-Setup'...");

  BLEDevice::init("MyIoT-Setup");
  pServer = BLEDevice::createServer();
  pService = pServer->createService(SERVICE_UUID);

  ssidChar = pService->createCharacteristic(SSID_UUID, BLECharacteristic::PROPERTY_WRITE);
  passChar = pService->createCharacteristic(PASS_UUID, BLECharacteristic::PROPERTY_WRITE);
  wsChar   = pService->createCharacteristic(WSURL_UUID, BLECharacteristic::PROPERTY_WRITE);
  pinChar  = pService->createCharacteristic(PIN_UUID, BLECharacteristic::PROPERTY_WRITE);
  cmdChar  = pService->createCharacteristic(CMD_UUID, BLECharacteristic::PROPERTY_WRITE);

  GenericWriteCallback* cb = new GenericWriteCallback();
  ssidChar->setCallbacks(cb);
  passChar->setCallbacks(cb);
  wsChar->setCallbacks(cb);
  pinChar->setCallbacks(cb);
  cmdChar->setCallbacks(cb);

  // Optionally add descriptors so typical BLE apps can subscribe/see characteristics
  ssidChar->addDescriptor(new BLE2902());
  passChar->addDescriptor(new BLE2902());
  wsChar->addDescriptor(new BLE2902());
  pinChar->addDescriptor(new BLE2902());

  pService->start();
  BLEDevice::startAdvertising();

  Serial.println("BLE advertising started. Waiting for SSID, PASS, WSURL, PIN writes...");

  // Wait for all required fields (with a timeout)
  unsigned long start = millis();
  unsigned long timeout = 5 * 60 * 1000UL; // 5 minutes max provisioning time
  while (millis() - start < timeout) {
    if (haveSSID && havePASS && haveWS && havePIN) {
      Serial.println("All provisioning values received over BLE.");
      // Validate PIN: the device expects a PIN that matches ble_pin (stored) OR default when first setup
      // If first time and no stored pin, accept the written PIN and set it as device PIN.
      if (ble_pin == "" || ble_pin == "0000") {
        // first time: adopt provided PIN (but only if non-empty)
        if (recvPIN.length() > 0) {
          ble_pin = recvPIN;
          Serial.printf("No previous PIN found. Setting device PIN to '%s'\n", ble_pin.c_str());
        }
      } else {
        // check provided pin matches stored pin
        if (recvPIN != ble_pin) {
          Serial.println("Provided PIN mismatch. Rejecting provisioning request.");
          // clear flags so user can resend correct PIN
          havePIN = haveSSID = havePASS = haveWS = false;
          recvPIN = recvSSID = recvPASS = recvWS = "";
          continue;
        }
      }

      // Accept and save the received SSID/PASS/WSURL
      wifi_ssid = recvSSID;
      wifi_pass = recvPASS;
      ws_url = recvWS;
      Serial.println("Provisioning accepted. Storing values...");
      saveSettings();

      // Stop BLE advertising & free BLE resources
      BLEDevice::stopAdvertising();
      delay(100);
      BLEDevice::deinit();
      // Reset flags for future usage
      haveSSID = havePASS = haveWS = havePIN = false;
      recvPIN = recvSSID = recvPASS = recvWS = "";
      return;
    }
    delay(200);
  }

  Serial.println("Provisioning timed out. Restarting BLE advertising.");
  // stop and allow restart if desired
  BLEDevice::stopAdvertising();
  BLEDevice::deinit();
}

// Connect to WiFi (blocking attempt with tries). Returns true if connected
bool connectToWiFiOnce() {
  if (wifi_ssid.length() == 0) {
    Serial.println("No saved SSID. Cannot connect.");
    return false;
  }
  Serial.printf("Connecting to WiFi '%s' ...\n", wifi_ssid.c_str());
  WiFi.begin(wifi_ssid.c_str(), wifi_pass.c_str());

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < WIFI_CONNECT_TRIES) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("WiFi connected. IP=%s\n", WiFi.localIP().toString().c_str());
    wifiConnected = true;
    wifiFailCycles = 0;
    return true;
  } else {
    Serial.println("WiFi connection failed.");
    wifiConnected = false;
    return false;
  }
}

// WebSocket event handler
void webSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
  switch(type) {
    case WStype_DISCONNECTED:
      Serial.println("[WS] Disconnected");
      wsConnected = false;
      break;
    case WStype_CONNECTED:
      {
        Serial.println("[WS] Connected");
        wsConnected = true;
        // Send an identify/status JSON immediately
        StaticJsonDocument<256> doc;
        doc["id"] = DEVICE_ID;
        doc["status"] = "online";
        doc["ip"] = WiFi.localIP().toString();
        char buf[256];
        size_t n = serializeJson(doc, buf);
        webSocket.sendTXT(buf, n);
      }
      break;
    case WStype_TEXT:
      {
        // Incoming message
        String msg((char*)payload, length);
        Serial.printf("[WS] Message: %s\n", msg.c_str());

        StaticJsonDocument<512> root;
        DeserializationError err = deserializeJson(root, msg);
        if (err) {
          Serial.println("[WS] JSON parse error");
          return;
        }

        // if message contains "id", check if it matches this device
        if (root.containsKey("id")) {
          String target = root["id"].as<const char*>();
          if (target != DEVICE_ID) {
            Serial.printf("[WS] Message for '%s' ignored (this device is '%s')\n", target.c_str(), DEVICE_ID);
            return;
          }
        }

        // execute commands
        if (root.containsKey("cmd")) {
          String cmd = root["cmd"].as<const char*>();
          if (cmd.equalsIgnoreCase("led_on")) {
            digitalWrite(LED_PIN, HIGH);
            Serial.println("LED ON");
            // ack back
            StaticJsonDocument<256> ack;
            ack["id"] = DEVICE_ID;
            ack["led"] = "on";
            ack["status"] = "ok";
            char b[256]; size_t s = serializeJson(ack, b); webSocket.sendTXT(b, s);
          } else if (cmd.equalsIgnoreCase("led_off")) {
            digitalWrite(LED_PIN, LOW);
            Serial.println("LED OFF");
            StaticJsonDocument<256> ack;
            ack["id"] = DEVICE_ID;
            ack["led"] = "off";
            ack["status"] = "ok";
            char b[256]; size_t s = serializeJson(ack, b); webSocket.sendTXT(b, s);
          } else if (cmd.equalsIgnoreCase("toggle")) {
            int st = digitalRead(LED_PIN);
            digitalWrite(LED_PIN, !st);
            StaticJsonDocument<256> ack;
            ack["id"] = DEVICE_ID;
            ack["led"] = digitalRead(LED_PIN) ? "on" : "off";
            ack["status"] = "ok";
            char b[256]; size_t s = serializeJson(ack, b); webSocket.sendTXT(b, s);
          } else if (cmd.equalsIgnoreCase("reboot")) {
            StaticJsonDocument<256> ack;
            ack["id"] = DEVICE_ID;
            ack["status"] = "rebooting";
            char b[256]; size_t s = serializeJson(ack, b); webSocket.sendTXT(b, s);
            delay(200);
            ESP.restart();
          } else {
            Serial.printf("[WS] Unknown command '%s'\n", cmd.c_str());
          }
        }
      }
      break;
    default:
      break;
  }
}

// Start websocket client to the ws_url (expects ws:// or wss://)
void startWebSocket() {
  if (ws_url.length() == 0) {
    Serial.println("No WebSocket URL configured.");
    return;
  }

  // parse ws_url to host/path/port could be handled by webSocket.beginSSL or begin depending on ws:// or wss://
  bool useSSL = false;
  String url = ws_url;
  if (url.startsWith("wss://")) useSSL = true;
  if (url.startsWith("ws://")) url = url.substring(5);
  else if (url.startsWith("wss://")) url = url.substring(6);

  // split host and path
  String host = url;
  String path = "/";
  int slashPos = url.indexOf('/');
  if (slashPos != -1) {
    host = url.substring(0, slashPos);
    path = url.substring(slashPos);
  }

  // extract port if present
  int port = useSSL ? 443 : 80;
  int colonIdx = host.indexOf(':');
  if (colonIdx != -1) {
    port = host.substring(colonIdx + 1).toInt();
    host = host.substring(0, colonIdx);
  }

  Serial.printf("Starting WebSocket: host='%s', port=%d, path='%s', ssl=%d\n", host.c_str(), port, path.c_str(), useSSL);

  if (useSSL) {
    webSocket.beginSSL(host.c_str(), port, path.c_str());
  } else {
    webSocket.begin(host.c_str(), port, path.c_str());
  }
  webSocket.onEvent(webSocketEvent);
  webSocket.setReconnectInterval(5000);
}

// attempt to ensure websocket is connected (non-blocking)
void ensureWebSocketConnected() {
  if (!wsConnected && millis() - lastWsReconnectAttempt > wsReconnectInterval) {
    Serial.println("[WS] Attempting reconnect...");
    startWebSocket();
    lastWsReconnectAttempt = millis();
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  loadSettings();

  // If no wifi settings found, start BLE provisioning immediately
  if (wifi_ssid.length() == 0) {
    Serial.println("No WiFi config found. Entering BLE provisioning.");
    startBLEProvisioning();
    // after provisioning returns, load settings again
    loadSettings();
  }

  // try to connect to WiFi (with retries)
  if (!connectToWiFiOnce()) {
    // repeated attempts cycles
    wifiFailCycles++;
    if (wifiFailCycles >= WIFI_RECONNECT_CYCLES_BEFORE_PROVISION) {
      Serial.println("Repeated WiFi failures. Switching to BLE provisioning mode.");
      startBLEProvisioning();
      loadSettings();
      connectToWiFiOnce();
    }
  } else {
    // start websocket client
    startWebSocket();
  }
}

unsigned long lastWiFiCheck = 0;
void loop() {
  // simple WiFi watchdog — check every 3s
  if (millis() - lastWiFiCheck > 3000) {
    lastWiFiCheck = millis();
    if (WiFi.status() != WL_CONNECTED) {
      wifiConnected = false;
      Serial.println("WiFi disconnected. Attempting reconnect...");
      if (!connectToWiFiOnce()) {
        wifiFailCycles++;
        if (wifiFailCycles >= WIFI_RECONNECT_CYCLES_BEFORE_PROVISION) {
          Serial.println("Too many WiFi failures. Start BLE provisioning.");
          startBLEProvisioning();
          loadSettings();
          connectToWiFiOnce();
        }
      } else {
        // connected now
        startWebSocket();
      }
    } else {
      wifiConnected = true;
    }
  }

  // WebSocket loop
  webSocket.loop();

  // if websocket not connected, attempt reconnect periodically
  if (wifiConnected && !wsConnected) {
    ensureWebSocketConnected();
  }

  // Example heartbeat every 30s
  static unsigned long lastHeartbeat = 0;
  if (millis() - lastHeartbeat > 30000 && wsConnected) {
    lastHeartbeat = millis();
    StaticJsonDocument<128> hb;
    hb["id"] = DEVICE_ID;
    hb["type"] = "heartbeat";
    hb["uptime_ms"] = (uint32_t)millis();
    char buf[128]; size_t n = serializeJson(hb, buf);
    webSocket.sendTXT(buf, n);
  }

  // small delay to yield
  delay(10);
}
