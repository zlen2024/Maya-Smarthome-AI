#include "Maya.h"

#include <WiFi.h>
#include <Preferences.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <WebSocketsClient.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <time.h>

// Provisioning, WiFi and the WebSocket link, moved out of the sketch they used
// to live in (hardware/smartextension) without changing how they behave: the
// app's provisioning flow, the status codes it reads over BLE and the PIN rules
// are all part of the contract this library has to keep.

namespace {

Preferences prefs;
WebSocketsClient webSocket;
Maya* self = nullptr;

String DEVICE_ID;

// ─── The local link (PROTOCOL.md section 7) ──────────────────────────────────
// Everything that *decides* lives in MayaPeer.cpp and is tested on a laptop. What
// is here is the part that touches hardware, and it has been compiled but never
// run on two boards: the radio is the one thing the test harness cannot stand in for.

// NVS, under the same namespace the rest of the device's settings use, so a
// factory reset (prefs.clear()) takes the grants and the epoch with everything else.
class PrefsStorage : public mayalib::Storage {
 public:
  bool read(const char* name, uint8_t* buf, size_t cap, size_t& len) override {
    Preferences p;
    p.begin("iotdata", true);
    size_t have = p.getBytesLength(name);
    bool ok = have > 0 && have <= cap;
    if (ok) { p.getBytes(name, buf, have); len = have; }
    p.end();
    return ok;
  }
  bool write(const char* name, const uint8_t* buf, size_t len) override {
    Preferences p;
    p.begin("iotdata", false);
    bool ok = p.putBytes(name, buf, len) == len;
    p.end();
    return ok;
  }
};
PrefsStorage peerStorage;

// A tiny single-producer single-consumer queue: the radio callback runs in the
// WiFi task and must not parse JSON or touch the sketch's hardware, so it copies
// the frame here and loop() does the work.
struct RxSlot { uint8_t mac[6]; uint8_t len; uint8_t data[MAYA_LOCAL_FRAME_MAX]; };
const int RX_SLOTS = 4;
RxSlot rxq[RX_SLOTS];
volatile uint8_t rxHead = 0, rxTail = 0;

void queueFrame(const uint8_t* mac, const uint8_t* data, int len) {
  if (len <= 0 || len > MAYA_LOCAL_FRAME_MAX) return;
  uint8_t next = (rxHead + 1) % RX_SLOTS;
  if (next == rxTail) return;   // full: drop. A peer retries; a stuck queue helps nobody.
  memcpy(rxq[rxHead].mac, mac, 6);
  memcpy(rxq[rxHead].data, data, len);
  rxq[rxHead].len = (uint8_t)len;
  rxHead = next;
}

#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
// Arduino-ESP32 3.x passes an info struct. Written from the API, not compiled.
void onEspNowRecv(const esp_now_recv_info_t* info, const uint8_t* data, int len) {
  queueFrame(info->src_addr, data, len);
}
#else
void onEspNowRecv(const uint8_t* mac, const uint8_t* data, int len) { queueFrame(mac, data, len); }
#endif

bool espNowUp = false;
uint8_t espNowPeers[MAYA_MAX_PEERS][6];
size_t espNowPeerCount = 0;
uint32_t espNowPeersSeen = 0xFFFFFFFF;

// A battery sensor's memory across deep sleep (5.9): how long it has been alive, how
// often its hub has failed, and when it last joined WiFi to refresh its grants and the
// hub's channel. RTC memory survives deep sleep and nothing else.
RTC_DATA_ATTR uint32_t rtcSecs = 0;
RTC_DATA_ATTR uint32_t rtcLastSync = 0;
RTC_DATA_ATTR uint32_t rtcDownSince = 0;
RTC_DATA_ATTR uint8_t rtcFails = 0;
RTC_DATA_ATTR uint8_t rtcChannel = 0;
RTC_DATA_ATTR bool rtcAnnounced = false;
RTC_DATA_ATTR bool rtcSynced = false;
const uint32_t SENSOR_SYNC_EVERY_S = 86400;   // 5.9: a daily visit to WiFi is enough
uint32_t sensorSecs() { return rtcSecs + millis() / 1000; }

#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
void onEspNowSent(const wifi_tx_info_t*, esp_now_send_status_t status);
#else
void onEspNowSent(const uint8_t*, esp_now_send_status_t status);
#endif

bool startEspNow() {
  if (espNowUp) return true;
  // ESP-NOW needs the radio on the access point's channel, which station mode
  // gives it (7: "a device MUST NOT change WiFi channel to reach a peer").
  if (esp_now_init() != ESP_OK) {
    Serial.println("[Maya] ESP-NOW init failed; the local link is off");
    return false;
  }
  esp_now_register_recv_cb(onEspNowRecv);
  esp_now_register_send_cb(onEspNowSent);
  espNowUp = true;
  return true;
}

// Whether the last frame was acknowledged by the receiver's radio. This is what lets
// a sensor know its hub is alive without a reply at the application layer (5.9 rule 1).
volatile int sendResult = -1;
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
void onEspNowSent(const wifi_tx_info_t*, esp_now_send_status_t status) { sendResult = status == ESP_NOW_SEND_SUCCESS; }
#else
void onEspNowSent(const uint8_t*, esp_now_send_status_t status) { sendResult = status == ESP_NOW_SEND_SUCCESS; }
#endif

// Sends one frame and waits for the radio's verdict. True means the peer's radio
// acknowledged it; false means it was not sent or nobody answered. The core counts a
// sensor's consecutive failures from this, so it must be the MAC layer's word and not
// merely "esp_now_send did not complain".
bool radioSend(const uint8_t* mac, const uint8_t* data, size_t len) {
  if (!espNowUp) return false;
  sendResult = -1;
  if (esp_now_send(mac, data, len) != ESP_OK) return false;
  uint32_t t = millis();
  while (sendResult < 0 && millis() - t < 200) delay(1);
  return sendResult == 1;
}

// Keep the radio's peer list equal to the grants held: every peer in a grant, and
// no one else.
void syncEspNowPeers(Maya& m) {
  if (!espNowUp || m.peersVersion() == espNowPeersSeen) return;
  for (size_t i = 0; i < espNowPeerCount; i++) esp_now_del_peer(espNowPeers[i]);
  espNowPeerCount = 0;
  uint8_t mac[6];
  for (size_t i = 0; m.peerMacAt(i, mac) && espNowPeerCount < MAYA_MAX_PEERS; i++) {
    esp_now_peer_info_t info;
    memset(&info, 0, sizeof info);
    memcpy(info.peer_addr, mac, 6);
    info.channel = 0;        // the current channel
    info.encrypt = false;    // authentication is the frame MAC, not ESP-NOW's own (5.9)
    if (esp_now_add_peer(&info) == ESP_OK) memcpy(espNowPeers[espNowPeerCount++], mac, 6);
  }
  espNowPeersSeen = m.peersVersion();
}

// BLE UUIDs - the app is written against these.
#define SERVICE_UUID  "12345678-1234-1234-1234-123456789000"
#define SSID_UUID     "12345678-1234-1234-1234-123456789001"
#define PASS_UUID     "12345678-1234-1234-1234-123456789002"
#define WSURL_UUID    "12345678-1234-1234-1234-123456789004"
#define PIN_UUID      "12345678-1234-1234-1234-123456789003"
#define CMD_UUID      "12345678-1234-1234-1234-123456789005"
#define STATUS_UUID   "12345678-1234-1234-1234-123456789006"
#define NEWPIN_UUID   "12345678-1234-1234-1234-123456789007"

String wifi_ssid = "";
String wifi_pass = "";
String ws_url    = "";
String ble_pin   = "";

String recvSSID = "", recvPASS = "", recvWS = "", recvPIN = "";
String recvNEWPIN = "";
bool haveSSID = false, havePASS = false, haveWS = false, havePIN = false;

bool wifiConnected = false;
bool wsConnected   = false;

const int WIFI_CONNECT_TRIES = 20;
const int WIFI_RECONNECT_CYCLES_BEFORE_PROVISION = 6;
int wifiFailCycles = 0;
int wsFailCycles   = 0;
unsigned long lastServerContact = 0;

BLEServer*         pServer  = nullptr;
BLEService*        pService = nullptr;
BLECharacteristic* ssidChar;
BLECharacteristic* passChar;
BLECharacteristic* wsChar;
BLECharacteristic* pinChar;
BLECharacteristic* newpinChar;
BLECharacteristic* cmdChar;
BLECharacteristic* statusChar;

String sanitizeBleText(String s) {
  s.replace("\r", "");
  s.replace("\n", "");
  s.replace("\0", "");
  s.trim();
  return s;
}

void setStatus(const char* code) {
  if (statusChar) {
    statusChar->setValue(code);
    statusChar->notify();
    Serial.printf("Status update sent to BLE: %s\n", code);
  }
}

// NVS survives sketch uploads, so a reflashed board could keep an old owner's PIN
// and WiFi. Wipe everything whenever the firmware changes - every flash starts
// clean: no PIN, no WiFi, BLE provisioning. An empty PIN means unclaimed, which
// is the only state where provisioning is allowed without presenting one.
//
// The fingerprint is the running sketch's MD5, not __DATE__/__TIME__: those
// would be baked in when *this library* was compiled, and a cached library
// object would then never notice a new sketch.
void resetPrefsIfNewFirmware() {
  const String buildTag = ESP.getSketchMD5();
  prefs.begin("iotdata", false);
  if (prefs.getString("build", "") != buildTag) {
    prefs.clear();
    prefs.putString("build", buildTag);
    Serial.println("New firmware build detected. Settings wiped: no PIN, no WiFi config.");
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
  ble_pin   = prefs.getString("pin",  "");   // "" = unclaimed, never "0000"
  prefs.end();
  wifi_ssid = sanitizeBleText(wifi_ssid);
  wifi_pass = sanitizeBleText(wifi_pass);
  ws_url    = sanitizeBleText(ws_url);
  ble_pin   = sanitizeBleText(ble_pin);
  Serial.printf("Loaded: ssid='%s', ws='%s', pin_len=%d\n",
    wifi_ssid.c_str(), ws_url.c_str(), (int)ble_pin.length());
}

class GenericWriteCallback : public BLECharacteristicCallbacks {
 public:
  void onWrite(BLECharacteristic* pChar) {
    String s = String(pChar->getValue().c_str());   // std::string on core 2.x, String on 3.x
    s = sanitizeBleText(s);
    String uuid = pChar->getUUID().toString().c_str();
    // The length only, never the value: two of these are the WiFi password and the PIN.
    Serial.printf("BLE write received: %s (%d bytes)\n", uuid.c_str(), (int)s.length());

    if      (uuid == SSID_UUID)   { recvSSID = s; haveSSID = true; }
    else if (uuid == PASS_UUID)   { recvPASS = s; havePASS = true; }
    else if (uuid == WSURL_UUID)  { recvWS   = s; haveWS   = true; }
    else if (uuid == PIN_UUID)    { recvPIN  = s; havePIN  = true; }
    else if (uuid == NEWPIN_UUID) { recvNEWPIN = s; }
  }
};

// A PIN the owner will actually be asked for, rather than one that defeats the
// check. Keep this in step with normalize_device_pin() in
// software/server/validators.py.
bool isAcceptablePin(const String& p) {
  if (p.length() != 4) return false;
  for (int i = 0; i < 4; i++) {
    if (!isDigit(p[i])) return false;
  }
  bool allSame = true;
  for (int i = 1; i < 4; i++) {
    if (p[i] != p[0]) { allSame = false; break; }
  }
  if (allSame) return false;                      // 0000, 1111, ...
  if (p == "1234" || p == "4321") return false;   // the next thing anyone tries
  return true;
}

// The BLE library of core 2.0.x does NOT start advertising again when a phone
// disconnects (its own comment says it should). Without this, one dropped or
// refused connection leaves the board silent until it is rebooted, and the app
// reports that it cannot find the device.
class ProvisionServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer*) override {
    Serial.println("BLE: phone connected.");
  }
  void onDisconnect(BLEServer*) override {
    Serial.println("BLE: phone disconnected. Advertising again.");
    BLEDevice::startAdvertising();
  }
};

// Why a WiFi attempt failed, in the serial log. Reason codes are the ESP-IDF
// ones: 201 no AP found (wrong name, or a 5 GHz-only network - the C3 is
// 2.4 GHz only), 202/15/204 auth or handshake failed (wrong password), 205
// connection failed, 2 auth expired.
void onWifiDisconnected(WiFiEvent_t, WiFiEventInfo_t info) {
  Serial.printf("WiFi: disconnected, reason %d\n", (int)info.wifi_sta_disconnected.reason);
}

// What the board can actually hear. If the network is not in this list, no
// password will help: it is out of range or on 5 GHz.
void logVisibleNetworks(const String& wanted) {
  int n = WiFi.scanNetworks(false, true);   // blocking, include hidden
  Serial.printf("WiFi scan: %d networks.\n", n);
  bool found = false;
  for (int i = 0; i < n; i++) {
    bool match = WiFi.SSID(i) == wanted;
    if (match) found = true;
    Serial.printf("  %s '%s'  %d dBm  ch %d\n", match ? "->" : "  ",
                  WiFi.SSID(i).c_str(), (int)WiFi.RSSI(i), (int)WiFi.channel(i));
  }
  Serial.println(found ? "WiFi scan: the network was found." : "WiFi scan: the network was NOT found (name differs, out of range, or 5 GHz only).");
  WiFi.scanDelete();
}

void startBLEProvisioning() {
  WiFi.onEvent(onWifiDisconnected, ARDUINO_EVENT_WIFI_STA_DISCONNECTED);
  String advName = "Maya-" + String(DEVICE_ID);
  Serial.printf("Starting BLE provisioning mode. Advertising as '%s'...\n", advName.c_str());
  Serial.printf("PIN protection: %s\n", ble_pin == "" ? "unclaimed (first owner sets the PIN)" : "enabled");

  BLEDevice::setMTU(517);
  BLEDevice::init(advName.c_str());
  pServer  = BLEDevice::createServer();
  pServer->setCallbacks(new ProvisionServerCallbacks());
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

  statusChar->setValue("0");

  pService->start();
  BLEDevice::startAdvertising();
  Serial.println("BLE advertising started. Waiting for SSID, PASS, WSURL, PIN...");

  unsigned long start   = millis();
  unsigned long timeout = 5UL * 60 * 1000;
  while (millis() - start < timeout) {
    if (haveSSID && havePASS && haveWS && havePIN) {
      Serial.println("All provisioning values received.");

      // An empty stored PIN means unclaimed: the first owner's PIN is accepted
      // as-is and becomes the device's PIN. Any stored PIN is then required.
      if (ble_pin != "" && recvPIN != ble_pin) {
        Serial.println("PIN mismatch. Rejecting.");
        setStatus("6");
        havePIN = haveSSID = havePASS = haveWS = false;
        recvPIN = recvSSID = recvPASS = recvWS = recvNEWPIN = "";
        continue;
      }

      // The PIN in force after this round must be a real one. Rejecting it here,
      // rather than saving it, is what stops the board from ending up with a PIN
      // that cannot protect it.
      String pinToStore = recvNEWPIN.length() > 0 ? recvNEWPIN : recvPIN;
      if (!isAcceptablePin(pinToStore)) {
        Serial.println("PIN rejected: must be 4 digits, not 0000/1111/1234.");
        setStatus("9");
        havePIN = haveSSID = havePASS = haveWS = false;
        recvPIN = recvSSID = recvPASS = recvWS = recvNEWPIN = "";
        continue;
      }

      setStatus("1");
      delay(200);

      bool wifiOk = false;
      int connectRetries = 3;
      for (int r = 0; r < connectRetries; r++) {
        Serial.printf("Attempting WiFi connect to '%s' (try %d/%d)...\n", recvSSID.c_str(), r + 1, connectRetries);
        WiFi.persistent(false);
        WiFi.mode(WIFI_STA);
        WiFi.disconnect(true);
        delay(150);
#if CONFIG_IDF_TARGET_ESP32C3
        // Many C3 boards (SuperMini and clones) have an antenna that cannot take
        // full transmit power: they hear the router and never complete the
        // handshake. A lower TX power is the usual cure.
        WiFi.mode(WIFI_STA);
        WiFi.setTxPower(WIFI_POWER_8_5dBm);
#endif
        if (r == 0) logVisibleNetworks(recvSSID);
        WiFi.begin(recvSSID.c_str(), recvPASS.c_str());

        int attempts = 0;
        while (attempts < WIFI_CONNECT_TRIES) {
          delay(500);
          if (WiFi.status() == WL_CONNECTED) { wifiOk = true; break; }
          attempts++;
        }
        if (wifiOk) break;
        Serial.println("WiFi connect attempt failed.");
      }

      if (!wifiOk) {
        Serial.println("WiFi connection failed during BLE setup.");
        setStatus("4");
        WiFi.disconnect(true);
        delay(1000);
        haveSSID = havePASS = haveWS = havePIN = false;
        recvPIN = recvSSID = recvPASS = recvWS = recvNEWPIN = "";
        start = millis();
        continue;
      }

      setStatus("2");
      Serial.println("WiFi connected during provisioning.");

      // Commit the verified credentials, then reboot to reach the server. The
      // TLS WebSocket is deliberately NOT opened while BLE is up: the single
      // 2.4GHz radio is shared with the BLE link to the phone, and a TLS
      // handshake gets corrupted under that coexistence (and Bluedroid + mbedTLS
      // compete for heap). A clean WiFi-only boot connects reliably.
      wifi_ssid = recvSSID;
      wifi_pass = recvPASS;
      ws_url    = recvWS;
      ble_pin   = pinToStore;
      saveSettings();
      wifiFailCycles = 0;
      wsFailCycles   = 0;
      wifiConnected  = true;

      setStatus("8");
      Serial.println("Credentials saved. Rebooting to connect to the server with BLE off.");
      delay(1500);

      BLEDevice::stopAdvertising();
      delay(100);
      ESP.restart();
    }
    delay(200);
  }

  Serial.println("Provisioning timed out.");
  BLEDevice::stopAdvertising();
  BLEDevice::deinit();
  statusChar = ssidChar = passChar = wsChar = pinChar = newpinChar = cmdChar = nullptr;
}

bool connectToWiFiOnce() {
  if (WiFi.status() == WL_CONNECTED) { wifiConnected = true; return true; }
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

void sendFrame(const char* json, size_t len) {
  webSocket.sendTXT((uint8_t*)json, len);
}

void webSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
  if (!self) return;
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
      // The PIN is verified by the server here, and the descriptor is the first
      // moment it learns what this device is (PROTOCOL.md 4.1, 5).
      if (!self->sendIdentify(DEVICE_ID.c_str(), ble_pin.c_str(),
                              WiFi.localIP().toString().c_str(),
                              WiFi.macAddress().c_str(), sendFrame)) {
        Serial.printf("[Maya] Identify not sent: %s\n", self->problem() ? self->problem() : "descriptor unusable");
      }
      break;
    }

    case WStype_TEXT: {
      lastServerContact = millis();
      mayalib::Action a = self->onFrame((const char*)payload, length, DEVICE_ID.c_str(),
                                     (uint32_t)millis(), sendFrame);
      if (a == mayalib::REBOOT) {
        delay(200);
        ESP.restart();
      } else if (a == mayalib::FACTORY_RESET) {
        self->factoryReset();
      }
      break;
    }

    default: break;
  }
}

void startWebSocket() {
  if (wsConnected) return;
  if (ws_url.length() == 0) { Serial.println("No WS URL configured."); return; }

  bool useSSL = false;
  String url  = ws_url;
  // wss:// is checked first: "wss://" also starts with "ws"
  if (url.startsWith("wss://")) { useSSL = true; url = url.substring(6); }
  else if (url.startsWith("ws://")) { url = url.substring(5); }

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
    // beginSSL with no CA cert skips verification - needed for Fly.io TLS
    webSocket.beginSSL(host.c_str(), port, path.c_str());
  } else {
    webSocket.begin(host.c_str(), port, path.c_str());
  }

  webSocket.onEvent(webSocketEvent);
  webSocket.setReconnectInterval(5000);
  // Protocol-level ping/pong detects half-open sockets the TCP stack never
  // reports (server scale-to-zero, a NAT mapping dropped). Ping every 15s; two
  // missed pongs fire DISCONNECTED and the reconnect timer takes over.
  webSocket.enableHeartbeat(15000, 3000, 2);
  webSocket.setExtraHeaders("ngrok-skip-browser-warning: true");
}

}  // namespace

// ---------------------------------------------------------------------------

void Maya::enableHealth() {
  addReserved("_rssi");
  addReserved("_uptime");
  addReserved("_fw");
  health_ = true;
}

void Maya::refreshHealth() {
  if (!health_) return;
  setNumber("_rssi", WiFi.RSSI());
  setNumber("_uptime", millis() / 1000);
}

bool Maya::askMaya(const char* text, mayalib::AgentReplyFn onReply) {
  return wsConnected && agentRequest(DEVICE_ID.c_str(), text, onReply, sendFrame);
}

const char* Maya::id() const { return DEVICE_ID.c_str(); }
bool Maya::connected() const { return wsConnected; }

void Maya::factoryReset() {
  Serial.println("Factory reset. Wiping settings and rebooting.");
  delay(300);
  prefs.begin("iotdata", false);
  prefs.clear();   // WiFi, WS URL, PIN and build tag: boots fresh into BLE provisioning
  prefs.end();
  ESP.restart();
}

void Maya::begin() {
  self = this;
  Serial.begin(115200);

  // Unique per-board id from the factory MAC (lower 32 bits).
  DEVICE_ID = "esp32-" + String((uint32_t)ESP.getEfuseMac(), HEX);
  Serial.printf("Device ID: %s\n", DEVICE_ID.c_str());

  if (problem()) {
    // Not fatal to the board, but the server would refuse this descriptor, so
    // say so where the person writing the sketch is looking.
    Serial.printf("[Maya] Declaration problem: %s\n", problem());
  }

  resetPrefsIfNewFirmware();
  loadSettings();

  // The local link (7): grants and the epoch come back from flash, and the core is
  // told how to read the clock, send a radio frame and find the time.
  setMillis([]() { return (uint32_t)millis(); });
  setClock([]() -> uint32_t {
    time_t t = time(nullptr);
    return t > 1700000000 ? (uint32_t)t : 0;   // 0 = SNTP has not answered: expiry is then not evaluable (7.1)
  });
  setPeerTransport(radioSend);
  beginPeering(&peerStorage, DEVICE_ID.c_str());

  if (wifi_ssid.length() == 0) {
    Serial.println("No WiFi config. Entering BLE provisioning.");
    startBLEProvisioning();
    loadSettings();
  }

  if (!connectToWiFiOnce()) {
    Serial.println("Boot WiFi failed. Entering BLE provisioning for re-setup.");
    startBLEProvisioning();
    loadSettings();
    connectToWiFiOnce();
  } else {
    startWebSocket();
  }
  if (WiFi.status() == WL_CONNECTED) {
    configTime(0, 0, "pool.ntp.org", "time.google.com");   // for grant expiry; harmless if it never answers
    startEspNow();
  }
  refreshHealth();
}

void Maya::loop() {
  // WiFi watchdog - every 3s
  if (millis() - lastWiFiCheck_ > 3000) {
    lastWiFiCheck_ = millis();
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

  webSocket.loop();

  // The local link: frames the radio callback queued, then the peer list.
  while (rxTail != rxHead) {
    RxSlot& slot = rxq[rxTail];
    onLocalFrame(slot.data, slot.len, slot.mac);
    rxTail = (rxTail + 1) % RX_SLOTS;
  }
  syncEspNowPeers(*this);
  agentTick();   // a request the server never answered is given up on (8.1)

  // Zombie-link watchdog: with pings every 15s the server should never be silent
  // for long while "connected". If it is, force a disconnect so the reconnect
  // timer takes over. Deliberately NOT ESP.restart(): that would drop every
  // output the sketch is holding.
  if (wsConnected && millis() - lastServerContact > 180000) {
    Serial.println("[WS] No server contact for 3 min. Forcing reconnect.");
    wsConnected = false;
    webSocket.disconnect();
  }

  if (wsFailCycles >= 5 && millis() - lastWarning_ > 30000) {
    Serial.println("Warning: Multiple WebSocket connection failures. Retrying in background...");
    lastWarning_ = millis();
  }

  if (wsConnected) {
    // Changes the sketch made, at most four times a second: a noisy sensor
    // calling setNumber() every pass must not turn into a frame every pass.
    if (millis() - lastFlush_ > 250) {
      lastFlush_ = millis();
      flush(DEVICE_ID.c_str(), (uint32_t)millis(), sendFrame);
    }
    // The audit of what the local link did (7.3). Buffered while offline, sent when due.
    flushPeerLog(DEVICE_ID.c_str(), sendFrame);
    // A hub tells the server its channel (a router that moves silently breaks every
    // pairing otherwise, 5.9) and carries what its sensors sent (7.5).
    if (isHub()) {
      sendHubStatus(DEVICE_ID.c_str(), (uint8_t)WiFi.channel(), sendFrame);
      flushRelay(DEVICE_ID.c_str(), sendFrame);
    }
    // A full report every 30s doubles as the keep-alive the server's
    // last-heartbeat time comes from.
    if (millis() - lastFull_ > 30000) {
      lastFull_ = millis();
      refreshHealth();
      sendFullState(DEVICE_ID.c_str(), (uint32_t)millis(), sendFrame);
    }
  }

  delay(10);
}

// ---------------------------------------------------------------------------
// a battery sensor that reports through a hub (PROTOCOL.md 5.9)
// ---------------------------------------------------------------------------
//
// The shape of a wake: setup() declares capabilities, calls beginSensor(), sets the
// values it read, calls reportNow(), then sleepFor(). Nothing here loops; the sensor
// is awake for well under a second when its hub answers.
//
// Like the rest of this file, this has been compiled and never run on a board.

void Maya::beginSensor() {
  self = this;
  Serial.begin(115200);
  DEVICE_ID = "esp32-" + String((uint32_t)ESP.getEfuseMac(), HEX);
  if (problem()) Serial.printf("[Maya] Declaration problem: %s\n", problem());

  resetPrefsIfNewFirmware();
  loadSettings();

  setMillis([]() { return (uint32_t)millis(); });
  setClock([]() -> uint32_t {
    time_t t = time(nullptr);
    return t > 1700000000 ? (uint32_t)t : 0;
  });
  setSecondsClock([]() { return sensorSecs(); });     // keeps counting through sleep
  setPeerTransport(radioSend);
  beginPeering(&peerStorage, DEVICE_ID.c_str());
  restoreHubState(rtcFails, rtcDownSince, rtcAnnounced);

  // The first time a sensor is switched on it needs WiFi and the server once, to be
  // claimed and to be handed its pairing. After that it visits again only daily.
  if (wifi_ssid.length() == 0) {
    Serial.println("No WiFi config. Entering BLE provisioning.");
    startBLEProvisioning();
    loadSettings();
  }
}

// Joins WiFi, connects to the server, and stays long enough to be told everything it
// needs: its grants, the hub's channel, and (once) that the hub failed.
bool Maya::goOnline() {
  if (!connectToWiFiOnce()) return false;
  startWebSocket();
  uint32_t t = millis();
  while (!wsConnected && millis() - t < 15000) { webSocket.loop(); delay(10); }
  if (!wsConnected) return false;

  // identify has gone; the server answers with peer_grant / peer_sync / hub_channel
  t = millis();
  while (millis() - t < 1500) { webSocket.loop(); delay(10); }

  flush(DEVICE_ID.c_str(), (uint32_t)millis(), sendFrame);       // hub_failed, anything identify did not carry
  flushPeerLog(DEVICE_ID.c_str(), sendFrame);
  t = millis();
  while (millis() - t < 400) { webSocket.loop(); delay(10); }

  rtcSynced = true;
  rtcLastSync = sensorSecs();
  rtcChannel = (uint8_t)WiFi.channel();     // the hub is on the same router, so this is its channel too
  return true;
}

bool Maya::reportNow() {
  bool due = !rtcSynced || hubId() == nullptr || sensorSecs() - rtcLastSync >= SENSOR_SYNC_EVERY_S;

  if (!due && hubUsable()) {
    // Radio only: no association, no DHCP, no TLS - which is the whole of ESP-NOW's
    // advantage (5.9), and why this path is a few hundred milliseconds.
    uint8_t channel = hubChannel() ? hubChannel() : (rtcChannel ? rtcChannel : 1);
    WiFi.persistent(false);
    WiFi.mode(WIFI_STA);
    WiFi.disconnect();
    esp_wifi_set_promiscuous(true);       // the documented way to pin the channel while not associated
    esp_wifi_set_channel(channel, WIFI_SECOND_CHAN_NONE);
    esp_wifi_set_promiscuous(false);
    if (startEspNow()) {
      syncEspNowPeers(*this);
      if (report()) {
        hubState(rtcFails, rtcDownSince, rtcAnnounced);
        return true;
      }
    }
  }

  // The hub could not be reached, is being given up on, or it is simply the daily visit.
  // Whatever is still buffered goes to the server instead - the latest value of each
  // key, because a state frame has no timestamp - and if the hub is down the first
  // report says so.
  fallBackToServer();
  bool ok = goOnline();
  hubState(rtcFails, rtcDownSince, rtcAnnounced);
  return ok;
}

void Maya::sleepFor(uint32_t seconds) {
  hubState(rtcFails, rtcDownSince, rtcAnnounced);
  rtcSecs += millis() / 1000 + seconds;
  Serial.flush();
  esp_deep_sleep((uint64_t)seconds * 1000000ULL);
}
