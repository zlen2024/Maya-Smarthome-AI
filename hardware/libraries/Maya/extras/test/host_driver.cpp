// Drives MayaCore on a laptop so the real server can judge what it says.
//
//   host_driver <profile>      reads commands on stdin, writes frames on stdout
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
#include <string.h>
#include <string>
#include <iostream>
#include "MayaCore.h"

using namespace mayalib;

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
  else if (!strcmp(profile, "broken")) profileBroken(m);
  else if (!strcmp(profile, "toomany")) profileTooMany(m);
  else if (!strcmp(profile, "reserved")) profileReservedAbuse(m);
  else if (!strcmp(profile, "toobig")) profileTooBig(m);
  else { fprintf(stderr, "unknown profile %s\n", profile); return 2; }

  const char* ID = "esp32-test";
  uint32_t uptime = 1000;
  std::string line;
  setvbuf(stdout, nullptr, _IOLBF, 0);

  while (std::getline(std::cin, line)) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    if (line == "identify") {
      bool ok = m.sendIdentify(ID, "4821", "192.168.0.42", tx);
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
    } else if (line == "sync") {
      printf("SYNC\n");   // the caller reads until this, so it knows the command is done
    }
    fflush(stdout);
  }
  return 0;
}
