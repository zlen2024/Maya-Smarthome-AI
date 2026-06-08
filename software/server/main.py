import os
import json
import random
import string
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status as http_status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session
from database import engine, Base, get_db, SessionLocal
from models import (
    Account, AccountRole, House, Child, Device, SmartExtension,
    Relay, Permission, MsgHistory, Heartbeat, AccountHouse
)
from auth import (
    hash_password, verify_password, create_access_token, get_current_user,
    get_current_user_or_child, SECRET_KEY, ALGORITHM
)

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


run_migrations()

app = FastAPI()

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

    async def wait_for_ack(self, device_id: str, timeout: float = 5.0) -> dict | None:
        future = asyncio.Future()
        self.pending_commands[device_id] = future
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
DEFAULT_ADMIN_PASSWORD_HASH = None

def get_default_admin_hash():
    global DEFAULT_ADMIN_PASSWORD_HASH
    if DEFAULT_ADMIN_PASSWORD_HASH is None:
        DEFAULT_ADMIN_PASSWORD_HASH = hash_password("admin")
    return DEFAULT_ADMIN_PASSWORD_HASH


@app.get("/", response_class=HTMLResponse)
async def root_page():
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(credentials: HTTPBasicCredentials = Depends(security_basic)):
    admin_pw_hash = os.environ.get("ADMIN_PASSWORD_HASH")
    if not admin_pw_hash:
        admin_pw_hash = get_default_admin_hash()
        
    if credentials.username != "admin" or not verify_password(credentials.password, admin_pw_hash):
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    html_path = STATIC_DIR / "admin.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


# ─── Auth Endpoints ───────────────────────────────────────────

@app.post("/api/auth/register")
async def register(payload: dict, db: Session = Depends(get_db)):
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
async def login(payload: dict, db: Session = Depends(get_db)):
    email = payload.get("email", "").strip()
    password = payload.get("password", "")
    account = db.query(Account).filter(Account.email == email).first()
    if not account or not verify_password(password, account.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
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
async def get_me(current_user: Account = Depends(get_current_user)):
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
    house = db.query(House).filter(House.house_id == house_id).first()
    if not house or house.join_pin != pin:
        raise HTTPException(status_code=403, detail="Invalid house ID or PIN")
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
            })
    return {"members": members}


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


# ─── Child Management ─────────────────────────────────────────

@app.post("/api/children")
async def create_child(payload: dict, db: Session = Depends(get_db),
                       current_user: Account = Depends(get_current_user)):
    if current_user.role not in (AccountRole.parent, AccountRole.admin):
        raise HTTPException(status_code=403, detail="Only parents/admins can register children")
    house_id = current_user.house_id
    if not house_id:
        raise HTTPException(status_code=400, detail="Account has no house")
    pin = payload.get("pin", "0000")
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
    return {"children": [{"child_id": c.child_id, "name": c.name, "is_home": c.is_home} for c in children]}


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
    if not verify_password(pin, child.pin):
        raise HTTPException(status_code=401, detail="Invalid PIN")
    token = create_access_token({"sub": f"child_{child.child_id}", "role": "child", "house_id": child.house_id})
    return {"child_id": child.child_id, "name": child.name, "token": token}


# ─── Device Registration ──────────────────────────────────────

@app.post("/api/devices/register")
async def register_device(payload: dict, db: Session = Depends(get_db),
                          current_user: Account = Depends(get_current_user)):
    if current_user.role not in (AccountRole.parent, AccountRole.admin):
        raise HTTPException(status_code=403, detail="Only parents/admins can register devices")
    house_id = current_user.house_id
    if not house_id:
        raise HTTPException(status_code=400, detail="Account has no house")
    device_id = payload.get("device_id", "").strip()
    name = payload.get("name", "Smart Extension")
    price = payload.get("price", 0.0)
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id required")
    existing = db.query(Device).filter(Device.device_id == device_id).first()
    if existing:
        existing.house_id = house_id
        existing.name = name
        existing.price = price
        existing.status = "registered"
        existing.blocked = False
        device = existing
    else:
        device = Device(device_id=device_id, house_id=house_id, name=name, price=price, status="registered")
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
    return {"device_id": device.device_id, "name": device.name, "status": device.status, "house_id": device.house_id}


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


@app.delete("/api/devices/{device_id}")
async def delete_device(device_id: str, db: Session = Depends(get_db),
                        current_user: Account = Depends(get_current_user)):
    if current_user.role not in (AccountRole.parent, AccountRole.admin):
        raise HTTPException(status_code=403, detail="Only parents/admins can unregister devices")
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if current_user.role != AccountRole.admin and device.house_id is not None and device.house_id != current_user.house_id:
        raise HTTPException(status_code=403, detail="Device does not belong to your house")
        
    ext = db.query(SmartExtension).filter(SmartExtension.device_id == device_id).first()
    if ext:
        db.query(Relay).filter(Relay.se_id == ext.se_id).delete()
        db.delete(ext)
    db.delete(device)
    db.commit()
    return {"status": "deleted", "device_id": device_id}


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
        child_id = current_auth["child"].child_id
        ext = db.query(SmartExtension).filter(SmartExtension.device_id == device_id).first()
        if not ext:
            raise HTTPException(status_code=400, detail="Smart extension not found for device")
            
        if cmd in ("all_on", "all_off"):
            relays = db.query(Relay).filter(Relay.se_id == ext.se_id).all()
            for r in relays:
                perm = db.query(Permission).filter(
                    Permission.child_id == child_id,
                    Permission.relay_id == r.relay_id
                ).first()
                if not perm or not perm.is_allowed:
                    raise HTTPException(status_code=403, detail=f"Permission denied for channel {r.channel_number}")
        else:
            relay = db.query(Relay).filter(Relay.se_id == ext.se_id, Relay.channel_number == channel).first()
            if not relay:
                raise HTTPException(status_code=400, detail="Relay channel not found")
            perm = db.query(Permission).filter(
                Permission.child_id == child_id,
                Permission.relay_id == relay.relay_id
            ).first()
            if not perm or not perm.is_allowed:
                raise HTTPException(status_code=403, detail="You do not have permission to control this channel")
                
    pin = payload.get("pin", "")
    cmd_payload = json.dumps({"id": device_id, "cmd": cmd, "channel": channel, "pin": pin})
    success = await manager.send_personal_message(cmd_payload, device_id)
    if not success:
        return {"status": "not_connected", "device_id": device_id}
    ack = await manager.wait_for_ack(device_id, timeout=5.0)
    if ack:
        return {"status": "ok", "device_id": device_id, **{k: ack.get(k) for k in ("ch1", "ch2", "ch3") if k in ack}}
    return {"status": "timeout", "device_id": device_id}


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
                           current_user: Account = Depends(get_current_user)):
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
                    manager.identify(websocket, device_id)

                if json_data.get("type") == "heartbeat":
                    uptime = json_data.get("uptime_ms", 0)
                    ch1 = json_data.get("ch1", "off")
                    ch2 = json_data.get("ch2", "off")
                    ch3 = json_data.get("ch3", "off")
                    print(f"Heartbeat from {device_id}, uptime: {uptime}ms, ch1={ch1} ch2={ch2} ch3={ch3}")

                    manager.update_device_info(device_id, uptime_ms=uptime, ch1=ch1, ch2=ch2, ch3=ch3)

                    hb = Heartbeat(device_id=device_id, uptime_ms=uptime, ch1=ch1, ch2=ch2, ch3=ch3)
                    db.add(hb)
                    
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

                    device_db = db.query(Device).filter(Device.device_id == device_id).first()
                    if not device_db:
                        device_db = Device(device_id=device_id, name="Smart Extension", status="registered")
                        db.add(device_db)
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
                            "pin": json_data.get("pin", ""),
                        })
                        success = await manager.send_personal_message(cmd_payload, target_id)
                        if not success:
                            print(f"Target device {target_id} not connected")
                    else:
                        print(f"Command intended for self?: {json_data}")

                elif json_data.get("status") == "ok":
                    print(f"Ack from {device_id}: {json_data}")
                    ch1 = json_data.get("ch1", "off")
                    ch2 = json_data.get("ch2", "off")
                    ch3 = json_data.get("ch3", "off")

                    manager.update_device_info(device_id, ch1=ch1, ch2=ch2, ch3=ch3)
                    manager.resolve_ack(device_id, json_data)

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
                    db.commit()
                    print(f"Updated channel states: ch1={ch1} ch2={ch2} ch3={ch3}")

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
                        })

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
