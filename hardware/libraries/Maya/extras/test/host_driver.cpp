// Drives MayaCore on a laptop so the real server can judge what it says.
//
//   host_driver <profile> [state-dir]   reads commands on stdin, writes frames on stdout
//
//   With a state-dir the device keeps its grants and epoch there, so a second
//   run against the same directory is a reboot.
//
// stdin commands (one per line)
//   identify                   send the identify frame
//   frame <json>               hand the core a frame from the server
//   setsw <key> <0|1>          the sketch reports a switch
//   setnum <key> <number>      ... a number
//   settext <key> <text>       ... a string
//   flush                      send a partial state report
//   full                       send a full state report
//   problem                    print the declaration problem, if any
//   local <srcmac> <text>      a radio frame arrives from that MAC (12 hex digits)
//   localhex <srcmac> <hex>    the same, for bytes that are not text
//   psw|pnum|ptxt <peer> <key> <v>   send a `set` to a peer; ppress <peer> <key>
//   pmsg <peer> <kind>         send an event/msg with a small payload
//   plog                       flush the audit buffer if it is due
//   ms <n> / clock <n>         set the device's millis() / wall clock (0 = unknown)
//   peers                      list held grants
//   ask <text>                 ask Maya for help; tick = let a waiting request time out
//   report                     a sensor carries what changed to its hub (REPORT ok buffered lost fails)
//   relay                      a hub sends the frames it holds to the server (RELAYED 0|1)
//   hubstatus <channel>        a hub tells the server its WiFi channel (HUBSTATUS 0|1)
//   queued                     a hub's queue (QUEUED n dropped=n)
//   fallback                   give the buffered readings back to the state report (FALLBACK n)
//   hub                        what a sensor knows of its hub (HUB id usable down channel fails announced)
//   restore <fails> <since> <announced>   a deep-sleeping sensor's saved hub state
//   secs <n>                   the seconds clock (which keeps counting across sleep on a board)
//   txok <0|1>                 whether the radio reports a frame as acknowledged (0 = dead hub)
//   sync                       print SYNC, so the caller knows the lines above are complete
//
// stdout
//   TX <json>                  a frame the device would send
//   ACTION <name>              what the transport would do next
//   HW <what>                  the hardware callback that ran
//   PROBLEM <text>             the declaration problem ("none" if clean)
//
// Profiles are declarations, the same calls a sketch makes in setup().
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <string>
#include <iostream>
#include <fstream>
#include <map>
#include "MayaCore.h"

using namespace mayalib;

static uint32_t g_ms = 0, g_clock = 0, g_secs = 0;
static bool g_txok = true;

// A directory standing in for NVS: one file per key.
class FileStorage : public Storage {
 public:
  explicit FileStorage(std::string dir) : dir_(dir) {}
  bool read(const char* name, uint8_t* buf, size_t cap, size_t& len) override {
    std::ifstream f(dir_ + "/" + name, std::ios::binary);
    if (!f) return false;
    f.read((char*)buf, cap);
    len = (size_t)f.gcount();
    return true;
  }
  bool write(const char* name, const uint8_t* buf, size_t len) override {
    std::ofstream f(dir_ + "/" + name, std::ios::binary | std::ios::trunc);
    if (!f) return false;
    f.write((const char*)buf, len);
    return true;
  }
 private:
  std::string dir_;
};

// Memory-only, for runs that do not care about a reboot.
class MemStorage : public Storage {
 public:
  bool read(const char* name, uint8_t* buf, size_t cap, size_t& len) override {
    auto it = m_.find(name);
    if (it == m_.end()) return false;
    len = it->second.size() < cap ? it->second.size() : cap;
    memcpy(buf, it->second.data(), len);
    return true;
  }
  bool write(const char* name, const uint8_t* buf, size_t len) override {
    m_[name] = std::string((const char*)buf, len);
    return true;
  }
 private:
  std::map<std::string, std::string> m_;
};

static bool macFromHex(const char* hex, uint8_t out[6]) {
  if (strlen(hex) != 12) return false;
  for (int i = 0; i < 6; i++) { unsigned v; if (sscanf(hex + i * 2, "%2x", &v) != 1) return false; out[i] = (uint8_t)v; }
  return true;
}

static void tx(const char* json, size_t len) { printf("TX %.*s\n", (int)len, json); }

static const char* const MODES[] = {"eco", "normal", "boost"};

static void profileLampFan(Core& m) {
  m.addSwitch("lamp", "Lamp", [](bool on) { printf("HW lamp=%d\n", on); return true; });
  m.addRange("fan", "Fan speed", 0, 100, 5, [](double v) { printf("HW fan=%g\n", v); return true; }).unit("%");
  m.addNumber("temp", "Temperature").unit("C").history();
  m.addEnum("mode", "Mode", MODES, 3, [](const char* s) { printf("HW mode=%s\n", s); return true; });
  m.addText("msg", "Display", 8, [](const char* s) { printf("HW msg=%s\n", s); return true; });
  m.addColor("strip", "Strip", [](const char* s) { printf("HW strip=%s\n", s); return true; });
  m.addTime("wake", "Wake at", [](const char* s) { printf("HW wake=%s\n", s); return true; });
  m.addDuration("runfor", "Run for", 7200, [](double v) { printf("HW runfor=%g\n", v); return true; });
  m.addButton("horn", "Horn", []() { printf("HW horn\n"); }).confirm();
  m.addButton("reset", "Reset", []() { printf("HW reset\n"); }).agentDeny();
  m.addLocation("pos", "Position");
  m.addSwitch("motion", "Motion").readOnly();
  m.addSwitch("picky", "Picky", [](bool) { return false; });   // the hardware refuses everything
  m.addReserved("_batt");
  m.addReserved("_rssi");
  m.addReserved("_fw");
}

// A mains-powered extension that also carries other devices' readings (7.5).
static void profileHub(Core& m) {
  m.addSwitch("out1", "Output 1", [](bool on) { printf("HW out1=%d\n", on); return true; });
  m.setSwitch("out1", false);
  m.enableHub();
}

// A battery sensor: readings, one reserved health key, and a writable switch so the
// scope of a relay grant has something it must leave out.
static void profileSalt(Core& m) {
  m.addNumber("salt", "Salt left").readOnly().unit("%");
  m.addNumber("level", "Level").readOnly();
  m.addText("note", "Note", 60).readOnly();
  m.addSwitch("led", "Status LED", [](bool on) { printf("HW led=%d\n", on); return true; });
  m.addReserved("_batt");
}

static void profileExt3(Core& m) {
  m.addSwitch("ch1", "Channel 1", [](bool on) { printf("HW ch1=%d\n", on); return true; });
  m.addSwitch("ch2", "Channel 2", [](bool on) { printf("HW ch2=%d\n", on); return true; });
  m.addSwitch("ch3", "Channel 3", [](bool on) { printf("HW ch3=%d\n", on); return true; });
  m.setSwitch("ch1", false); m.setSwitch("ch2", false); m.setSwitch("ch3", false);
}

// A declaration that breaks the rules, so the library's refusal can be checked.
static void profileBroken(Core& m) {
  m.addSwitch("Bad Key", "x");
}
static void profileTooMany(Core& m) {
  static char keys[40][8];
  for (int i = 0; i < 40; i++) {
    snprintf(keys[i], sizeof keys[i], "k%d", i);
    m.addSwitch(keys[i], "x");
  }
}
static void profileReservedAbuse(Core& m) {
  m.addSwitch("_mine", "x");
}
static void profileTooBig(Core& m) {
  static char keys[32][8];
  static char labels[32][130];
  for (int i = 0; i < 32; i++) {
    snprintf(keys[i], sizeof keys[i], "k%d", i);
    memset(labels[i], 'x', 128); labels[i][128] = 0;
    m.addSwitch(keys[i], labels[i]);
  }
}

int main(int argc, char** argv) {
  const char* profile = argc > 1 ? argv[1] : "lampfan";
  Core m("host_test", "9.9.9");
  if (!strcmp(profile, "lampfan")) profileLampFan(m);
  else if (!strcmp(profile, "ext3")) profileExt3(m);
  else if (!strcmp(profile, "hub")) profileHub(m);
  else if (!strcmp(profile, "salt")) profileSalt(m);
  else if (!strcmp(profile, "broken")) profileBroken(m);
  else if (!strcmp(profile, "toomany")) profileTooMany(m);
  else if (!strcmp(profile, "reserved")) profileReservedAbuse(m);
  else if (!strcmp(profile, "toobig")) profileTooBig(m);
  else { fprintf(stderr, "unknown profile %s\n", profile); return 2; }

  // MAYA_ID / MAYA_MAC let two drivers be two different boards at once.
  const char* ID = getenv("MAYA_ID") ? getenv("MAYA_ID") : "esp32-test";
  uint32_t uptime = 1000;
  const char* ID_MAC = getenv("MAYA_MAC") ? getenv("MAYA_MAC") : "24:6F:28:AA:BB:01";

  FileStorage fileStore(argc > 2 ? argv[2] : ".");
  MemStorage memStore;
  Storage* store = argc > 2 ? (Storage*)&fileStore : (Storage*)&memStore;
  m.setMillis([]() { return g_ms; });
  m.setClock([]() { return g_clock; });
  m.setSecondsClock([]() { return g_secs; });
  m.setPeerTransport([](const uint8_t* mac, const uint8_t* data, size_t len) {
    printf("LTX ");
    for (int i = 0; i < 6; i++) printf("%02X", mac[i]);
    printf(" %.*s\n", (int)len, (const char*)data);
    return g_txok;
  });
  m.onPeerAck([](const char* peer, const char* status, const char* failed) {
    printf("PACK %s %s %s\n", peer, status, failed ? failed : "-");
  });
  m.onPeerMessage([](const char* peer, const char* kind, JsonObjectConst payload) {
    char out[200];
    serializeJson(payload, out, sizeof out);
    printf("PMSG %s %s %s\n", peer, kind, out);
  });
  m.beginPeering(store, ID);
  std::string line;
  setvbuf(stdout, nullptr, _IOLBF, 0);

  while (std::getline(std::cin, line)) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    if (line == "identify") {
      bool ok = m.sendIdentify(ID, "4821", "192.168.0.42", ID_MAC, tx);
      if (!ok) printf("IDENTIFY_REFUSED %s\n", m.problem() ? m.problem() : "?");
    } else if (line.rfind("frame ", 0) == 0) {
      std::string f = line.substr(6);
      Action a = m.onFrame(f.c_str(), f.size(), ID, uptime, tx);
      printf("ACTION %s\n", a == NONE ? "none" : a == REBOOT ? "reboot" : "factory_reset");
    } else if (line.rfind("setsw ", 0) == 0) {
      char k[40]; int v; sscanf(line.c_str() + 6, "%39s %d", k, &v);
      printf("SET %d\n", m.setSwitch(k, v != 0));
    } else if (line.rfind("setnum ", 0) == 0) {
      char k[40]; double v; sscanf(line.c_str() + 7, "%39s %lf", k, &v);
      printf("SET %d\n", m.setNumber(k, v));
    } else if (line.rfind("settext ", 0) == 0) {
      char k[40]; char v[80]; sscanf(line.c_str() + 8, "%39s %79s", k, v);
      printf("SET %d\n", m.setText(k, v));
    } else if (line == "flush") {
      printf("FLUSHED %d\n", m.flush(ID, uptime, tx));
    } else if (line == "full") {
      m.sendFullState(ID, uptime, tx);
    } else if (line == "problem") {
      printf("PROBLEM %s\n", m.problem() ? m.problem() : "none");
    } else if (line.rfind("local ", 0) == 0) {
      size_t sp = line.find(' ', 6);
      uint8_t src[6];
      if (sp == std::string::npos || !macFromHex(line.substr(6, sp - 6).c_str(), src)) { printf("BADCMD\n"); }
      else {
        std::string f = line.substr(sp + 1);
        m.onLocalFrame((const uint8_t*)f.data(), f.size(), src);
      }
    } else if (line.rfind("localhex ", 0) == 0) {
      // Arbitrary bytes, for a frame that is not valid text and cannot go through a text pipe.
      size_t sp = line.find(' ', 9);
      uint8_t src[6];
      if (sp == std::string::npos || !macFromHex(line.substr(9, sp - 9).c_str(), src)) { printf("BADCMD\n"); }
      else {
        std::string hex = line.substr(sp + 1), bytes;
        for (size_t i = 0; i + 1 < hex.size(); i += 2) { unsigned v; sscanf(hex.c_str() + i, "%2x", &v); bytes.push_back((char)v); }
        m.onLocalFrame((const uint8_t*)bytes.data(), bytes.size(), src);
      }
    } else if (line.rfind("psw ", 0) == 0) {
      char peer[40], k[40]; int v; sscanf(line.c_str() + 4, "%39s %39s %d", peer, k, &v);
      printf("PSEND %d\n", m.peerSetSwitch(peer, k, v != 0));
    } else if (line.rfind("pnum ", 0) == 0) {
      char peer[40], k[40]; double v; sscanf(line.c_str() + 5, "%39s %39s %lf", peer, k, &v);
      printf("PSEND %d\n", m.peerSetNumber(peer, k, v));
    } else if (line.rfind("ptxt ", 0) == 0) {
      char peer[40], k[40], v[200]; sscanf(line.c_str() + 5, "%39s %39s %199[^\n]", peer, k, v);
      printf("PSEND %d\n", m.peerSetText(peer, k, v));
    } else if (line.rfind("ppress ", 0) == 0) {
      char peer[40], k[40]; sscanf(line.c_str() + 7, "%39s %39s", peer, k);
      printf("PSEND %d\n", m.peerPress(peer, k));
    } else if (line.rfind("pmsg ", 0) == 0) {
      char peer[40], kind[10]; sscanf(line.c_str() + 5, "%39s %9s", peer, kind);
      printf("PSEND %d\n", m.peerMessage(peer, kind, [](JsonObject o) { o["hello"] = "world"; }));
    } else if (line == "plog") {
      printf("PLOG %d\n", m.flushPeerLog(ID, tx));
    } else if (line.rfind("ms ", 0) == 0) {
      g_ms = (uint32_t)strtoul(line.c_str() + 3, nullptr, 10);
    } else if (line.rfind("clock ", 0) == 0) {
      g_clock = (uint32_t)strtoul(line.c_str() + 6, nullptr, 10);
    } else if (line == "peers") {
      printf("PEERS %d epoch=%u pending=%d\n", (int)m.peerCount(), (unsigned)m.epoch(), (int)m.peerLogPending());
    } else if (line.rfind("ask ", 0) == 0) {
      std::string text = line.substr(4);
      bool sent = m.agentRequest(ID, text.c_str(),
          [](const char* status, const char* t, uint32_t retry) {
            printf("AREPLY %s %u |%s|\n", status, (unsigned)retry, t);
          }, tx);
      printf("AGENT %d\n", sent);
    } else if (line == "tick") {
      m.agentTick();
    } else if (line == "report") {
      bool ok = m.report();
      uint8_t fails; uint32_t since; bool announced;
      m.hubState(fails, since, announced);
      printf("REPORT %d buffered=%d lost=%u fails=%d\n", ok, (int)m.reportsBuffered(), (unsigned)m.reportsLost(), fails);
    } else if (line == "relay") {
      printf("RELAYED %d\n", m.flushRelay(ID, tx));
    } else if (line.rfind("hubstatus ", 0) == 0) {
      printf("HUBSTATUS %d\n", m.sendHubStatus(ID, (uint8_t)atoi(line.c_str() + 10), tx));
    } else if (line == "queued") {
      printf("QUEUED %d dropped=%u\n", (int)m.relayQueued(), (unsigned)m.relayDropped());
    } else if (line == "fallback") {
      printf("FALLBACK %d\n", (int)m.fallBackToServer());
    } else if (line == "hub") {
      uint8_t fails; uint32_t since; bool announced;
      m.hubState(fails, since, announced);
      printf("HUB %s usable=%d down=%d channel=%d fails=%d announced=%d\n", m.hubId() ? m.hubId() : "-",
             m.hubUsable(), m.hubDown(), m.hubChannel(), fails, announced);
    } else if (line.rfind("restore ", 0) == 0) {
      unsigned f, s, a; sscanf(line.c_str() + 8, "%u %u %u", &f, &s, &a);
      m.restoreHubState((uint8_t)f, s, a != 0);
    } else if (line.rfind("secs ", 0) == 0) {
      g_secs = (uint32_t)strtoul(line.c_str() + 5, nullptr, 10);
    } else if (line.rfind("txok ", 0) == 0) {
      g_txok = atoi(line.c_str() + 5) != 0;
    } else if (line == "sync") {
      printf("SYNC\n");   // the caller reads until this, so it knows the command is done
    }
    fflush(stdout);
  }
  return 0;
}
