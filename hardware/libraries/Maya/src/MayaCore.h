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
  bool sendIdentify(const char* id, const char* pin, const char* ip, Send send);

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

 private:
  Cap& add(const char* key, const char* label, Kind kind, bool reserved = false);
  Cap& refuse(const char* why);
  bool parseValue(Cap& c, JsonVariantConst raw, Value& out);
  void writeValue(JsonObject obj, const Cap& c) const;
  bool sendDoc(DynamicJsonDocument& doc, Send send) const;
  void handleSet(JsonObjectConst root, const char* myId, Send send);
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
};

// 5.1 - `[a-z0-9_]{1,24}`.
bool validKey(const char* key);

}  // namespace mayalib
