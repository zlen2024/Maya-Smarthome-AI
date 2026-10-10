// Maya - make an ESP32 board a Maya device.
//
//   #include <Maya.h>
//   Maya maya("my_lamp", "1.0.0");
//
//   void setup() {
//     maya.addSwitch("lamp", "Lamp", [](bool on) { digitalWrite(2, on); return true; });
//     maya.begin();
//   }
//   void loop() { maya.loop(); }
//
// The library owns everything the protocol (PROTOCOL.md) cares about: BLE
// provisioning, WiFi, the server link, the descriptor, and the answers to `set`.
// A sketch only says what the hardware can do and does it when asked.
//
// Capability keys and labels are kept as pointers - pass string literals.
#pragma once

#include <Arduino.h>
#include "MayaCore.h"

class Maya : public mayalib::Core {
 public:
  Maya(const char* model, const char* fw) : mayalib::Core(model, fw) {}

  // Declares the health keys of PROTOCOL.md 5.3 the library can fill in itself
  // (_rssi, _uptime, _fw) and keeps them current. Call before begin(). _batt is
  // yours to declare and report: only the sketch knows how it measures it.
  void enableHealth();

  // Loads settings, opens BLE provisioning if the board has no WiFi yet, joins
  // WiFi and starts the server link. Declare every capability before this.
  void begin();

  // Call from loop(). Keeps WiFi and the link up, answers the server, and sends
  // whatever the sketch changed with setSwitch()/setNumber()/....
  void loop();

  // The local link (PROTOCOL.md 7). A grant arrives from the server when a person
  // pairs two devices in the app; from then on, with a `send` grant:
  //   maya.peerSetNumber("esp32-9f83b1c1", "fan", 60);
  // returns false if there is no grant, it has expired, the key is outside its
  // scope, or the frame will not fit in 250 bytes. A `recv` device needs nothing:
  // a peer's `set` goes through the same handlers as one from the app, restricted
  // to the grant's scope. onPeerMessage()/onPeerAck() deliver events and answers.
  // The library reports what the link did to the server on its own.

  const char* id() const;
  bool connected() const;

  // Wipes WiFi, PIN and ownership and reboots into provisioning. The same thing
  // the server's `factory_reset` does - expose it to a physical button if the
  // board has one.
  void factoryReset();

 private:
  bool health_ = false;
  unsigned long lastFlush_ = 0;
  unsigned long lastFull_ = 0;
  unsigned long lastWiFiCheck_ = 0;
  unsigned long lastWarning_ = 0;
  void refreshHealth();
};
