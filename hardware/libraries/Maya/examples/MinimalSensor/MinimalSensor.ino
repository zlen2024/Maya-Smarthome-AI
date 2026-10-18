// The smallest useful Maya device, and the one to copy when you build your own:
// a lamp you can switch, a fan you can drag, a temperature you can read, and a
// button that does something.
//
// Nothing here edits software/. Flash it, provision it from the app, and the
// four controls appear - the app and Maya draw them from what is declared below.
#include <Maya.h>

Maya maya("example_lamp_fan", "1.0.0");

const int LAMP_PIN = 2;
const int FAN_PIN  = 4;     // PWM
const char* const MODES[] = {"eco", "normal", "boost"};

void setup() {
  pinMode(LAMP_PIN, OUTPUT);
  ledcAttachPin(FAN_PIN, 0);
  ledcSetup(0, 5000, 8);

  // What a person would call this. It is printed in the Serial banner (with the library
  // version and the time this sketch was built) and sits in the Bluetooth INFO
  // characteristic for an app to offer as the starting name. The current app does not
  // read it yet; the owner types the real name anyway.
  maya.setName("Lamp and fan");

  maya.addSwitch("lamp", "Lamp", [](bool on) { digitalWrite(LAMP_PIN, on); return true; });

  // A range is something the user drags between limits you know.
  maya.addRange("fan", "Fan speed", 0, 100, 5, [](double pct) {
    ledcWrite(0, (int)(pct * 255 / 100));
    return true;
  }).unit("%");

  // A measured value is a number with no handler: nothing can write it.
  maya.addNumber("temp", "Temperature").unit("C").history();

  maya.addEnum("mode", "Mode", MODES, 3, [](const char* mode) {
    Serial.printf("mode -> %s\n", mode);
    return true;
  });

  // A press has no state to read back. confirm() makes Maya ask the user first.
  maya.addButton("horn", "Horn", []() { Serial.println("beep"); }).confirm();

  // Anything destructive should be invisible to Maya. The app still shows it.
  maya.addButton("reset", "Reset counters", []() { Serial.println("reset"); }).agentDeny();

  maya.begin();
}

void loop() {
  maya.loop();

  // Report what you read. A value that has not changed is not re-sent.
  static unsigned long last = 0;
  if (millis() - last > 5000) {
    last = millis();
    maya.setNumber("temp", 20.0 + (millis() / 1000 % 10) * 0.5);   // replace with a real sensor
  }
}
