// The device's half of PROTOCOL.md section 7: holding grants, believing (or
// refusing) a local frame, sending one, and reporting what happened.
//
// Everything here is decided in RAM and flash and answered over a transport the
// caller supplies, so it is tested on a laptop. The radio that carries the frames
// (ESP-NOW) lives in Maya.cpp and is the part this file cannot vouch for.
#include "MayaCore.h"
#include "MayaCrypto.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

namespace mayalib {

namespace {
const uint32_t MAGIC = 0x3150594d;   // "MYP1"
const uint32_t LOG_INTERVAL_MS = 10000;   // 7.3: flush at most every 10 s ...
const size_t LOG_PER_FRAME = 20;          // ... and what fits one frame, well under the server's 64
const uint32_t AGGREGATE_MS = 1000;       // 7.3: faster than ~1 Hz is summarised, not listed

bool parseMac(const char* s, uint8_t out[6]) {
  if (!s || strlen(s) != 17) return false;
  for (int i = 0; i < 6; i++) {
    char a = s[i * 3], b = s[i * 3 + 1];
    if (i < 5 && s[i * 3 + 2] != ':') return false;
    auto hex = [](char c) -> int {
      if (c >= '0' && c <= '9') return c - '0';
      if (c >= 'a' && c <= 'f') return c - 'a' + 10;
      if (c >= 'A' && c <= 'F') return c - 'A' + 10;
      return -1;
    };
    int h = hex(a), l = hex(b);
    if (h < 0 || l < 0) return false;
    out[i] = (uint8_t)(h * 16 + l);
  }
  return true;
}

void copyStr(char* dst, size_t cap, const char* src) {
  strncpy(dst, src ? src : "", cap - 1);
  dst[cap - 1] = 0;
}

bool validGrantRef(const char* s) {
  if (!s || s[0] != 'g' || s[1] != '-' || !s[2] || strlen(s) > 15) return false;
  for (const char* p = s + 2; *p; p++) if (*p < '0' || *p > '9') return false;
  return true;
}
}  // namespace

// ---------------------------------------------------------------------------
// persistence
// ---------------------------------------------------------------------------

void Core::beginPeering(Storage* storage, const char* myId) {
  storage_ = storage;
  copyStr(myId_, sizeof myId_, myId);
  memset(peers_, 0, sizeof peers_);
  loadPeers();

  // 7.2: a new epoch every boot, persisted, so a restarted sender is newer rather
  // than indistinguishable from a replay.
  uint32_t stored = 0;
  size_t len = 0;
  if (storage_ && storage_->read("ep", (uint8_t*)&stored, sizeof stored, len) && len == sizeof stored)
    ep_ = stored + 1;
  else
    ep_ = 1;
  if (storage_) storage_->write("ep", (const uint8_t*)&ep_, sizeof ep_);
  peeringStarted_ = true;
}

void Core::loadPeers() {
  if (!storage_) return;
  static uint8_t buf[8 + sizeof(PeerRec) * MAYA_MAX_PEERS];
  size_t len = 0;
  if (!storage_->read("peers", buf, sizeof buf, len) || len != sizeof buf) return;
  uint32_t magic, recSize;
  memcpy(&magic, buf, 4);
  memcpy(&recSize, buf + 4, 4);
  // A build with a different grant layout must not misread this one's bytes as
  // keys: start empty instead, and let the server's peer_grant refill it.
  if (magic != MAGIC || recSize != sizeof(PeerRec)) return;
  memcpy(peers_, buf + 8, sizeof peers_);
  for (auto& g : peers_) {
    // Counters that live in RAM only. `inFresh` is the 7.2 residual window: after
    // a reboot the next frame of the stored epoch is accepted whatever its seq.
    g.inSeq = 0; g.inFresh = true; g.outSeq = 0; g.winStart = 0; g.winCount = 0;
    if (g.nScope > MAYA_PEER_SCOPE) g.used = false;
  }
}

void Core::savePeers() {
  if (!storage_) return;
  static uint8_t buf[8 + sizeof(PeerRec) * MAYA_MAX_PEERS];
  uint32_t magic = MAGIC, recSize = sizeof(PeerRec);
  memcpy(buf, &magic, 4);
  memcpy(buf + 4, &recSize, 4);
  memcpy(buf + 8, peers_, sizeof peers_);
  storage_->write("peers", buf, sizeof buf);
}

// ---------------------------------------------------------------------------
// lookups
// ---------------------------------------------------------------------------

PeerRec* Core::findPeer(const char* grant) {
  if (!grant) return nullptr;
  for (auto& g : peers_) if (g.used && !strcmp(g.grant, grant)) return &g;
  return nullptr;
}

const PeerRec* Core::peerByGrant(const char* grant) const {
  return const_cast<Core*>(this)->findPeer(grant);
}

PeerRec* Core::findSendGrant(const char* peer) {
  if (!peer) return nullptr;
  for (auto& g : peers_)
    if (g.used && g.role == 1 && g.purpose == 0 && !strcmp(g.peer, peer) && !expired(g)) return &g;
  return nullptr;
}

bool Core::expired(const PeerRec& g) const {
  if (!g.expires || !epochNow_) return false;   // no time known: not evaluable, so not expired (7.1)
  uint32_t t = epochNow_();
  return t != 0 && t > g.expires;
}

bool Core::inScope(const PeerRec& g, const char* key) const {
  for (uint8_t i = 0; i < g.nScope; i++) if (!strcmp(g.scope[i], key)) return true;
  return false;
}

size_t Core::peerCount() const {
  size_t n = 0;
  for (auto& g : peers_) if (g.used) n++;
  return n;
}

bool Core::peerMacAt(size_t i, uint8_t mac[6]) const {
  for (auto& g : peers_) {
    if (!g.used) continue;
    if (i-- == 0) { memcpy(mac, g.mac, 6); return true; }
  }
  return false;
}

// ---------------------------------------------------------------------------
// control plane: peer_grant / peer_revoke / peer_sync (7.1, 7.4)
// ---------------------------------------------------------------------------

void Core::handlePeerControl(JsonObjectConst root, const char* type) {
  if (!strcmp(type, "peer_grant")) {
    const char* ref = root["grant_id"] | (const char*)nullptr;
    const char* role = root["role"] | (const char*)nullptr;
    const char* peerId = root["peer"]["id"] | (const char*)nullptr;
    const char* peerMac = root["peer"]["mac"] | (const char*)nullptr;
    const char* key = root["key"] | (const char*)nullptr;
    const char* purpose = root["purpose"] | (const char*)nullptr;
    JsonArrayConst scope = root["scope"].as<JsonArrayConst>();
    uint8_t mac[6], keyBytes[40];
    // A malformed grant is dropped whole. Half a grant - a key without a scope, a
    // scope without a peer - is worse than none.
    if (!validGrantRef(ref) || !role || (strcmp(role, "send") && strcmp(role, "recv"))) return;
    if (!peerId || !*peerId || strlen(peerId) >= sizeof(PeerRec::peer) || !parseMac(peerMac, mac)) return;
    if (scope.isNull()) return;
    // 7.1: a purpose this library does not know is ignored, never read as control -
    // the two differ in whose keys `scope` names.
    if (purpose && strcmp(purpose, "relay") && strcmp(purpose, "control")) return;
    bool relay = purpose && !strcmp(purpose, "relay");
    bool isSend = !strcmp(role, "send");
    // 7.5: the hub end of a relay grant has no key, and must not keep one it is
    // sent by mistake - a hub that held it could sign for the sensor. Every other
    // grant needs its key.
    bool wantKey = !(relay && !isSend);
    if (wantKey && (!key || base64Decode(key, strlen(key), keyBytes, sizeof keyBytes) != 32)) return;

    PeerRec* slot = findPeer(ref);
    bool known = slot != nullptr;
    if (!slot)
      for (auto& g : peers_) if (!g.used) { slot = &g; break; }
    if (!slot) return;   // table full; the server will say so at the next sync, and the app can revoke

    PeerRec fresh;
    memset(&fresh, 0, sizeof fresh);
    fresh.used = true;
    fresh.role = isSend ? 1 : 2;
    fresh.purpose = relay ? 1 : 0;
    fresh.hasKey = wantKey;
    int channel = root["peer"]["channel"] | 0;
    fresh.channel = (channel >= 1 && channel <= 14) ? (uint8_t)channel : 0;
    copyStr(fresh.grant, sizeof fresh.grant, ref);
    copyStr(fresh.peer, sizeof fresh.peer, peerId);
    memcpy(fresh.mac, mac, 6);
    if (wantKey) memcpy(fresh.key, keyBytes, 32);
    for (JsonVariantConst k : scope) {
      const char* name = k.as<const char*>();
      if (name && strlen(name) < sizeof fresh.scope[0] && fresh.nScope < MAYA_PEER_SCOPE)
        copyStr(fresh.scope[fresh.nScope++], sizeof fresh.scope[0], name);
    }
    fresh.expires = parseIsoUtc(root["expires"] | "");
    if (known) {
      // The server re-sends every active grant at each identify. That must not
      // reopen the replay window, so the counters carry over - unless the key
      // changed, which is a different grant in all but its id.
      bool sameKey = slot->hasKey == fresh.hasKey && slot->purpose == fresh.purpose
                     && memcmp(slot->key, fresh.key, 32) == 0;
      if (sameKey) { fresh.inEp = slot->inEp; fresh.inSeq = slot->inSeq; fresh.inFresh = slot->inFresh; fresh.outSeq = slot->outSeq; }
      else fresh.inFresh = true;
    } else {
      fresh.inFresh = true;
    }
    *slot = fresh;
    peersVersion_++;
    savePeers();
    return;
  }

  if (!strcmp(type, "peer_revoke")) {
    PeerRec* g = findPeer(root["grant_id"] | (const char*)nullptr);
    if (g) { memset(g, 0, sizeof *g); peersVersion_++; savePeers(); }
    return;
  }

  if (!strcmp(type, "peer_sync")) {
    // The complete list of active grants. Anything held that is not on it was
    // revoked while this device was away, and is dropped now (7.1).
    JsonArrayConst list = root["grants"].as<JsonArrayConst>();
    if (list.isNull()) return;
    bool changed = false;
    for (auto& g : peers_) {
      if (!g.used) continue;
      bool listed = false;
      for (JsonVariantConst v : list) {
        const char* ref = v.as<const char*>();
        if (ref && !strcmp(ref, g.grant)) { listed = true; break; }
      }
      if (!listed) { memset(&g, 0, sizeof g); changed = true; }
    }
    if (changed) { peersVersion_++; savePeers(); }
  }
}

// ---------------------------------------------------------------------------
// audit ring buffer (7.3)
// ---------------------------------------------------------------------------

void Core::logPeer(const PeerRec& g, const char* dir, uint32_t ep, uint32_t seq, const char* kind,
                   const char* summary, const char* result) {
  bool ok = !strcmp(result, "ok");
  if (!ok) logUrgent_ = true;

  // Faster than about 1 Hz is summarised: one entry standing for many frames.
  if (logCount_ > 0 && ok) {
    LogEntry& last = log_[(logHead_ + MAYA_PEER_LOG_CAP - 1) % MAYA_PEER_LOG_CAP];
    if (!strcmp(last.grant, g.grant) && !strcmp(last.dir, dir) && last.ep == ep
        && !strcmp(last.kind, kind) && !strcmp(last.result, "ok")
        && now() - last.at < AGGREGATE_MS && seq >= last.seq) {
      last.count += 1;
      last.seq = seq;
      copyStr(last.summary, sizeof last.summary, summary);
      last.at = now();
      return;
    }
  }

  if (logCount_ == MAYA_PEER_LOG_CAP) { logCount_--; logDropped_++; }   // drop oldest, say so (7.3)
  LogEntry& e = log_[logHead_];
  memset(&e, 0, sizeof e);
  copyStr(e.grant, sizeof e.grant, g.grant);
  copyStr(e.dir, sizeof e.dir, dir);
  e.ep = ep; e.seq = seq; e.count = 1;
  copyStr(e.kind, sizeof e.kind, kind);
  copyStr(e.peer, sizeof e.peer, g.peer);
  copyStr(e.summary, sizeof e.summary, summary);
  copyStr(e.result, sizeof e.result, result);
  e.at = now();
  logHead_ = (logHead_ + 1) % MAYA_PEER_LOG_CAP;
  logCount_++;
}

bool Core::flushPeerLog(const char* myId, Send send) {
  if (logCount_ == 0 && logDropped_ == 0) return false;
  uint32_t t = now();
  bool due = logUrgent_ || (t - lastLogFlush_) >= LOG_INTERVAL_MS;
  if (!due || !send) return false;

  DynamicJsonDocument doc(MAYA_TX_BYTES);
  doc["id"] = myId;
  doc["type"] = "peer_log";
  char boot[16];
  snprintf(boot, sizeof boot, "b-%lu", (unsigned long)ep_);
  doc["boot_id"] = boot;
  if (logDropped_) doc["dropped"] = logDropped_;
  JsonArray batch = doc.createNestedArray("batch");

  size_t n = logCount_ < LOG_PER_FRAME ? logCount_ : LOG_PER_FRAME;
  size_t oldest = (logHead_ + MAYA_PEER_LOG_CAP - logCount_) % MAYA_PEER_LOG_CAP;
  for (size_t i = 0; i < n; i++) {
    const LogEntry& e = log_[(oldest + i) % MAYA_PEER_LOG_CAP];
    JsonObject o = batch.createNestedObject();
    o["grant"] = e.grant; o["dir"] = e.dir; o["ep"] = e.ep; o["seq"] = e.seq;
    if (e.count > 1) o["count"] = e.count;
    o["kind"] = e.kind; o["peer"] = e.peer;
    if (e.summary[0]) o["summary"] = e.summary;
    o["result"] = e.result;
  }
  if (!sendDoc(doc, send)) return false;

  logCount_ -= n;
  logDropped_ = 0;
  lastLogFlush_ = t;
  // Still urgent only if something unwelcome is still waiting.
  logUrgent_ = false;
  size_t rest = (logHead_ + MAYA_PEER_LOG_CAP - logCount_) % MAYA_PEER_LOG_CAP;
  for (size_t i = 0; i < logCount_; i++)
    if (strcmp(log_[(rest + i) % MAYA_PEER_LOG_CAP].result, "ok") != 0) { logUrgent_ = true; break; }
  return true;
}

// ---------------------------------------------------------------------------
// sending (data plane)
// ---------------------------------------------------------------------------

// Builds `<json>.<mac>` and puts it on the air. The MAC covers the exact bytes
// of the JSON as written (7.2), so nothing is re-serialised between signing and
// sending.
bool Core::peerSendRaw(PeerRec& g, DynamicJsonDocument& doc) {
  if (!peerTx_ || doc.overflowed()) return false;
  uint8_t frame[MAYA_LOCAL_FRAME_MAX + 8];
  size_t jsonLen = measureJson(doc);
  if (jsonLen + 1 + 22 > MAYA_LOCAL_FRAME_MAX) return false;   // does not fit one ESP-NOW payload; never fragmented
  serializeJson(doc, (char*)frame, sizeof frame);
  uint8_t mac[32];
  hmacSha256(g.key, 32, frame, jsonLen, mac);
  frame[jsonLen] = '.';
  char b64[24];
  base64UrlEncode(mac, 16, b64, sizeof b64);
  memcpy(frame + jsonLen + 1, b64, 22);
  return peerTx_(g.mac, frame, jsonLen + 1 + 22);
}

bool Core::peerSend(PeerRec& g, const char* kind, std::function<void(JsonObject)> fill) {
  if (!peeringStarted_) return false;
  DynamicJsonDocument doc(512);
  doc["v"] = 2;
  doc["from"] = myId_;
  doc["grant"] = g.grant;
  doc["ep"] = ep_;
  doc["seq"] = g.outSeq + 1;
  doc["kind"] = kind;
  fill(doc.as<JsonObject>());
  if (!peerSendRaw(g, doc)) return false;
  g.outSeq++;   // consumed only once the frame has actually gone, so a refusal leaves no hole
  return true;
}

bool Core::peerMessage(const char* peer, const char* kind, std::function<void(JsonObject)> fill) {
  PeerRec* g = findSendGrant(peer);
  if (!g || !kind || (strcmp(kind, "event") && strcmp(kind, "msg"))) return false;
  bool ok = peerSend(*g, kind, [&](JsonObject o) { fill(o.createNestedObject("data")); });
  if (ok) logPeer(*g, "out", ep_, g->outSeq, kind, "", "ok");
  return ok;
}

static void summaryOf(JsonObjectConst values, char* out, size_t cap) {
  serializeJson(values, out, cap);   // truncates, which is what a one-line summary wants
}

// One `set` frame with a single key, whatever its value.
bool Core::peerSetKey(const char* peer, const char* key, std::function<void(JsonObject, const char*)> assign) {
  PeerRec* g = findSendGrant(peer);
  if (!g || !key || !inScope(*g, key)) return false;   // the receiver would refuse it; do not spend the air on it
  bool ok = peerSend(*g, "set", [&](JsonObject o) { assign(o.createNestedObject("values"), key); });
  if (ok) {
    char sum[40];
    DynamicJsonDocument d(128);
    JsonObject v = d.to<JsonObject>();
    assign(v, key);
    serializeJson(v, sum, sizeof sum);   // truncates, which is what a one-line summary wants
    logPeer(*g, "out", ep_, g->outSeq, "set", sum, "ok");
  }
  return ok;
}

bool Core::peerSetSwitch(const char* peer, const char* key, bool on) {
  return peerSetKey(peer, key, [on](JsonObject v, const char* k) { v[k] = on ? "on" : "off"; });
}
bool Core::peerSetNumber(const char* peer, const char* key, double n) {
  return peerSetKey(peer, key, [n](JsonObject v, const char* k) { v[k] = n; });
}
bool Core::peerSetText(const char* peer, const char* key, const char* t) {
  return peerSetKey(peer, key, [t](JsonObject v, const char* k) { v[k] = t; });
}
bool Core::peerPress(const char* peer, const char* key) {
  // 6.2: a press is null.
  return peerSetKey(peer, key, [](JsonObject v, const char* k) { v[k] = (const char*)nullptr; });
}

// ---------------------------------------------------------------------------
// receiving (data plane)
// ---------------------------------------------------------------------------

void Core::onLocalFrame(const uint8_t* data, size_t len, const uint8_t srcMac[6]) {
  if (!peeringStarted_ || !data || len < 30 || len > MAYA_LOCAL_FRAME_MAX) return;

  // <json>.<22 chars>. The last dot, because a number may contain one.
  size_t dot = len;
  while (dot > 0 && data[dot - 1] != '.') dot--;
  if (dot == 0) return;
  dot--;
  if (len - dot - 1 != 22) return;

  // Nothing in the JSON is trusted yet. It is parsed only to learn which key to
  // try; a frame that fails the MAC is dropped without a word, not answered and
  // not logged, so noise from outside cannot fill the audit buffer (7.3).
  DynamicJsonDocument doc(MAYA_RX_BYTES);
  if (deserializeJson(doc, (const char*)data, dot)) return;
  PeerRec* g = findPeer(doc["grant"] | (const char*)nullptr);
  if (!g || expired(*g)) return;

  // A relay grant (7.5). The sender holds the key and the server checks it; the hub
  // end has none, so it cannot check the MAC and takes the other path. A sensor is
  // never sent anything over a relay grant.
  if (g->purpose == 1) {
    if (g->role == 2) hubAccept(*g, data, len, doc, srcMac);
    return;
  }

  uint8_t want[32];
  hmacSha256(g->key, 32, data, dot, want);
  char b64[24];
  base64UrlEncode(want, 16, b64, sizeof b64);
  if (!constantTimeEqual((const uint8_t*)b64, data + dot + 1, 22)) return;

  // From here the frame is genuine: someone holding this grant's key wrote it.
  uint32_t ep = doc["ep"] | 0u, seq = doc["seq"] | 0u;
  const char* kind = doc["kind"] | "";
  const char* from = doc["from"] | "";
  if (doc["v"] != 2 || strcmp(from, g->peer) != 0) return;

  // The radio-level source is a tripwire, not the defence (7.2). A mismatch with a
  // valid MAC is worth reporting: a key in the wrong place.
  if (memcmp(srcMac, g->mac, 6) != 0) { logPeer(*g, "in", ep, seq, "frame", "", "bad_source"); return; }

  // Replay: only (ep, seq) strictly newer than the last accepted is believed. After
  // a reboot the next frame of the stored epoch is taken whatever its seq - the
  // one-frame residual window the spec states.
  if (ep < g->inEp || (ep == g->inEp && !g->inFresh && seq <= g->inSeq) || seq == 0 || ep == 0) {
    logPeer(*g, "in", ep, seq, kind, "", "replay");
    return;
  }
  bool newEpoch = ep != g->inEp;
  g->inEp = ep; g->inSeq = seq; g->inFresh = false;
  if (newEpoch) savePeers();

  if (g->role == 2) {   // we receive: set, event, msg
    if (!strcmp(kind, "set")) {
      JsonObjectConst values = doc["values"].as<JsonObjectConst>();
      char sum[40]; sum[0] = 0;
      Cap* applied[MAYA_MAX_CAPS];
      size_t n = 0;
      const char* failed = nullptr;
      const char* status = values.isNull() ? "bad_value" : applyValues(values, g, &failed, applied, n);
      if (!values.isNull()) summaryOf(values, sum, sizeof sum);
      logPeer(*g, "in", ep, seq, "set", sum, status);

      DynamicJsonDocument ack(512);
      ack["v"] = 2; ack["from"] = myId_; ack["grant"] = g->grant; ack["ep"] = ep_;
      ack["seq"] = g->outSeq + 1; ack["kind"] = "ack"; ack["re"] = seq; ack["status"] = status;
      if (failed && strcmp(status, "ok") != 0) ack["failed"] = failed;
      JsonObject state = ack.createNestedObject("state");
      bool any = false;
      for (size_t i = 0; i < n; i++)
        if (applied[i]->hasValue_ && applied[i]->readable() && applied[i]->kind_ != BUTTON) {
          writeValue(state, *applied[i]); any = true;
        }
      if (!any) ack.remove("state");
      if (peerSendRaw(*g, ack)) g->outSeq++;
    } else if (!strcmp(kind, "event") || !strcmp(kind, "msg")) {
      logPeer(*g, "in", ep, seq, kind, "", "ok");
      if (peerMsg_) peerMsg_(g->peer, kind, doc["data"].as<JsonObjectConst>());
    } else {
      logPeer(*g, "in", ep, seq, kind, "", "unsupported");
    }
  } else if (g->role == 1) {   // we sent: the only thing that comes back is an ack
    if (!strcmp(kind, "ack")) {
      // Not logged a second time (7.3): the receiver's entry carries the result.
      if (peerAck_) peerAck_(g->peer, doc["status"] | "unknown", doc["failed"] | (const char*)nullptr);
    }
  }
}

}  // namespace mayalib
