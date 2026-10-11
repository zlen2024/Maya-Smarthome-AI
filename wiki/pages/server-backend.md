# Server backend (FastAPI)

`software/server` — 6 Python files, 179 symbols, indexed at tier `scope`.
Deployed to Fly.io (`fly.toml`, `Dockerfile`).

## Files

| File | Lines | Role |
|---|---|---|
| `main.py` | 2,429 | FastAPI app: all routes, both WS handlers, the Maya agent loop, automations, migrations |
| `models.py` | 255 | 14 SQLAlchemy models — see [data model](data-model.md) |
| `ai.py` | 142 | System prompt + tool schemas + the single model call. DB-free by design |
| `auth.py` | 115 | Password hashing, JWT mint/verify, the `Depends` guards, API-key resolution |
| `database.py` | 22 | Engine, `SessionLocal`, `Base`, `get_db` generator |
| `test_screen_limit.py` | 55 | The only server test |

`main.py` holding 63% of server lines is the dominant structural fact here
([known-gaps](known-gaps.md#codebase-gaps)).

## Layering

`database` ← `models` ← `auth` ← `main`, confirmed by `module-deps`
(see [architecture overview](architecture-overview.md#module-dependency-graph-server)).
`ai.py` sits off to the side: it imports only `os`, `json` and `fastapi.HTTPException`,
and deliberately knows nothing about the database — the agent loop in `main.py`
owns identity, permissions and persistence.

## Auth guards — query with `usages`, not `callers`

Four `Depends`-injected symbols carry the whole auth surface. **All four report
zero `callers`** because they are passed by reference into `Depends(...)`
([known-gaps §1](known-gaps.md#1-callers-and-impact-miss-fastapi-depends-injection)):

| Symbol | `usages` | Gates |
|---|---|---|
| `get_current_user` (`auth.py:37`) | 36 | Parent/admin JSON API |
| `get_current_user_or_child` (`auth.py:61`) | 20 | Routes a child may also call |
| `get_api_key_house` (`auth.py:101`) | 4 (3 routes + import) | *(pre-2026-10-11 count: the Open API routes now depend on `api_key_limited`, which resolves the key row and its scope; this symbol is kept for callers that need only the house)* |
| `get_db` (`database.py:17`) | 64 | Every DB-touching route |

`get_api_key_house`'s three route sites are `open_list_devices` (`main.py:646`),
`open_get_device` (`main.py:654`) and `open_send_command` (`main.py:661`) —
a tight, auditable surface.

## Route surface

69 `@app.*` decorators — 66 HTTP routes plus 3 WebSocket. Groups, by first appearance:

- **Pages** (4) — `/`, `/store`, `/integrate`, `/admin`. HTML from `static/`.
  `/admin` is HTTP Basic; the rest are public.
- **Auth** (3) — register, login, me. Both register and login carry abuse limits
  (`ratelimit.py`); the full table is in
  [security-notes](security-notes.md#abuse-limits-in-one-place).
- **Capabilities** (5, added 2026-10-10) — `GET /api/devices/{id}/capabilities`,
  `POST /api/devices/{id}/capability` (the generic `set`),
  `PUT /api/devices/{id}/capabilities/{key}` (rename, §5.11) and
  `GET`/`PUT /api/children/{id}/grants` (§5.10). The v1 `POST /command` and
  `/api/permissions` both stay: the latter is now a translating facade over the
  grant store, not a second store. See [device protocol](device-protocol.md).
- **Houses** (12) — CRUD, join-by-PIN, switch, members, per-member device
  permission, kick, reset-pin, and API-key create/list/revoke.
- **Open API v1** (3) and **v2** (3, 2026-10-11) — `X-API-Key`, `tags=["Open API v1"]` /
  `["Open API v2"]` so they render as their own sections in the generated OpenAPI docs. v1 is
  frozen (three channels); v2 serves descriptors and one generic `set`; both honour the key's
  scope (`open_api.py`). Paired with the `software/skills/maya-open-api` agent skill.
- **Chat & mentions** (6) — history, mentionables, unseen, mark-seen, clear.
- **Children / homework / screen time** (14) — including `POST /api/children/location`
  and `POST /api/screen-time/report`, the two endpoints child devices push to.
- **Devices & relays** (10) — register, list, detail, block, command, relay rename.
- **Maya** (1) — `POST /api/maya/voice`.
- **Store** (4) — catalog, public catalog, orders.
- **Permissions** (4), **messages** (2), **activity** (1).
- **Admin** (4 JSON + `/db`) — gated on `current_user.role != AccountRole.admin`,
  a *different* gate from `/admin`'s Basic auth ([security notes §2](security-notes.md#2-admin-fell-back-to-password-admin--fixed-2026-10-10)).

## WebSockets

Two handlers with different auth models:

- **`/ws/mobile`** (`main.py:2289`) — client sends a JSON frame with `token`
  within 10 s; the server decodes the JWT inline (`main.py:2303`). A `sub` of
  `child_<id>` marks the connection as a child and pins `house_id` from the child
  record; otherwise it resolves an account. Also accepts an optional
  `house_id` override.
- **`/ws` and `/`** (`main.py:2422`, `main.py:2427`) — both delegate to
  `_handle_websocket`; this is the device path, identified by an `id` in the
  message and validated by device PIN. Two routes exist so firmware pointed at
  either URL form connects.

`ConnectionManager` is instantiated exactly once — `manager` at `main.py:229`,
the only `usages` hit — and is the fan-out point (`broadcast_to_house`).

## Migrations

`run_migrations()` (`main.py:34`) runs at import time after
`Base.metadata.create_all`. It uses SQLAlchemy's `inspect()` to test for a column
and issues raw `ALTER TABLE ... ADD COLUMN` when missing, then backfills (e.g.
generating `join_pin` for houses that predate it, `main.py:103`). Additive only —
no tool, no version table, no rollback.
