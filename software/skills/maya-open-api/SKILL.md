---
name: maya-open-api
description: >-
  Control a Maya Smart Home house through its public Open API v1 — list devices
  and relay channels, read their on/off state, and switch them. Authenticates
  with a house-scoped X-API-Key. Use whenever the user asks to turn something
  on/off, check whether a device/light/TV is on, or automate their Maya home
  (e.g. "turn on the living room TV", "is the fan on?", "switch everything off").
---

# Maya Smart Home — Open API v1

Maya is a smart-home system where a physical **device** (an ESP32 smart
extension) exposes up to **3 relay channels** (channel `1`–`3`), each wired to
an appliance (TV, lamp, fan…). This skill drives the public **Open API v1** so
an agent can read state and switch channels on a user's behalf.

## Setup (once)

- **Base URL:** `https://maya-smarthome-ai.fly.dev`
- **Key:** a house-scoped API key the house **master** creates in the Maya app
  (Settings → API Keys) or web portal (`/integrate`). It looks like a long
  random string, shown once at creation. Ask the user for it and store it as
  `MAYA_API_KEY`. One key = one house; every call acts on that house only.

Auth is a header on **every** request:

```
X-API-Key: <MAYA_API_KEY>
```

There is no OAuth, no per-command PIN, no user login. The key is the credential.

## The one rule: list before you command

Users speak in names ("the television", "kitchen light"); the API acts on
`device_id` + `channel`. **Always call `GET /devices` first** to resolve names
to the exact `device_id` and channel number, and to read current state. Never
guess a `device_id` or channel.

## Endpoints

### 1. List devices (start here)

```bash
curl -s https://maya-smarthome-ai.fly.dev/api/open/v1/devices \
  -H "X-API-Key: $MAYA_API_KEY"
```

Response:

```json
{
  "devices": [
    {
      "device_id": "esp32-d82c34c",
      "name": "Living Room Extension",
      "online": true,
      "blocked": false,
      "channels": [
        { "channel": 1, "name": "Television", "is_on": false },
        { "channel": 2, "name": "Lamp",       "is_on": true  },
        { "channel": 3, "name": "Channel 3",   "is_on": false }
      ]
    }
  ]
}
```

- `online: false` → the device is unplugged/offline; commands will not take
  effect (see errors). Tell the user instead of silently failing.
- `blocked: true` → the device is disabled; commands return `"blocked"`.
- `is_on` is the source of truth for current state — use it to answer "is X on?"
  and to avoid redundant commands.

### 2. Get one device

```bash
curl -s https://maya-smarthome-ai.fly.dev/api/open/v1/devices/esp32-d82c34c \
  -H "X-API-Key: $MAYA_API_KEY"
```

Returns the same single-device object as above.

### 3. Send a command

```bash
curl -s -X POST \
  https://maya-smarthome-ai.fly.dev/api/open/v1/devices/esp32-d82c34c/command \
  -H "X-API-Key: $MAYA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"cmd": "on", "channel": 1}'
```

Body:

| field     | values                              | notes                                  |
|-----------|-------------------------------------|----------------------------------------|
| `cmd`     | `on`, `off`, `all_on`, `all_off`    | required                               |
| `channel` | `1`–`3`                             | required for `on`/`off`; ignored for `all_*` |

Success response echoes the device's new channel states:

```json
{ "status": "ok", "device_id": "esp32-d82c34c", "ch1": "on", "ch2": "on", "ch3": "off" }
```

## How to reason: natural language → API call

Turn a request into calls with this loop:

1. **List** (`GET /devices`). Build a map of `channel.name` (and `device.name`)
   → `(device_id, channel)`.
2. **Resolve the target** by fuzzy-matching the user's words against channel
   names, then device names. "the TV" → the channel named `"Television"`.
   - No match → ask the user which device/channel they mean; show the options.
   - Multiple matches → ask, or if the user said "all", use `all_on`/`all_off`.
3. **Decide the command:**
   - "turn on / switch on / start" → `on`; "turn off / stop" → `off`.
   - "turn everything/all off", "shut it all down" → `all_off` (per device;
     repeat across devices if there are several).
   - A state query ("is the fan on?") needs **no command** — answer from `is_on`.
4. **Check before acting:** if `is_on` already matches the request, say so
   instead of resending. If `online` is false, tell the user it's offline.
5. **POST the command**, then confirm using the returned `ch1/ch2/ch3`.

### Worked examples

**"Turn on the living room TV."**
1. `GET /devices` → channel `1` named `"Television"` on `esp32-d82c34c`, `is_on:false`, `online:true`.
2. `POST /devices/esp32-d82c34c/command` `{"cmd":"on","channel":1}` → `{"status":"ok","ch1":"on",...}`.
3. Reply: "Done — the Television is now on."

**"Is the lamp on?"**
1. `GET /devices` → channel `2` `"Lamp"` `is_on:true`.
2. No command. Reply: "Yes, the Lamp is on."

**"Switch everything off."**
1. `GET /devices`.
2. For each device: `POST /devices/<id>/command` `{"cmd":"all_off"}`.
3. Reply: "All channels are off across your 1 device."

**"Turn on the heater."** (no matching channel)
1. `GET /devices` → no channel named like "heater".
2. Reply: "I don't see a channel named 'heater'. Your channels are: Television,
   Lamp, Channel 3. Which one is the heater?" (Suggest renaming it in the app.)

## Command status values

The command response `status` tells you what happened:

| status          | meaning                                            | what to tell the user                    |
|-----------------|----------------------------------------------------|------------------------------------------|
| `ok`            | delivered; `ch1/ch2/ch3` are the new states        | confirm the change                       |
| `not_connected` | device is offline                                  | "That device is offline right now."      |
| `timeout`       | device didn't acknowledge in time                  | "The device didn't respond — try again." |
| `blocked`       | device is blocked in the app                        | "That device is blocked."                |

## HTTP errors

- `401` / `403` — missing or invalid `X-API-Key`. Ask the user to re-check the
  key (it's shown only once at creation; they may need to make a new one).
- `404` — `device_id` not in this key's house. Re-run `GET /devices`; don't
  reuse a `device_id` from another house/key.
- `400` — bad `cmd` (must be `on`/`off`/`all_on`/`all_off`).

## Safety

- Switching real appliances is a physical action. For anything ambiguous or
  bulk ("turn everything off"), confirm the target with the user before POSTing.
- One key controls one whole house — treat it like a password; never print it
  back in full or send it anywhere except the `X-API-Key` header.
- Channels named `"Channel N"` are unconfigured — tell the user to name them in
  the Maya app so matching works reliably.
```
