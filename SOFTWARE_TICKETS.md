# Software tickets

Things the **app** or **server** would need to change to take full advantage of the Arduino
library (`hardware/libraries/Maya`) or to fix a hardware-visible problem. The library
and firmware were changed to be additive so none of these blocks them: until a ticket is
done, the device works as before and simply does not show the new information.

Nobody has changed `software/` for these. Each says what the device already does, so the
fix is on one side only.

Format: **what is wrong / wanted - what the device already sends - the smallest change -
how to tell it is done.**

---

## T-1  The app cannot show or prefill a device's own name, version or build time

**Wanted.** While adding a device, the name field starts with something meaningful
("Smart Jar", from the firmware's `maya.setName()`), and the device's detail page shows the
library version, firmware version and when it was built.

**Already sent (library 0.3.0).** (Check on a real board with a BLE explorer such as nRF Connect
that the characteristic is really present before building on it: it is one of the service's characteristics (the stack registers them in pointer order, not declaration order), and the
library now reserves 40 attribute handles for the service instead of the default 15 to make room.)
A new read-only BLE characteristic
`12345678-1234-1234-1234-123456789008` on the existing service. Value (UTF-8 JSON, no secrets):

```json
{"lib":"0.3.0","id":"esp32-9fc13de8","model":"smart_jar","fw":"1.0.0","name":"Smart Jar","built":"Oct 18 2026 01:23:45","bin":"3f9a1c2e"}
```
`name` is absent when the sketch did not call `setName()`. The advertised name is still
`Maya-<id>`; nothing about the original characteristics or status codes changed.

**Change (mobile).** In `provision_screen.dart`, after finding the characteristics: if the
`...9008` characteristic exists, read it once and use `name` as the default for the name field
(today a fixed "Maya Device XXXX"). Treat a missing characteristic or invalid JSON as "old
firmware" and keep the current behaviour. Never block provisioning on it.

**Done when.** A board flashed with 0.3.0 and `setName("Smart Jar")` offers "Smart Jar"; a
board on 0.2.0 still provisions and offers the old default.

## T-2  The server drops `lib`/`built`, so the device card cannot show the library version

**Wanted.** The device page shows "library 0.3.0, built Oct 18 2026" for a connected device,
not only during Bluetooth setup.

**Already sent.** Nothing yet over the WebSocket: `identify` carries `model` and `fw` only.
Adding fields to `identify` is a protocol change (PROTOCOL.md section 4), so the library
has not done it.

**Change (server + protocol).** Decide whether `identify` may carry two optional strings,
`lib` and `built` (<= 24 bytes each); store them on the device row beside `fw`; return them in
the device JSON. Then the library adds them (one line in `MayaCore.cpp`).

**Done when.** `PROTOCOL.md` describes the fields and the host test in
`extras/test/test_library.py` checks the server keeps them.

## T-3  The app does not show that a device is a hub, nor its MAC

**Wanted.** A hub is visibly a hub (and which devices are paired through it); the MAC is
available for support.

**Already sent.** `hub:true` and `mac` in `identify`; the server stores `is_hub` and `mac`
(`models.py`, `main.py`).

**Change (mobile).** Show them in the device detail page. Nothing else.

## T-4  Provisioning failure reasons are one number the app cannot explain

**Wanted.** "The network was not found (is it 2.4 GHz?)" vs "the password was refused"
vs "no answer from the router" instead of a single "could not connect".

**Already sent.** Status code `4` for every WiFi failure. The device prints the exact
reason on Serial (reason code in words); the information exists, but only over USB.

**Change (mobile + library together).** Add status codes, e.g. `10` network not heard,
`11` password refused, `12` router did not answer, and make the app show the right message
(`_handleBleStatusCode` ignores any code it does not know, so the app would sit waiting on a
failed board - which is why the library does not send new codes on its own). The library change is three lines once the app handles them.

**Done when.** The app shows the three messages for the three causes on a real board.

## T-5  Provisioning on a busy radio (observed on an ESP32-C3 SuperMini)

**Observed.** With a phone connected over Bluetooth, a C3 failed to join a 2.4 GHz router (reasons
39, 8, 202 in turn) with the right password; a bare WiFi sketch with no Bluetooth joined
first try. The library now relaxes the phone link just before the join and lowers transmit
power (a first version of that power change was silently ignored by the core; the library now waits
for the station and prints the power it got, which should make it apply - unverified). **None of that has been tested on a board** and may not be enough.

**If it is not enough (mobile).** The robust fix is for the app to disconnect Bluetooth
after sending the credentials and learn the result by polling the server (the app already has
this path for older firmware: "Fallback for older firmware: poll the server API"). That
changes the app's flow, so it is a ticket and not something the library can do alone.

## T-6  Server cold start looks like a device fault

**Observed.** A device whose server is asleep prints `[WS] Disconnected` for ~30 s after
boot; the app shows it offline. Not a library bug. A cheap health ping from the app on
open, or a longer first-connect grace in the app's "offline" label, would hide it.
