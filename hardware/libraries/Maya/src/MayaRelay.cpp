// The hub relay (PROTOCOL.md 5.9, 7.5): a hub carrying other devices' readings to the
// server, and a sensor handing them to a hub.
//
// Like MayaPeer.cpp this decides everything in RAM and flash and speaks through a
// transport the caller supplies, so it is built and tested on a laptop. The radio
// that carries a frame between a sensor and a hub lives in Maya.cpp.
//
// The one idea to keep in mind while reading: a hub is a COURIER. The grant key goes
// to the sensor and the server only (7.5), so nothing in the hub half below ever
// checks a MAC - it cannot - and nothing in it signs. It forwards bytes it did not
// write and cannot vouch for, and the server decides whether to believe them.
#include "MayaCore.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

namespace mayalib {

namespace {
void copyStr(char* dst, size_t cap, const char* src) {
  strncpy(dst, src ? src : "", cap - 1);
  dst[cap - 1] = 0;
}

// A relay message is JSON text on a WebSocket, and a text frame that is not valid UTF-8
// closes the connection - for every device the hub carries, not just the one that
// sent the bad frame. So a frame with a control character or a malformed sequence is
// dropped here rather than forwarded.
bool validText(const uint8_t* p, size_t n) {
  size_t i = 0;
  while (i < n) {
    uint8_t c = p[i];
    if (c < 0x20 || c == 0x7F) return false;
    if (c < 0x80) { i++; continue; }
    size_t extra;
    uint8_t lo = 0x80, hi = 0xBF;          // the range of the first continuation byte
    if (c >= 0xC2 && c <= 0xDF) extra = 1;
    else if (c >= 0xE0 && c <= 0xEF) { extra = 2; if (c == 0xE0) lo = 0xA0; if (c == 0xED) hi = 0x9F; }
    else if (c >= 0xF0 && c <= 0xF4) { extra = 3; if (c == 0xF0) lo = 0x90; if (c == 0xF4) hi = 0x8F; }
    else return false;
    if (i + extra >= n) return false;
    if (p[i + 1] < lo || p[i + 1] > hi) return false;
    for (size_t k = 2; k <= extra; k++)
      if (p[i + k] < 0x80 || p[i + k] > 0xBF) return false;
    i += extra + 1;
  }
  return true;
}

bool oneOf(const char* s, const char* const* list, size_t n) {
  for (size_t i = 0; i < n; i++) if (!strcmp(s, list[i])) return true;
  return false;
}
}  // namespace

// ---------------------------------------------------------------------------
// the hub
// ---------------------------------------------------------------------------

void Core::enableHub() {
  if (!relayQ_) relayQ_ = (RelaySlot*)calloc(MAYA_RELAY_QUEUE, sizeof(RelaySlot));
  hub_ = relayQ_ != nullptr;   // out of memory: not a hub, rather than a hub that drops everything
}

// A frame from a sensor this hub was paired with arrived on the radio. Everything
// checked here is something a hub CAN check without a key; none of it is
// authentication - a source address is spoofable - it only stops the hub spending the
// house's WiFi on noise. What gets past it is stopped by the server (7.5).
bool Core::hubAccept(PeerRec& g, const uint8_t* data, size_t len, JsonDocument& doc, const uint8_t src[6]) {
  if (!hub_ || !relayQ_) return false;
  if (memcmp(src, g.mac, 6) != 0) return false;                 // not from the sensor it was paired with
  if (doc["v"] != 2) return false;
  if (strcmp(doc["from"] | "", g.peer) != 0) return false;
  if (strcmp(doc["kind"] | "", "report") != 0) return false;    // a sensor sends reports and nothing else here
  if (!doc["values"].is<JsonObject>() || doc["values"].as<JsonObject>().size() == 0) return false;
  uint32_t ep = doc["ep"] | 0u, seq = doc["seq"] | 0u;
  if (!ep || !seq) return false;
  if (!validText(data, len)) return false;

  // At most MAYA_RELAY_RATE a minute from one sender. A burst after a buffer flush is
  // the legitimate case, and fits.
  uint32_t t = now();
  if (t - g.winStart >= 60000) { g.winStart = t; g.winCount = 0; }
  if (g.winCount >= MAYA_RELAY_RATE) return false;
  g.winCount++;

  // A full queue drops the NEWEST, never the oldest, so what is kept is contiguous: a
  // sensor's readings arrive with a gap at the end, not a hole in the middle that the
  // server's ordering would turn into lost frames.
  if (relayCount_ >= MAYA_RELAY_QUEUE) { relayDropped_++; return false; }
  RelaySlot& s = relayQ_[(relayHead_ + relayCount_) % MAYA_RELAY_QUEUE];
  copyStr(s.grant, sizeof s.grant, g.grant);
  s.ep = ep; s.seq = seq;
  memcpy(s.text, data, len);       // exactly as received: the MAC is over these bytes (7.2)
  s.text[len] = 0;
  relayCount_++;
  return true;
}

bool Core::flushRelay(const char* myId, Send send) {
  if (!hub_ || !relayQ_ || !send) return false;
  uint32_t t = now();
  if (relayInflight_) {
    if (t - relaySentAt_ < MAYA_RELAY_ACK_MS) return false;   // one message at a time
    relayInflight_ = 0;                                       // never answered: send them again
  }
  if (relayCount_ == 0 || t < relayRetryAt_) return false;

  size_t n = relayCount_ < MAYA_RELAY_BATCH ? relayCount_ : MAYA_RELAY_BATCH;
  DynamicJsonDocument doc(MAYA_TX_BYTES);
  doc["id"] = myId;
  doc["type"] = "relay";
  JsonArray frames = doc.createNestedArray("frames");
  for (size_t i = 0; i < n; i++)
    frames.add((const char*)relayQ_[(relayHead_ + i) % MAYA_RELAY_QUEUE].text);   // by reference, not copied
  if (!sendDoc(doc, send)) return false;
  relayInflight_ = n;
  relaySentAt_ = t;
  return true;
}

void Core::handleRelayAck(JsonObjectConst root) {
  if (!hub_ || !relayQ_) return;
  const char* status = root["status"] | (const char*)nullptr;
  if (status && !strcmp(status, "rate_limited")) {
    // Told to slow down: keep the queue, wait as long as the server said.
    uint32_t after = root["retry_after"] | 60u;
    relayRetryAt_ = now() + after * 1000u;
    relayInflight_ = 0;
    return;
  }
  JsonArrayConst results = root["results"].as<JsonArrayConst>();
  if (results.isNull()) return;

  // One result per frame, in the order sent. A frame the server refused is not
  // sent again: it was a sensor's problem (a rotated key, a spoofed address), not the
  // hub's, and trying again changes nothing.
  static const char* const NOT_LOGGED[] = {"bad_mac", "bad_frame", "unknown_grant"};   // 7.3: noise is not written down
  size_t taken = 0;
  for (JsonObjectConst r : results) {
    if (taken >= relayInflight_) break;
    RelaySlot& s = relayQ_[relayHead_];
    const char* st = r["status"] | "unknown";     // anything unrecognised is a failure, and logged as one
    if (!oneOf(st, NOT_LOGGED, 3)) {
      PeerRec* g = findPeer(s.grant);
      if (g) logPeer(*g, "in", s.ep, s.seq, "report", "", st);
    }
    relayHead_ = (relayHead_ + 1) % MAYA_RELAY_QUEUE;
    relayCount_--;
    taken++;
  }
  relayInflight_ = 0;   // whatever the answer did not cover is sent again
}

bool Core::sendHubStatus(const char* myId, uint8_t channel, Send send) {
  if (!hub_ || !send || channel < 1 || channel > 14) return false;
  if (hubStatusSent_ && hubStatusChannel_ == channel) return false;
  DynamicJsonDocument doc(128);
  doc["id"] = myId;
  doc["type"] = "hub_status";
  doc["channel"] = channel;
  if (!sendDoc(doc, send)) return false;
  hubStatusSent_ = true;
  hubStatusChannel_ = channel;
  return true;
}

// ---------------------------------------------------------------------------
// a sensor
// ---------------------------------------------------------------------------

uint32_t Core::secs() const { return secsFn_ ? secsFn_() : now() / 1000; }

PeerRec* Core::findRelaySendGrant() {
  for (auto& g : peers_)
    if (g.used && g.purpose == 1 && g.role == 1 && g.hasKey && !expired(g)) return &g;
  return nullptr;
}

const char* Core::hubId() const {
  const PeerRec* g = const_cast<Core*>(this)->findRelaySendGrant();
  return g ? g->peer : nullptr;
}

uint8_t Core::hubChannel() const {
  const PeerRec* g = const_cast<Core*>(this)->findRelaySendGrant();
  return g ? g->channel : 0;
}

// 5.9: the server told us where the hub is. Remembered across a reboot, because a
// sensor that wakes with its WiFi off has no other way to know.
void Core::handleHubChannel(JsonObjectConst root) {
  const char* hub = root["hub"] | (const char*)nullptr;
  int channel = root["channel"] | 0;
  if (!hub || channel < 1 || channel > 14) return;
  bool changed = false;
  for (auto& g : peers_)
    if (g.used && g.purpose == 1 && g.role == 1 && !strcmp(g.peer, hub) && g.channel != channel) {
      g.channel = (uint8_t)channel;
      changed = true;
    }
  if (changed) savePeers();
}

bool Core::hubUsable() const {
  if (!hubDown()) return true;
  return secs() - hubDownSince_ >= MAYA_HUB_RETRY_S;     // 5.9 rule 5: keep trying, slowly
}

void Core::noteHubFailure() {
  if (hubFails_ < 255) hubFails_++;
  if (hubFails_ < MAYA_HUB_FAIL_LIMIT) return;
  hubDownSince_ = secs();
  // 5.9 rule 3: say why, once. A hub that dies quietly looks like sensors going flat.
  const char* hub = hubId();
  if (hub && !hubAnnounced_) copyStr(hubFailedPending_, sizeof hubFailedPending_, hub);
}

void Core::hubState(uint8_t& fails, uint32_t& downSince, bool& announced) const {
  fails = hubFails_; downSince = hubDownSince_; announced = hubAnnounced_;
}

void Core::restoreHubState(uint8_t fails, uint32_t downSince, bool announced) {
  hubFails_ = fails; hubDownSince_ = downSince; hubAnnounced_ = announced;
  if (hubDown() && !announced) {
    const char* hub = hubId();
    if (hub) copyStr(hubFailedPending_, sizeof hubFailedPending_, hub);
  }
}

// What changed since the last report, kept with the moment it was taken. Only keys the
// hub grant covers: anything else stays dirty for the server.
void Core::bufferDirty(PeerRec& g) {
  if (!rep_) {
    rep_ = (Reading*)calloc(MAYA_REPORT_BUFFER, sizeof(Reading));
    if (!rep_) return;
  }
  uint32_t t = secs();
  for (size_t i = 0; i < n_; i++) {
    Cap& c = caps_[i];
    if (!c.dirty_ || !c.hasValue_ || !c.readable() || c.kind_ == BUTTON || !inScope(g, c.key_)) continue;
    if (repCount_ == MAYA_REPORT_BUFFER) {          // full: drop the oldest, and count it (5.9 rule 4)
      repHead_ = (repHead_ + 1) % MAYA_REPORT_BUFFER;
      repCount_--;
      repLost_++;
    }
    Reading& r = rep_[(repHead_ + repCount_) % MAYA_REPORT_BUFFER];
    r.cap = &c; r.v = c.cur_; r.takenAt = t;
    repCount_++;
    c.dirty_ = false;
  }
}

// Carries the buffer to the hub, oldest first. A frame must fit one ESP-NOW payload
// (7.2), so readings taken at the same moment are packed together while they fit, and
// the rest follow in their own frames.
bool Core::sendReadings(PeerRec& g) {
  while (repCount_ > 0) {
    uint32_t t0 = rep_[repHead_].takenAt;
    size_t group = 1;
    while (group < repCount_ && group < 8 && rep_[(repHead_ + group) % MAYA_REPORT_BUFFER].takenAt == t0) group++;
    uint32_t now_s = secs();
    uint32_t age = now_s > t0 ? now_s - t0 : 0;
    if (age > 604800) age = 604800;                // 7.5: a reading may claim to be at most 7 days old

    DynamicJsonDocument doc(768);
    size_t n = group;
    for (; n >= 1; n--) {
      doc.clear();
      doc["v"] = 2;
      doc["from"] = myId_;
      doc["grant"] = g.grant;
      doc["ep"] = ep_;
      doc["seq"] = g.outSeq + 1;
      doc["kind"] = "report";
      JsonObject values = doc.createNestedObject("values");
      for (size_t i = 0; i < n; i++) {
        Reading& r = rep_[(repHead_ + i) % MAYA_REPORT_BUFFER];
        Value keep = r.cap->cur_;                  // writeValue reads the cap's current value
        r.cap->cur_ = r.v;
        writeValue(values, *r.cap);
        r.cap->cur_ = keep;
      }
      if (age) doc["age"] = age;
      if (!doc.overflowed() && measureJson(doc) + 1 + 22 <= MAYA_LOCAL_FRAME_MAX) break;
    }
    if (n == 0) {
      // Not even one reading fits a radio frame (a long text value). Holding it would
      // block every reading behind it, and it cannot be fragmented (7.2).
      repHead_ = (repHead_ + 1) % MAYA_REPORT_BUFFER;
      repCount_--;
      repLost_++;
      continue;
    }

    if (!peerSendRaw(g, doc)) { noteHubFailure(); return false; }
    g.outSeq++;
    char sum[40];
    serializeJson(doc["values"], sum, sizeof sum);
    logPeer(g, "out", ep_, g.outSeq, "report", sum, "ok");
    repHead_ = (repHead_ + n) % MAYA_REPORT_BUFFER;
    repCount_ -= n;
    // The hub answered (the MAC layer says so, 5.9 rule 1): it is alive, and there is
    // nothing left to announce.
    hubFails_ = 0; hubDownSince_ = 0; hubAnnounced_ = false; hubFailedPending_[0] = 0;
  }
  return true;
}

bool Core::report() {
  if (!peeringStarted_ || !peerTx_) return false;
  PeerRec* g = findRelaySendGrant();
  if (!g) return false;               // no hub: the caller reports through the server
  bufferDirty(*g);
  if (!hubUsable()) return false;
  return sendReadings(*g);
}

size_t Core::fallBackToServer() {
  size_t n = 0;
  while (repCount_ > 0) {
    rep_[repHead_].cap->dirty_ = true;     // the cap holds the latest value; the next flush() sends it
    repHead_ = (repHead_ + 1) % MAYA_REPORT_BUFFER;
    repCount_--;
    n++;
  }
  // The announcement (5.9 rule 3) was queued when the hub was given up on, or restored
  // with the sleeping sensor's state; the next flush() carries it.
  return n;
}

}  // namespace mayalib
