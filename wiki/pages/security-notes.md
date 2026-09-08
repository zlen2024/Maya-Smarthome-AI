# Security notes

Security-relevant facts surfaced while indexing the codebase, kept here rather
than buried in module pages. Each was read from source and is cited by
`path:line`. This is a record of *what the code does*, not a pentest.

This is a final-year-project demo deployed to Fly.io (`fly.toml`), so several
items below are reasonable demo defaults — the risk is that a demo default
silently becomes the deployed one, because in every case here **the insecure
value is what you get when an env var is simply absent**.

## 1. JWT signing key falls back to a hardcoded literal

```python
# software/server/auth.py:12
SECRET_KEY = os.environ.get("SECRET_KEY", "maya-smarthome-secret-key-change-in-production")
```

Signs every access token (`create_access_token`, `auth.py:34`) and is the
verification key for the HTTP API (`auth.py:43`, `auth.py:67`) **and** the mobile
WebSocket handshake (`software/server/main.py:2303`). If `SECRET_KEY` is unset in
the deployment environment, anyone who has read this repo can mint a valid token
for any account, including `sub` values of the form `child_<id>`.
Tokens last 24h (`ACCESS_TOKEN_EXPIRE_MINUTES = 1440`, `auth.py:14`).

**Check:** confirm `SECRET_KEY` is set as a Fly secret. There is no startup
warning if it is missing.

## 2. `/admin` falls back to password `admin`

```python
# software/server/main.py:238-241
def get_default_admin_hash():
    global DEFAULT_ADMIN_PASSWORD_HASH
    if DEFAULT_ADMIN_PASSWORD_HASH is None:
        DEFAULT_ADMIN_PASSWORD_HASH = hash_password("admin")
    return DEFAULT_ADMIN_PASSWORD_HASH
```

`admin_page` (`main.py:262`) uses `ADMIN_PASSWORD_HASH` from the environment and
falls back to the above when unset, with HTTP Basic and username `admin`.

Note the separation: the `/admin` **page** is Basic-auth'd this way, while the
`/api/admin/*` JSON endpoints and `/db` are gated instead by
`current_user.role != AccountRole.admin` on a JWT (`main.py:2066`). They are
independent gates — hardening one does not harden the other.

## 3. House join PINs and device PINs are stored in plaintext

- `join_pin` is a 6-digit random string (`_generate_pin`, `main.py:377`) stored
  as a plain column and compared directly: `house.join_pin != pin` (`main.py:436`).
  It is also returned in API responses (`main.py:397`, `main.py:422`) — guarded
  by `is_master` in the members listing.
- Migration `main.py:81` adds `devices.pin` with **`DEFAULT '0000'`**, so
  pre-existing devices get a known PIN. The firmware also validates commands
  against a PIN it stores in ESP32 Preferences.

Account passwords, by contrast, *are* properly hashed — bcrypt via passlib
(`auth.py:16`).

## 4. Open API keys: SHA-256, unsalted, no rate limiting

```python
# software/server/auth.py:97-98
def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()
```

`get_api_key_house` (`auth.py:101`) resolves an `X-API-Key` header to a house and
gates the three `/api/open/v1/*` endpoints (`main.py:644`, `:652`, `:659`) —
confirmed by `code2graph usages get_api_key_house` (3 route sites + the import).
A single unsalted SHA-256 is **acceptable here**: keys are minted as
`"maya_" + secrets.token_urlsafe(32)` (`main.py:583`) — 256 bits of CSPRNG
entropy, so there is nothing for a salt to defend against (no rainbow table, no
brute force). Only the hash is stored and the plaintext is returned exactly once
(`main.py:594`), which is the right shape. Revocation is a `revoked` flag checked
in the same query. Remaining weakness is operational, not cryptographic: **no
rate limiting** and no per-key scope narrower than the whole house — a key grants
full device read + command rights over every device in it.

## 5. Maya's tool permissions are enforced server-side — correctly

Worth recording as a **positive** finding, since it is the design decision most
likely to be undone by accident. `ai.py`'s docstring states it plainly, and the
system prompt tells the model "Permission and privacy are enforced by the tools,
not by you". The enforcement really does live in `_execute_maya_tool`
(`main.py:1468`) — device-blocked checks, `_child_command_denial` for child
senders, and parent-only guards — **not** in the prompt.

Keep it that way: the model's tool schemas (`ai.py:32`) are described in the code
as guidance for the model only. Since tools are string-dispatched with no graph
edge (see [known-gaps §4](known-gaps.md#4-mayas-ai-tools-are-string-dispatched--no-edges-at-all)),
a permission check dropped from one branch would not show up in any query.
