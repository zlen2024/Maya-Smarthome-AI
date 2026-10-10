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
};

// A frame the transport must put on the air: where, and what.
typedef std::function<bool(const uint8_t* mac, const uint8_t* data, size_t len)> PeerTx;
typedef std::function<void(const char* peer, const char* status, const char* failed)> PeerAckFn;
typedef std::function<void(const char* peer, const char* kind, JsonObjectConst payload)> PeerMsgFn;

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
};

// 5.1 - `[a-z0-9_]{1,24}`.
bool validKey(const char* key);

}  // namespace mayalib
