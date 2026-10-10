# Data model (SQLite)

`software/server/models.py` — 14 SQLAlchemy models on a declarative `Base`.

## Engine

`software/server/database.py` is 22 lines and does three things: build the
engine, expose `SessionLocal`, and yield `get_db`.

```python
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./iot_data.db")
connect_args = {"check_same_thread": False} if ...startswith("sqlite") else {}
```

`check_same_thread: False` is required because FastAPI hands sessions across
threads — including `asyncio.to_thread` in the Maya loop. `DATABASE_URL` allows
pointing at another backend, but the schema is hand-migrated for SQLite
(see [server backend](server-backend.md#migrations)).

## Tables

| Model | Table | Notes |
|---|---|---|
| `Account` | `accounts` | Bcrypt password hash; `role` is `AccountRole` |
| `AccountRole` | *(enum)* | `str`-enum; `admin` gates `/db` and `/api/admin/*` |
| `House` | `houses` | `join_pin` — plaintext 6 digits |
| `AccountHouse` | `account_houses` | Join table: an account can belong to several houses; carries `is_master` and per-member device permission |
| `Child` | `children` | `last_lat`/`last_lng`, screen-time limit |
| `Device` | `devices` | `device_id`, `status`, `blocked`, `pin` (added by migration with `DEFAULT '0000'` — the column default survives, but `register_device` has refused that value since 2026-10-10) |
| `SmartExtension` | `smart_extensions` | The 3-channel extension type |
| `Relay` | `relays` | Per-channel state and name |
| `Permission` | `permissions` | Child → device/channel grants |
| `MsgHistory` | `msg_history` | House chat; `sender_type` `parent`/`child`/`ai`, Maya writes `sender_id = 0` |
| `Homework` | `homework` | Title, due date, completion |
| `ScreenTime` | `screen_time` | Per child per date |
| `Order` | `orders` | Store purchases |
| `ApiKey` | `api_keys` | `prefix` shown in UI + `key_hash` (SHA-256); `revoked` flag |
| `ActivityLog` | `activity_log` | Written by `log_activity`, read by `read_activity_log` |
| `Mention` | `mentions` | Unread `@`-mention badge state |
| `Heartbeat` | `heartbeats` | Device uptime, IP, `ch1`/`ch2`/`ch3` snapshot |
| `PeerGrant` | `peer_grants` | One-way device-to-device permission (§7.1): sender, receiver, the shared key, the scope, expiry, `revoked_at`. Revoked rather than deleted so the audit outlives the pairing. The key is never returned by an API. |
| `PeerLogEntry` | `peer_log` | One audit line a device reported about a grant (§7.3). Capped at 5,000 per house. |
| `PeerLogCounter` | `peer_log_counters` | Per (grant, reporter, direction, epoch): highest `seq` claimed and frames logged. `grant_id = 0` is the sentinel row for a reporter's total `dropped`. |
| `Device.can_invoke_agent` | column | May this device ask Maya to act (§8)? Default false; only a person who can manage devices sets it; re-read before every action a request takes. |
| `Device.mac` | column | WiFi station MAC from identify; null means the device cannot be paired. |

## Shape notes

- **Multi-house is real, not vestigial.** `AccountHouse` means every query must be
  scoped by `house_id`; the Open API's `get_api_key_house` returns a `House`
  precisely so the three v1 routes are scoped by construction.
- **`Heartbeat` denormalises channel state** (`ch1`–`ch3`) alongside `Relay`. The
  heartbeat is the time series; `Relay` is current state.
- **Maya's `sender_id = 0`** is a sentinel (`MAYA_SENDER_ID`, `main.py:1393`), not
  a real account row — joins from `msg_history` to `accounts` must tolerate it.
- **`ScreenTime` is the automation trigger** — see
  [Maya AI agent](maya-ai-agent.md#automation-the-screen-limit-alert).

Protocol 2 added four tables (2026-10-10) and removed one:

| Table | Holds |
|---|---|
| `device_capabilities` | One row per capability a device declared about itself |
| `capability_state` | One row per capability's current value, `value` as JSON text — a typed value cannot fit `Relay.is_on`, which is a `Boolean` |
| `capability_grants` | What a child may **write**, per `(child, device, key)` — replaces `permissions`, which keyed on `relay_id` |
| `capability_labels` | A name a house member gave a capability; kept out of `device_capabilities` because that table is rewritten on every identify |

`permissions` was migrated onto `capability_grants` and **dropped**; `Relay.name`
values moved into `capability_labels`. `Relay` itself remains as the protocol-1
shim's backing store, created when a v1 device identifies rather than when it is
claimed (§4.1). `Device` also gained `proto`, `model`, `fw` and `report_every`.
See [device protocol](device-protocol.md).

Security-relevant columns (`join_pin`, `devices.pin`, `key_hash`) are discussed in
[security notes](security-notes.md).
