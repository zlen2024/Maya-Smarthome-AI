// MayaCore - the Maya Device Protocol v2 (PROTOCOL.md), with no hardware in it.
//
// This file and MayaCore.cpp touch nothing but ArduinoJson, so they compile on a
// laptop. That is deliberate: the part of a device that has to be *right* is the
// descriptor it declares and the way it answers a `set`, and both can be checked
// byte for byte against the real server without flashing a board
// (extras/test/). Everything that needs a radio lives in Maya.h.
//
// If this file and PROTOCOL.md disagree, PROTOCOL.md wins and this has a bug
// (section 11).
#pragma once

#include <stddef.h>
#include <stdint.h>
#include <functional>
#include <ArduinoJson.h>

#define MAYA_PROTO 2          // the one version this library speaks (11); it does not negotiate below it

#ifndef MAYA_MAX_CAPS
#define MAYA_MAX_CAPS 32      // 5.5 - the server rejects more
#endif
#ifndef MAYA_TEXT_BUF
#define MAYA_TEXT_BUF 65      // longest text/enum value held, plus the terminator
#endif
#define MAYA_MAX_DESCRIPTOR 4096   // 5.5
#ifndef MAYA_TX_BYTES
#define MAYA_TX_BYTES 8192    // ArduinoJson pool for building a frame
#endif
#ifndef MAYA_RX_BYTES
#define MAYA_RX_BYTES 1536    // ArduinoJson pool for reading one
#ifndef MAYA_MAX_PEERS
#define MAYA_MAX_PEERS 8      // grants held at once (7.1); each is ~310 bytes of flash
#endif
#ifndef MAYA_PEER_SCOPE
#define MAYA_PEER_SCOPE 8     // capability keys one grant may name
#endif
#ifndef MAYA_PEER_LOG_CAP
#define MAYA_PEER_LOG_CAP 64  // audit ring buffer (7.3 RECOMMENDS at least 64)
#endif
#define MAYA_LOCAL_FRAME_MAX 250   // one ESP-NOW payload, MAC included (7.2)
#define MAYA_AGENT_TEXT_MAX 280    // bytes, a request and a reply (8.1)
#define MAYA_AGENT_TIMEOUT_MS 45000   // a device gives up after this (8.1)
#endif
#ifndef MAYA_RELAY_QUEUE
#define MAYA_RELAY_QUEUE 32   // a hub holds this many frames waiting for the server (7.5 RECOMMENDS 32)
#endif
#define MAYA_RELAY_BATCH 16   // frames in one `relay` message (7.5)
#define MAYA_RELAY_RATE 12    // frames a minute a hub takes from one sender (7.5)
#define MAYA_RELAY_ACK_MS 10000   // a hub sends again when the server has not answered in this long
#ifndef MAYA_REPORT_BUFFER
#define MAYA_REPORT_BUFFER 16 // readings a sensor keeps while its hub cannot be reached (5.9 rule 4)
#endif
#define MAYA_HUB_FAIL_LIMIT 3 // consecutive failures before a sensor gives up on its hub (5.9 rule 2)
#ifndef MAYA_HUB_RETRY_S
#define MAYA_HUB_RETRY_S 1800 // while on the fallback path, try the hub again this often (5.9 rule 5)
#endif

namespace mayalib {

// 5.2 - a closed set of ten. A new one costs a widget in the app, so
// expressiveness is supposed to arrive as a field, not here.
enum Kind : uint8_t {
  SWITCH, RANGE, NUMBER, TEXT, ENUM, BUTTON, COLOR, TIME, DURATION, LOCATION
};

enum Access : uint8_t { RW, R, W };

// What a write handler is handed. Only the member that matches the capability's
// kind is meaningful: `on` for a switch, `n` for range/number/duration, `s` for
// text/enum/color/time, `lat`/`lng` for location. A button carries nothing.
struct Value {
  bool on = false;
  double n = 0;
  char s[MAYA_TEXT_BUF] = {0};
  double lat = 0, lng = 0;
};

// Return true when the hardware did what was asked. false answers `bad_value`
// (9): the value was well-formed but this device would not take it.
typedef std::function<bool(const Value&)> Handler;

// One declared capability, plus the value the library currently believes it has.
class Cap {
 public:
  // fluent modifiers, chained off the add*() call
  Cap& unit(const char* u)  { unit_ = u; return *this; }
  Cap& group(const char* g) { group_ = g; return *this; }
  Cap& readOnly()  { access_ = R; return *this; }   // a sensor
  Cap& writeOnly() { access_ = W; return *this; }   // it shows, never reads back
  Cap& history()   { history_ = true; return *this; }
  // 5.4 - hide this from Maya entirely. Fails closed on the server.
  Cap& agentDeny() { agentDeny_ = true; return *this; }
  // 5.4 - Maya must ask the user first, and the app shows a confirm step.
  Cap& confirm()   { confirm_ = true; return *this; }
  // Bounds for a number (5.2).
  Cap& limits(double lo, double hi) {
    hasMin_ = hasMax_ = true; min_ = lo; max_ = hi; return *this;
  }

  // set by the library
  const char* key_ = nullptr;
  const char* label_ = nullptr;
  Kind kind_ = SWITCH;
  Access access_ = RW;
  const char* unit_ = nullptr;
  const char* group_ = nullptr;
  const char* const* options_ = nullptr;
  uint8_t nOptions_ = 0;
  bool hasMin_ = false, hasMax_ = false, hasStep_ = false;
  double min_ = 0, max_ = 0, step_ = 0;
  bool history_ = false, agentDeny_ = false, confirm_ = false;
  Handler onWrite_;

  Value cur_;
  bool hasValue_ = false;
  bool dirty_ = false;       // changed since the last state report

  bool writable() const { return access_ == RW || access_ == W; }
  bool readable() const { return access_ == RW || access_ == R; }
};

// What the transport must do after a frame has been handled.
enum Action : uint8_t { NONE, REBOOT, FACTORY_RESET };

// Where the library keeps what must survive a reboot: its grants and its epoch.
// The Arduino half backs this with NVS; a test backs it with a directory.
class Storage {
 public:
  virtual ~Storage() {}
  virtual bool read(const char* name, uint8_t* buf, size_t cap, size_t& len) = 0;
  virtual bool write(const char* name, const uint8_t* buf, size_t len) = 0;
};

// One grant as held on the device (PROTOCOL.md 7.1). Plain data, so it can be
// written to flash as it is.
struct PeerRec {
  bool used;
  uint8_t role;               // 1 = send, 2 = recv
  uint8_t purpose;            // 0 = control, 1 = relay (7.5)
  uint8_t channel;            // the peer's WiFi channel when the server said so (5.9); 0 = unknown
  bool hasKey;                // false only for the hub end of a relay grant: a hub is never given the key (7.5)
  char grant[16];             // "g-42"
  char peer[32];              // the other device's id
  uint8_t mac[6];             // ... and its radio address
  uint8_t key[32];
  uint8_t nScope;
  char scope[MAYA_PEER_SCOPE][25];
  uint32_t expires;           // unix seconds; 0 = unknown, which is never judged expired
  uint32_t inEp;              // newest epoch accepted from the peer (persisted)
  // RAM only: reset on boot
  uint32_t inSeq;
  bool inFresh;               // first frame since boot in inEp may carry any seq (7.2 residual window)
  uint32_t outSeq;
  uint32_t winStart;          // a hub's per-sender rate window (7.5)
  uint16_t winCount;
};

// A frame the transport must put on the air: where, and what.
typedef std::function<bool(const uint8_t* mac, const uint8_t* data, size_t len)> PeerTx;
typedef std::function<void(const char* peer, const char* status, const char* failed)> PeerAckFn;
typedef std::function<void(const char* peer, const char* kind, JsonObjectConst payload)> PeerMsgFn;
// What came back from Maya (8.1). `status` is ok, not_permitted, rate_limited, busy,
// bad_value or unavailable; anything else MUST be treated as failure. `retryAfter` is
// seconds, and only meaningful for rate_limited.
typedef std::function<void(const char* status, const char* text, uint32_t retryAfter)> AgentReplyFn;

// Where finished frames go. The core builds a frame and hands it over; whether
// that is a WebSocket or a test's list is not its business.
typedef std::function<void(const char* json, size_t len)> Send;

class Core {
 public:
  Core(const char* model, const char* fw) : model_(model), fw_(fw) {}

  // declaring capabilities
  // `key` and `label` are kept as pointers, not copied: pass string literals.
  Cap& addSwitch(const char* key, const char* label, std::function<bool(bool)> fn = nullptr);
  Cap& addRange(const char* key, const char* label, double min, double max, double step,
                std::function<bool(double)> fn = nullptr);
  // A number is almost always a sensor - chain .readOnly(). With a handler it is
  // a setpoint the user types; give it limits with .limits().
  Cap& addNumber(const char* key, const char* label, std::function<bool(double)> fn = nullptr);
  Cap& addText(const char* key, const char* label, uint8_t maxChars,
               std::function<bool(const char*)> fn = nullptr);
  Cap& addEnum(const char* key, const char* label, const char* const* options, uint8_t n,
               std::function<bool(const char*)> fn = nullptr);
  Cap& addButton(const char* key, const char* label, std::function<void()> fn);
  Cap& addColor(const char* key, const char* label, std::function<bool(const char*)> fn = nullptr);
  Cap& addTime(const char* key, const char* label, std::function<bool(const char*)> fn = nullptr);
  Cap& addDuration(const char* key, const char* label, double maxSeconds,
                   std::function<bool(double)> fn = nullptr);
  Cap& addLocation(const char* key, const char* label);   // read-only; report with setLocation()

  // 5.3 - health keys have a fixed shape and a fixed meaning, so they are
  // declared by name rather than described. Accepts _batt, _rssi, _fw, _uptime.
  Cap& addReserved(const char* key);

  // reporting what the hardware reads
  // Each returns false for an unknown key or one of another kind. A changed
  // value is queued and goes out on the next flush(); an unchanged one is not
  // re-sent (6.1: send only what changed).
  bool setSwitch(const char* key, bool on);
  bool setNumber(const char* key, double v);
  bool setText(const char* key, const char* v);
  bool setLocation(const char* key, double lat, double lng);

  Cap* find(const char* key);
  size_t count() const { return n_; }

  // Declarations that were refused (bad key, duplicate, past 32). Null when the
  // firmware declared cleanly. begin() prints it - see Maya.h.
  const char* problem() const { return problem_; }

  // the wire
  // Builds the identify frame (5). False if the declaration is unusable, e.g.
  // the descriptor passes 4 KB; nothing is sent in that case, because the server
  // would only reject it.
  bool sendIdentify(const char* id, const char* pin, const char* ip, const char* mac, Send send);

  // Reads one frame from the server and answers it. Frames for another id are
  // ignored (3). The returned action is for the transport to carry out *after*
  // the ack has gone out.
  Action onFrame(const char* data, size_t len, const char* myId, uint32_t uptimeMs, Send send);

  // Sends a partial state report of everything that changed. No-op if nothing
  // did. `uptimeMs` rides along as 6.1 shows.
  bool flush(const char* myId, uint32_t uptimeMs, Send send);

  // A full state report - every identify and every get_status (6.1).
  bool sendFullState(const char* myId, uint32_t uptimeMs, Send send);

  bool hasPending() const;

  // ── asking Maya for help (8) ─────────────────────────────────────────────
  // Sends one request and remembers the callback. False if a request is already
  // waiting (the server allows one at a time), or the text is empty or longer than
  // 280 bytes: those are refused here, so the sketch learns at once rather than
  // after a round trip. Whether the device is *allowed* to ask is a person's choice
  // in the app, not the sketch's: until it is switched on the answer is not_permitted.
  bool agentRequest(const char* myId, const char* text, AgentReplyFn cb, Send send);
  // Gives up on a request that has waited past 45 s, with status "unavailable".
  void agentTick();
  bool agentWaiting() const { return agentPending_; }

  // ── the local link (7) ───────────────────────────────────────────────────
  // Call once, after every capability is declared. Loads the stored grants and
  // moves to a new epoch (7.2), which is what lets a rebooted sender be newer
  // rather than a replay. Without a Storage the device holds grants only until it
  // reboots and starts every boot at epoch 1, which a peer will reject as a
  // replay - so a real device must give one.
  void beginPeering(Storage* storage, const char* myId);
  void setPeerTransport(PeerTx tx) { peerTx_ = tx; }
  // Seconds since 1970, or 0 when the device does not know the time. With no
  // time, expiry is not evaluable and a grant is honoured until revoked (7.1).
  void setClock(std::function<uint32_t()> epochNow) { epochNow_ = epochNow; }
  void setMillis(std::function<uint32_t()> ms) { millis_ = ms; }
  void onPeerAck(PeerAckFn fn) { peerAck_ = fn; }
  void onPeerMessage(PeerMsgFn fn) { peerMsg_ = fn; }

  // A radio frame arrived from `srcMac`. Answers over the peer transport.
  void onLocalFrame(const uint8_t* data, size_t len, const uint8_t srcMac[6]);

  // Send to a peer this device holds a `send` grant for. False if there is none,
  // it has expired, the key is outside its scope, or the frame will not fit in
  // 250 bytes - the caller learns, rather than a frame being quietly mangled.
  bool peerSetSwitch(const char* peer, const char* key, bool on);
  bool peerSetNumber(const char* peer, const char* key, double v);
  bool peerSetText(const char* peer, const char* key, const char* v);
  bool peerPress(const char* peer, const char* key);
  bool peerMessage(const char* peer, const char* kind, std::function<void(JsonObject)> fill);

  // The audit (7.3). Sends at most one `peer_log` frame, and only when due: every
  // 10 s, or at once when an entry reports something other than ok.
  bool flushPeerLog(const char* myId, Send send);
  size_t peerLogPending() const { return logCount_; }

  // For the transport: which radio addresses it must be able to reach, and a
  // counter that moves whenever that list does.
  size_t peerCount() const;
  bool peerMacAt(size_t i, uint8_t mac[6]) const;
  uint32_t peersVersion() const { return peersVersion_; }
  uint32_t epoch() const { return ep_; }
  const PeerRec* peerByGrant(const char* grant) const;

  // ── a hub (5.9, 7.5) ─────────────────────────────────────────────────────
  // Offers to carry other devices' readings: identify says `"hub":true`. That is
  // all it is - an offer. A person still has to pair a sensor to it. Call before
  // the first identify. Allocates the queue, so a device that is not a hub pays
  // nothing for this.
  void enableHub();
  bool isHub() const { return hub_; }
  // Sends one `relay` message if frames are waiting and the last one has been
  // answered. A hub holds no key for its sensors, so it cannot check a frame's MAC;
  // it forwards what came from a sensor it was paired with and the server does the
  // authenticating (7.5).
  bool flushRelay(const char* myId, Send send);
  // Tells the server the WiFi channel (5.9), once per identify and again whenever
  // it changes. False when there is nothing new to say.
  bool sendHubStatus(const char* myId, uint8_t channel, Send send);
  size_t relayQueued() const { return relayCount_; }
  uint32_t relayDropped() const { return relayDropped_; }

  // ── a sensor that reports through a hub (5.9, 7.5) ───────────────────────
  // Seconds that keep counting across deep sleep, so a reading can say how old it
  // is (`age`) without a clock. Defaults to millis()/1000, which is right for a
  // device that never sleeps.
  void setSecondsClock(std::function<uint32_t()> fn) { secsFn_ = fn; }
  // Moves what changed since the last report into a small buffer, then tries to
  // carry the buffer to the hub, oldest first. True when nothing is left waiting;
  // false when there is no hub, the hub is being given up on, or a frame was not
  // acknowledged. Nothing is thrown away because the network was down: what does not
  // fit the buffer drops the oldest and is counted in reportsLost().
  bool report();
  // False once the hub has failed MAYA_HUB_FAIL_LIMIT times in a row, until
  // MAYA_HUB_RETRY_S has passed. The caller then reports through the server.
  bool hubUsable() const;
  bool hubDown() const { return hubFails_ >= MAYA_HUB_FAIL_LIMIT; }
  const char* hubId() const;       // the hub this device reports through, or null
  uint8_t hubChannel() const;      // its WiFi channel as the server last said, 0 if unknown
  size_t reportsBuffered() const { return repCount_; }
  uint32_t reportsLost() const { return repLost_; }
  // Gives the buffered readings back to the state report, so the next flush()
  // carries them to the server. Only the latest value of each key survives: a
  // state frame has no timestamp. The first flush also says `hub_failed`.
  size_t fallBackToServer();
  // What a deep-sleeping sensor must keep across a wake: consecutive failures, when
  // the hub was given up on, and whether the server has been told.
  void hubState(uint8_t& fails, uint32_t& downSince, bool& announced) const;
  void restoreHubState(uint8_t fails, uint32_t downSince, bool announced);

 private:
  Cap& add(const char* key, const char* label, Kind kind, bool reserved = false);
  Cap& refuse(const char* why);
  bool parseValue(Cap& c, JsonVariantConst raw, Value& out);
  void writeValue(JsonObject obj, const Cap& c) const;
  bool sendDoc(DynamicJsonDocument& doc, Send send) const;
  void handleSet(JsonObjectConst root, const char* myId, Send send);
  // The one place a set of values is validated and applied. `scope` (null for the
  // server) is the list of keys a peer may touch. Returns "ok" or a 9 status.
  const char* applyValues(JsonObjectConst values, const PeerRec* scope, const char** failed,
                          Cap** applied, size_t& nApplied);
  void handlePeerControl(JsonObjectConst root, const char* type);
  void handleAgentReply(JsonObjectConst root);
  void loadPeers();
  void savePeers();
  bool peerSend(PeerRec& g, const char* kind, std::function<void(JsonObject)> fill);
  bool peerSetKey(const char* peer, const char* key, std::function<void(JsonObject, const char*)> assign);
  bool peerSendRaw(PeerRec& g, DynamicJsonDocument& doc);
  PeerRec* findPeer(const char* grant);
  PeerRec* findSendGrant(const char* peer);
  bool expired(const PeerRec& g) const;
  bool inScope(const PeerRec& g, const char* key) const;
  void logPeer(const PeerRec& g, const char* dir, uint32_t ep, uint32_t seq, const char* kind,
               const char* summary, const char* result);
  uint32_t now() const { return millis_ ? millis_() : 0; }
  void addHubFailed(JsonDocument& doc);
  void handleRelayAck(JsonObjectConst root);
  void handleHubChannel(JsonObjectConst root);
  bool hubAccept(PeerRec& g, const uint8_t* data, size_t len, JsonDocument& doc, const uint8_t src[6]);
  PeerRec* findRelaySendGrant();
  void noteHubFailure();
  void bufferDirty(PeerRec& g);
  bool sendReadings(PeerRec& g);
  uint32_t secs() const;
  Action handleLegacy(JsonObjectConst root, const char* cmd, const char* myId, uint32_t uptimeMs, Send send);
  void sendAck(const char* myId, const char* req, const char* status, const char* failed,
               Cap** applied, size_t nApplied, Send send);
  void sendLegacyAck(const char* myId, const char* status, Send send);
  void sendSimpleAck(const char* myId, const char* req, const char* status, Send send);
  void commit(Cap& c, const Value& v);

  const char* model_;
  const char* fw_;
  Cap caps_[MAYA_MAX_CAPS];
  size_t n_ = 0;
  const char* problem_ = nullptr;
  Cap overflow_;          // handed back when a declaration is refused, so chaining stays valid

  // local link state
  struct LogEntry {
    char grant[16]; char dir[4]; uint32_t ep, seq, count; char kind[8]; char peer[32];
    char summary[40]; char result[16]; uint32_t at;
  };
  Storage* storage_ = nullptr;
  char myId_[32] = {0};
  PeerRec peers_[MAYA_MAX_PEERS];
  PeerTx peerTx_;
  std::function<uint32_t()> epochNow_;
  std::function<uint32_t()> millis_;
  PeerAckFn peerAck_;
  PeerMsgFn peerMsg_;
  uint32_t ep_ = 0;
  uint32_t peersVersion_ = 0;
  LogEntry log_[MAYA_PEER_LOG_CAP];
  size_t logHead_ = 0, logCount_ = 0;
  uint32_t logDropped_ = 0;
  uint32_t lastLogFlush_ = 0;
  bool logUrgent_ = false;
  bool peeringStarted_ = false;

  // a hub (7.5): frames waiting for the server, oldest first
  struct RelaySlot { char grant[16]; uint32_t ep, seq; char text[MAYA_LOCAL_FRAME_MAX + 1]; };
  bool hub_ = false;
  RelaySlot* relayQ_ = nullptr;
  size_t relayHead_ = 0, relayCount_ = 0, relayInflight_ = 0;
  uint32_t relaySentAt_ = 0, relayRetryAt_ = 0, relayDropped_ = 0;
  bool hubStatusSent_ = false;
  uint8_t hubStatusChannel_ = 0;

  // a sensor (5.9)
  struct Reading { Cap* cap; Value v; uint32_t takenAt; };
  Reading* rep_ = nullptr;
  size_t repHead_ = 0, repCount_ = 0;
  uint32_t repLost_ = 0;
  std::function<uint32_t()> secsFn_;
  uint8_t hubFails_ = 0;
  uint32_t hubDownSince_ = 0;
  bool hubAnnounced_ = false;
  char hubFailedPending_[32] = {0};

  AgentReplyFn agentCb_;
  bool agentPending_ = false;
  char agentReq_[16] = {0};
  uint32_t agentSince_ = 0;
  uint32_t agentCount_ = 0;
};

// 5.1 - `[a-z0-9_]{1,24}`.
bool validKey(const char* key);

}  // namespace mayalib
