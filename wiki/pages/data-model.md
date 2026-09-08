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
| `Device` | `devices` | `device_id`, `status`, `blocked`, `pin` (added by migration, `DEFAULT '0000'`) |
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

Security-relevant columns (`join_pin`, `devices.pin`, `key_hash`) are discussed in
[security notes](security-notes.md).
