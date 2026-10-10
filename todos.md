# Maya — Report vs. Implementation TODOs

Tracks features the **report describes as planned/future** that are **not yet built**, plus
report artifacts that still need manual updating. Generated alongside the report update
(`FYP-NEL2025_Maya_updated.docx`). The branch at time of writing is `dev-itteration-2.9`.

## Not yet implemented (deferred features)

### Iteration 3.0 — AI / LLM agent (DONE — 2026-07-08)
- [x] LLM natural-language command processing. Provider is **Ollama Cloud** (`gpt-oss:20b-cloud` via `https://ollama.com`, `OLLAMA_API_KEY` secret) — not OpenRouter as originally planned. Logic in `server/ai.py`.
- [x] AI in the family chat: a user types **`@maya …`** in the house chat; Maya reads recent `msg_history` + device state, replies as a chat participant (`sender_type="ai"`), and switches devices. Wired into the `/ws/mobile` chat handler (`_run_maya`).
- [x] Runs as the invoking sender: a child's `@maya` commands hit the same per-relay permission checks as a manual tap (shared `_child_command_denial`).
- [x] Maya is a **tool-calling agent** (Ollama tools): `control_device`, `get_child_location`, `list_homework`, `get_screen_time`, `add_homework`, `read_activity_log`. Agent loop in `main.py` (capped 5 steps). Tools enforce child=self-only, parent=any child in house; control keeps per-relay checks.
- [x] **Activity log** (`activity_log` table + `log_activity`): device switches, homework assign/complete, member join, child login, Maya-driven actions. `GET /api/activity` (parent=house, child=own) + Maya's `read_activity_log`.
- [x] **Rename relay channels** (`PUT /api/relays/{id}`, device-managers): channel gets a real name ("Television"); shown/edited in Devices tab; Maya maps names via context.
- [x] **@-mention** in chat: `@` autocomplete (Maya + members + children); `mentions` table marks messages per target, unseen until the target opens chat; unseen badge on the Chat tab.
- [x] **Clear chat** (house master): `DELETE /api/houses/{id}/chat` wipes messages + mentions, broadcasts `chat_cleared`.
- [x] FIX: firmware only accepts `output_on`/`output_off` — normalise `on`/`off` in `_dispatch_command` so Maya AND the Open API actually switch relays.
- [x] **Web marketplace** (`/store`, `static/store.html`): public catalog (`GET /api/store/public-catalog`, no auth), buy uses the portal's saved login (mock checkout). Mobile "Buy Devices" opens `{baseUrl}/store` in the browser; in-app `StoreScreen` removed. Marketplace is web-only now.
- [x] **Web API & Docs** (`/integrate`, `static/integrate.html`): create/list/revoke API keys + Open API v1 guide (curl examples) + Swagger link. "API & Docs" button in the portal header after login. Store link always in header.
- [x] **Mobile fix**: switching house reloads the shell (pushReplacement) so tabs refetch — no more stale data from the previous house.
- [x] **Automation rule** (screen-time limit alert): on each screen-time report, when a child crosses `daily_screen_limit_min`, Maya fires **once/day** — posts a chat message, @-mentions the parent AND child (badges), and logs `screen_limit_reached`. Deduped via `screen_time.limit_notified` (resets next day). Notify-only by design (screen-time is phone usage, not a relay). Self-check: `server/test_screen_limit.py`.
- [x] **Voice command** (mobile, both parent+child): on-device ASR via the **Android native recognizer** (`speech_to_text`, Malay `ms_MY` + English) → transcript → private `POST /api/maya/voice` → full Maya tool-agent as the caller (same per-sender permissions) with 5-min in-RAM session memory → reply shown AND **spoken** (on-device **TTS**, `flutter_tts` 3.8.5) in a full-screen **voice overlay** (pulsing orb + ripple rings, live transcript, ChatGPT-style). NOT written to house chat. Two entry points: (1) mic FAB on both shells, (2) **Quick Settings tile** ("Maya" in Control Centre) — native `MayaTileService` opens the overlay even when the app is closed. **Greet-on-open**: Maya speaks a name-personalized greeting per language, then auto-listens. **Language toggle** (EN/MS, top of overlay, persisted): sets both ASR locale + TTS voice; switching interrupts + re-greets. Wake-word dropped (future work). Agent core extracted to `run_maya_agent()`. Built + verified on emulator + phone 2026-07-09.
  - **STT (final):** device recognizer (`speech_to_text`, EN/MS via locale, live partials, offline) is the **default**. Optional **Groq `whisper-large-v3`** (BYOK): Settings → Voice Assistant toggle + API-key field (stored on-device); `GroqStt` records a WAV (`record`) and POSTs client-side to Groq (key never touches our server). `VoiceService` auto-selects: Groq if enabled+key, else device. TTS = `flutter_tts` 3.8.5.
  - **Tried + dropped on-device Whisper:** `mesolitica/malaysian-whisper-tiny` converted HF→ONNX (Colab notebook `software/tools/convert_malaysian_whisper_tiny_to_sherpa.ipynb`) + run via `sherpa_onnx` — worked end-to-end offline but **tiny accuracy too poor** (hallucinated on silence). Removed. `whisper_ggml` earlier abandoned (ffmpeg-kit deprecated → 9-byte stub); `pocket-tts` rejected (Python, no mobile, no Malay).
  - **Toolchain upgrade (kept — `record` needs it):** AGP **7.3.0 → 8.1.4**, Gradle **7.6.3 → 8.4**, Java/Kotlin **8 → 17** (record_android uses Java-17 sealed classes AGP 7.3's D8 can't dex), minSdk **21 → 23**. Verified on emulator 2026-07-10: device STT restored, Groq settings render, no crash. APK ~23MB.
  - NOTE: originally planned on-device Whisper (`whisper_ggml` + mesolitica Malay GGML) but **whisper_ggml is unbuildable** — its `ffmpeg-kit` dependency was deprecated upstream and now ships a 9-byte "Not Found" stub instead of the AAR binary. Native recognizer does the same job (short foreground commands) with no 200MB model / NDK / CMake / ffmpeg. Revisit Whisper only if offline/custom-model accuracy is required (would need a non-ffmpeg engine, e.g. sherpa_onnx).
- [ ] Agentic *power-off* automation (actually cut a relay on a rule) — still **deferred to 3.1**; current rule is notify-only.
- DEPLOY: `OLLAMA_API_KEY` is set as a Fly secret (live). Optional: `OLLAMA_MODEL` to override the model.

### Iteration 4 — security hardening (DONE — 2026-10-10)
Implements the four findings from the 2026-09-08 review, which had been decided but
never built. Full reasoning in `wiki/pages/security-notes.md`; the self-check is
`software/server/test_security.py` (run `python test_security.py`).
- [x] **Brute-force chain to a child's GPS closed.** `POST /api/houses/join` was the
  gate: sequential `house_id`, 6-digit `join_pin`, `!=` comparison, no rate limit at
  all — then `GET /api/children` returns `last_lat`/`last_lng`. Now `JOIN_LOCK`
  (5 failures/h per account+house → 1h lockout), `JOIN_WALK_LOCK` (10/h per account,
  so walking the id space dies too), `secrets.compare_digest`, and every failed join
  written to the house activity log so an attack is visible to the household.
- [x] **No more `"0000"` anywhere.** It was the default at six layers, and WS identify
  read `if stored_pin and stored_pin != "0000"` — so the device PIN check never ran.
  New `validators.py` (4 digits, no repeated digits, no 1234/4321) enforced in
  `register_device` + `create_child`; `compare_digest` on identify; firmware
  `isAcceptablePin` refuses to *store* a weak PIN (BLE status `9`) and treats an empty
  PIN as "unclaimed"; app no longer pre-fills the field.
  **Needs a reflash** to take effect on the board — existing devices keep working
  meanwhile (they send the PIN they were provisioned with, which is now compared).
- [x] **`/admin` default password gone.** No fixed fallback: absent
  `ADMIN_PASSWORD_HASH` mints a random password per process and prints it once.
  Guarded by `ADMIN_LOCK` (5 failures/15m per IP → 30m).
- [x] **General rate limiting.** `ratelimit.py` — login (per email + per IP),
  registration (per IP), `/api/maya/voice` (20/min + 300/day per caller, a budget
  guard: every call is a paid Ollama request), Open API (60/min per key, documented
  on `/integrate` and in the agent skill as a `429` + `Retry-After`).
- [x] **`SECRET_KEY` fallback literal removed** (`auth.py`). Was already safe in the
  live deployment (set as a Fly secret) but was a trap for anyone forking a public
  repo. Absent now means a random per-process key plus a warning.
- [ ] **Per-key Open API scoping** — a key still grants full rights over every device
  in its house. Rate limiting closed the operational half of that finding only.
- [ ] **`list_children` shows GPS to any house member**, not only the master.
  Accepted deliberately: a co-parent given the join PIN is a legitimate viewer, and
  there is no role between `is_master` and plain member to express "may not see
  locations". Revisit with the permissions UI.
- [ ] Hash `join_pin` / `devices.pin` at rest. Low value while the device must present
  its PIN in cleartext on every connect, and the master's own join PIN is displayed
  on purpose.

### Iteration 4 — device protocol v2, step 1 of 6 (DONE — 2026-10-10)
`PROTOCOL.md` §10 defines the migration order; step 1 is "server accepts and stores
descriptors; shims protocol 1. Nothing else changes." Status and reasoning:
`wiki/pages/device-protocol.md`. Self-check: `python test_descriptor.py` (11 checks).
- [x] **Devices describe themselves.** `descriptor.py` implements §4-§6: version
  negotiation, the capability descriptor, the ten kinds, reserved `_` keys, the two
  §5.5 limits, and value coercion per kind. `capability_store.py` stores it.
- [x] **Two new tables** — `device_capabilities` and `capability_state`. `value` is
  JSON text because a typed value cannot fit `Relay.is_on`, which is a `Boolean`
  (Appendix B named that the most load-bearing assumption in the codebase).
  `Device` gained `proto`/`model`/`fw`/`report_every`. Migration verified against a
  database created before the columns existed.
- [x] **Protocol-1 shim** — a device that sends no `proto` gets a 3-switch
  descriptor synthesised for it, so the rest of the stack sees only v2 shapes.
  **No firmware change was needed**; the ESP32 still speaks protocol 1.
- [x] **Both representations written in parallel** (`Relay.is_on` *and*
  `capability_state`) so the server could move without the app, Maya or the
  firmware changing in the same commit. Step 2 removes the duplication.
- [x] `GET /api/devices/{id}/capabilities` + `POST /api/devices/{id}/capability`
  (§6.2 `set`, validated against the declaration before anything is sent).
- [x] `agent:"deny"` filtering built into `descriptor_payload(for_agent=True)` now,
  not left for step 3 — §5.4 warns it must land with the generic tool, not after.
- [x] Fixed three pre-existing bugs the tests exposed in the command path: a v2 ack
  switched relays off via `ch1` defaults; an error ack matched no branch so the
  caller waited the full 5s timeout; `wait_for_ack` registered its future after the
  send, so a fast device's ack could be dropped.
- [ ] **Step 2** — app renders from the descriptor. Needs per-capability permissions
  (`Permission` keys on `relay_id` today) and capability renaming to replace the
  `Relay.name` override.
- [ ] **Step 3** — Maya's six tools become one `set_capability`, honouring `confirm`.
- [ ] **Step 4** — extract the Arduino library. **Step 5** — peering (§7).
  **Step 6** — device to Maya (§8).
- [ ] `report_every` is stored but unread: §5.8 redefines `status` as "reported
  within its expected interval", which touches `ConnectionManager`, the device list
  endpoint and Maya's house context.
- [ ] `history:true` is stored; no time series is retained, so no sparkline yet.

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

## Hardware (DONE — 2026-07-07)
- [x] Wire GPIO outputs (`OUTPUT_PINS = {2,4,5}`) to real AC relay channels — done physically, all 3 channels working.
- [x] Firmware zombie-WebSocket fix (ping/pong + 3-min watchdog) — committed; flash the ESP32 to apply.

### Branding + Open API skill (DONE — 2026-07-10)
- [x] **Maya logo everywhere** from the hijabi-girl portrait (`software/mobile/assets/brand/`): Android launcher + adaptive icon (`flutter_launcher_icons`), app label "mobile"→**"Maya"**, Flutter login + splash logo, **QS tile** mono drawable (`ic_maya_tile`, tint-friendly silhouette), and web favicon + header logo on all `static/*.html`. (App `applicationId` still `com.example.mobile` — visible name is Maya; rename the package id only if a fresh app identity is wanted.)
- [x] **Open API agent skill** `software/skills/maya-open-api/SKILL.md` (also installed to `~/.claude/skills/`): teaches an agent to drive the Open API v1 (`X-API-Key`, `GET /api/open/v1/devices`, `POST /api/open/v1/devices/{id}/command`) with worked curl examples + NL→(device_id,channel,cmd) reasoning.

## Report artifacts needing manual update (cannot be auto-generated)
These are images/diagrams in the report; redraw to match the current Maya architecture:
- [ ] §5.3 Use Case Diagram — reflect roles (parent/master, child, admin), access-control, multi-house, chat.
- [ ] §5.4 Class Diagram — align with `models.py` (Account, House, AccountHouse, Child, Device, SmartExtension, Relay, Permission, MsgHistory, Heartbeat).
- [ ] §5.5 ERD — same entities as above.
- [ ] §5.6 Flow Chart — BLE provisioning + WebSocket command flow (drop HTTP/MQTT).
- [ ] §5.7 Network Architecture — Flutter app ⇄ FastAPI on Fly.io (WebSocket) ⇄ ESP32; drop Firebase/Supabase/MQTT.
- [ ] §5.8 Sequence Diagrams — update protocols to WebSocket. (§5.8.2 "buy product" can now stay — the mock marketplace flow exists as of 2026-07-07.)
- [ ] Report text still frames GPS / screen-time / homework / marketplace / Open API as future work — now implemented (see sections above); update the relevant chapters before submission.
- [ ] Front matter still has template placeholders: ABSTRACT / ABSTRAK / ACKNOWLEDGEMENT ("Text text text…"), DEDICATION, and "TITLE OF FINAL YEAR PROJECT" / "NAME OF CANDIDATE" on the inner title page. The real Abstract/Abstrak text exists in the old `Muhamad Daniel Hakimi(...)_Report latest.docx`/`.pdf` and can be pasted in.
- [ ] List of Tables / List of Figures / Symbols still use template captions ("Table caption", Diameter/Force, etc.).

## Notes on what WAS updated in the report
- Renamed **NexusLink → Maya** (and NexusAI → Maya) throughout.
- Backend: Firebase/Supabase → **FastAPI + SQLAlchemy + SQLite on Fly.io (Singapore)**, JWT + bcrypt.
- Device link: HTTP/MQTT → **WebSocket**; added **BLE provisioning** + QR onboarding.
- Relay: **4-channel → 3-channel** (Maya sections only; the Alexa case study in §2.3.4 keeps its real 4-channel).
- Iteration 2 recast to the **companion + access-control module** (accounts, per-channel permissions, multi-house, family chat, device PINs).
- AI / GPS / screen-time / homework reframed as **future work**.
