---
name: maya-library-maintainer
description: Change the Maya Arduino library itself (hardware/libraries/Maya) - fix a bug, add an API, change provisioning/WiFi/BLE behaviour - without breaking the app, the server or devices already flashed. Use when a task needs the library to change, a version to be bumped, a release cut, or the library's tests run. Not for building a single device: use maya-device-builder.
---

# Maintaining the Maya library

The library is a contract with two things it does not own: the **app** (it speaks to the
board over Bluetooth) and the **server** (over WebSocket, `PROTOCOL.md`). A change that
helps one device by moving either of those breaks every other device and the app. Most
"library bugs" are a device bug; check `maya-device-builder/references/troubleshooting.md`
first.

## What must not change without a ticket

| Frozen | Why |
|---|---|
| Advertised name `Maya-<device id>` | the app parses the id out of it |
| BLE service/characteristic UUIDs `...9000`-`...9007`, and their meaning | the app is written against them |
| Status codes sent on `...9006` ("0"-"9") | the app switches on them and **ignores an unknown code**, so a new one leaves it waiting on a failed board |
| The identify / state / ack / set frames | `PROTOCOL.md`; the server validates them |
| Wiping WiFi + PIN on every new firmware | a security rule, not a bug |
| Key rules (`[a-z0-9_]`, 1-24) | permissions are filed under keys |

**Additive is fine:** a new read-only characteristic (INFO `...9008` is one), a new Serial
line, a new method. **If the app or server would have to change to use it, do not change
them;** write a ticket in `SOFTWARE_TICKETS.md` (repository root) and ship the library part.

## Layout

| File | Is | Tested by |
|---|---|---|
| `src/MayaCore.*`, `MayaPeer.cpp`, `MayaRelay.cpp`, `MayaCrypto.*` | the protocol, no hardware | `extras/test/` on a laptop, against the real server |
| `src/Maya.cpp` | BLE, WiFi, the WebSocket, ESP-NOW glue, deep sleep | **only compiled**, never by the host tests |
| `src/Maya.h` | public API | compiles |

Put logic in the Core files where a test can reach it. Anything in `Maya.cpp` needs a board.

## Before every change

1. `python extras/test/check_version.py` and the three protocol tests pass **before** you touch
   anything (so you know whom to blame). Commands are in `README.md` "Testing without a board".
2. Decide the version: patch = fix, minor = new API, major = something frozen above moved.

## After every change

1. Compile **all** of: the five `examples/`, `hardware/smart_jar` (both `JAR_BATTERY` values),
   `hardware/smartextension`, `hardware/smartextension_hub`, for the classic ESP32 **and** the
   C3 where the sketch allows. A change that only builds for one chip is a change that
   breaks the other.
   ```
   arduino-cli compile --fqbn esp32:esp32:esp32:PartitionScheme=huge_app --libraries hardware/libraries <sketch>
   ```
2. Re-run `extras/test/` (needs g++ or `pip install ziglang`, ArduinoJson headers, the
   server's test dependencies). Exit `3` = could not build the driver = **not a pass**.
3. Bump the version in **three** places - `library.properties`, `MAYA_LIB_VERSION` in
   `src/Maya.h`, the newest heading in `CHANGELOG.md` - and run `check_version.py`.
4. Update `README.md`'s "What is and is not verified". **Never write "works" for something
   that was only compiled.** The honest line is "compiles; not run on a board".
5. Copy the library into the Arduino IDE's `libraries/Maya` if the human uses the IDE, or they
   will keep flashing the old one and report the old bug.
6. Commit, then tag `maya-lib-v<version>` (only when the human asks for the tag).

## Style

Match the file: comments say **why** (the measured or documented reason), not what. A claim
about the radio, BLE or power that has not been run on a board is written as "unverified"
in the comment and in `CHANGELOG.md`.
