# Decision log

The graph only shows **current** state. Anything reversed, superseded, or
deliberately not done is recorded here — otherwise the reasoning is lost and the
same path gets retried. Sourced from git history and `todos.md`, newest first.

---

## 2026-09-08 — Replaced the single-file `CODE_WIKI.md`

Root `CODE_WIKI.md` was a single 18 KB file that had drifted badly: 4 mobile
screens documented (there are 14), no `ai.py` or `auth.py`, and absolute paths
from a different machine (`/workspace`, `c:/dev/fyp/Maya-Smarthome-AI/...`).
Superseded by this `wiki/`, which separates the regenerable graph from
hand-written narrative so drift is detectable via `git diff` on
`symbol_index.md`. The old file is kept as a pointer rather than deleted.

## 2026-07-10 — App renamed to Maya, but the package id was not

The visible label went `mobile` → **Maya** with launcher/adaptive icons, splash,
QS tile drawable and web favicons. `applicationId` deliberately **stays**
`com.example.mobile` — renaming it creates a fresh app identity (new install, lost
data). Recorded because the mismatch looks like an oversight and is not.

## 2026-07-09 — Wake-word dropped from the voice assistant

Voice shipped with two entry points — a mic FAB on both shells and an Android
**Quick Settings tile** (`MayaTileService`) that opens the overlay even when the
app is closed. A wake word was intended and **dropped**; the QS tile is the
"hands-free" substitute. Filed as future work.

Also decided here: voice replies are **never written to house chat**. The voice
path returns Maya's answer privately with 5-minute in-RAM session memory, while
the chat path posts publicly. This is why `run_maya_agent` was extracted — one
loop, two entry points ([Maya AI agent](maya-ai-agent.md#two-entry-points-one-loop)).

## 2026-07-09 — Screen-time automation is notify-only

When a child crosses `daily_screen_limit_min`, Maya posts, `@`-mentions the
parent and child, and logs — **once per day**, deduped via
`screen_time.limit_notified`. It does **not** cut power. Rationale recorded in
`todos.md`: screen time is phone usage, not a relay, so cutting a relay would be
the wrong lever. Agentic power-off is explicitly deferred to iteration 3.1.

## House switching reloads rather than re-resolving state

`ApiService` keeps `token`, `houseId`, `activeHouse`, `houses` and `activeChannel`
as **static** fields ([mobile app](mobile-app.md#apiservice--the-single-backend-boundary)).
Rather than teach every tab to observe a house change, switching house does a
`pushReplacement` on the shell so all tabs remount and refetch. Recorded because
it looks like a heavy-handed fix and was a deliberate trade: the alternative was
adding a state-management dependency to invalidate per-tab caches. The bug it
fixed was stale data leaking from the previous house.

## 2026-07-07 — Marketplace moved to web-only; in-app store removed

`StoreScreen` was **deleted** from the Flutter app. The catalog now lives at
`/store` (`static/store.html`) with a no-auth public catalog endpoint, and the
mobile "Buy Devices" button opens `{baseUrl}/store` in a browser. Don't
reintroduce an in-app store screen expecting it to be the primary surface.

## 2026-07-08 — Ollama Cloud, not OpenRouter

The LLM provider was **planned as OpenRouter** and shipped as **Ollama Cloud**
(`gpt-oss:20b-cloud` via `https://ollama.com`, `OLLAMA_API_KEY`). Any report or
diagram still saying OpenRouter is stale.

## 2026-06-10 — Deferred device registration: implemented, then reverted

`1f86713` ("deferred registration and deletion cleanup to prevent stray offline
devices") was reverted wholesale by `aa2a77e`, removing ~153 lines across
`provision_screen.dart`, `device_management_tab.dart`, `api_service.dart` and
`main.py`. **The stray-offline-device problem it targeted is therefore still
open** — the fix was rejected, not the problem. Related surviving work:
`92462a7` "reject orphaned devices at identify, stop zombie resurrection".

## Provisioning: reboot into WiFi-only mode, don't test WS over BLE

`116b8fd` replaced an approach that validated the WebSocket URL while still on
BLE with one that commits credentials atomically and reboots into WiFi-only mode.
`bcfc28e` separately **disabled the old WiFi fallback** and reset the BLE
timeout. The surviving recovery path is the counter in the firmware:
`WIFI_RECONNECT_CYCLES_BEFORE_PROVISION = 6` failed cycles → back to BLE
provisioning ([firmware](firmware-esp32.md#connection-lifecycle)).

## Firmware accepts `output_on`/`output_off`, not `on`/`off`

The wire protocol uses `output_on`/`output_off`. Rather than change the firmware,
`_dispatch_command` **normalises** `on`/`off` server-side — which is what makes
Maya's tools *and* the Open API able to switch relays. Changing the firmware
vocabulary now would require re-flashing every deployed device.

## Deployment: Fly.io, Singapore, scale-to-zero, volume-backed SQLite

`76498ae` moved to the Singapore region and put SQLite on a Fly **volume** (the
container filesystem is ephemeral — without this the DB is lost on restart).
`6d818c7` set scale-to-zero to save credits, which means **cold starts** are
expected; a first request after idle may be slow.

## Android-only, by design

iOS is not supported and is a **stated constraint**, not a backlog item: the
child-side features (foreground GPS, Android `UsageStats` screen time via the
`maya/usage` MethodChannel) depend on Android background/permission behaviour
that iOS does not permit.
