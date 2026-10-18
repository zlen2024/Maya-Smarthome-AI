# Maya library changelog

One heading per release, newest first. The number in the newest heading must equal
`version=` in `library.properties` and `MAYA_LIB_VERSION` in `src/Maya.h`
(`python extras/test/check_version.py` checks all three).

How to cut a release: edit the three places, add the heading here, run
`extras/test/check_version.py` and the three protocol tests, commit, then tag the
repository `maya-lib-v<version>` so a sketch's "library 0.3.0" in its Serial banner
can be traced to an exact commit. (The library lives inside the Maya repository on
purpose; a second git repository inside it would hide its history from the project's.)

## [0.3.0]

The protocol tests (`extras/test/`) were re-run and pass. **Not run on
a board:** every behaviour below that touches the radio or Bluetooth is unverified until a
board has done it.

### Added
- `setName("Smart Jar")`: the name a person would call the device. It goes to Serial and to
  the Bluetooth INFO characteristic. **The phone app does not read it yet** (it shows a fixed
  "Maya Device XXXX"): `SOFTWARE_TICKETS.md` T-1. The owner's own name still wins (PROTOCOL.md 4).
- `printInfo()` and a boot banner on Serial: library version, model, firmware, name,
  device id, **when the sketch was built**, chip, free heap. Printed after waiting up to
  2.5 s for a USB serial monitor, so a board whose Serial is its USB port is not silent
  just because the monitor opened late; printed again when Bluetooth setup starts.
- `Maya::libraryVersion()`, `builtAt()`, `name()`, `model()`, `fw()`.
- A read-only Bluetooth **INFO** characteristic (`...9008`): `{"lib","id","model","fw",
  "name","built","bin"}`. No secrets. An app that does not know about it is unaffected.
- `setWifiTxPower()`; the ESP32-C3 defaults to 8.5 dBm (see Changed).
- Serial now says **why** WiFi failed, with the router's reason code in words, in the
  provisioning path and at boot.
- A "waiting for the app" line every 15 s during Bluetooth setup, so waiting is
  distinguishable from hung.
- `skills/`: two skills for an agent or a person building a Maya device, or changing the
  library. See `skills/README.md`.
- `extras/test/check_version.py`.

### Changed
- Bluetooth provisioning no longer leaves the board silent after a phone disconnects:
  advertising restarts. (The BLE library of core 2.0.x says it does this and does not.)
- Just before the WiFi join in provisioning the phone link is asked for a 60-100 ms interval, to
  give WiFi airtime on the shared radio (asked then, not at connect, so service discovery stays fast).
- The Bluetooth service reserves 40 attribute handles (default 15; it needs ~22).
- WiFi is brought up once and retried on, not torn down and rebuilt on every try.
- The station asks for a 20 MHz channel.
- ESP32-C3: 8.5 dBm transmit power unless the sketch says otherwise. Many SuperMini
  clones hear a router and never finish joining it at full power. **Fixed a real bug:** the
  0.2.0 code asked for a lower power before the station had started, and the core ignores
  that silently, so it was never applied. The library now waits for the station and prints
  the power it got.
- WiFi reason 8 (our own disconnect between tries) no longer overwrites the router's real reason.
- A sensor (`beginSensor()`) prints the banner and waits for a monitor only after a
  power-on or reset, never after a timer wake.

### Unchanged on purpose
- The advertised name stays `Maya-<id>` and the original characteristics and status
  codes keep their meaning: the app depends on them.
- Every flash still wipes WiFi and the PIN (the first owner sets a PIN).

## [0.2.0]

The hub relay, the battery sensor (`beginSensor`/`reportNow`/`sleepFor`), the local
link, `askMaya`, Open API scoped keys (PROTOCOL.md rev 2.5).
