import os
import json
import random
import string
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from fastapi import (FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException,
                     Request, status as http_status)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session
from database import engine, Base, get_db, SessionLocal
from models import (
    Account, AccountRole, House, Child, Device, SmartExtension,
    Relay, Permission, MsgHistory, Heartbeat, AccountHouse, Homework, ScreenTime, Order
)
from models import ApiKey, ActivityLog, Mention
from models import DeviceCapability, CapabilityState
from auth import (
    hash_password, verify_password, create_access_token, get_current_user,
    get_current_user_or_child, get_api_key_house, hash_api_key,
    SECRET_KEY, ALGORITHM
)
import secrets

import ai
from ratelimit import RateLimit, FailureLock, client_ip
import capability_store
from descriptor import (PROTO_MAX, DescriptorError, coerce_value, parse_identify,
                        v1_state)
from validators import normalize_device_pin, normalize_child_pin

import mimetypes
mimetypes.add_type('application/vnd.android.package-archive', '.apk')

Base.metadata.create_all(bind=engine)


def run_migrations():
    """Run SQLite schema migrations for backward compatibility."""
    db = SessionLocal()
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(engine)

        # Add join_pin to houses if missing
        house_cols = [c['name'] for c in inspector.get_columns('houses')]
        if 'join_pin' not in house_cols:
            db.execute(text('ALTER TABLE houses ADD COLUMN join_pin TEXT'))
            db.commit()

        # Add sender_name to msg_history if missing
        msg_cols = [c['name'] for c in inspector.get_columns('msg_history')]
        if 'sender_name' not in msg_cols:
            db.execute(text("ALTER TABLE msg_history ADD COLUMN sender_name TEXT DEFAULT ''"))
            db.commit()

        # Create account_houses table if not exists
        if 'account_houses' not in inspector.get_table_names():
            AccountHouse.__table__.create(bind=engine)

        # Add can_manage_devices to account_houses if missing.
        # Must run BEFORE the populate query below — the ORM selects this
        # column, so querying an old table without it aborts the migration.
        ah_cols = [c['name'] for c in inspector.get_columns('account_houses')]
        if 'can_manage_devices' not in ah_cols:
            db.execute(text("ALTER TABLE account_houses ADD COLUMN can_manage_devices BOOLEAN DEFAULT 0"))
            db.commit()

        # Populate account_houses from existing accounts
        existing = db.query(AccountHouse).first()
        if not existing:
            accounts = db.query(Account).filter(Account.house_id.isnot(None)).all()
            for acc in accounts:
                assoc = AccountHouse(
                    acc_id=acc.acc_id,
                    house_id=acc.house_id,
                    is_master=acc.is_master,
                )
                db.add(assoc)
            db.commit()

        # Add pin to devices if missing
        device_cols = [c['name'] for c in inspector.get_columns('devices')]
        if 'pin' not in device_cols:
            db.execute(text("ALTER TABLE devices ADD COLUMN pin TEXT DEFAULT '0000'"))
            db.commit()

        # Protocol 2 (PROTOCOL.md §5): what the device said about itself. Existing
        # rows get proto=1, which is exactly right — they predate the protocol
        # and are served by the shim.
        for col, ddl in (
            ('proto', 'ALTER TABLE devices ADD COLUMN proto INTEGER DEFAULT 1'),
            ('model', 'ALTER TABLE devices ADD COLUMN model TEXT'),
            ('fw', 'ALTER TABLE devices ADD COLUMN fw TEXT'),
            ('report_every', 'ALTER TABLE devices ADD COLUMN report_every INTEGER'),
        ):
            if col not in device_cols:
                db.execute(text(ddl))
                db.commit()

        # The capability tables themselves. create_all() at import already makes
        # them on a fresh database; this covers an existing one.
        for table in ('device_capabilities', 'capability_state'):
            if table not in inspector.get_table_names():
                {'device_capabilities': DeviceCapability,
                 'capability_state': CapabilityState}[table].__table__.create(bind=engine)

        # Add location/screen-limit columns to children if missing
        child_cols = [c['name'] for c in inspector.get_columns('children')]
        for col, ddl in (
            ('last_lat', 'ALTER TABLE children ADD COLUMN last_lat FLOAT'),
            ('last_lng', 'ALTER TABLE children ADD COLUMN last_lng FLOAT'),
            ('last_seen_at', 'ALTER TABLE children ADD COLUMN last_seen_at DATETIME'),
            ('daily_screen_limit_min', 'ALTER TABLE children ADD COLUMN daily_screen_limit_min INTEGER'),
        ):
            if col not in child_cols:
                db.execute(text(ddl))
                db.commit()

        # Add limit_notified to screen_time if missing
        st_cols = [c['name'] for c in inspector.get_columns('screen_time')]
        if 'limit_notified' not in st_cols:
            db.execute(text("ALTER TABLE screen_time ADD COLUMN limit_notified BOOLEAN DEFAULT 0"))
            db.commit()

        # Generate PINs for houses missing one
        houses = db.query(House).filter(House.join_pin.is_(None)).all()
        for h in houses:
            h.join_pin = ''.join(random.choices(string.digits, k=6))
        db.commit()
    except Exception as e:
        print(f'Migration warning: {e}')
        db.rollback()
    finally:
        db.close()


def warn_about_legacy_device_pins():
    """Name the devices that still carry the old default PIN.

    The identify check used to be skipped whenever a device's stored PIN was
    "0000", so rows left at the migration default (`ALTER TABLE devices ADD
    COLUMN pin TEXT DEFAULT '0000'`) connected without proving anything. The
    check now runs for every stored PIN -- but a PIN of "0000" is a value anyone
    can read in this repo, so these rows are verified against a secret that is
    not secret. Only the owner re-provisioning the board fixes that. Nothing is
    rewritten here, because changing a PIN the firmware still holds would lock a
    working device out; the list is printed so it is actionable instead of
    invisible.
    """
    db = SessionLocal()
    try:
        stale = db.query(Device).filter(Device.pin.in_(("0000", ""))).all()
        if stale:
            ids = ", ".join(d.device_id for d in stale)
            print(f"WARNING: {len(stale)} device(s) still carry the old default PIN, "
                  f"which is public knowledge, so identify proves nothing for them: "
                  f"{ids}. Re-provision each one from the app (set a New PIN).")
    except Exception as e:
        print(f"Legacy PIN check skipped: {e}")
    finally:
        db.close()


run_migrations()
warn_about_legacy_device_pins()

app = FastAPI(
    title="Maya Smart Home API",
    version="1.0.0",
    description=(
        "REST + WebSocket backend for the Maya smart-home ecosystem.\n\n"
        "Third-party integrations should use the **Open API v1** endpoints, "
        "authenticated with a house-scoped key in the `X-API-Key` header. "
        "Keys are issued by the house master in the Maya app (Settings → API Keys)."
    ),
    openapi_tags=[
        {"name": "Open API v1",
         "description": "Stable, key-authenticated endpoints for third-party integrations. "
                        "All data is scoped to the house the API key belongs to."},
    ],
)

# ─── Abuse limits ─────────────────────────────────────────────
# Guessable secrets get a FailureLock; costly endpoints get a RateLimit. The
# numbers are chosen to be invisible to a household and fatal to a script: a
# 6-digit house PIN at 5 tries/hour needs ~23 years of uninterrupted guessing.
JOIN_LOCK      = FailureLock(5,  3600, 3600, "house join")        # per account+house
JOIN_WALK_LOCK = FailureLock(10, 3600, 3600, "house join")        # per account, any house
LOGIN_LOCK     = FailureLock(8,  900,  900,  "login")             # per email
CHILD_PIN_LOCK = FailureLock(5,  900,  900,  "child sign-in")     # per child
ADMIN_LOCK     = FailureLock(5,  900,  1800, "admin sign-in")     # per IP
LOGIN_RATE     = RateLimit(30, 300, "login")                      # per IP
REGISTER_RATE  = RateLimit(5, 3600, "account registration")       # per IP
VOICE_RATE     = RateLimit(20, 60, "voice command")               # per caller
VOICE_DAY_RATE = RateLimit(300, 86400, "voice command (daily)")   # per caller
OPEN_API_RATE  = RateLimit(60, 60, "Open API")                    # per key


async def api_key_house_limited(request: Request,
                                house: House = Depends(get_api_key_house)) -> House:
    """`get_api_key_house` plus a per-key rate limit. Open API keys are long-lived
    and live in other people's scripts, so a loop there is the likeliest source of
    load on this server."""
    OPEN_API_RATE.hit(hash_api_key(request.headers.get("x-api-key", ""))[:16])
    return house


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.unidentified_connections: list[WebSocket] = []
        self.device_info: dict[str, dict] = {}
        self.pending_commands: dict[str, asyncio.Future] = {}
        # Mobile client tracking (house-scoped)
        self.mobile_clients: dict[WebSocket, dict] = {}           # ws → {"acc_id", "house_id"}
        self.house_mobile_clients: dict[int, set[WebSocket]] = {} # house_id → set of ws

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.unidentified_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.unidentified_connections:
            self.unidentified_connections.remove(websocket)
        for client_id, ws in list(self.active_connections.items()):
            if ws == websocket:
                del self.active_connections[client_id]
                print(f"Client {client_id} disconnected")
                break

    async def send_personal_message(self, message: str, client_id: str):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_text(message)
            return True
        return False

    def identify(self, websocket: WebSocket, client_id: str):
        if websocket in self.unidentified_connections:
            self.unidentified_connections.remove(websocket)
        self.active_connections[client_id] = websocket
        print(f"Client {client_id} identified and registered")

    def update_device_info(self, device_id: str, **kwargs):
        if device_id not in self.device_info:
            self.device_info[device_id] = {}
        self.device_info[device_id].update(kwargs)

    def arm_ack(self, device_id: str) -> asyncio.Future:
        """Register the ack slot BEFORE the command is sent.

        A device on the same LAN can ack inside a millisecond — before the task
        that sent the command is scheduled again. A future registered after the
        send would miss that ack entirely, and the caller would then sit through
        the whole 5-second timeout waiting for an answer that had already
        arrived. Arming first removes the race rather than narrowing it.
        """
        future = asyncio.get_running_loop().create_future()
        self.pending_commands[device_id] = future
        return future

    def disarm_ack(self, device_id: str) -> None:
        self.pending_commands.pop(device_id, None)

    async def wait_for_ack(self, device_id: str, timeout: float = 5.0,
                           future: asyncio.Future | None = None) -> dict | None:
        if future is None:
            # No slot was armed: keep the old behaviour for any caller that still
            # sends first and asks afterwards.
            future = self.pending_commands.get(device_id) or self.arm_ack(device_id)
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            return None
        finally:
            self.pending_commands.pop(device_id, None)

    def resolve_ack(self, device_id: str, data: dict):
        future = self.pending_commands.get(device_id)
        if future and not future.done():
            future.set_result(data)

    # ── Mobile Client Management ──────────────────────────────

    async def connect_mobile(self, websocket: WebSocket, acc_id: int, house_id: int):
        """Register an authenticated mobile client, grouped by house."""
        self.mobile_clients[websocket] = {"acc_id": acc_id, "house_id": house_id}
        if house_id not in self.house_mobile_clients:
            self.house_mobile_clients[house_id] = set()
        self.house_mobile_clients[house_id].add(websocket)
        print(f"Mobile client acc_id={acc_id} connected (house {house_id})")

    def disconnect_mobile(self, websocket: WebSocket):
        """Remove a mobile client from tracking."""
        info = self.mobile_clients.pop(websocket, None)
        if info:
            house_id = info["house_id"]
            self.house_mobile_clients.get(house_id, set()).discard(websocket)
            if not self.house_mobile_clients.get(house_id):
                self.house_mobile_clients.pop(house_id, None)
            print(f"Mobile client acc_id={info['acc_id']} disconnected (house {house_id})")

    async def broadcast_to_house(self, house_id: int, payload: dict):
        """Send a JSON message to all mobile clients belonging to a house."""
        clients = self.house_mobile_clients.get(house_id, set()).copy()
        if not clients:
            return
        message = json.dumps(payload)
        dead = []
        for ws in clients:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect_mobile(ws)



manager = ConnectionManager()


# ─── Landing Page & Admin Page ────────────────────────────────

security_basic = HTTPBasic()

# `/admin` used to fall back to the password "admin" when ADMIN_PASSWORD_HASH was
# unset — a known credential on a public URL, reachable by anyone who read the
# source. There is no fixed fallback now: without the env var a random password
# is minted per process and printed to the log once, so a local run stays usable
# and no deployment ever carries a guessable one.
_EPHEMERAL_ADMIN_PASSWORD = None
_EPHEMERAL_ADMIN_HASH = None


def get_admin_hash() -> str:
    global _EPHEMERAL_ADMIN_PASSWORD, _EPHEMERAL_ADMIN_HASH
    configured = os.environ.get("ADMIN_PASSWORD_HASH")
    if configured:
        return configured
    if _EPHEMERAL_ADMIN_HASH is None:
        _EPHEMERAL_ADMIN_PASSWORD = secrets.token_urlsafe(12)
        _EPHEMERAL_ADMIN_HASH = hash_password(_EPHEMERAL_ADMIN_PASSWORD)
        print("WARNING: ADMIN_PASSWORD_HASH is not set. This run's /admin password "
              f"is: {_EPHEMERAL_ADMIN_PASSWORD}  (user 'admin'; changes on restart)")
    return _EPHEMERAL_ADMIN_HASH


@app.get("/", response_class=HTMLResponse)
async def root_page():
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.get("/store", response_class=HTMLResponse)
async def store_page():
    """Public marketplace storefront."""
    return HTMLResponse(content=(STATIC_DIR / "store.html").read_text(encoding="utf-8"))


@app.get("/integrate", response_class=HTMLResponse)
async def integrate_page():
    """Open API integration guide + key management (uses the portal login)."""
    return HTMLResponse(content=(STATIC_DIR / "integrate.html").read_text(encoding="utf-8"))


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request,
                     credentials: HTTPBasicCredentials = Depends(security_basic)):
    ip = client_ip(request)
    ADMIN_LOCK.guard(ip)
    ok = (secrets.compare_digest(credentials.username, "admin")
          and verify_password(credentials.password, get_admin_hash()))
    if not ok:
        ADMIN_LOCK.fail(ip)
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    ADMIN_LOCK.clear(ip)
    html_path = STATIC_DIR / "admin.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


# ─── Auth Endpoints ───────────────────────────────────────────

@app.post("/api/auth/register")
async def register(payload: dict, request: Request, db: Session = Depends(get_db)):
    # Registration is open by design (anyone can create a household), but an
    # unlimited supply of accounts is what makes guessing a house PIN cheap --
    # each fresh account gets its own lockout budget. Cap how fast they appear.
    REGISTER_RATE.hit(client_ip(request))
    email = payload.get("email", "").strip()
    password = payload.get("password", "")
    name = payload.get("name", "").strip()
    if not email or not password or not name:
        raise HTTPException(status_code=400, detail="email, password, name required")
    existing = db.query(Account).filter(Account.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    account = Account(
        email=email,
        password=hash_password(password),
        name=name,
        role=AccountRole.parent,
        is_master=False,
    )
    db.add(account)
    db.commit()
    token = create_access_token({"sub": account.acc_id})
    return {
        "acc_id": account.acc_id,
        "email": account.email,
        "name": account.name,
        "house_id": None,
        "token": token,
    }


@app.post("/api/auth/login")
async def login(payload: dict, request: Request, db: Session = Depends(get_db)):
    email = payload.get("email", "").strip()
    password = payload.get("password", "")
    # bcrypt already makes each guess slow; the lockout is what makes a long run
    # pointless. Keyed on the email so one attacker cannot lock out a whole
    # household by hammering from the same address, and rate-limited per IP so a
    # spray across many emails is bounded too.
    LOGIN_RATE.hit(client_ip(request))
    LOGIN_LOCK.guard(email.lower())
    account = db.query(Account).filter(Account.email == email).first()
    if not account or not verify_password(password, account.password):
        LOGIN_LOCK.fail(email.lower())
        raise HTTPException(status_code=401, detail="Invalid credentials")
    LOGIN_LOCK.clear(email.lower())
    token = create_access_token({"sub": account.acc_id})
    return {
        "acc_id": account.acc_id,
        "email": account.email,
        "name": account.name,
        "role": account.role.value,
        "house_id": account.house_id,
        "token": token,
    }


@app.get("/api/auth/me")
async def get_me(auth: dict = Depends(get_current_user_or_child)):
    if auth["type"] == "child":
        child = auth["child"]
        return {
            "child_id": child.child_id,
            "name": child.name,
            "role": "child",
            "house_id": child.house_id,
            "is_home": child.is_home,
        }
    current_user = auth["user"]
    return {
        "acc_id": current_user.acc_id,
        "email": current_user.email,
        "name": current_user.name,
        "role": current_user.role.value,
        "house_id": current_user.house_id,
        "is_master": current_user.is_master,
        "is_home": current_user.is_home,
    }


# ─── House Endpoints ──────────────────────────────────────────

@app.get("/api/houses/{house_id}")
async def get_house(house_id: int, db: Session = Depends(get_db),
                    current_user: Account = Depends(get_current_user)):
    if current_user.role != AccountRole.admin and current_user.house_id != house_id:
        raise HTTPException(status_code=403, detail="Access denied to this house")
    house = db.query(House).filter(House.house_id == house_id).first()
    if not house:
        raise HTTPException(status_code=404, detail="House not found")
    return {"house_id": house.house_id, "location": house.location, "created_at": house.created_at.isoformat() if house.created_at else None}


@app.put("/api/houses/{house_id}")
async def update_house(house_id: int, payload: dict, db: Session = Depends(get_db),
                       current_user: Account = Depends(get_current_user)):
    if current_user.role != AccountRole.admin and current_user.house_id != house_id:
        raise HTTPException(status_code=403, detail="Access denied to this house")
    house = db.query(House).filter(House.house_id == house_id).first()
    if not house:
        raise HTTPException(status_code=404, detail="House not found")
    if "location" in payload:
        house.location = payload["location"]
    db.commit()
    return {"house_id": house.house_id, "location": house.location}


def _generate_pin():
    return ''.join(random.choices(string.digits, k=6))


# ─── Multi-House Management ───────────────────────────────────

@app.get("/api/houses")
async def list_my_houses(db: Session = Depends(get_db),
                        current_user: Account = Depends(get_current_user)):
    """List all houses the current user has joined."""
    assocs = db.query(AccountHouse).filter(AccountHouse.acc_id == current_user.acc_id).all()
    result = []
    for a in assocs:
        house = db.query(House).filter(House.house_id == a.house_id).first()
        if house:
            result.append({
                "house_id": house.house_id,
                "location": house.location,
                "is_master": a.is_master,
                "can_manage_devices": bool(a.is_master or a.can_manage_devices),
                "join_pin": house.join_pin if a.is_master else None,
                "is_active": current_user.house_id == house.house_id,
            })
    return {"houses": result}


@app.post("/api/houses")
async def create_house(payload: dict, db: Session = Depends(get_db),
                      current_user: Account = Depends(get_current_user)):
    """Create a new house and link the user as master."""
    location = payload.get("location", "").strip()
    if not location:
        raise HTTPException(status_code=400, detail="location required")
    house = House(location=location, join_pin=_generate_pin())
    db.add(house)
    db.flush()
    assoc = AccountHouse(acc_id=current_user.acc_id, house_id=house.house_id, is_master=True)
    db.add(assoc)
    # Set as active house if user has none
    if not current_user.house_id:
        current_user.house_id = house.house_id
    db.commit()
    return {
        "house_id": house.house_id,
        "location": house.location,
        "join_pin": house.join_pin,
        "is_master": True,
    }


@app.post("/api/houses/join")
async def join_house(payload: dict, db: Session = Depends(get_db),
                    current_user: Account = Depends(get_current_user)):
    """Join an existing house using house_id + 6-digit PIN."""
    house_id = payload.get("house_id")
    pin = payload.get("pin", "").strip()
    if not house_id or not pin:
        raise HTTPException(status_code=400, detail="house_id and pin required")
    # This is the endpoint that guarded a child's GPS coordinates: house ids are
    # sequential, the PIN is 6 digits, and nothing used to slow a guess down, so
    # a script could walk id 1..n and brute the PIN for each. Two locks: one per
    # (account, house) so repeated tries at one house die quickly, and one per
    # account across all houses so walking the id space dies too. A failure is
    # also written to the target house's activity log, which makes a quiet attack
    # visible to the people who live there.
    acct_key = str(current_user.acc_id)
    pair_key = "%s:%s" % (current_user.acc_id, house_id)
    JOIN_LOCK.guard(pair_key)
    JOIN_WALK_LOCK.guard(acct_key)
    house = db.query(House).filter(House.house_id == house_id).first()
    stored = (house.join_pin or "") if house else ""
    # Constant-time: a plain != leaks how many leading digits matched through its
    # return time, which turns 10**6 guesses into roughly 6 * 10 of them.
    if not house or not stored or not secrets.compare_digest(stored, pin):
        locked = JOIN_LOCK.fail(pair_key)
        JOIN_WALK_LOCK.fail(acct_key)
        if house:
            log_activity(db, house.house_id, "parent", current_user.acc_id,
                         current_user.name, "join_failed",
                         f"Failed join attempt for house {house_id} by {current_user.email}"
                         + (" - further attempts blocked for an hour" if locked else ""))
            db.commit()
        raise HTTPException(status_code=403, detail="Invalid house ID or PIN")
    JOIN_LOCK.clear(pair_key)
    JOIN_WALK_LOCK.clear(acct_key)
    # Check if already joined
    existing = db.query(AccountHouse).filter(
        AccountHouse.acc_id == current_user.acc_id,
        AccountHouse.house_id == house_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Already a member of this house")
    assoc = AccountHouse(acc_id=current_user.acc_id, house_id=house.house_id, is_master=False)
    db.add(assoc)
    if not current_user.house_id:
        current_user.house_id = house.house_id
    log_activity(db, house.house_id, "parent", current_user.acc_id, current_user.name,
                 "member_joined", f"{current_user.name} joined the house")
    db.commit()
    return {"house_id": house.house_id, "location": house.location, "is_master": False}


@app.post("/api/houses/switch")
async def switch_house(payload: dict, db: Session = Depends(get_db),
                      current_user: Account = Depends(get_current_user)):
    """Switch the user's active house."""
    house_id = payload.get("house_id")
    if not house_id:
        raise HTTPException(status_code=400, detail="house_id required")
    assoc = db.query(AccountHouse).filter(
        AccountHouse.acc_id == current_user.acc_id,
        AccountHouse.house_id == house_id
    ).first()
    if not assoc:
        raise HTTPException(status_code=403, detail="Not a member of this house")
    current_user.house_id = house_id
    db.commit()
    return {"house_id": house_id, "active": True}


@app.get("/api/houses/{house_id}/members")
async def list_house_members(house_id: int, db: Session = Depends(get_db),
                            current_user: Account = Depends(get_current_user)):
    """List all members of a house."""
    # Check caller is a member
    caller_assoc = db.query(AccountHouse).filter(
        AccountHouse.acc_id == current_user.acc_id,
        AccountHouse.house_id == house_id
    ).first()
    if not caller_assoc:
        raise HTTPException(status_code=403, detail="Not a member of this house")
    assocs = db.query(AccountHouse).filter(AccountHouse.house_id == house_id).all()
    members = []
    for a in assocs:
        acc = db.query(Account).filter(Account.acc_id == a.acc_id).first()
        if acc:
            members.append({
                "acc_id": acc.acc_id,
                "name": acc.name,
                "email": acc.email,
                "is_master": a.is_master,
                "can_manage_devices": bool(a.is_master or a.can_manage_devices),
            })
    return {"members": members}


@app.put("/api/houses/{house_id}/members/{acc_id}/device-permission")
async def set_member_device_permission(house_id: int, acc_id: int, payload: dict,
                                       db: Session = Depends(get_db),
                                       current_user: Account = Depends(get_current_user)):
    """Grant or revoke a member's right to add/remove devices (master-only)."""
    caller_assoc = db.query(AccountHouse).filter(
        AccountHouse.acc_id == current_user.acc_id,
        AccountHouse.house_id == house_id
    ).first()
    if not caller_assoc or not caller_assoc.is_master:
        raise HTTPException(status_code=403, detail="Only the house master can change device permissions")
    target = db.query(AccountHouse).filter(
        AccountHouse.acc_id == acc_id,
        AccountHouse.house_id == house_id
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Member not found in this house")
    if target.is_master:
        raise HTTPException(status_code=400, detail="The master always has device permissions")
    target.can_manage_devices = bool(payload.get("allowed", False))
    db.commit()
    return {"acc_id": acc_id, "can_manage_devices": target.can_manage_devices}


@app.delete("/api/houses/{house_id}/members/{acc_id}")
async def kick_member(house_id: int, acc_id: int, db: Session = Depends(get_db),
                     current_user: Account = Depends(get_current_user)):
    """Remove a member from a house (master-only)."""
    caller_assoc = db.query(AccountHouse).filter(
        AccountHouse.acc_id == current_user.acc_id,
        AccountHouse.house_id == house_id
    ).first()
    if not caller_assoc or not caller_assoc.is_master:
        raise HTTPException(status_code=403, detail="Only the house master can remove members")
    if acc_id == current_user.acc_id:
        raise HTTPException(status_code=400, detail="Cannot remove yourself")
    target = db.query(AccountHouse).filter(
        AccountHouse.acc_id == acc_id,
        AccountHouse.house_id == house_id
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Member not found in this house")
    db.delete(target)
    # If the kicked user's active house was this one, clear it
    kicked_user = db.query(Account).filter(Account.acc_id == acc_id).first()
    if kicked_user and kicked_user.house_id == house_id:
        kicked_user.house_id = None
    db.commit()
    return {"removed": acc_id}


@app.post("/api/houses/{house_id}/reset-pin")
async def reset_house_pin(house_id: int, db: Session = Depends(get_db),
                         current_user: Account = Depends(get_current_user)):
    """Regenerate the join PIN for a house (master-only)."""
    caller_assoc = db.query(AccountHouse).filter(
        AccountHouse.acc_id == current_user.acc_id,
        AccountHouse.house_id == house_id
    ).first()
    if not caller_assoc or not caller_assoc.is_master:
        raise HTTPException(status_code=403, detail="Only the house master can reset the PIN")
    house = db.query(House).filter(House.house_id == house_id).first()
    if not house:
        raise HTTPException(status_code=404, detail="House not found")
    house.join_pin = _generate_pin()
    db.commit()
    return {"house_id": house.house_id, "join_pin": house.join_pin}


# ─── API Key Management (Open API) ────────────────────────────

def _require_master(db: Session, current_user: Account, house_id: int):
    assoc = db.query(AccountHouse).filter(
        AccountHouse.acc_id == current_user.acc_id,
        AccountHouse.house_id == house_id
    ).first()
    if not assoc or not assoc.is_master:
        raise HTTPException(status_code=403, detail="Only the house master can manage API keys")


@app.post("/api/houses/{house_id}/api-keys")
async def create_api_key(house_id: int, payload: dict, db: Session = Depends(get_db),
                         current_user: Account = Depends(get_current_user)):
    _require_master(db, current_user, house_id)
    plaintext = "maya_" + secrets.token_urlsafe(32)
    key = ApiKey(
        house_id=house_id,
        name=(payload.get("name") or "API Key").strip(),
        prefix=plaintext[:12],
        key_hash=hash_api_key(plaintext),
        created_by=current_user.acc_id,
    )
    db.add(key)
    db.commit()
    # The plaintext key is returned exactly once — only its hash is stored.
    return {"key_id": key.key_id, "name": key.name, "prefix": key.prefix, "api_key": plaintext}


@app.get("/api/houses/{house_id}/api-keys")
async def list_api_keys(house_id: int, db: Session = Depends(get_db),
                        current_user: Account = Depends(get_current_user)):
    _require_master(db, current_user, house_id)
    keys = db.query(ApiKey).filter(ApiKey.house_id == house_id, ApiKey.revoked == False).all()  # noqa: E712
    return {"api_keys": [{
        "key_id": k.key_id, "name": k.name, "prefix": k.prefix,
        "created_at": k.created_at.isoformat() if k.created_at else None,
    } for k in keys]}


@app.delete("/api/houses/{house_id}/api-keys/{key_id}")
async def revoke_api_key(house_id: int, key_id: int, db: Session = Depends(get_db),
                         current_user: Account = Depends(get_current_user)):
    _require_master(db, current_user, house_id)
    key = db.query(ApiKey).filter(ApiKey.key_id == key_id, ApiKey.house_id == house_id).first()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    key.revoked = True
    db.commit()
    return {"status": "revoked"}


# ─── Open API v1 (third-party, X-API-Key) ─────────────────────

def _open_device_or_404(db: Session, house: House, device_id: str) -> Device:
    device = db.query(Device).filter(
        Device.device_id == device_id, Device.house_id == house.house_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found in this house")
    return device


def _open_device_dict(db: Session, device: Device) -> dict:
    ext = db.query(SmartExtension).filter(SmartExtension.device_id == device.device_id).first()
    relays = db.query(Relay).filter(Relay.se_id == ext.se_id).all() if ext else []
    return {
        "device_id": device.device_id,
        "name": device.name,
        "online": device.device_id in manager.active_connections,
        "blocked": device.blocked,
        "channels": [{
            "channel": r.channel_number, "name": r.name, "is_on": r.is_on,
        } for r in sorted(relays, key=lambda r: r.channel_number)],
    }


@app.get("/api/open/v1/devices", tags=["Open API v1"])
async def open_list_devices(db: Session = Depends(get_db),
                            house: House = Depends(api_key_house_limited)):
    """List every device in the key's house with channel states."""
    devices = db.query(Device).filter(Device.house_id == house.house_id).all()
    return {"devices": [_open_device_dict(db, d) for d in devices]}


@app.get("/api/open/v1/devices/{device_id}", tags=["Open API v1"])
async def open_get_device(device_id: str, db: Session = Depends(get_db),
                          house: House = Depends(api_key_house_limited)):
    """Get one device with channel states."""
    return _open_device_dict(db, _open_device_or_404(db, house, device_id))


@app.post("/api/open/v1/devices/{device_id}/command", tags=["Open API v1"])
async def open_send_command(device_id: str, payload: dict, db: Session = Depends(get_db),
                            house: House = Depends(api_key_house_limited)):
    """Switch a channel: body {"cmd": "on"|"off"|"all_on"|"all_off", "channel": 1-3}."""
    device = _open_device_or_404(db, house, device_id)
    if device.blocked:
        return {"status": "blocked", "device_id": device_id}
    cmd = payload.get("cmd", "")
    channel = payload.get("channel", 1)
    if cmd not in ("on", "off", "all_on", "all_off"):
        raise HTTPException(status_code=400, detail="cmd must be on/off/all_on/all_off")
    return await _dispatch_command(device_id, cmd, channel)


@app.get("/api/houses/{house_id}/chat")
async def get_chat_history(house_id: int, before: int = None, db: Session = Depends(get_db),
                          user_info: dict = Depends(get_current_user_or_child)):
    """Get the last 50 chat messages for a house, with cursor pagination."""
    caller_house = user_info.get("house_id")
    if caller_house != house_id:
        # Also check AccountHouse for parent multi-house
        if user_info["type"] == "user":
            assoc = db.query(AccountHouse).filter(
                AccountHouse.acc_id == user_info["user"].acc_id,
                AccountHouse.house_id == house_id
            ).first()
            if not assoc:
                raise HTTPException(status_code=403, detail="Not a member of this house")
        else:
            raise HTTPException(status_code=403, detail="Access denied")
    query = db.query(MsgHistory).filter(MsgHistory.house_id == house_id)
    if before:
        query = query.filter(MsgHistory.msg_id < before)
    messages = query.order_by(MsgHistory.msg_id.desc()).limit(50).all()
    messages.reverse()  # oldest first
    return {
        "messages": [{
            "msg_id": m.msg_id,
            "sender_id": m.sender_id,
            "sender_type": m.sender_type,
            "sender_name": m.sender_name,
            "message": m.message,
            "timestamp": m.timestamp.isoformat() if m.timestamp else None,
        } for m in messages],
        "has_more": len(messages) == 50,
    }


# ─── Mentions (@name in chat) ─────────────────────────────────

def _caller_in_house(db: Session, user_info: dict, house_id: int) -> bool:
    if user_info.get("house_id") == house_id:
        return True
    if user_info["type"] == "user":
        return db.query(AccountHouse).filter(
            AccountHouse.acc_id == user_info["user"].acc_id,
            AccountHouse.house_id == house_id).first() is not None
    return False


def _house_mentionables(db: Session, house_id: int) -> list:
    """Everyone (and Maya) who can be @-mentioned in a house."""
    people = [{"type": "ai", "id": MAYA_SENDER_ID, "name": "Maya"}]
    for a in db.query(AccountHouse).filter(AccountHouse.house_id == house_id).all():
        acc = db.query(Account).filter(Account.acc_id == a.acc_id).first()
        if acc:
            people.append({"type": "parent", "id": acc.acc_id, "name": acc.name})
    for c in db.query(Child).filter(Child.house_id == house_id).all():
        people.append({"type": "child", "id": c.child_id, "name": c.name})
    return people


def _record_mentions(db: Session, house_id: int, msg_id: int, message: str,
                     sender_type: str, sender_id: int):
    """Create unseen Mention rows for each real person named '@Name' in message
    (case-insensitive). Skips Maya and the sender themselves."""
    low = message.lower()
    for p in _house_mentionables(db, house_id):
        if p["type"] == "ai":
            continue
        if p["type"] == sender_type and p["id"] == sender_id:
            continue  # don't flag your own name back at you
        if f"@{p['name'].lower()}" in low:
            db.add(Mention(msg_id=msg_id, house_id=house_id,
                           target_type=p["type"], target_id=p["id"], seen=False))


@app.get("/api/houses/{house_id}/mentionables")
async def list_mentionables(house_id: int, db: Session = Depends(get_db),
                            user_info: dict = Depends(get_current_user_or_child)):
    """Names the chat's '@' autocomplete offers: Maya + members + children."""
    if not _caller_in_house(db, user_info, house_id):
        raise HTTPException(status_code=403, detail="Not a member of this house")
    return {"mentionables": _house_mentionables(db, house_id)}


def _caller_target(user_info: dict) -> tuple:
    if user_info["type"] == "child":
        return "child", user_info["child"].child_id
    return "parent", user_info["user"].acc_id


@app.get("/api/houses/{house_id}/mentions/unseen")
async def unseen_mentions(house_id: int, db: Session = Depends(get_db),
                          user_info: dict = Depends(get_current_user_or_child)):
    """Message ids that @-mention the caller and are not yet seen (for the badge
    and bubble highlight)."""
    if not _caller_in_house(db, user_info, house_id):
        raise HTTPException(status_code=403, detail="Not a member of this house")
    t_type, t_id = _caller_target(user_info)
    rows = db.query(Mention).filter(
        Mention.house_id == house_id, Mention.target_type == t_type,
        Mention.target_id == t_id, Mention.seen == False).all()  # noqa: E712
    return {"count": len(rows), "msg_ids": [m.msg_id for m in rows]}


@app.post("/api/houses/{house_id}/mentions/seen")
async def mark_mentions_seen(house_id: int, db: Session = Depends(get_db),
                             user_info: dict = Depends(get_current_user_or_child)):
    """Clear the caller's unseen mentions in this house (called when they open chat)."""
    if not _caller_in_house(db, user_info, house_id):
        raise HTTPException(status_code=403, detail="Not a member of this house")
    t_type, t_id = _caller_target(user_info)
    n = db.query(Mention).filter(
        Mention.house_id == house_id, Mention.target_type == t_type,
        Mention.target_id == t_id, Mention.seen == False).update({"seen": True})  # noqa: E712
    db.commit()
    return {"marked": n}


@app.delete("/api/houses/{house_id}/chat")
async def clear_chat(house_id: int, db: Session = Depends(get_db),
                     current_user: Account = Depends(get_current_user)):
    """Delete all chat history for a house. House master only. Broadcasts a
    chat_cleared event so every connected client wipes its local view."""
    _require_master(db, current_user, house_id)
    db.query(Mention).filter(Mention.house_id == house_id).delete()
    deleted = db.query(MsgHistory).filter(MsgHistory.house_id == house_id).delete()
    log_activity(db, house_id, "parent", current_user.acc_id, current_user.name,
                 "chat_cleared", f"{current_user.name} cleared the chat")
    db.commit()
    await manager.broadcast_to_house(house_id, {"type": "chat_cleared", "house_id": house_id})
    return {"deleted": deleted}


# ─── Child Management ─────────────────────────────────────────

@app.post("/api/children")
async def create_child(payload: dict, db: Session = Depends(get_db),
                       current_user: Account = Depends(get_current_user)):
    if current_user.role not in (AccountRole.parent, AccountRole.admin):
        raise HTTPException(status_code=403, detail="Only parents/admins can register children")
    house_id = current_user.house_id
    if not house_id:
        raise HTTPException(status_code=400, detail="Account has no house")
    try:
        pin = normalize_child_pin(payload.get("pin"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    child = Child(
        house_id=house_id,
        name=payload.get("name", "").strip(),
        pin=hash_password(pin),
    )
    db.add(child)
    db.commit()
    return {"child_id": child.child_id, "name": child.name, "house_id": child.house_id}


@app.get("/api/children")
async def list_children(db: Session = Depends(get_db),
                        current_user: Account = Depends(get_current_user)):
    house_id = current_user.house_id
    if not house_id:
        return {"children": []}
    children = db.query(Child).filter(Child.house_id == house_id).all()

    def latest_screen_time(child_id: int):
        row = db.query(ScreenTime).filter(ScreenTime.child_id == child_id) \
            .order_by(ScreenTime.date.desc()).first()
        return {"date": row.date, "total_min": row.total_min} if row else None

    return {"children": [{
        "child_id": c.child_id, "name": c.name, "is_home": c.is_home,
        "last_lat": c.last_lat, "last_lng": c.last_lng,
        "last_seen_at": c.last_seen_at.isoformat() if c.last_seen_at else None,
        "daily_screen_limit_min": c.daily_screen_limit_min,
        "screen_time": latest_screen_time(c.child_id),
    } for c in children]}


@app.get("/api/children/{child_id}")
async def get_child(child_id: int, db: Session = Depends(get_db),
                    current_user: Account = Depends(get_current_user)):
    child = db.query(Child).filter(Child.child_id == child_id).first()
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    if current_user.role != AccountRole.admin and child.house_id != current_user.house_id:
        raise HTTPException(status_code=403, detail="Access denied to this child")
    return {"child_id": child.child_id, "name": child.name, "is_home": child.is_home, "house_id": child.house_id}


@app.post("/api/children/{child_id}/login")
async def child_login(child_id: int, payload: dict, db: Session = Depends(get_db)):
    child = db.query(Child).filter(Child.child_id == child_id).first()
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    pin = payload.get("pin", "")
    # A 4-digit PIN is 10,000 guesses - minutes without a lockout. child_id is
    # the key because the PIN is per child, and the child's own device is the
    # only legitimate caller.
    lock_key = str(child.child_id)
    CHILD_PIN_LOCK.guard(lock_key)
    if not verify_password(pin, child.pin):
        if CHILD_PIN_LOCK.fail(lock_key):
            log_activity(db, child.house_id, "child", child.child_id, child.name,
                         "child_login_blocked",
                         f"Too many wrong PINs for {child.name} - sign-in blocked for 15 minutes")
            db.commit()
        raise HTTPException(status_code=401, detail="Invalid PIN")
    CHILD_PIN_LOCK.clear(lock_key)
    token = create_access_token({"sub": f"child_{child.child_id}", "role": "child", "house_id": child.house_id})
    log_activity(db, child.house_id, "child", child.child_id, child.name,
                 "child_login", f"{child.name} logged in")
    db.commit()
    return {"child_id": child.child_id, "name": child.name, "token": token}


@app.post("/api/children/location")
async def report_child_location(payload: dict, db: Session = Depends(get_db),
                                current_auth: dict = Depends(get_current_user_or_child)):
    if current_auth["type"] != "child":
        raise HTTPException(status_code=403, detail="Only child devices report location")
    lat, lng = payload.get("lat"), payload.get("lng")
    if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
        raise HTTPException(status_code=400, detail="lat and lng required")
    child = current_auth["child"]
    child.last_lat = float(lat)
    child.last_lng = float(lng)
    child.last_seen_at = datetime.now(timezone.utc)
    db.commit()
    await manager.broadcast_to_house(child.house_id, {
        "type": "child_location", "child_id": child.child_id,
        "lat": child.last_lat, "lng": child.last_lng,
        "at": child.last_seen_at.isoformat(),
    })
    return {"status": "ok"}


@app.put("/api/children/{child_id}/screen-limit")
async def set_screen_limit(child_id: int, payload: dict, db: Session = Depends(get_db),
                           current_user: Account = Depends(get_current_user)):
    child = db.query(Child).filter(Child.child_id == child_id).first()
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    if current_user.role != AccountRole.admin and child.house_id != current_user.house_id:
        raise HTTPException(status_code=403, detail="Access denied to this child")
    limit = payload.get("daily_limit_min")
    if limit is not None and (not isinstance(limit, int) or limit < 0):
        raise HTTPException(status_code=400, detail="daily_limit_min must be a non-negative integer or null")
    child.daily_screen_limit_min = limit
    db.commit()
    return {"child_id": child.child_id, "daily_screen_limit_min": child.daily_screen_limit_min}


# ─── Screen Time ──────────────────────────────────────────────

@app.post("/api/screen-time/report")
async def report_screen_time(payload: dict, db: Session = Depends(get_db),
                             current_auth: dict = Depends(get_current_user_or_child)):
    if current_auth["type"] != "child":
        raise HTTPException(status_code=403, detail="Only child devices report screen time")
    date = payload.get("date", "")
    total_min = payload.get("total_min")
    if len(date) != 10 or not isinstance(total_min, int) or total_min < 0:
        raise HTTPException(status_code=400, detail="date (YYYY-MM-DD) and total_min required")
    child = current_auth["child"]
    row = db.query(ScreenTime).filter(
        ScreenTime.child_id == child.child_id, ScreenTime.date == date).first()
    if row:
        row.total_min = total_min
        row.updated_at = datetime.now(timezone.utc)
    else:
        row = ScreenTime(child_id=child.child_id, date=date, total_min=total_min)
        db.add(row)
    db.commit()

    # Automation: fire the daily screen-limit alert once, the first time the
    # child crosses their limit for the day. limit_notified dedups across the
    # many reports a device sends per day; a new day = new row = flag resets.
    limit = child.daily_screen_limit_min
    if limit is not None and total_min >= limit and not row.limit_notified:
        row.limit_notified = True
        db.commit()
        await _notify_screen_limit(db, child, total_min, limit)
    return {"status": "ok"}


@app.get("/api/screen-time/me")
async def my_screen_time(date: str, db: Session = Depends(get_db),
                         current_auth: dict = Depends(get_current_user_or_child)):
    if current_auth["type"] != "child":
        raise HTTPException(status_code=403, detail="Child endpoint")
    child = current_auth["child"]
    row = db.query(ScreenTime).filter(
        ScreenTime.child_id == child.child_id, ScreenTime.date == date).first()
    used = row.total_min if row else 0
    limit = child.daily_screen_limit_min
    return {
        "date": date, "used_min": used, "limit_min": limit,
        "remaining_min": max(0, limit - used) if limit is not None else None,
    }


# ─── Homework ─────────────────────────────────────────────────

def _get_house_child_or_403(db: Session, current_user: Account, child_id: int) -> Child:
    child = db.query(Child).filter(Child.child_id == child_id).first()
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    if current_user.role != AccountRole.admin and child.house_id != current_user.house_id:
        raise HTTPException(status_code=403, detail="Access denied to this child")
    return child


@app.post("/api/homework")
async def create_homework(payload: dict, db: Session = Depends(get_db),
                          current_user: Account = Depends(get_current_user)):
    child_id = payload.get("child_id")
    title = (payload.get("title") or "").strip()
    if not child_id or not title:
        raise HTTPException(status_code=400, detail="child_id and title required")
    child = _get_house_child_or_403(db, current_user, child_id)
    hw = Homework(
        house_id=child.house_id, child_id=child.child_id, title=title,
        description=payload.get("description", ""), due_date=payload.get("due_date"),
    )
    db.add(hw)
    log_activity(db, child.house_id, "parent", current_user.acc_id, current_user.name,
                 "homework_assigned", f'{current_user.name} assigned "{title}" to {child.name}')
    db.commit()
    return {"hw_id": hw.hw_id}


@app.get("/api/homework")
async def list_homework(child_id: int | None = None, db: Session = Depends(get_db),
                        current_auth: dict = Depends(get_current_user_or_child)):
    if current_auth["type"] == "child":
        q = db.query(Homework).filter(Homework.child_id == current_auth["child"].child_id)
    else:
        current_user = current_auth["user"]
        if child_id:
            _get_house_child_or_403(db, current_user, child_id)
            q = db.query(Homework).filter(Homework.child_id == child_id)
        elif current_user.role == AccountRole.admin:
            q = db.query(Homework)
        else:
            q = db.query(Homework).filter(Homework.house_id == current_user.house_id)
    return {"homework": [{
        "hw_id": h.hw_id, "child_id": h.child_id, "title": h.title,
        "description": h.description, "due_date": h.due_date, "is_done": h.is_done,
        "created_at": h.created_at.isoformat() if h.created_at else None,
    } for h in q.order_by(Homework.is_done, Homework.created_at.desc()).all()]}


@app.put("/api/homework/{hw_id}")
async def update_homework(hw_id: int, payload: dict, db: Session = Depends(get_db),
                          current_auth: dict = Depends(get_current_user_or_child)):
    hw = db.query(Homework).filter(Homework.hw_id == hw_id).first()
    if not hw:
        raise HTTPException(status_code=404, detail="Homework not found")
    was_done = hw.is_done
    if current_auth["type"] == "child":
        if hw.child_id != current_auth["child"].child_id:
            raise HTTPException(status_code=403, detail="Not your homework")
        if "is_done" in payload:  # children may only toggle completion
            hw.is_done = bool(payload["is_done"])
    else:
        _get_house_child_or_403(db, current_auth["user"], hw.child_id)
        for field in ("title", "description", "due_date"):
            if field in payload:
                setattr(hw, field, payload[field])
        if "is_done" in payload:
            hw.is_done = bool(payload["is_done"])
    if hw.is_done and not was_done:
        child = db.query(Child).filter(Child.child_id == hw.child_id).first()
        actor = current_auth["child"] if current_auth["type"] == "child" else current_auth["user"]
        actor_id = actor.child_id if current_auth["type"] == "child" else actor.acc_id
        log_activity(db, hw.house_id, current_auth["role"], actor_id, actor.name,
                     "homework_completed", f'{child.name if child else "A child"} completed "{hw.title}"')
    db.commit()
    return {"hw_id": hw.hw_id, "is_done": hw.is_done}


@app.delete("/api/homework/{hw_id}")
async def delete_homework(hw_id: int, db: Session = Depends(get_db),
                          current_user: Account = Depends(get_current_user)):
    hw = db.query(Homework).filter(Homework.hw_id == hw_id).first()
    if not hw:
        raise HTTPException(status_code=404, detail="Homework not found")
    _get_house_child_or_403(db, current_user, hw.child_id)
    db.delete(hw)
    db.commit()
    return {"status": "deleted"}


# ─── Device Registration ──────────────────────────────────────

async def _reset_and_close(websocket: WebSocket, device_id: str, reason: str):
    """Tell a connecting device to wipe itself back to provisioning mode, then close.
    Used when the device is unknown or orphaned (no valid house)."""
    print(f"Device {device_id} rejected at identify ({reason}). Sending factory_reset.")
    try:
        await websocket.send_text(json.dumps({"id": device_id, "cmd": "factory_reset"}))
    except Exception:
        pass
    manager.disconnect(websocket)
    await websocket.close(code=1008)


def _device_has_valid_house(db: Session, device_db: Device) -> bool:
    """A device is only valid if it belongs to a house that still exists."""
    if not device_db.house_id:
        return False
    return db.query(House).filter(House.house_id == device_db.house_id).first() is not None


def _user_can_manage_devices(db: Session, user: Account) -> bool:
    """Master of the active house, a member the master granted the right to,
    or a global admin. Children can never manage devices."""
    if user.role == AccountRole.admin:
        return True
    if user.role != AccountRole.parent or not user.house_id:
        return False
    assoc = db.query(AccountHouse).filter(
        AccountHouse.acc_id == user.acc_id,
        AccountHouse.house_id == user.house_id
    ).first()
    return bool(assoc and (assoc.is_master or assoc.can_manage_devices))


@app.post("/api/devices/register")
async def register_device(payload: dict, db: Session = Depends(get_db),
                          current_user: Account = Depends(get_current_user)):
    if not _user_can_manage_devices(db, current_user):
        raise HTTPException(status_code=403, detail="Only the house owner (or members they've authorized) can add devices")
    house_id = current_user.house_id
    if not house_id:
        raise HTTPException(status_code=400, detail="Account has no house")
    device_id = payload.get("device_id", "").strip()
    name = payload.get("name", "Smart Extension")
    price = payload.get("price", 0.0)
    try:
        pin = normalize_device_pin(payload.get("pin"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id required")
    existing = db.query(Device).filter(Device.device_id == device_id).first()
    if existing:
        existing.house_id = house_id
        existing.name = name
        existing.price = price
        existing.pin = pin
        existing.status = "registered"
        existing.blocked = False
        device = existing
    else:
        device = Device(device_id=device_id, house_id=house_id, name=name, price=price, pin=pin, status="registered")
        db.add(device)
    db.flush()
    
    existing_ext = db.query(SmartExtension).filter(SmartExtension.device_id == device_id).first()
    if existing_ext:
        ext = existing_ext
        ext.name = f"{name} Extension"
        for ch in range(1, 4):
            relay = db.query(Relay).filter(Relay.se_id == ext.se_id, Relay.channel_number == ch).first()
            if not relay:
                relay = Relay(se_id=ext.se_id, name=f"Channel {ch}", channel_number=ch, is_on=False)
                db.add(relay)
            else:
                relay.name = f"Channel {ch}"
    else:
        ext = SmartExtension(device_id=device_id, name=f"{name} Extension")
        db.add(ext)
        db.flush()
        for ch in range(1, 4):
            relay = Relay(se_id=ext.se_id, name=f"Channel {ch}", channel_number=ch, is_on=False)
            db.add(relay)
    db.commit()
    return {"device_id": device.device_id, "name": device.name, "status": device.status,
            "house_id": device.house_id, "created": existing is None}


@app.delete("/api/devices/{device_id}")
async def delete_device(device_id: str, db: Session = Depends(get_db),
                        current_user: Account = Depends(get_current_user)):
    if not _user_can_manage_devices(db, current_user):
        raise HTTPException(status_code=403, detail="Only the house owner (or members they've authorized) can remove devices")
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if current_user.role != AccountRole.admin and device.house_id != current_user.house_id:
        raise HTTPException(status_code=403, detail="Device belongs to another house")

    # Tell the device to wipe its credentials and reboot into provisioning mode.
    # If it's offline now, the unknown-device check at WS identify will
    # factory-reset it whenever it next connects.
    device_was_online = device_id in manager.active_connections
    if device_was_online:
        await manager.send_personal_message(
            json.dumps({"id": device_id, "cmd": "factory_reset"}), device_id)

    # ORM cascade removes SmartExtension -> Relays -> Permissions
    db.delete(device)
    db.query(Heartbeat).filter(Heartbeat.device_id == device_id).delete()
    db.commit()
    manager.device_info.pop(device_id, None)
    return {"status": "deleted", "device_id": device_id, "device_reset": device_was_online}


@app.get("/api/devices")
async def get_devices(db: Session = Depends(get_db), current_auth: dict = Depends(get_current_user_or_child)):
    is_admin = current_auth["role"] == "admin"
    house_id = current_auth["house_id"]
    
    if is_admin:
        devices_db = db.query(Device).all()
    else:
        devices_db = db.query(Device).filter(Device.house_id == house_id).all()
        
    devices = []
    for device_db in devices_db:
        device_id = device_db.device_id
        info = manager.device_info.get(device_id, {})
        
        ext = db.query(SmartExtension).filter(SmartExtension.device_id == device_id).first()
        ch1 = "off"
        ch2 = "off"
        ch3 = "off"
        if ext:
            relays = db.query(Relay).filter(Relay.se_id == ext.se_id).all()
            for r in relays:
                if r.channel_number == 1:
                    ch1 = "on" if r.is_on else "off"
                elif r.channel_number == 2:
                    ch2 = "on" if r.is_on else "off"
                elif r.channel_number == 3:
                    ch3 = "on" if r.is_on else "off"
        else:
            ch1 = info.get("ch1", "off")
            ch2 = info.get("ch2", "off")
            ch3 = info.get("ch3", "off")
            
        latest_hb = (
            db.query(Heartbeat)
            .filter(Heartbeat.device_id == device_id)
            .order_by(Heartbeat.timestamp.desc())
            .first()
        )
        devices.append({
            "device_id": device_id,
            "name": device_db.name,
            "ip": info.get("ip"),
            "last_uptime_ms": info.get("uptime_ms"),
            "last_heartbeat": latest_hb.timestamp.isoformat() if latest_hb and latest_hb.timestamp else None,
            "ch1": ch1,
            "ch2": ch2,
            "ch3": ch3,
            "blocked": device_db.blocked,
            "online": device_id in manager.active_connections,
        })
    unidentified_count = len(manager.unidentified_connections) if is_admin else 0
    return {"devices": devices, "unidentified_count": unidentified_count}


@app.get("/api/devices/{device_id}")
async def get_device_status(device_id: str, db: Session = Depends(get_db), current_auth: dict = Depends(get_current_user_or_child)):
    device_db = db.query(Device).filter(Device.device_id == device_id).first()
    if not device_db:
        raise HTTPException(status_code=404, detail="Device not found")
    if current_auth["role"] != "admin" and device_db.house_id != current_auth["house_id"]:
        raise HTTPException(status_code=403, detail="Access denied to this device")
        
    info = manager.device_info.get(device_id, {})
    online = device_id in manager.active_connections
    
    ext = db.query(SmartExtension).filter(SmartExtension.device_id == device_id).first()
    ch1 = "off"
    ch2 = "off"
    ch3 = "off"
    if ext:
        relays = db.query(Relay).filter(Relay.se_id == ext.se_id).all()
        for r in relays:
            if r.channel_number == 1:
                ch1 = "on" if r.is_on else "off"
            elif r.channel_number == 2:
                ch2 = "on" if r.is_on else "off"
            elif r.channel_number == 3:
                ch3 = "on" if r.is_on else "off"
    else:
        ch1 = info.get("ch1", "off")
        ch2 = info.get("ch2", "off")
        ch3 = info.get("ch3", "off")
        
    latest_hb = (
        db.query(Heartbeat)
        .filter(Heartbeat.device_id == device_id)
        .order_by(Heartbeat.timestamp.desc())
        .first()
    )
    return {
        "device_id": device_id,
        "name": device_db.name,
        "online": online,
        "ip": info.get("ip"),
        "uptime_ms": info.get("uptime_ms"),
        "ch1": ch1,
        "ch2": ch2,
        "ch3": ch3,
        "blocked": device_db.blocked,
        "last_heartbeat": latest_hb.timestamp.isoformat() if latest_hb and latest_hb.timestamp else None,
    }


def _capability_label_overrides(db: Session, device: Device) -> dict[str, str]:
    """The house's own names for the three channels.

    §5.1 gives the app's label precedence over the firmware's. Today a member
    renames a channel through `Relay.name`, so those names are mapped onto the
    `ch1`/`ch2`/`ch3` capability keys here. When step 2 lets a member rename any
    capability, this is the function that grows a second source.
    """
    ext = db.query(SmartExtension).filter(SmartExtension.device_id == device.device_id).first()
    if not ext:
        return {}
    out = {}
    for relay in db.query(Relay).filter(Relay.se_id == ext.se_id).all():
        if relay.name and relay.channel_number in (1, 2, 3):
            out[f"ch{relay.channel_number}"] = relay.name
    return out


def _device_in_house_or_404(db: Session, device_id: str, house_id) -> Device:
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if device.house_id != house_id:
        raise HTTPException(status_code=403, detail="Device does not belong to your house")
    return device


@app.get("/api/devices/{device_id}/capabilities")
async def get_device_capabilities(device_id: str, db: Session = Depends(get_db),
                                  current_auth: dict = Depends(get_current_user_or_child)):
    """What this device says it can do, and its current values (PROTOCOL.md §5).

    Every device has an answer here: one that declared nothing is served the
    three switches the server synthesised for it, so a caller never has to know
    which protocol the firmware speaks.
    """
    device = _device_in_house_or_404(db, device_id, current_auth["house_id"])
    payload = capability_store.descriptor_payload(
        db, device, label_overrides=_capability_label_overrides(db, device))
    return {"device_id": device_id, "name": device.name,
            "blocked": bool(device.blocked), "status": device.status, **payload}


@app.post("/api/devices/{device_id}/capability")
async def set_device_capability(device_id: str, payload: dict,
                                db: Session = Depends(get_db),
                                current_auth: dict = Depends(get_current_user_or_child)):
    """Set capabilities by key: {"values": {"ch1": "on", "speed": 60}} (§6.2).

    The generic replacement for `POST /command`, which stays for the app, the
    Open API and Maya until steps 2 and 3 move them over. A capability declared
    `confirm:true` also needs `"confirmed": true`, which the client sends only
    after a human has said yes (§5.4).
    """
    device = _device_in_house_or_404(db, device_id, current_auth["house_id"])
    if device.blocked:
        return {"status": "blocked", "device_id": device_id}

    values = payload.get("values")
    if not isinstance(values, dict) or not values:
        raise HTTPException(status_code=400, detail="values object required")

    if current_auth["role"] == "child":
        # Permissions are per relay channel today, so a child is held to exactly
        # the rights they already have: the three channel keys go through the
        # same check as a manual tap, and anything else is refused outright
        # rather than silently allowed. Per-capability permissions need the
        # `Permission` table to key on a capability instead of a relay — a
        # schema change that belongs with the app work in step 2.
        for key in values:
            if key not in ("ch1", "ch2", "ch3"):
                raise HTTPException(
                    status_code=403,
                    detail=f"Children cannot set {key} yet — only the relay channels")
            channel = int(key[-1])
            denial = _child_command_denial(db, current_auth["child"].child_id,
                                           device_id, "on", channel)
            if denial:
                raise HTTPException(status_code=403, detail=denial)

    result = await _dispatch_set(db, device_id, values,
                                 confirmed=payload.get("confirmed") is True)
    if result.get("status") == "ok":
        db.commit()          # _dispatch_set merged nothing, but the ack handler may have
        if current_auth["type"] == "child":
            actor_type, actor_id, actor_name = ("child", current_auth["child"].child_id,
                                                current_auth["child"].name)
        else:
            actor_type, actor_id, actor_name = ("parent", current_auth["user"].acc_id,
                                                current_auth["user"].name)
        labels = {c.key: c.label for c in capability_store.load_capabilities(db, device_id)}
        overrides = _capability_label_overrides(db, device)
        described = ", ".join(
            f'"{overrides.get(k, labels.get(k, k))}" to {v}' for k, v in values.items())
        log_activity(db, device.house_id, actor_type, actor_id, actor_name,
                     "device_switch", f"{actor_name} set {described} on {device.name}")
        db.commit()
    return result


@app.post("/api/devices/{device_id}/block")
async def block_device(device_id: str, payload: dict, db: Session = Depends(get_db),
                       current_user: Account = Depends(get_current_user)):
    if current_user.role != AccountRole.admin:
        raise HTTPException(status_code=403, detail="Only admins can block devices")
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    device.blocked = payload.get("blocked", True)
    db.commit()
    return {"device_id": device_id, "blocked": device.blocked}


@app.post("/api/devices/{device_id}/command")
async def send_device_command(device_id: str, payload: dict,
                              db: Session = Depends(get_db),
                              current_auth: dict = Depends(get_current_user_or_child)):
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if device.house_id != current_auth["house_id"]:
        raise HTTPException(status_code=403, detail="Device does not belong to your house")
    if device.blocked:
        return {"status": "blocked", "device_id": device_id}

    cmd = payload.get("cmd", "")
    channel = payload.get("channel", 1)

    if current_auth["role"] == "child":
        denial = _child_command_denial(db, current_auth["child"].child_id, device_id, cmd, channel)
        if denial:
            raise HTTPException(status_code=403, detail=denial)

    result = await _dispatch_command(device_id, cmd, channel)
    if result.get("status") == "ok":
        if current_auth["type"] == "child":
            actor_type, actor_id, actor_name = "child", current_auth["child"].child_id, current_auth["child"].name
        else:
            actor_type, actor_id, actor_name = "parent", current_auth["user"].acc_id, current_auth["user"].name
        label = _channel_label(db, device, channel) if cmd in ("on", "off", "output_on", "output_off") else device.name
        verb = "ON" if cmd in ("on", "output_on") else "OFF" if cmd in ("off", "output_off") else cmd
        log_activity(db, device.house_id, actor_type, actor_id, actor_name,
                     "device_switch", f'{actor_name} turned {verb} "{label}"')
        db.commit()
    return result


def _child_command_denial(db: Session, child_id: int, device_id: str, cmd: str, channel: int) -> str | None:
    """Return a human-readable reason a child may NOT run this command, or None
    if allowed. Shared by the JWT command endpoint and the Maya AI path so the
    permission rule lives in exactly one place."""
    ext = db.query(SmartExtension).filter(SmartExtension.device_id == device_id).first()
    if not ext:
        return "Smart extension not found for device"
    if cmd in ("all_on", "all_off"):
        relays = db.query(Relay).filter(Relay.se_id == ext.se_id).all()
        for r in relays:
            perm = db.query(Permission).filter(
                Permission.child_id == child_id,
                Permission.relay_id == r.relay_id
            ).first()
            if not perm or not perm.is_allowed:
                return f"Permission denied for channel {r.channel_number}"
        return None
    relay = db.query(Relay).filter(Relay.se_id == ext.se_id, Relay.channel_number == channel).first()
    if not relay:
        return "Relay channel not found"
    perm = db.query(Permission).filter(
        Permission.child_id == child_id,
        Permission.relay_id == relay.relay_id
    ).first()
    if not perm or not perm.is_allowed:
        return "You do not have permission to control this channel"
    return None


# The firmware only understands output_on/output_off (see smartextension.ino);
# on/off are the API-facing verbs. Normalise here so every caller — the app, the
# Open API and Maya — speaks the firmware's dialect. all_on/all_off pass through.
_FIRMWARE_CMD = {"on": "output_on", "off": "output_off"}


_req_counter = 0


def _next_req() -> str:
    """Correlation id for a v2 command (§6.2). Acks are still matched per device
    by `ConnectionManager.pending_commands` — one outstanding command each — so
    `req` is a cross-check that the ack belongs to the command we are waiting on,
    not the keying mechanism."""
    global _req_counter
    _req_counter += 1
    return f"c-{_req_counter}"


async def _dispatch_set(db: Session, device_id: str, values: dict,
                        confirmed: bool = False) -> dict:
    """Set one or more capabilities on a protocol-2 device (§6.2).

    Values are validated against what the device declared at identify time
    before anything is sent, so a bad value is a 400 from us rather than a
    `bad_value` ack after a round trip. The reply carries the device's own state
    echo, which is what the caller should believe over what it asked for.

    `confirmed` carries the evidence for §5.4's `confirm:true`: a client acting
    for a present human — the app after its confirm step, or Maya after an
    explicit yes in the turn she asked. The gate is here rather than in those
    clients because the same capability is reachable from every caller, and a
    flag enforced only in clients is enforced nowhere.
    """
    caps = {c.key: c for c in capability_store.load_capabilities(db, device_id)}
    if not caps:
        return {"status": "unsupported", "device_id": device_id,
                "detail": "device has no declared capabilities"}

    resolved = {}
    for key, raw in values.items():
        cap = caps.get(key)
        if cap is None:
            return {"status": "unknown_capability", "device_id": device_id, "key": key}
        if not cap.writable:
            return {"status": "not_permitted", "device_id": device_id, "key": key,
                    "detail": f"{key} is read-only"}
        if cap.confirm and not confirmed:
            return {"status": "not_permitted", "device_id": device_id, "key": key,
                    "needs_confirmation": True,
                    "detail": f"{cap.label} needs confirming before it can be set"}
        try:
            resolved[key] = coerce_value(cap, raw)
        except ValueError as e:
            return {"status": "bad_value", "device_id": device_id, "key": key,
                    "detail": str(e)}

    req = _next_req()
    payload = json.dumps({"id": device_id, "type": "set", "req": req, "values": resolved})
    waiter = manager.arm_ack(device_id)
    if not await manager.send_personal_message(payload, device_id):
        manager.disarm_ack(device_id)
        return {"status": "not_connected", "device_id": device_id}
    ack = await manager.wait_for_ack(device_id, timeout=5.0, future=waiter)
    if not ack:
        return {"status": "timeout", "device_id": device_id}
    if ack.get("req") and ack.get("req") != req:
        # An ack for a command that is not this one. Treat it as a failure rather
        # than reporting someone else's success.
        return {"status": "busy", "device_id": device_id}
    status = ack.get("status", "ok")
    echoed = ack.get("state") if isinstance(ack.get("state"), dict) else {}
    out = {"status": status, "device_id": device_id,
           "state": echoed or ({} if status != "ok" else resolved)}
    # §6.2: a partial failure names the capability it stopped at, and the state
    # it reports is what did apply before that. Pass both through — the caller
    # cannot act on "something went wrong" without knowing which thing.
    if ack.get("failed"):
        out["failed"] = ack["failed"]
    return out


async def _dispatch_command(device_id: str, cmd: str, channel: int) -> dict:
    """Send a relay command to a connected device and wait for its ack.
    Shared by the JWT command endpoint, the Open API, and Maya."""
    cmd = _FIRMWARE_CMD.get(cmd, cmd)
    cmd_payload = json.dumps({"id": device_id, "cmd": cmd, "channel": channel})
    waiter = manager.arm_ack(device_id)
    success = await manager.send_personal_message(cmd_payload, device_id)
    if not success:
        manager.disarm_ack(device_id)
        return {"status": "not_connected", "device_id": device_id}
    ack = await manager.wait_for_ack(device_id, timeout=5.0, future=waiter)
    if ack:
        return {"status": "ok", "device_id": device_id, **{k: ack.get(k) for k in ("ch1", "ch2", "ch3") if k in ack}}
    return {"status": "timeout", "device_id": device_id}


# ─── Activity Log ─────────────────────────────────────────────

def log_activity(db: Session, house_id: int, actor_type: str, actor_id: int | None,
                 actor_name: str, action: str, summary: str):
    """Record one meaningful house activity. Best-effort: never let logging break
    the caller's own transaction — caller commits."""
    try:
        db.add(ActivityLog(house_id=house_id, actor_type=actor_type, actor_id=actor_id,
                           actor_name=actor_name or "", action=action, summary=summary))
    except Exception as e:
        print(f"log_activity failed: {e}")


def _channel_label(db: Session, device: Device, channel: int) -> str:
    """Human name of a device channel, e.g. 'Living Room / Television'."""
    ext = db.query(SmartExtension).filter(SmartExtension.device_id == device.device_id).first()
    relay = db.query(Relay).filter(Relay.se_id == ext.se_id, Relay.channel_number == channel).first() if ext else None
    ch_name = relay.name if relay else f"Channel {channel}"
    return f"{device.name} / {ch_name}"


# ─── AI Agent (Maya) ──────────────────────────────────────────
# Triggered when a house chat message mentions @maya. Maya is a tool-using agent:
# she reads the house's recent chat + device state, may call tools (control a
# device, look up a child's location/homework/screen-time, assign homework, read
# the activity log), then replies in the chat. Every tool runs as the invoking
# sender — a child may only touch their own data and permitted channels.

MAYA_TRIGGER = "@maya"
MAYA_SENDER_ID = 0      # sentinel sender_id for AI-authored chat rows
MAYA_MAX_STEPS = 5      # cap tool-call rounds so a loop can't run forever

# In-RAM voice session memory: (house_id, auth_type, sender_id) -> {"turns":[...], "ts":datetime}.
# Gives voice commands short multi-turn context WITHOUT writing to the house chat.
# Single Fly instance, so a plain dict is enough; cleared on idle (no Redis).
# ponytail: process-local dict, swap for Redis only if we ever run >1 instance.
_voice_sessions: dict = {}
_VOICE_SESSION_TTL = timedelta(minutes=5)   # idle timeout = "session end"
_VOICE_MEM_TURNS = 8                          # user+assistant turns kept per session


def _maya_context(db: Session, house_id: int, sender_role: str, child_id: int | None) -> str:
    """House state injected into the system prompt: devices (with channel names)
    and the child roster the caller is allowed to see."""
    lines = ["House state — devices:"]
    devices = db.query(Device).filter(Device.house_id == house_id).all()
    if not devices:
        lines.append("  (none registered)")
    for d in devices:
        online = "online" if d.device_id in manager.active_connections else "offline"
        ext = db.query(SmartExtension).filter(SmartExtension.device_id == d.device_id).first()
        relays = db.query(Relay).filter(Relay.se_id == ext.se_id).all() if ext else []
        chans = ", ".join(f"ch{r.channel_number}=\"{r.name}\" ({'on' if r.is_on else 'off'})"
                          for r in sorted(relays, key=lambda r: r.channel_number))
        lines.append(f"- device_id={d.device_id} name=\"{d.name}\" ({online}) [{chans}]")

    lines.append("Children in this house:")
    if sender_role == "child":
        me = db.query(Child).filter(Child.child_id == child_id).first()
        lines.append(f"  - {me.name} (you). You may only ask about yourself." if me else "  (you)")
    else:
        kids = db.query(Child).filter(Child.house_id == house_id).all()
        lines.append("  " + ", ".join(k.name for k in kids) if kids else "  (none)")
    return "\n".join(lines)


def _maya_messages(db: Session, house_id: int, context: str) -> list:
    """[system, ...recent chat] for the model. The last chat row is the @maya
    message that triggered this run (already persisted before we were spawned)."""
    msgs = [{"role": "system", "content": ai.SYSTEM_PROMPT + "\n\n" + context}]
    rows = (db.query(MsgHistory).filter(MsgHistory.house_id == house_id)
            .order_by(MsgHistory.msg_id.desc()).limit(20).all())
    rows.reverse()
    for m in rows:
        if m.sender_type == "ai":
            msgs.append({"role": "assistant", "content": m.message})
        else:
            msgs.append({"role": "user", "content": f"{m.sender_name or 'Someone'}: {m.message}"})
    return msgs


def _resolve_child_for(db: Session, house_id: int, sender_role: str, child_id: int | None,
                       requested_name: str):
    """Resolve a tool's child_name to a Child, enforcing the privacy boundary.
    Returns (Child, None) or (None, refusal_string)."""
    if sender_role == "child":
        me = db.query(Child).filter(Child.child_id == child_id).first()
        if not me:
            return None, "child not found"
        name = (requested_name or "").strip().lower()
        if name and name != me.name.lower():
            return None, "You can only ask about yourself."
        return me, None
    name = (requested_name or "").strip().lower()
    kids = db.query(Child).filter(Child.house_id == house_id).all()
    if not name:
        return (kids[0], None) if len(kids) == 1 else (None, "Which child? Please name them.")
    exact = [k for k in kids if k.name.lower() == name]
    part = exact or [k for k in kids if name in k.name.lower()]
    if not part:
        return None, f"No child named '{requested_name}' in this house."
    return part[0], None


async def _execute_maya_tool(db: Session, house_id: int, sender_role: str, sender_id: int,
                             sender_name: str, child_id: int | None, name: str, args: dict) -> str:
    """Run one tool call as the invoking sender and return a text result for the
    model. All permission/privacy enforcement lives here."""
    try:
        if name == "control_device":
            device = db.query(Device).filter(
                Device.device_id == str(args.get("device_id", "")), Device.house_id == house_id).first()
            if not device:
                return "Error: no such device in this house."
            if device.blocked:
                return f"Error: {device.name} is blocked."
            cmd = str(args.get("cmd", ""))
            channel = args.get("channel", 1)
            if not isinstance(channel, int) or not 1 <= channel <= 3:
                channel = 1
            if cmd not in ("on", "off", "all_on", "all_off"):
                return "Error: cmd must be on/off/all_on/all_off."
            if sender_role == "child":
                denial = _child_command_denial(db, child_id, device.device_id, cmd, channel)
                if denial:
                    return f"Denied: {denial}"
            result = await _dispatch_command(device.device_id, cmd, channel)
            status = result.get("status")
            if status == "not_connected":
                return f"Error: {device.name} is offline."
            if status == "timeout":
                return f"Error: {device.name} did not respond."
            label = _channel_label(db, device, channel) if cmd in ("on", "off") else device.name
            verb = {"on": "ON", "off": "OFF", "all_on": "all ON", "all_off": "all OFF"}[cmd]
            log_activity(db, house_id, "ai", sender_id, sender_name,
                         "device_switch", f'{sender_name} turned {verb} "{label}" (via Maya)')
            db.commit()
            return f"Done: {label} is now {verb}."

        if name in ("get_child_location", "list_homework", "get_screen_time"):
            child, err = _resolve_child_for(db, house_id, sender_role, child_id, args.get("child_name", ""))
            if err:
                return err
            if name == "get_child_location":
                if child.last_lat is None:
                    return f"No location on record for {child.name}."
                when = child.last_seen_at.isoformat() if child.last_seen_at else "unknown time"
                return f"{child.name} was near {child.last_lat:.5f},{child.last_lng:.5f} at {when} (UTC)."
            if name == "list_homework":
                hw = db.query(Homework).filter(Homework.child_id == child.child_id) \
                    .order_by(Homework.is_done, Homework.created_at.desc()).all()
                if not hw:
                    return f"{child.name} has no homework."
                return f"{child.name}'s homework: " + "; ".join(
                    f"{h.title}{' (due ' + h.due_date + ')' if h.due_date else ''} — {'done' if h.is_done else 'not done'}"
                    for h in hw)
            # get_screen_time
            from datetime import date as _date
            today = _date.today().isoformat()
            row = db.query(ScreenTime).filter(
                ScreenTime.child_id == child.child_id, ScreenTime.date == today).first()
            used = row.total_min if row else 0
            limit = child.daily_screen_limit_min
            if limit is None:
                return f"{child.name} used {used} min today; no limit set."
            return f"{child.name} used {used} of {limit} min today; {max(0, limit - used)} min left."

        if name == "add_homework":
            if sender_role == "child":
                return "Only a parent can assign homework."
            child, err = _resolve_child_for(db, house_id, sender_role, child_id, args.get("child_name", ""))
            if err:
                return err
            title = str(args.get("title", "")).strip()
            if not title:
                return "Error: homework needs a title."
            hw = Homework(house_id=house_id, child_id=child.child_id, title=title,
                          due_date=(args.get("due_date") or None))
            db.add(hw)
            log_activity(db, house_id, "ai", sender_id, sender_name,
                         "homework_assigned", f'{sender_name} assigned "{title}" to {child.name} (via Maya)')
            db.commit()
            return f'Assigned "{title}" to {child.name}.'

        if name == "read_activity_log":
            limit = args.get("limit", 15)
            if not isinstance(limit, int) or limit < 1:
                limit = 15
            limit = min(limit, 50)
            q = db.query(ActivityLog).filter(ActivityLog.house_id == house_id)
            if sender_role == "child":
                # A child sees only their own actions.
                q = q.filter(ActivityLog.actor_type == "child", ActivityLog.actor_id == child_id)
            rows = q.order_by(ActivityLog.created_at.desc()).limit(limit).all()
            if not rows:
                return "No recent activity."
            return "Recent activity: " + "; ".join(
                f"{r.summary} ({r.created_at.strftime('%H:%M') if r.created_at else ''})" for r in rows)

        return f"Error: unknown tool {name}."
    except Exception as e:
        db.rollback()
        print(f"Maya tool {name} error: {e}")
        return f"Error running {name}."


async def run_maya_agent(db: Session, house_id: int, sender_role: str, sender_id: int,
                         sender_name: str, child_id: int | None, messages: list) -> str:
    """Run the tool-calling loop over a prepared `messages` list and return Maya's
    reply text. Shared by the chat path (which posts the reply to chat) and the
    voice path (which returns it privately). Tool side effects still happen."""
    reply = None
    for _ in range(MAYA_MAX_STEPS):
        # ollama Client is synchronous network IO — keep it off the event loop.
        msg = await asyncio.to_thread(ai.call_model, messages)
        if getattr(msg, "tool_calls", None):
            messages.append(msg)
            for tc in msg.tool_calls:
                call = ai.tool_call_dict(tc)
                result = await _execute_maya_tool(
                    db, house_id, sender_role, sender_id, sender_name, child_id,
                    call["name"], call["arguments"])
                messages.append({"role": "tool", "content": result, "tool_name": call["name"]})
            continue
        reply = (msg.content or "").strip()
        break
    return reply or "Sorry, I couldn't finish that."


async def _run_maya(house_id: int, sender_role: str, sender_id: int, sender_name: str, message: str):
    """Background task: run the agent, then post Maya's reply to the house chat.
    Owns its own DB session; never raises into the WS loop."""
    db = SessionLocal()
    child_id = sender_id if sender_role == "child" else None
    try:
        context = _maya_context(db, house_id, sender_role, child_id)
        messages = _maya_messages(db, house_id, context)
        reply = await run_maya_agent(db, house_id, sender_role, sender_id, sender_name, child_id, messages)
        await _maya_say(db, house_id, reply)
    except HTTPException as e:
        await _maya_say(db, house_id, f"Sorry, I can't respond right now ({e.detail}).")
    except Exception as e:
        print(f"Maya error: {e}")
        await _maya_say(db, house_id, "Sorry, something went wrong on my end.")
    finally:
        db.close()


async def _maya_say(db: Session, house_id: int, text: str):
    """Persist and broadcast a Maya chat message."""
    try:
        db.rollback()  # clear any half-done tool transaction before writing the reply
        msg = MsgHistory(house_id=house_id, sender_id=MAYA_SENDER_ID,
                         sender_type="ai", sender_name="Maya", message=text)
        db.add(msg)
        db.commit()
        await manager.broadcast_to_house(house_id, {
            "type": "chat_message", "msg_id": msg.msg_id,
            "sender_id": MAYA_SENDER_ID, "sender_type": "ai", "sender_name": "Maya",
            "message": text,
            "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
        })
    except Exception as e:
        print(f"Maya failed to post message: {e}")


async def _notify_screen_limit(db: Session, child, used: int, limit: int):
    """Automation alert: a child hit their daily screen-time limit. Posts a Maya
    chat message, @-mentions every parent AND the child, logs it, and broadcasts.
    Best-effort — never let a failed alert break the report request."""
    house_id = child.house_id
    text = f"⏰ {child.name} has reached the daily screen-time limit ({used}/{limit} min today)."
    try:
        db.rollback()  # start clean; the screen_time write is already committed
        msg = MsgHistory(house_id=house_id, sender_id=MAYA_SENDER_ID,
                         sender_type="ai", sender_name="Maya", message=text)
        db.add(msg)
        db.flush()  # need msg.msg_id for the mentions
        for p in _house_mentionables(db, house_id):
            if p["type"] == "parent" or (p["type"] == "child" and p["id"] == child.child_id):
                db.add(Mention(msg_id=msg.msg_id, house_id=house_id,
                               target_type=p["type"], target_id=p["id"], seen=False))
        log_activity(db, house_id, "system", None, "Maya",
                     "screen_limit_reached",
                     f"{child.name} reached the daily screen-time limit ({used}/{limit} min)")
        db.commit()
        await manager.broadcast_to_house(house_id, {
            "type": "chat_message", "msg_id": msg.msg_id,
            "sender_id": MAYA_SENDER_ID, "sender_type": "ai", "sender_name": "Maya",
            "message": text,
            "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
        })
    except Exception as e:
        db.rollback()
        print(f"screen-limit alert failed: {e}")


def _voice_session(key: tuple) -> dict:
    """Fetch (and refresh) a caller's voice session, pruning idle ones."""
    now = datetime.now(timezone.utc)
    for k in [k for k, s in _voice_sessions.items() if now - s["ts"] > _VOICE_SESSION_TTL]:
        del _voice_sessions[k]
    sess = _voice_sessions.get(key)
    if sess is None:
        sess = {"turns": [], "ts": now}
        _voice_sessions[key] = sess
    sess["ts"] = now
    return sess


@app.post("/api/maya/voice")
async def maya_voice(payload: dict, db: Session = Depends(get_db),
                     current_auth: dict = Depends(get_current_user_or_child)):
    """Private voice command: transcript in, Maya's reply text out. Runs the full
    tool-calling agent as the caller (same permissions as chat), keeps short
    in-RAM multi-turn memory, and does NOT write to the house chat."""
    transcript = str(payload.get("transcript", "")).strip()
    if not transcript:
        raise HTTPException(status_code=400, detail="transcript required")

    # Every call here is a paid Ollama request, so this is a budget guard as much
    # as an abuse one: a loop in a client could otherwise drain the account.
    if current_auth["type"] == "child":
        caller = "child:%s" % current_auth["child"].child_id
    else:
        caller = "parent:%s" % current_auth["user"].acc_id
    VOICE_RATE.hit(caller)
    VOICE_DAY_RATE.hit(caller)

    if current_auth["type"] == "child":
        child = current_auth["child"]
        house_id, sender_role, sender_id, sender_name, child_id = (
            child.house_id, "child", child.child_id, child.name, child.child_id)
    else:
        user = current_auth["user"]
        if user.house_id is None:
            raise HTTPException(status_code=400, detail="No active house")
        house_id, sender_role, sender_id, sender_name, child_id = (
            user.house_id, "parent", user.acc_id, user.name, None)

    key = (house_id, current_auth["type"], sender_id)
    sess = _voice_session(key)

    context = _maya_context(db, house_id, sender_role, child_id)
    messages = [{"role": "system", "content": ai.SYSTEM_PROMPT + "\n\n" + context}]
    messages += sess["turns"][-_VOICE_MEM_TURNS:]
    user_turn = {"role": "user", "content": f"{sender_name}: {transcript}"}
    messages.append(user_turn)

    reply = await run_maya_agent(db, house_id, sender_role, sender_id, sender_name, child_id, messages)

    # Remember only the plain user/assistant turns (not tool rows) for context.
    sess["turns"].append(user_turn)
    sess["turns"].append({"role": "assistant", "content": reply})
    sess["turns"] = sess["turns"][-2 * _VOICE_MEM_TURNS:]
    return {"reply": reply}


# ─── Store (mock marketplace) ─────────────────────────────────
# ponytail: hardcoded catalog — swap for a Product table when real inventory exists
STORE_CATALOG = [
    {"sku": "maya-ext-3ch", "name": "Maya Smart Extension (3-Channel)",
     "description": "WiFi smart power extension with 3 individually switchable channels, BLE setup and PIN security.", "price": 149.00},
    {"sku": "maya-ext-3ch-pro", "name": "Maya Smart Extension Pro",
     "description": "3-channel smart extension with surge protection and energy monitoring.", "price": 219.00},
    {"sku": "maya-starter-kit", "name": "Maya Starter Kit",
     "description": "Two 3-channel smart extensions plus quick-start guide — everything to smarten one room.", "price": 279.00},
]


@app.get("/api/store/catalog")
async def store_catalog(current_user: Account = Depends(get_current_user)):
    return {"catalog": STORE_CATALOG}


@app.get("/api/store/public-catalog")
async def store_public_catalog():
    """Catalog for the public storefront — no auth (login is only needed to buy)."""
    return {"catalog": STORE_CATALOG}


@app.post("/api/store/orders")
async def create_order(payload: dict, db: Session = Depends(get_db),
                       current_user: Account = Depends(get_current_user)):
    if not current_user.house_id:
        raise HTTPException(status_code=400, detail="Account has no house")
    sku = payload.get("sku", "")
    item = next((i for i in STORE_CATALOG if i["sku"] == sku), None)
    if not item:
        raise HTTPException(status_code=404, detail="Unknown product")
    order = Order(
        house_id=current_user.house_id, acc_id=current_user.acc_id,
        sku=item["sku"], item_name=item["name"], price=item["price"],  # price from catalog, never the client
    )
    db.add(order)
    db.commit()
    return {"order_id": order.order_id, "status": order.status,
            "item_name": order.item_name, "price": order.price}


@app.get("/api/store/orders")
async def list_orders(db: Session = Depends(get_db),
                      current_user: Account = Depends(get_current_user)):
    orders = db.query(Order).filter(Order.house_id == current_user.house_id) \
        .order_by(Order.created_at.desc()).all()
    return {"orders": [{
        "order_id": o.order_id, "sku": o.sku, "item_name": o.item_name,
        "price": o.price, "status": o.status,
        "created_at": o.created_at.isoformat() if o.created_at else None,
    } for o in orders]}


# ─── Permission Endpoints ─────────────────────────────────────

@app.post("/api/permissions")
async def create_permission(payload: dict, db: Session = Depends(get_db),
                            current_user: Account = Depends(get_current_user)):
    if current_user.role not in (AccountRole.parent, AccountRole.admin):
        raise HTTPException(status_code=403, detail="Only parents/admins can set permissions")
    child_id = payload.get("child_id")
    relay_id = payload.get("relay_id")
    is_allowed = payload.get("is_allowed", True)
    if not child_id or not relay_id:
        raise HTTPException(status_code=400, detail="child_id and relay_id required")
        
    child = db.query(Child).filter(Child.child_id == child_id).first()
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    if current_user.role != AccountRole.admin and child.house_id != current_user.house_id:
        raise HTTPException(status_code=403, detail="Child does not belong to your house")
        
    relay = db.query(Relay).filter(Relay.relay_id == relay_id).first()
    if not relay:
        raise HTTPException(status_code=404, detail="Relay not found")
    ext = db.query(SmartExtension).filter(SmartExtension.se_id == relay.se_id).first()
    if not ext:
        raise HTTPException(status_code=404, detail="Smart extension not found")
    device = db.query(Device).filter(Device.device_id == ext.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if current_user.role != AccountRole.admin and device.house_id != current_user.house_id:
        raise HTTPException(status_code=403, detail="Device does not belong to your house")
        
    perm = Permission(child_id=child_id, relay_id=relay_id, is_allowed=is_allowed)
    db.add(perm)
    db.commit()
    return {"permission_id": perm.permission_id, "child_id": child_id, "relay_id": relay_id, "is_allowed": is_allowed}


@app.get("/api/permissions")
async def list_permissions(child_id: int | None = None, db: Session = Depends(get_db),
                           current_auth: dict = Depends(get_current_user_or_child)):
    if current_auth["type"] == "child":
        # Children can only ever see their own permissions.
        perms = db.query(Permission).filter(
            Permission.child_id == current_auth["child"].child_id).all()
        return {"permissions": [
            {"permission_id": p.permission_id, "child_id": p.child_id, "relay_id": p.relay_id, "is_allowed": p.is_allowed}
            for p in perms
        ]}
    current_user = current_auth["user"]
    if current_user.role == AccountRole.admin:
        q = db.query(Permission)
        if child_id:
            q = q.filter(Permission.child_id == child_id)
        perms = q.all()
    else:
        if child_id:
            child = db.query(Child).filter(Child.child_id == child_id).first()
            if not child or child.house_id != current_user.house_id:
                raise HTTPException(status_code=403, detail="Child not found or access denied")
            perms = db.query(Permission).filter(Permission.child_id == child_id).all()
        else:
            children_ids = [c.child_id for c in db.query(Child).filter(Child.house_id == current_user.house_id).all()]
            perms = db.query(Permission).filter(Permission.child_id.in_(children_ids)).all()
            
    return {"permissions": [
        {"permission_id": p.permission_id, "child_id": p.child_id, "relay_id": p.relay_id, "is_allowed": p.is_allowed}
        for p in perms
    ]}


@app.put("/api/permissions/{permission_id}")
async def update_permission(permission_id: int, payload: dict, db: Session = Depends(get_db),
                            current_user: Account = Depends(get_current_user)):
    perm = db.query(Permission).filter(Permission.permission_id == permission_id).first()
    if not perm:
        raise HTTPException(status_code=404, detail="Permission not found")
    if current_user.role != AccountRole.admin:
        child = db.query(Child).filter(Child.child_id == perm.child_id).first()
        if not child or child.house_id != current_user.house_id:
            raise HTTPException(status_code=403, detail="Access denied")
    if "is_allowed" in payload:
        perm.is_allowed = payload["is_allowed"]
    db.commit()
    return {"permission_id": perm.permission_id, "is_allowed": perm.is_allowed}


@app.delete("/api/permissions/{permission_id}")
async def delete_permission(permission_id: int, db: Session = Depends(get_db),
                            current_user: Account = Depends(get_current_user)):
    perm = db.query(Permission).filter(Permission.permission_id == permission_id).first()
    if not perm:
        raise HTTPException(status_code=404, detail="Permission not found")
    if current_user.role != AccountRole.admin:
        child = db.query(Child).filter(Child.child_id == perm.child_id).first()
        if not child or child.house_id != current_user.house_id:
            raise HTTPException(status_code=403, detail="Access denied")
    db.delete(perm)
    db.commit()
    return {"status": "deleted"}


@app.put("/api/relays/{relay_id}")
async def rename_relay(relay_id: int, payload: dict, db: Session = Depends(get_db),
                       current_user: Account = Depends(get_current_user)):
    """Rename a relay channel (e.g. 'Television'). Device-managers only. The name
    is a server-side label — the firmware still addresses channels by number, and
    Maya maps the name to a channel from the house context."""
    if not _user_can_manage_devices(db, current_user):
        raise HTTPException(status_code=403, detail="Only the house owner (or authorized members) can rename channels")
    relay = db.query(Relay).filter(Relay.relay_id == relay_id).first()
    if not relay:
        raise HTTPException(status_code=404, detail="Relay not found")
    ext = db.query(SmartExtension).filter(SmartExtension.se_id == relay.se_id).first()
    device = db.query(Device).filter(Device.device_id == ext.device_id).first() if ext else None
    if not device or (current_user.role != AccountRole.admin and device.house_id != current_user.house_id):
        raise HTTPException(status_code=403, detail="Relay belongs to another house")
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    relay.name = name[:40]
    db.commit()
    return {"relay_id": relay.relay_id, "name": relay.name, "channel_number": relay.channel_number}


@app.get("/api/activity")
async def get_activity(limit: int = 30, db: Session = Depends(get_db),
                       current_auth: dict = Depends(get_current_user_or_child)):
    """Recent house activity. Parents see the whole house; a child sees only their
    own actions."""
    house_id = current_auth["house_id"]
    if not house_id:
        return {"activity": []}
    limit = max(1, min(limit, 100))
    q = db.query(ActivityLog).filter(ActivityLog.house_id == house_id)
    if current_auth["type"] == "child":
        q = q.filter(ActivityLog.actor_type == "child",
                     ActivityLog.actor_id == current_auth["child"].child_id)
    rows = q.order_by(ActivityLog.created_at.desc()).limit(limit).all()
    return {"activity": [{
        "id": r.id, "actor_type": r.actor_type, "actor_name": r.actor_name,
        "action": r.action, "summary": r.summary,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]}


@app.get("/api/relays")
async def get_relays(db: Session = Depends(get_db), current_auth: dict = Depends(get_current_user_or_child)):
    house_id = current_auth["house_id"]
    if not house_id:
        return {"relays": []}
    devices = db.query(Device).filter(Device.house_id == house_id).all()
    device_ids = [d.device_id for d in devices]
    extensions = db.query(SmartExtension).filter(SmartExtension.device_id.in_(device_ids)).all()
    ext_map = {e.se_id: e.device_id for e in extensions}
    se_ids = list(ext_map.keys())
    relays = db.query(Relay).filter(Relay.se_id.in_(se_ids)).all() if se_ids else []
    return {
        "relays": [
            {
                "relay_id": r.relay_id,
                "se_id": r.se_id,
                "name": r.name,
                "channel_number": r.channel_number,
                "is_on": r.is_on,
                "device_id": ext_map.get(r.se_id)
            }
            for r in relays
        ]
    }


# ─── Messaging ─────────────────────────────────────────────────

@app.post("/api/messages")
async def send_message(payload: dict, db: Session = Depends(get_db),
                       current_auth: dict = Depends(get_current_user_or_child)):
    house_id = current_auth["house_id"]
    if not house_id:
        raise HTTPException(status_code=400, detail="Caller has no house")
        
    sender_id = current_auth["user"].acc_id if current_auth["type"] == "user" else current_auth["child"].child_id
    sender_type = current_auth["role"]
    
    msg = MsgHistory(
        house_id=house_id,
        sender_id=sender_id,
        sender_type=sender_type,
        message=payload.get("message", "").strip(),
    )
    db.add(msg)
    db.commit()
    return {"msg_id": msg.msg_id, "timestamp": msg.timestamp.isoformat() if msg.timestamp else None}


@app.get("/api/messages")
async def get_messages(limit: int = 50, db: Session = Depends(get_db),
                       current_auth: dict = Depends(get_current_user_or_child)):
    house_id = current_auth["house_id"]
    if not house_id:
        return {"messages": []}
    msgs = (
        db.query(MsgHistory)
        .filter(MsgHistory.house_id == house_id)
        .order_by(MsgHistory.timestamp.desc())
        .limit(limit)
        .all()
    )
    return {"messages": [
        {"msg_id": m.msg_id, "sender_id": m.sender_id, "sender_type": m.sender_type, "message": m.message,
         "timestamp": m.timestamp.isoformat() if m.timestamp else None}
        for m in reversed(msgs)
    ]}


# ─── Admin Endpoints ──────────────────────────────────────────

@app.get("/api/admin/users")
async def admin_list_users(db: Session = Depends(get_db),
                           current_user: Account = Depends(get_current_user)):
    if current_user.role != AccountRole.admin:
        raise HTTPException(status_code=403, detail="Admin only")
    accounts = db.query(Account).all()
    return {"users": [
        {"acc_id": a.acc_id, "email": a.email, "name": a.name, "role": a.role.value, "house_id": a.house_id}
        for a in accounts
    ]}


@app.get("/api/admin/logs")
async def admin_get_logs(limit: int = 100, db: Session = Depends(get_db),
                         current_user: Account = Depends(get_current_user)):
    if current_user.role != AccountRole.admin:
        raise HTTPException(status_code=403, detail="Admin only")
    heartbeats = db.query(Heartbeat).order_by(Heartbeat.timestamp.desc()).limit(limit).all()
    return {"logs": [
        {"id": h.id, "device_id": h.device_id, "uptime_ms": h.uptime_ms, "ip_address": h.ip_address,
         "ch1": h.ch1, "ch2": h.ch2, "ch3": h.ch3,
         "timestamp": h.timestamp.isoformat() if h.timestamp else None}
        for h in heartbeats
    ]}


@app.put("/api/admin/users/{user_id}")
async def admin_update_user(user_id: int, payload: dict, db: Session = Depends(get_db),
                            current_user: Account = Depends(get_current_user)):
    if current_user.role != AccountRole.admin:
        raise HTTPException(status_code=403, detail="Admin only")
    user = db.query(Account).filter(Account.acc_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if "name" in payload:
        user.name = payload["name"]
    if "email" in payload:
        user.email = payload["email"]
    if "role" in payload:
        try:
            user.role = AccountRole(payload["role"])
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid role")
    if "password" in payload and payload["password"]:
        user.password = hash_password(payload["password"])
    db.commit()
    return {"acc_id": user.acc_id, "email": user.email, "name": user.name, "role": user.role.value}


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(user_id: int, db: Session = Depends(get_db),
                             current_user: Account = Depends(get_current_user)):
    if current_user.role != AccountRole.admin:
        raise HTTPException(status_code=403, detail="Admin only")
    user = db.query(Account).filter(Account.acc_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()
    return {"status": "deleted"}


# ─── Legacy Status Endpoint (backward compat) ─────────────────

@app.get("/device/{device_id}/status")
async def get_device_status_legacy(device_id: str, db: Session = Depends(get_db)):
    info = manager.device_info.get(device_id, {})
    online = device_id in manager.active_connections
    return {
        "device_id": device_id,
        "online": online,
        "ip": info.get("ip"),
        "uptime_ms": info.get("uptime_ms"),
        "ch1": info.get("ch1", "off"),
        "ch2": info.get("ch2", "off"),
        "ch3": info.get("ch3", "off"),
        "last_heartbeat": info.get("last_heartbeat"),
    }


# ─── DB Dump ──────────────────────────────────────────────────

@app.get("/db")
async def get_all_data(db: Session = Depends(get_db), current_user: Account = Depends(get_current_user)):
    if current_user.role != AccountRole.admin:
        raise HTTPException(status_code=403, detail="Admin only")
    heartbeats = db.query(Heartbeat).all()
    devices = db.query(Device).all()
    accounts = db.query(Account).all()
    children = db.query(Child).all()
    return {
        "heartbeats": [
            {"id": h.id, "device_id": h.device_id, "uptime_ms": h.uptime_ms,
             "ip_address": h.ip_address, "ch1": h.ch1, "ch2": h.ch2, "ch3": h.ch3,
             "timestamp": h.timestamp.isoformat() if h.timestamp else None}
            for h in heartbeats
        ],
        "devices": [{"device_id": d.device_id, "name": d.name, "status": d.status, "blocked": d.blocked} for d in devices],
        "accounts": [{"acc_id": a.acc_id, "email": a.email, "name": a.name, "role": a.role.value} for a in accounts],
        "children": [{"child_id": c.child_id, "name": c.name, "house_id": c.house_id} for c in children],
    }


# ─── WebSocket Handler ────────────────────────────────────────

def _mirror_channels_to_relays(db: Session, device_id: str, state: dict) -> None:
    """Keep `Relay.is_on` in step with the `ch1`/`ch2`/`ch3` capability values.

    Step 1 deliberately runs both representations at once: `Relay` is what the
    app and Maya read today, `capability_state` is what they will read after step
    2. Writing both means neither side has to change in the same commit, which is
    the whole point of the migration order in §10.
    """
    ext = db.query(SmartExtension).filter(SmartExtension.device_id == device_id).first()
    if not ext:
        return
    for channel, key in enumerate(("ch1", "ch2", "ch3"), start=1):
        if key not in state:
            continue
        relay = db.query(Relay).filter(Relay.se_id == ext.se_id,
                                       Relay.channel_number == channel).first()
        if relay:
            relay.is_on = (state[key] == "on")


def _record_v1_channels(db: Session, device_id: str, frame: dict) -> None:
    """Mirror a protocol-1 frame's channels into `capability_state`.

    Identify, heartbeat and ack all carry all three channels (Appendix A). Writing
    them here is what makes a shimmed device indistinguishable from a v2 one as
    far as the capability tables are concerned.
    """
    values = v1_state(frame)
    if values:
        capability_store.merge_state(db, device_id, values)


async def _handle_websocket(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            print(f"Received data: {data}")

            db = SessionLocal()
            try:
                json_data = json.loads(data)
                device_id = json_data.get("id")

                if not device_id:
                    print("Received message without 'id'")
                    continue

                if websocket not in manager.active_connections.values():
                    # Unidentified connections may only identify via an "online"
                    # message; the device must present its PIN if one is set.
                    if json_data.get("status") != "online":
                        print(f"Ignoring message from unidentified connection (id={device_id})")
                        continue
                    device_db = db.query(Device).filter(Device.device_id == device_id).first()
                    if not device_db:
                        # Device was deleted (or never registered, e.g. a wiped/
                        # rebuilt server DB) — wipe it back to provisioning mode.
                        await _reset_and_close(websocket, device_id, "unknown device")
                        return
                    # PIN proves identity first, so an impostor can't probe house state
                    stored_pin = (device_db.pin or "").strip()
                    if stored_pin:
                        # The old condition skipped verification when the stored
                        # PIN was "0000" -- and "0000" was the default everywhere,
                        # so in practice this check never ran. Registration now
                        # refuses that PIN, and any stored PIN is enforced.
                        sent_pin = str(json_data.get("pin", "")).strip()
                        if not secrets.compare_digest(sent_pin, stored_pin):
                            print(f"Device {device_id} failed PIN verification. Closing connection.")
                            manager.disconnect(websocket)
                            await websocket.close(code=1008)
                            return
                    # Must still belong to a real house — rejects orphaned devices
                    # (house deleted, stale row, or DB rebuilt without this house).
                    if not _device_has_valid_house(db, device_db):
                        await _reset_and_close(websocket, device_id, "no valid house")
                        return
                    manager.identify(websocket, device_id)

                    # ─ Protocol 2 (§4, §5) ─
                    # Store what the device declares about itself, or synthesise
                    # a 3-switch descriptor for a device that declares nothing,
                    # so everything downstream sees one shape.
                    try:
                        desc = parse_identify(json_data)
                    except DescriptorError as e:
                        print(f"Device {device_id} descriptor rejected: {e}")
                        await websocket.send_text(json.dumps({
                            "id": device_id, "type": "error", "status": e.code,
                            "detail": e.detail}))
                        manager.disconnect(websocket)
                        await websocket.close(code=1009)
                        return
                    capability_store.store_descriptor(db, device_db, desc)
                    db.commit()
                    for note in desc.warnings:
                        print(f"Device {device_id} descriptor: {note}")
                    await websocket.send_text(json.dumps({
                        "id": device_id, "type": "welcome",
                        "proto": desc.proto, "server_proto_max": PROTO_MAX}))

                if json_data.get("type") == "state":
                    # §6.1 — replaces the ch1/ch2/ch3 heartbeat for v2 devices.
                    # Partial reports are allowed; the server merges.
                    caps = capability_store.load_capabilities(db, device_id)
                    written = capability_store.merge_state(
                        db, device_id, json_data.get("state") or {}, capabilities=caps)
                    uptime = json_data.get("uptime_ms", 0)
                    manager.update_device_info(device_id, uptime_ms=uptime, **{
                        k: v for k, v in written.items() if k in ("ch1", "ch2", "ch3")})
                    device_db = db.query(Device).filter(Device.device_id == device_id).first()
                    if device_db:
                        device_db.status = "online"
                    # The channel keys also feed the Relay rows the current app
                    # reads, so a v2 device that happens to expose ch1..ch3 shows
                    # up correctly before step 2 lands.
                    _mirror_channels_to_relays(db, device_id, written)
                    db.commit()
                    print(f"State from {device_id}: {written}")
                    if device_db and device_db.house_id:
                        await manager.broadcast_to_house(device_db.house_id, {
                            "type": "device_update",
                            "device_id": device_id,
                            "state": written,
                            "online": True,
                            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
                            **{k: v for k, v in written.items() if k in ("ch1", "ch2", "ch3")},
                        })

                elif json_data.get("type") == "heartbeat":
                    uptime = json_data.get("uptime_ms", 0)
                    ch1 = json_data.get("ch1", "off")
                    ch2 = json_data.get("ch2", "off")
                    ch3 = json_data.get("ch3", "off")
                    print(f"Heartbeat from {device_id}, uptime: {uptime}ms, ch1={ch1} ch2={ch2} ch3={ch3}")

                    manager.update_device_info(device_id, uptime_ms=uptime, ch1=ch1, ch2=ch2, ch3=ch3)

                    hb = Heartbeat(device_id=device_id, uptime_ms=uptime, ch1=ch1, ch2=ch2, ch3=ch3)
                    db.add(hb)
                    _record_v1_channels(db, device_id, json_data)
                    
                    ext = db.query(SmartExtension).filter(SmartExtension.device_id == device_id).first()
                    if ext:
                        for ch_num, val in [(1, ch1), (2, ch2), (3, ch3)]:
                            relay = db.query(Relay).filter(Relay.se_id == ext.se_id, Relay.channel_number == ch_num).first()
                            if relay:
                                relay.is_on = (val == "on")
                    db.commit()
                    
                    # Broadcast status update to all mobile clients in the same house
                    device_db = db.query(Device).filter(Device.device_id == device_id).first()
                    if device_db and device_db.house_id:
                        await manager.broadcast_to_house(device_db.house_id, {
                            "type": "device_update",
                            "device_id": device_id,
                            "ch1": ch1,
                            "ch2": ch2,
                            "ch3": ch3,
                            "online": True,
                            "last_heartbeat": datetime.now(timezone.utc).isoformat()
                        })

                elif json_data.get("status") == "online":
                    ip = json_data.get("ip")
                    ch1 = json_data.get("ch1", "off")
                    ch2 = json_data.get("ch2", "off")
                    ch3 = json_data.get("ch3", "off")
                    print(f"Device {device_id} is online at {ip}")

                    manager.update_device_info(device_id, ip=ip, ch1=ch1, ch2=ch2, ch3=ch3)

                    hb = Heartbeat(device_id=device_id, ip_address=ip, ch1=ch1, ch2=ch2, ch3=ch3)
                    db.add(hb)
                    _record_v1_channels(db, device_id, json_data)

                    device_db = db.query(Device).filter(Device.device_id == device_id).first()
                    if not device_db:
                        # Removed mid-session — do NOT resurrect it as a houseless
                        # zombie. The identify gate already validated it at connect,
                        # so this only happens if a master deleted it just now.
                        db.rollback()
                        continue
                    device_db.status = "online"
                    
                    ext = db.query(SmartExtension).filter(SmartExtension.device_id == device_id).first()
                    if ext:
                        for ch_num, val in [(1, ch1), (2, ch2), (3, ch3)]:
                            relay = db.query(Relay).filter(Relay.se_id == ext.se_id, Relay.channel_number == ch_num).first()
                            if relay:
                                relay.is_on = (val == "on")
                    db.commit()

                    # Broadcast status update to all mobile clients in the same house
                    device_db = db.query(Device).filter(Device.device_id == device_id).first()
                    if device_db and device_db.house_id:
                        await manager.broadcast_to_house(device_db.house_id, {
                            "type": "device_update",
                            "device_id": device_id,
                            "ch1": ch1,
                            "ch2": ch2,
                            "ch3": ch3,
                            "online": True,
                            "last_heartbeat": datetime.now(timezone.utc).isoformat()
                        })

                elif "cmd" in json_data:
                    target_id = json_data.get("target_id", device_id)
                    if target_id != device_id:
                        print(f"Routing command to {target_id}: {json_data}")
                        cmd_payload = json.dumps({
                            "id": target_id,
                            "cmd": json_data["cmd"],
                            "channel": json_data.get("channel", 1),
                        })
                        success = await manager.send_personal_message(cmd_payload, target_id)
                        if not success:
                            print(f"Target device {target_id} not connected")
                    else:
                        print(f"Command intended for self?: {json_data}")

                elif json_data.get("type") == "ack" or "status" in json_data:
                    # One branch for every ack shape (§6.1):
                    #   v1 success — {"status":"ok","ch1","ch2","ch3"}
                    #   v1 failure — {"status":"invalid_channel"}
                    #   v2         — {"type":"ack","req","status","state"}
                    # They are handled together because what differs is which
                    # payload is attached, not what has to happen: resolve the
                    # command someone is waiting on, then store whatever state
                    # arrived. Resolving on a *failure* matters — before this, an
                    # error ack matched no branch at all, so the caller sat
                    # through the full 5-second timeout for an answer that had
                    # already arrived.
                    print(f"Ack from {device_id}: {json_data}")
                    manager.resolve_ack(device_id, json_data)

                    broadcast = {"type": "device_update", "device_id": device_id,
                                 "online": True}

                    if any(k in json_data for k in ("ch1", "ch2", "ch3")):
                        # A v1 ack always carries all three channels, which is what
                        # keeps the whole relay row in sync off a single-channel
                        # command (Appendix A). Reading them with a default of
                        # "off" is only safe *because* they are all present — a v2
                        # ack carries none of them, and defaulting there would
                        # switch the row off behind the device's back.
                        ch1 = json_data.get("ch1", "off")
                        ch2 = json_data.get("ch2", "off")
                        ch3 = json_data.get("ch3", "off")
                        manager.update_device_info(device_id, ch1=ch1, ch2=ch2, ch3=ch3)
                        _record_v1_channels(db, device_id, json_data)

                        hb = db.query(Heartbeat).filter(Heartbeat.device_id == device_id).order_by(Heartbeat.timestamp.desc()).first()
                        if hb:
                            hb.ch1 = ch1
                            hb.ch2 = ch2
                            hb.ch3 = ch3

                        ext = db.query(SmartExtension).filter(SmartExtension.device_id == device_id).first()
                        if ext:
                            for ch_num, val in [(1, ch1), (2, ch2), (3, ch3)]:
                                relay = db.query(Relay).filter(Relay.se_id == ext.se_id, Relay.channel_number == ch_num).first()
                                if relay:
                                    relay.is_on = (val == "on")
                        print(f"Updated channel states: ch1={ch1} ch2={ch2} ch3={ch3}")
                        broadcast.update({"ch1": ch1, "ch2": ch2, "ch3": ch3})

                    if isinstance(json_data.get("state"), dict):
                        # A v2 ack reports typed state for the keys it touched and
                        # says nothing about the ones it did not (§6.1).
                        written = capability_store.merge_state(
                            db, device_id, json_data["state"],
                            capabilities=capability_store.load_capabilities(db, device_id))
                        _mirror_channels_to_relays(db, device_id, written)
                        if written:
                            broadcast["state"] = written
                            broadcast.update({k: v for k, v in written.items()
                                              if k in ("ch1", "ch2", "ch3")})
                            print(f"Updated capability state: {written}")

                    db.commit()

                    # Broadcast status update to all mobile clients in the same
                    # house — but only if the ack actually carried state. An error
                    # ack changes nothing and must not be announced as an update.
                    device_db = db.query(Device).filter(Device.device_id == device_id).first()
                    if device_db and device_db.house_id and len(broadcast) > 3:
                        await manager.broadcast_to_house(device_db.house_id, broadcast)


            except json.JSONDecodeError:
                print(f"Failed to parse JSON: {data}")
            except Exception as e:
                db.rollback()
                print(f"Error handling websocket message: {e}")
            finally:
                db.close()

    except WebSocketDisconnect:
        disconnected_id = None
        for cid, ws in list(manager.active_connections.items()):
            if ws == websocket:
                disconnected_id = cid
                break
        manager.disconnect(websocket)
        if disconnected_id:
            db = SessionLocal()
            try:
                device_db = db.query(Device).filter(Device.device_id == disconnected_id).first()
                if device_db:
                    device_db.status = "offline"
                    db.commit()
                    if device_db.house_id:
                        await manager.broadcast_to_house(device_db.house_id, {
                            "type": "device_offline",
                            "device_id": disconnected_id,
                            "online": False,
                        })
            finally:
                db.close()


@app.websocket("/ws/mobile")
async def mobile_websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    sender_name = "Unknown"
    sender_type = "parent"
    try:
        # Wait for first message with the auth token
        auth_msg = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
        auth_data = json.loads(auth_msg)
        token = auth_data.get("token", "")
        requested_house_id = auth_data.get("house_id")  # optional override

        from jose import jwt as jose_jwt, JWTError
        try:
            payload = jose_jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            sub = payload.get("sub")
            if sub is None:
                await websocket.close(code=4001, reason="Invalid token")
                return
        except JWTError:
            await websocket.close(code=4001, reason="Invalid token")
            return

        db = SessionLocal()
        try:
            house_id = None
            if isinstance(sub, str) and sub.startswith("child_"):
                try:
                    child_id = int(sub.split("_")[1])
                except (ValueError, IndexError):
                    await websocket.close(code=4001, reason="Invalid child ID")
                    return
                child = db.query(Child).filter(Child.child_id == child_id).first()
                if not child:
                    await websocket.close(code=4001, reason="Child not found")
                    return
                acc_id = child_id
                house_id = child.house_id
                sender_name = child.name
                sender_type = "child"
            else:
                try:
                    acc_id = int(sub)
                except ValueError:
                    await websocket.close(code=4001, reason="Invalid account ID")
                    return
                account = db.query(Account).filter(Account.acc_id == acc_id).first()
                if not account:
                    await websocket.close(code=4001, reason="User not found")
                    return
                sender_name = account.name
                sender_type = "parent"
                # Use requested house_id if provided, otherwise fall back
                if requested_house_id is not None:
                    # Verify the user is a member of that house
                    assoc = db.query(AccountHouse).filter(
                        AccountHouse.acc_id == acc_id,
                        AccountHouse.house_id == requested_house_id
                    ).first()
                    if assoc:
                        house_id = requested_house_id
                    else:
                        house_id = account.house_id
                else:
                    house_id = account.house_id
        finally:
            db.close()

        if house_id is None:
            await websocket.close(code=4001, reason="No house associated")
            return

        await manager.connect_mobile(websocket, acc_id, house_id)
        await websocket.send_text(json.dumps({"type": "auth_ok", "house_id": house_id}))

        while True:
            raw = await websocket.receive_text()
            try:
                msg_data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if msg_data.get("type") == "chat":
                message_text = msg_data.get("message", "").strip()
                if not message_text:
                    continue
                db = SessionLocal()
                try:
                    msg = MsgHistory(
                        house_id=house_id,
                        sender_id=acc_id,
                        sender_type=sender_type,
                        sender_name=sender_name,
                        message=message_text,
                    )
                    db.add(msg)
                    db.commit()
                    _record_mentions(db, house_id, msg.msg_id, message_text, sender_type, acc_id)
                    db.commit()
                    await manager.broadcast_to_house(house_id, {
                        "type": "chat_message",
                        "msg_id": msg.msg_id,
                        "sender_id": acc_id,
                        "sender_type": sender_type,
                        "sender_name": sender_name,
                        "message": message_text,
                        "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
                    })
                except Exception as e:
                    db.rollback()
                    print(f"Error saving chat message: {e}")
                finally:
                    db.close()

                # Maya responds only when explicitly mentioned, and acts as the
                # sender so a child's per-relay permissions still apply.
                if MAYA_TRIGGER in message_text.lower():
                    asyncio.create_task(
                        _run_maya(house_id, sender_type, acc_id, sender_name, message_text))

    except asyncio.TimeoutError:
        try:
            await websocket.close(code=4002, reason="Auth timeout")
        except Exception:
            pass
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"Error in mobile websocket: {e}")
    finally:
        manager.disconnect_mobile(websocket)


@app.websocket("/ws")
async def websocket_endpoint_ws(websocket: WebSocket):
    await _handle_websocket(websocket)


@app.websocket("/")
async def websocket_endpoint_root(websocket: WebSocket):
    await _handle_websocket(websocket)
