# Troubleshooting: what Serial says, and what it means

Open Serial at **115200**. On an ESP32-C3 that uses its own USB, compile with
`CDCOnBoot=cdc`. The banner appears up to ~2.5 s after boot (the library waits for the
monitor; **on a C3 powered from a charger, with no monitor, every boot takes that 2.5 s longer**). If a C3 prints nothing: unplug and replug, reopen the monitor, and check it
is not held open by another program (the upload will then fail with "port does not exist").

## Boot

| You see | Meaning | Do |
|---|---|---|
| `[Maya] library 0.3.0 \| model ... \| fw ...` then `name`, `sketch built ...` | healthy start | note the library version and build time when reporting any bug |
| `New firmware build detected. Settings wiped` | every flash resets WiFi + PIN, by design | provision again |
| `[Maya] Declaration problem: ...` | the descriptor would be refused (bad key, duplicate, > 32) | fix the declaration |
| `No WiFi config. Entering BLE provisioning.` | a fresh board | provision from the app |
| `Waiting for the app over Bluetooth (N s left)` | alive and waiting, 5-minute window | open the app's Add Device |
| `Provisioning timed out.` | nobody connected in 5 min | it restarts setup; try again |

## Bluetooth

| You see | Meaning | Do |
|---|---|---|
| `BLE: phone connected.` | the app reached the board | proceed |
| `BLE write received: ...0001 (N bytes)` | SSID arrived (`...0002` password, `...0004` server URL, `...0003` PIN). Lengths only: values are never printed | check N matches what you typed (a password of 8 chars is 8) |
| connected but no `write received` | the phone's write was refused/dropped | retry; forget the device in the phone's Bluetooth settings |
| `BLE: phone disconnected. Advertising again.` | normal after a finished or failed try | the board is findable again |
| app says "no devices found" | not advertising, or phone permission off | check Serial shows `Advertising as 'Maya-...'`; allow Nearby devices/Location |
| `PIN mismatch` / `PIN rejected` | wrong PIN / weak PIN (0000, 1111, 1234) | use another 4-digit PIN |

## WiFi (the line says why)

`WiFi: not joined, reason N - <words>`:

| Reason | Cause | Do |
|---|---|---|
| 201 | the network is not heard | the name is wrong (case counts), it is out of range, or it is **5 GHz only**. ESP32 and C3 are 2.4 GHz only |
| 202, 15, 204 | password refused / handshake timed out | retype the password; check WPA3-only routers (use WPA2/WPA2+3 mixed) |
| 39 | the router did not answer | weak signal, a crowded channel, or an antenna that cannot drive full power (try `setWifiTxPower`) |
| 8 | this device left the access point. Also what our own disconnect between retries reports, so the library ignores it when a real reason exists | read the earlier reason line, not this one |
| 2 | authentication expired | retry; check the router is not rebooting |
| 200 | signal lost mid-join | move closer |

`WiFi scan: '<name>' heard at -64 dBm on channel 11` - the board hears it; the password or
radio is the problem. `NOT heard among N networks` - nothing to do with the password.

Rules of thumb: -67 dBm or better joins reliably, -80 does not. A hotspot on a phone is often
5 GHz: turn on "Maximize Compatibility" (iPhone) or choose 2.4 GHz (Android).

**Fails only while a phone is connected over Bluetooth, joins fine in a bare WiFi sketch:**
the two share one radio. The library pauses advertising and relaxes the link during a join; if
it still fails, tell the owner to retry, and file a ticket with the Serial log.

## Server link

| You see | Meaning |
|---|---|
| `[WS] Connected` then no card in the app | the server refused the identify: read `[Maya] Identify not sent`, or the PIN |
| `[WS] Disconnected` repeatedly | wrong server URL, or the server is asleep (cold start ~30 s) |
| `Warning: Multiple WebSocket connection failures` | the same, for over 5 tries |

## Build

| Error | Cause |
|---|---|
| `Sketch too big` | not the Huge APP partition |
| `Maya.h: No such file` | the library is not in the Arduino libraries folder, or `--libraries` is wrong |
| `bits/error_constants.h` / `Ethernet.h` not found | path over 260 chars (short data folder) / `build.extra_flags` overridden |
| `ArduinoJson ... ambiguous` | ArduinoJson 7 installed; use 6.x |
| upload: `Failed to connect` / `chip stopped responding` | enter download mode by hand; try `--no-stub`; flash mode DIO 40 MHz |
| upload ok, then `Packet content transfer stopped` | harmless on a C3: the USB port vanished as the chip reset |
