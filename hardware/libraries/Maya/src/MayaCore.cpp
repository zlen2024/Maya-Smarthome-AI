#include "MayaCore.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

namespace mayalib {

static const char* const KIND_NAMES[] = {
  "switch", "range", "number", "text", "enum", "button", "color", "time", "duration", "location"
};

bool validKey(const char* key) {
  if (!key) return false;
  size_t n = strlen(key);
  if (n < 1 || n > 24) return false;
  for (size_t i = 0; i < n; i++) {
    char c = key[i];
    if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_')) return false;
  }
  return true;
}

static bool ieq(const char* a, const char* b) {
  if (!a || !b) return false;
  for (; *a && *b; a++, b++) {
    char x = (*a >= 'A' && *a <= 'Z') ? *a + 32 : *a;
    char y = (*b >= 'A' && *b <= 'Z') ? *b + 32 : *b;
    if (x != y) return false;
  }
  return *a == 0 && *b == 0;
}

// "ch1" .. "ch99": the keys a protocol-1 server's legacy commands address (Appendix A).
static bool isChannelKey(const char* key) {
  if (!key || key[0] != 'c' || key[1] != 'h' || !key[2]) return false;
  for (const char* p = key + 2; *p; p++) if (*p < '0' || *p > '9') return false;
  return true;
}

// ---------------------------------------------------------------------------
// declaring
// ---------------------------------------------------------------------------

Cap& Core::refuse(const char* why) {
  if (!problem_) problem_ = why;   // the first one is the one worth fixing
  overflow_ = Cap();
  return overflow_;
}

Cap& Core::add(const char* key, const char* label, Kind kind, bool reserved) {
  if (n_ >= MAYA_MAX_CAPS) return refuse("more than 32 capabilities (PROTOCOL.md 5.5)");
  if (!validKey(key)) return refuse("capability key must be [a-z0-9_], 1-24 chars (5.1)");
  if (key[0] == '_' && !reserved) return refuse("keys starting with _ are reserved for the protocol (5.3)");
  if (find(key)) return refuse("duplicate capability key");
  Cap& c = caps_[n_++];
  c = Cap();
  c.key_ = key;
  c.label_ = label;
  c.kind_ = kind;
  return c;
}

Cap& Core::addSwitch(const char* key, const char* label, std::function<bool(bool)> fn) {
  Cap& c = add(key, label, SWITCH);
  if (fn) c.onWrite_ = [fn](const Value& v) { return fn(v.on); };
  return c;
}

Cap& Core::addRange(const char* key, const char* label, double min, double max, double step,
                    std::function<bool(double)> fn) {
  if (!(max > min)) return refuse("range needs max > min");
  Cap& c = add(key, label, RANGE);
  c.hasMin_ = c.hasMax_ = true; c.min_ = min; c.max_ = max;
  if (step > 0) { c.hasStep_ = true; c.step_ = step; }
  if (fn) c.onWrite_ = [fn](const Value& v) { return fn(v.n); };
  return c;
}

Cap& Core::addNumber(const char* key, const char* label, std::function<bool(double)> fn) {
  Cap& c = add(key, label, NUMBER);
  if (fn) c.onWrite_ = [fn](const Value& v) { return fn(v.n); };
  else c.access_ = R;   // nothing can write it, so say so rather than leave a control that fails
  return c;
}

Cap& Core::addText(const char* key, const char* label, uint8_t maxChars,
                   std::function<bool(const char*)> fn) {
  Cap& c = add(key, label, TEXT);
  c.hasMax_ = true;
  c.max_ = maxChars < MAYA_TEXT_BUF - 1 ? maxChars : MAYA_TEXT_BUF - 1;
  if (fn) c.onWrite_ = [fn](const Value& v) { return fn(v.s); };
  else c.access_ = R;
  return c;
}

Cap& Core::addEnum(const char* key, const char* label, const char* const* options, uint8_t n,
                   std::function<bool(const char*)> fn) {
  if (!options || n == 0) return refuse("enum needs at least one option");
  for (uint8_t i = 0; i < n; i++)
    if (!options[i] || strlen(options[i]) >= MAYA_TEXT_BUF) return refuse("enum option too long");
  Cap& c = add(key, label, ENUM);
  c.options_ = options; c.nOptions_ = n;
  if (fn) c.onWrite_ = [fn](const Value& v) { return fn(v.s); };
  else c.access_ = R;
  return c;
}

Cap& Core::addButton(const char* key, const char* label, std::function<void()> fn) {
  Cap& c = add(key, label, BUTTON);
  if (fn) c.onWrite_ = [fn](const Value&) { fn(); return true; };
  return c;
}

Cap& Core::addColor(const char* key, const char* label, std::function<bool(const char*)> fn) {
  Cap& c = add(key, label, COLOR);
  if (fn) c.onWrite_ = [fn](const Value& v) { return fn(v.s); };
  else c.access_ = R;
  return c;
}

Cap& Core::addTime(const char* key, const char* label, std::function<bool(const char*)> fn) {
  Cap& c = add(key, label, TIME);
  if (fn) c.onWrite_ = [fn](const Value& v) { return fn(v.s); };
  else c.access_ = R;
  return c;
}

Cap& Core::addDuration(const char* key, const char* label, double maxSeconds,
                       std::function<bool(double)> fn) {
  Cap& c = add(key, label, DURATION);
  if (maxSeconds > 0) { c.hasMax_ = true; c.max_ = maxSeconds; }
  if (fn) c.onWrite_ = [fn](const Value& v) { return fn(v.n); };
  else c.access_ = R;
  return c;
}

Cap& Core::addLocation(const char* key, const char* label) {
  Cap& c = add(key, label, LOCATION);
  c.access_ = R;
  return c;
}

Cap& Core::addReserved(const char* key) {
  if (!key) return refuse("null reserved key");
  if (!strcmp(key, "_batt")) {
    Cap& c = add(key, nullptr, NUMBER, true);
    c.access_ = R; c.unit_ = "%"; c.hasMin_ = c.hasMax_ = true; c.min_ = 0; c.max_ = 100;
    return c;
  }
  if (!strcmp(key, "_rssi")) {
    Cap& c = add(key, nullptr, NUMBER, true);
    c.access_ = R; c.unit_ = "dBm";
    return c;
  }
  if (!strcmp(key, "_uptime")) {
    Cap& c = add(key, nullptr, NUMBER, true);
    c.access_ = R; c.unit_ = "s";
    return c;
  }
  if (!strcmp(key, "_fw")) {
    Cap& c = add(key, nullptr, TEXT, true);
    c.access_ = R;
    if (fw_) {
      strncpy(c.cur_.s, fw_, MAYA_TEXT_BUF - 1);
      c.hasValue_ = true;
    }
    return c;
  }
  return refuse("unknown reserved key; the _ namespace belongs to PROTOCOL.md (5.3)");
}

Cap* Core::find(const char* key) {
  if (!key) return nullptr;
  for (size_t i = 0; i < n_; i++)
    if (!strcmp(caps_[i].key_, key)) return &caps_[i];
  return nullptr;
}

// ---------------------------------------------------------------------------
// reporting
// ---------------------------------------------------------------------------

bool Core::setSwitch(const char* key, bool on) {
  Cap* c = find(key);
  if (!c || c->kind_ != SWITCH) return false;
  if (!c->hasValue_ || c->cur_.on != on) c->dirty_ = true;
  c->cur_.on = on; c->hasValue_ = true;
  return true;
}

bool Core::setNumber(const char* key, double v) {
  Cap* c = find(key);
  if (!c || (c->kind_ != NUMBER && c->kind_ != RANGE && c->kind_ != DURATION)) return false;
  if (!c->hasValue_ || c->cur_.n != v) c->dirty_ = true;
  c->cur_.n = v; c->hasValue_ = true;
  return true;
}

bool Core::setText(const char* key, const char* v) {
  Cap* c = find(key);
  if (!c || !v || (c->kind_ != TEXT && c->kind_ != ENUM && c->kind_ != COLOR && c->kind_ != TIME))
    return false;
  if (!c->hasValue_ || strncmp(c->cur_.s, v, MAYA_TEXT_BUF - 1) != 0) c->dirty_ = true;
  strncpy(c->cur_.s, v, MAYA_TEXT_BUF - 1);
  c->cur_.s[MAYA_TEXT_BUF - 1] = 0;
  c->hasValue_ = true;
  return true;
}

bool Core::setLocation(const char* key, double lat, double lng) {
  Cap* c = find(key);
  if (!c || c->kind_ != LOCATION) return false;
  if (lat < -90 || lat > 90 || lng < -180 || lng > 180) return false;
  if (!c->hasValue_ || c->cur_.lat != lat || c->cur_.lng != lng) c->dirty_ = true;
  c->cur_.lat = lat; c->cur_.lng = lng; c->hasValue_ = true;
  return true;
}

bool Core::hasPending() const {
  for (size_t i = 0; i < n_; i++) if (caps_[i].dirty_) return true;
  return false;
}

// ---------------------------------------------------------------------------
// values
// ---------------------------------------------------------------------------

// A whole number goes out as one. The server treats both as numbers, but "40"
// reads better in a log than "40.0".
static void putNumber(JsonObject obj, const char* key, double v) {
  if (v == floor(v) && fabs(v) < 2147483000.0) obj[key] = (long)v;
  else obj[key] = v;
}

void Core::writeValue(JsonObject obj, const Cap& c) const {
  switch (c.kind_) {
    case SWITCH:   obj[c.key_] = c.cur_.on ? "on" : "off"; break;
    case RANGE:
    case NUMBER:
    case DURATION: putNumber(obj, c.key_, c.cur_.n); break;
    case TEXT:
    case ENUM:
    case COLOR:
    case TIME:     obj[c.key_] = (const char*)c.cur_.s; break;
    case LOCATION: {
      JsonObject l = obj.createNestedObject(c.key_);
      l["lat"] = c.cur_.lat; l["lng"] = c.cur_.lng;
      break;
    }
    case BUTTON:   break;   // 6.2: a button has no state, and a device MUST NOT invent one
  }
}

static bool numberOf(JsonVariantConst raw, double& out) {
  if (raw.is<bool>() || !raw.is<double>()) return false;
  out = raw.as<double>();
  return !isnan(out) && !isinf(out);
}

// Mirrors coerce_value() in the server (software/server/descriptor.py). The
// server has already checked, so this is the second lock on the same door: a
// frame that arrives some other way (a peer, 7) is held to the same rules.
bool Core::parseValue(Cap& c, JsonVariantConst raw, Value& out) {
  switch (c.kind_) {
    case SWITCH: {
      if (raw.is<bool>()) { out.on = raw.as<bool>(); return true; }
      if (raw.is<const char*>()) {
        const char* s = raw.as<const char*>();
        if (ieq(s, "on") || ieq(s, "true") || !strcmp(s, "1"))  { out.on = true;  return true; }
        if (ieq(s, "off") || ieq(s, "false") || !strcmp(s, "0")) { out.on = false; return true; }
      }
      return false;
    }
    case RANGE:
    case NUMBER:
    case DURATION: {
      double v;
      if (!numberOf(raw, v)) return false;
      bool hasLo = c.hasMin_, hasHi = c.hasMax_;
      double lo = c.min_;
      if (c.kind_ == DURATION && !hasLo) { hasLo = true; lo = 0; }
      if (hasLo && v < lo) return false;
      if (hasHi && v > c.max_) return false;
      out.n = v;
      return true;
    }
    case TEXT: {
      if (!raw.is<const char*>()) return false;
      const char* s = raw.as<const char*>();
      size_t len = strlen(s);
      if (len >= MAYA_TEXT_BUF) return false;
      if (c.hasMax_ && len > (size_t)c.max_) return false;
      strcpy(out.s, s);
      return true;
    }
    case ENUM: {
      if (!raw.is<const char*>()) return false;
      const char* s = raw.as<const char*>();
      for (uint8_t i = 0; i < c.nOptions_; i++)
        if (!strcmp(c.options_[i], s)) { strcpy(out.s, s); return true; }
      return false;
    }
    case BUTTON:
      return true;   // 6.2: the press is null, and anything sent for it is discarded
    case COLOR: {
      if (!raw.is<const char*>()) return false;
      const char* s = raw.as<const char*>();
      if (strlen(s) != 7 || s[0] != '#') return false;
      for (int i = 1; i < 7; i++) {
        char ch = s[i];
        bool hex = (ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f') || (ch >= 'A' && ch <= 'F');
        if (!hex) return false;
        out.s[i] = (ch >= 'A' && ch <= 'F') ? ch + 32 : ch;   // the server lower-cases it too
      }
      out.s[0] = '#'; out.s[7] = 0;
      return true;
    }
    case TIME: {
      if (!raw.is<const char*>()) return false;
      const char* s = raw.as<const char*>();
      if (strlen(s) != 5 || s[2] != ':') return false;
      if (s[0] < '0' || s[0] > '2' || s[1] < '0' || s[1] > '9') return false;
      if (s[0] == '2' && s[1] > '3') return false;
      if (s[3] < '0' || s[3] > '5' || s[4] < '0' || s[4] > '9') return false;
      strcpy(out.s, s);
      return true;
    }
    case LOCATION: {
      JsonObjectConst o = raw.as<JsonObjectConst>();
      if (o.isNull()) return false;
      double lat, lng;
      if (!numberOf(o["lat"], lat) || !numberOf(o["lng"], lng)) return false;
      if (lat < -90 || lat > 90 || lng < -180 || lng > 180) return false;
      out.lat = lat; out.lng = lng;
      return true;
    }
  }
  return false;
}

void Core::commit(Cap& c, const Value& v) {
  c.cur_ = v;
  c.hasValue_ = true;
  c.dirty_ = false;   // the ack carries it
}

// ---------------------------------------------------------------------------
// sending
// ---------------------------------------------------------------------------

bool Core::sendDoc(DynamicJsonDocument& doc, Send send) const {
  if (doc.overflowed() || !send) return false;
  size_t len = measureJson(doc);
  char* buf = (char*)malloc(len + 1);
  if (!buf) return false;
  serializeJson(doc, buf, len + 1);
  send(buf, len);
  free(buf);
  return true;
}

bool Core::sendIdentify(const char* id, const char* pin, const char* ip, Send send) {
  if (problem_) return false;   // a refused declaration means the firmware is not what it meant to be
  DynamicJsonDocument doc(MAYA_TX_BYTES);
  doc["id"] = id;
  doc["proto"] = MAYA_PROTO;
  doc["status"] = "online";
  doc["pin"] = pin;
  if (ip && *ip) doc["ip"] = ip;
  if (model_) doc["model"] = model_;
  if (fw_) doc["fw"] = fw_;

  JsonArray caps = doc.createNestedArray("capabilities");
  for (size_t i = 0; i < n_; i++) {
    const Cap& c = caps_[i];
    JsonObject o = caps.createNestedObject();
    o["key"] = c.key_;
    o["kind"] = KIND_NAMES[c.kind_];
    if (c.label_) o["label"] = c.label_;
    if (c.access_ == R) o["access"] = "r";
    else if (c.access_ == W) o["access"] = "w";
    if (c.unit_) o["unit"] = c.unit_;
    if (c.group_) o["group"] = c.group_;
    if (c.kind_ == RANGE || c.kind_ == NUMBER || c.kind_ == DURATION) {
      if (c.hasMin_) putNumber(o, "min", c.min_);
      if (c.hasMax_) putNumber(o, "max", c.max_);
      if (c.hasStep_) putNumber(o, "step", c.step_);
    } else if (c.kind_ == TEXT && c.hasMax_) {
      putNumber(o, "max", c.max_);
    } else if (c.kind_ == ENUM) {
      JsonArray opts = o.createNestedArray("options");
      for (uint8_t k = 0; k < c.nOptions_; k++) opts.add(c.options_[k]);
    }
    if (c.history_) o["history"] = true;
    if (c.agentDeny_) o["agent"] = "deny";
    if (c.confirm_) o["confirm"] = true;
  }

  JsonObject state = doc.createNestedObject("state");
  for (size_t i = 0; i < n_; i++)
    if (caps_[i].hasValue_ && caps_[i].readable() && caps_[i].kind_ != BUTTON)
      writeValue(state, caps_[i]);

  if (doc.overflowed()) { problem_ = "descriptor does not fit MAYA_TX_BYTES"; return false; }
  if (measureJson(doc) > MAYA_MAX_DESCRIPTOR) { problem_ = "descriptor is larger than 4096 bytes (5.5)"; return false; }
  // Identify carries every value, so nothing is left to send.
  for (size_t i = 0; i < n_; i++) caps_[i].dirty_ = false;
  return sendDoc(doc, send);
}

bool Core::sendFullState(const char* myId, uint32_t uptimeMs, Send send) {
  DynamicJsonDocument doc(MAYA_TX_BYTES);
  doc["id"] = myId;
  doc["type"] = "state";
  doc["uptime_ms"] = uptimeMs;
  JsonObject state = doc.createNestedObject("state");
  for (size_t i = 0; i < n_; i++)
    if (caps_[i].hasValue_ && caps_[i].readable() && caps_[i].kind_ != BUTTON) {
      writeValue(state, caps_[i]);
      caps_[i].dirty_ = false;
    }
  return sendDoc(doc, send);
}

bool Core::flush(const char* myId, uint32_t uptimeMs, Send send) {
  if (!hasPending()) return false;
  DynamicJsonDocument doc(MAYA_TX_BYTES);
  doc["id"] = myId;
  doc["type"] = "state";
  doc["uptime_ms"] = uptimeMs;
  JsonObject state = doc.createNestedObject("state");
  for (size_t i = 0; i < n_; i++) {
    Cap& c = caps_[i];
    if (!c.dirty_) continue;
    if (c.hasValue_ && c.readable() && c.kind_ != BUTTON) writeValue(state, c);
    c.dirty_ = false;
  }
  return sendDoc(doc, send);
}

void Core::sendAck(const char* myId, const char* req, const char* status, const char* failed,
                   Cap** applied, size_t nApplied, Send send) {
  DynamicJsonDocument doc(MAYA_TX_BYTES);
  doc["id"] = myId;
  doc["type"] = "ack";
  if (req) doc["req"] = req;
  doc["status"] = status;
  if (failed) doc["failed"] = failed;
  JsonObject state = doc.createNestedObject("state");
  bool any = false;
  for (size_t i = 0; i < nApplied; i++) {
    Cap* c = applied[i];
    if (c->hasValue_ && c->readable() && c->kind_ != BUTTON) { writeValue(state, *c); any = true; }
  }
  if (!any) doc.remove("state");
  sendDoc(doc, send);
}

void Core::sendSimpleAck(const char* myId, const char* req, const char* status, Send send) {
  DynamicJsonDocument doc(256);
  doc["id"] = myId;
  doc["type"] = "ack";
  if (req) doc["req"] = req;
  doc["status"] = status;
  sendDoc(doc, send);
}

// The v1 ack: a bare status plus every channel, no `req` (Appendix A). Only sent
// in answer to a v1 `cmd` frame, i.e. by a server that has not been upgraded.
void Core::sendLegacyAck(const char* myId, const char* status, Send send) {
  DynamicJsonDocument doc(512);
  doc["id"] = myId;
  doc["status"] = status;
  for (size_t i = 0; i < n_; i++)
    if (caps_[i].kind_ == SWITCH && isChannelKey(caps_[i].key_))
      doc[caps_[i].key_] = caps_[i].cur_.on ? "on" : "off";
  sendDoc(doc, send);
}

// ---------------------------------------------------------------------------
// receiving
// ---------------------------------------------------------------------------

void Core::handleSet(JsonObjectConst root, const char* myId, Send send) {
  const char* req = root["req"] | (const char*)nullptr;
  JsonObjectConst values = root["values"].as<JsonObjectConst>();
  if (values.isNull()) { sendAck(myId, req, "bad_value", nullptr, nullptr, 0, send); return; }

  Cap* applied[MAYA_MAX_CAPS];
  size_t nApplied = 0;

  // 6.2: apply in order, stop at the first failure, and say exactly how far it
  // got. There is no rollback - a device cannot generally un-ring a bell.
  for (JsonPairConst kv : values) {
    const char* key = kv.key().c_str();
    Cap* c = find(key);
    if (!c) { sendAck(myId, req, "unknown_capability", key, applied, nApplied, send); return; }
    if (!c->writable()) { sendAck(myId, req, "not_permitted", key, applied, nApplied, send); return; }
    Value v;
    if (!parseValue(*c, kv.value(), v)) { sendAck(myId, req, "bad_value", key, applied, nApplied, send); return; }
    if (c->onWrite_ && !c->onWrite_(v)) { sendAck(myId, req, "bad_value", key, applied, nApplied, send); return; }
    if (c->kind_ != BUTTON) commit(*c, v);
    applied[nApplied++] = c;
  }
  sendAck(myId, req, "ok", nullptr, applied, nApplied, send);
}

// A v2 device MUST still answer the legacy command names (4), so that it works
// against a server that has not been upgraded yet.
Action Core::handleLegacy(JsonObjectConst root, const char* cmd, const char* myId,
                          uint32_t uptimeMs, Send send) {
  int channel = root["channel"] | 1;

  auto setChannel = [&](int ch, bool on) -> bool {
    char key[8];
    snprintf(key, sizeof key, "ch%d", ch);
    Cap* c = find(key);
    if (!c || c->kind_ != SWITCH || !c->writable()) return false;
    Value v; v.on = on;
    if (c->onWrite_ && !c->onWrite_(v)) return false;
    commit(*c, v);
    return true;
  };
  auto toggle = [&](int ch) -> bool {
    char key[8];
    snprintf(key, sizeof key, "ch%d", ch);
    Cap* c = find(key);
    return c && setChannel(ch, !c->cur_.on);
  };

  if (ieq(cmd, "output_on"))       sendLegacyAck(myId, setChannel(channel, true)  ? "ok" : "invalid_channel", send);
  else if (ieq(cmd, "output_off")) sendLegacyAck(myId, setChannel(channel, false) ? "ok" : "invalid_channel", send);
  else if (ieq(cmd, "output_toggle")) sendLegacyAck(myId, toggle(channel) ? "ok" : "invalid_channel", send);
  else if (ieq(cmd, "led_on"))     { setChannel(1, true);  sendLegacyAck(myId, "ok", send); }
  else if (ieq(cmd, "led_off"))    { setChannel(1, false); sendLegacyAck(myId, "ok", send); }
  else if (ieq(cmd, "toggle"))     { toggle(1);            sendLegacyAck(myId, "ok", send); }
  else if (ieq(cmd, "all_on") || ieq(cmd, "all_off")) {
    bool on = ieq(cmd, "all_on");
    for (size_t i = 0; i < n_; i++)
      if (caps_[i].kind_ == SWITCH && isChannelKey(caps_[i].key_) && caps_[i].writable())
        setChannel(atoi(caps_[i].key_ + 2), on);
    sendLegacyAck(myId, "ok", send);
  }
  else if (ieq(cmd, "get_status")) { sendLegacyAck(myId, "ok", send); sendFullState(myId, uptimeMs, send); }
  else if (ieq(cmd, "factory_reset")) {
    DynamicJsonDocument doc(128);
    doc["id"] = myId; doc["status"] = "factory_reset";
    sendDoc(doc, send);
    return FACTORY_RESET;
  }
  else if (ieq(cmd, "reboot")) {
    DynamicJsonDocument doc(128);
    doc["id"] = myId; doc["status"] = "rebooting";
    sendDoc(doc, send);
    return REBOOT;
  }
  return NONE;   // an unknown command is ignored, as the v1 firmware did
}

Action Core::onFrame(const char* data, size_t len, const char* myId, uint32_t uptimeMs, Send send) {
  DynamicJsonDocument doc(MAYA_RX_BYTES);
  if (deserializeJson(doc, data, len)) return NONE;
  JsonObjectConst root = doc.as<JsonObjectConst>();
  if (root.isNull()) return NONE;

  // 3: every frame carries the id, and a frame for another id is not ours.
  const char* target = root["id"] | (const char*)nullptr;
  if (target && strcmp(target, myId) != 0) return NONE;

  const char* type = root["type"] | (const char*)nullptr;
  const char* req = root["req"] | (const char*)nullptr;

  if (type) {
    if (!strcmp(type, "set")) { handleSet(root, myId, send); return NONE; }
    if (!strcmp(type, "get_status")) {
      sendFullState(myId, uptimeMs, send);
      if (req) sendSimpleAck(myId, req, "ok", send);
      return NONE;
    }
    if (!strcmp(type, "reboot"))        { sendSimpleAck(myId, req, "ok", send); return REBOOT; }
    if (!strcmp(type, "factory_reset")) { sendSimpleAck(myId, req, "ok", send); return FACTORY_RESET; }
    return NONE;   // welcome, error, and anything newer than this library: not ours to act on
  }

  const char* cmd = root["cmd"] | (const char*)nullptr;
  if (cmd) return handleLegacy(root, cmd, myId, uptimeMs, send);
  return NONE;
}

}  // namespace mayalib
