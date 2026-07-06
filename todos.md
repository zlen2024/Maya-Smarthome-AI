# Maya — Report vs. Implementation TODOs

Tracks features the **report describes as planned/future** that are **not yet built**, plus
report artifacts that still need manual updating. Generated alongside the report update
(`FYP-NEL2025_Maya_updated.docx`). The branch at time of writing is `dev-itteration-2.9`.

## Not yet implemented (deferred features)

### Iteration 3 — AI / LLM agent (planned)
- [ ] LLM natural-language command processing (OpenRouter API). No LLM code exists in server or app yet.
- [ ] "AI Mode" chat that turns intents into device commands. (Current "chat" tab is a family group chat, not AI.)
- [ ] Agentic automation engine (e.g. auto power-off when a screen-time limit is exceeded).

### Child data collection (DONE — 2026-07-07)
- [x] GPS location on the child device (foreground-only while app is open; `geolocator`, 3-min timer in `child_shell.dart`). Parent sees last-known location + "Open in Maps".
- [x] Screen-time / app-usage tracking (Android UsageStats via `maya/usage` MethodChannel in `MainActivity.kt`; needs the special Usage Access grant in Settings). Daily totals upserted to `screen_time`.
- [x] Homework tracker (parent assigns via Children tab; child sees Tasks tab and marks done).
- [x] "Remaining screen time" view in the child app (Tasks tab header; parent sets limit per child).
- Note: true *background* tracking (app closed) deliberately not built — foreground-only was the accepted scope.

### Other objectives (DONE — 2026-07-07)
- [x] Secured Open API (Objective 3): house-scoped `X-API-Key` keys (SHA-256 stored, shown once, master-issued in Settings → API Keys), `/api/open/v1/devices` + `/command`, documented at `/docs` under "Open API v1".
- [x] Product/marketplace "buy device" flow: mock checkout (hardcoded catalog, `orders` table, server-side pricing). Store screen via Device tab → "Buy Devices".
- [ ] iOS support. Apps are Android-only by design (background limits) — keep as a stated constraint.

## Hardware
- [ ] Firmware currently drives GPIO/LED outputs (`OUTPUT_PINS = {2,4,5}`); wire to real AC relay channels for the production prototype. (3 channels — report now says 3-channel throughout.)

## Report artifacts needing manual update (cannot be auto-generated)
These are images/diagrams in the report; redraw to match the current Maya architecture:
- [ ] §5.3 Use Case Diagram — reflect roles (parent/master, child, admin), access-control, multi-house, chat.
- [ ] §5.4 Class Diagram — align with `models.py` (Account, House, AccountHouse, Child, Device, SmartExtension, Relay, Permission, MsgHistory, Heartbeat).
- [ ] §5.5 ERD — same entities as above.
- [ ] §5.6 Flow Chart — BLE provisioning + WebSocket command flow (drop HTTP/MQTT).
- [ ] §5.7 Network Architecture — Flutter app ⇄ FastAPI on Fly.io (WebSocket) ⇄ ESP32; drop Firebase/Supabase/MQTT.
- [ ] §5.8 Sequence Diagrams — update protocols to WebSocket; §5.8.2 should reflect device registration, not "buy product".
- [ ] Front matter still has template placeholders: ABSTRACT / ABSTRAK / ACKNOWLEDGEMENT ("Text text text…"), DEDICATION, and "TITLE OF FINAL YEAR PROJECT" / "NAME OF CANDIDATE" on the inner title page. The real Abstract/Abstrak text exists in the old `Muhamad Daniel Hakimi(...)_Report latest.docx`/`.pdf` and can be pasted in.
- [ ] List of Tables / List of Figures / Symbols still use template captions ("Table caption", Diameter/Force, etc.).

## Notes on what WAS updated in the report
- Renamed **NexusLink → Maya** (and NexusAI → Maya) throughout.
- Backend: Firebase/Supabase → **FastAPI + SQLAlchemy + SQLite on Fly.io (Singapore)**, JWT + bcrypt.
- Device link: HTTP/MQTT → **WebSocket**; added **BLE provisioning** + QR onboarding.
- Relay: **4-channel → 3-channel** (Maya sections only; the Alexa case study in §2.3.4 keeps its real 4-channel).
- Iteration 2 recast to the **companion + access-control module** (accounts, per-channel permissions, multi-house, family chat, device PINs).
- AI / GPS / screen-time / homework reframed as **future work**.
