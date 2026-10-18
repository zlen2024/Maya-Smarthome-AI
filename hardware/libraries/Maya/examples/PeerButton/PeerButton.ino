// A button that drives another Maya device directly, over the local link, with no
// round trip through the server.
//
// Pair it in the app first: "this device may address that one", scope = the keys
// you want it to reach. Until a person does, this sketch does nothing - which is
// the point. The BOOT button on most ESP32 boards is GPIO0.
//
// The server still sees everything: both ends report what the link did, and the
// app shows where the two accounts differ.
#include <Maya.h>

Maya maya("example_peer_button", "1.0.0");

// The id of the device this one has been paired with. Shown in the app.
const char* FAN_ID = "esp32-9f83b1c1";
const int BUTTON = 0;

bool lastDown = false;
int level = 0;

void setup() {
  pinMode(BUTTON, INPUT_PULLUP);
  maya.setName("Fan button");

  // The answer to what we sent. A refusal arrives here: out of scope, or the
  // hardware said no. The sender does not log it again; the receiver's audit
  // line carries the result.
  maya.onPeerAck([](const char* peer, const char* status, const char* failed) {
    Serial.printf("%s answered %s%s%s\n", peer, status, failed ? " at " : "", failed ? failed : "");
  });

  maya.enableHealth();
  maya.begin();
}

void loop() {
  maya.loop();

  bool down = digitalRead(BUTTON) == LOW;
  if (down && !lastDown) {
    level = (level + 25) % 125;   // 0, 25, 50, 75, 100, 0, ...
    // false means: no grant for that device, it has expired, "fan" is not in the
    // grant's scope, or the frame would not fit one radio packet.
    if (!maya.peerSetNumber(FAN_ID, "fan", level)) Serial.println("not paired, or not allowed");
  }
  lastDown = down;
}
