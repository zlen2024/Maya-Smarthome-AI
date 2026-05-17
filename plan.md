# Maya Smart Home — Mobile → Server → ESP32 Command Flow

## Goal

Make the full round-trip work:  
**Mobile app sends HTTP request → Server routes command via WebSocket → ESP32 executes → Ack flows back → Mobile gets the real result with all 3 channel states.**

---

## Architecture Overview

```
┌──────────┐      HTTP REST         ┌──────────────┐      WebSocket       ┌──────────┐
│  Mobile  │ ───────────────────►   │    Server    │ ──────────────────►  │  ESP32   │
│   App    │ ◄───────────────────   │  (FastAPI)   │ ◄──────────────────  │ 3-ch out │
└──────────┘   JSON response        └──────────────┘   JSON ack           └──────────┘
                (with ch1/2/3)           │
                                         │ SQLite DB
                                         ▼
                                   ┌──────────────┐
                                   │  DeviceState  │
                                   │  ch1/ch2/ch3  │
                                   │  Heartbeats   │
                                   └──────────────┘
```

### Mobile → ESP32 flow (what we're building):
1. Mobile calls `POST /api/devices/{device_id}/command` with `{cmd, channel, pin}`
2. Server forwards command to ESP32 via its live WebSocket connection
3. Server **waits** (up to 5s) for ESP32 to respond with an ack
4. Server returns the ack payload to mobile (with `ch1/ch2/ch3` states)
5. If ESP32 doesn't respond in 5s → returns `{"status": "timeout"}`

### Mobile polling (status check):
1. Mobile calls `GET /api/devices/{device_id}/status`
2. Server returns current `ch1/ch2/ch3` states + online/offline + IP + uptime

---

## Current State

### What works ✅
- ESP32 connects to server via WebSocket and identifies itself
- ESP32 handles multi-channel commands (`output_on/off/toggle` with `channel: 1|2|3`)
- ESP32 sends ack with all channel states (`ch1/ch2/ch3`)
- ESP32 sends heartbeats every 30s with channel states
- Admin dashboard at `/admin` shows device + sends commands
- REST endpoint `POST /api/devices/{id}/command` exists but is incomplete

### What's broken ❌

| # | Gap | File | Impact |
|---|-----|------|--------|
| 1 | DeviceState model only has `led_status` | `models.py` | DB can't store 3-channel state |
| 2 | REST endpoint doesn't forward `channel` | `main.py:112-130` | Always defaults to ch1 |
| 3 | REST endpoint is fire-and-forget | `main.py:112-130` | Mobile never gets the real result |
| 4 | Ack handler doesn't update ch1/ch2/ch3 | `main.py:249-267` | DB stays stale |
| 5 | Heartbeat handler ignores ch states | `main.py:199-209` | Live info missing channel data |
| 6 | Admin dashboard is single-channel | `admin.html` | Only 1 LED toggle shown |
| 7 | No proper mobile API documentation | — | Mobile dev has no reference |

---

## Tasks

### Task 1: Update DeviceState model
**File:** `software/server/models.py`

- Replace `led_status = Column(String)` with:
  - `ch1 = Column(String, default="off")`
  - `ch2 = Column(String, default="off")`
  - `ch3 = Column(String, default="off")`
- Delete old `iot_data.db` so tables get recreated (dev-only, no migrations needed)

**Verify:** Server starts without error, `/db` endpoint shows `device_states` with ch1/ch2/ch3 fields.

---

### Task 2: Add ack-waiting mechanism to ConnectionManager
**File:** `software/server/main.py` (ConnectionManager class)

- Add `pending_commands: dict[str, asyncio.Future]` to ConnectionManager
- Add method `wait_for_ack(device_id, timeout=5.0) -> dict | None`
  - Creates an `asyncio.Future`, stores it keyed by `device_id`
  - Awaits with timeout, returns ack data or None
- Add method `resolve_ack(device_id, data: dict)`
  - Looks up pending future, sets result if exists

**Verify:** `manager.pending_commands` exists, methods callable.

---

### Task 3: Fix REST command endpoint
**File:** `software/server/main.py` (`send_device_command`)

- Forward ALL fields from payload: `cmd`, `channel`, `pin`
- After sending, call `manager.wait_for_ack(device_id, timeout=5.0)`
- If ack received → return full ack payload to mobile
- If timeout → return `{"status": "timeout", "device_id": ...}`
- If device not connected → return `{"status": "not_connected"}` (HTTP 200, not 404)

**Verify:**
```bash
curl -X POST http://localhost:8000/api/devices/esp32-9f83b1c1/command \
  -H "Content-Type: application/json" \
  -d '{"cmd": "output_on", "channel": 2}'
# Returns: {"id":"esp32-9f83b1c1","status":"ok","ch1":"off","ch2":"on","ch3":"off"}
```

---

### Task 4: Fix ack handler in WebSocket
**File:** `software/server/main.py` (`_handle_websocket`, the `status == "ok"` branch)

- Parse `ch1`, `ch2`, `ch3` from ack JSON
- Upsert into DeviceState table (update if exists, create if not)
- Update `manager.device_info` with channel states
- Call `manager.resolve_ack(device_id, json_data)` to unblock waiting REST endpoint

**Verify:** After sending a command, server log shows `Updated ch1=on ch2=off ch3=off` and DB reflects it.

---

### Task 5: Update heartbeat handler
**File:** `software/server/main.py` (`_handle_websocket`, the `type == "heartbeat"` branch)

- Extract `ch1`, `ch2`, `ch3` from heartbeat JSON
- Update `manager.device_info` with channel states
- Upsert DeviceState in DB with current channel values

**Verify:** After 30s heartbeat, `GET /api/devices` returns correct channel states.

---

### Task 6: Update device status endpoint
**File:** `software/server/main.py`

- Rewrite `GET /api/devices/{device_id}/status` to return:
  ```json
  {
    "device_id": "esp32-9f83b1c1",
    "online": true,
    "ip": "192.168.0.8",
    "uptime_ms": 120000,
    "ch1": "off",
    "ch2": "on",
    "ch3": "off",
    "last_heartbeat": "2026-05-14T03:21:26"
  }
  ```
- Pull from both `manager.device_info` (live) and `DeviceState` DB (persisted)
- `online` = `device_id in manager.active_connections`

**Verify:**
```bash
curl http://localhost:8000/api/devices/esp32-9f83b1c1/status
# Returns all fields above
```

---

### Task 7: Update `/api/devices` list endpoint
**File:** `software/server/main.py`

- Return `ch1/ch2/ch3` instead of `led_status` for each device
- Pull channel states from both `manager.device_info` and DB

**Verify:** `GET /api/devices` returns devices with `ch1`, `ch2`, `ch3` fields.

---

### Task 8: Update admin dashboard
**File:** `software/server/static/admin.html`

- Show 3 channels per device card (ch1/ch2/ch3) with individual on/off indicators
- Add per-channel toggle buttons: `CH1 On/Off`, `CH2 On/Off`, `CH3 On/Off`
- Add `All On` / `All Off` buttons
- Update command payloads to include `channel` field
- Keep existing device metadata (IP, uptime, last seen)

**Verify:** Open `/admin`, see 3 channels per device, toggle each independently.

---

### Task 9: Verification & Cleanup

- [ ] Test full flow: `curl POST command` → ESP32 reacts → ack returned to curl
- [ ] Test timeout: disconnect ESP32, send command → get `{"status": "timeout"}`
- [ ] Test not_connected: send to fake device → get `{"status": "not_connected"}`
- [ ] Test admin dashboard: toggle each channel, verify state updates
- [ ] Test heartbeat: wait 30s, verify `/api/devices` shows correct states
- [ ] Delete old `iot_data.db` before final test (clean slate)

---

## Done When
- [ ] Mobile can `POST /api/devices/{id}/command` with `{cmd, channel}` and get back real ack with ch1/ch2/ch3
- [ ] `GET /api/devices/{id}/status` returns online + all 3 channel states
- [ ] Admin dashboard shows 3 channels per device with independent controls
- [ ] Heartbeats keep DB in sync with actual hardware state

## Files Modified
| File | Changes |
|------|---------|
| `software/server/models.py` | ch1/ch2/ch3 columns |
| `software/server/main.py` | Ack waiting, command forwarding, ack handler, heartbeat handler, status endpoints |
| `software/server/static/admin.html` | 3-channel UI |
| `software/server/iot_data.db` | Delete & recreate |
