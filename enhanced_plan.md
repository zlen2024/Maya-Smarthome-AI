# Maya Smart Home — Enhanced Implementation Plan

## Diagram Analysis Summary

### ERD Diagram (8 entities)

| Entity | PK | Key Fields | Status |
|--------|----|-----------|----|
| **Account** | `acc_id` | house_id, email, password, name, is_master, is_home | ❌ Missing |
| **House** | `house_id` | location | ❌ Missing |
| **Device** | `device_id` | status, price, house_id | ⚠️ Partial — `DeviceState` exists but no house_id/price |
| **SmartExtension** | `se_id` | device_id, name | ❌ Missing |
| **Child** | `child_id` | house_id, name, is_home | ❌ Missing |
| **Permission** | `UniqueID` | child_id, relay_id, is_allowed | ❌ Missing |
| **Relay** | `relay_id` | name, is_on | ⚠️ Channels on ESP32 but no DB entity |
| **MsgHistory** | `msg_id` | message, sender, house_id | ❌ Missing |

### Use Case Diagram (3 actors, 14 use cases)

| Use Case | Actor(s) | Status |
|----------|----------|--------|
| Log-in | Parent, Admin | ❌ No auth |
| See device list | Parent, Child, Admin | ⚠️ Exists, no auth filter |
| Buy device | Parent | ❌ Not implemented |
| Register device | Parent, Admin | ❌ Auto-register only |
| Add device | Admin | ❌ No admin role |
| Manage device | Admin | ⚠️ Dashboard exists, no role check |
| Set device network | Parent | ⚠️ BLE only |
| Register child | Parent | ❌ Missing |
| Set permission | Parent | ❌ Missing |
| Login child | Child | ❌ Missing |
| Chat and communicate | Parent, Child | ❌ Missing |
| Get child data | Child | ❌ Missing |
| Check status | All | ⚠️ Incomplete |
| Use device | Parent, Child | ⚠️ No permission check |
| Block device | Admin | ❌ Missing |

### Class Diagram (ignoring Agent)

| Class | Status |
|-------|--------|
| **Parent** (registerChild, viewChildLocation, setRestrictions) | ❌ |
| **Child** (communicateWithParent, toggleSocket) | ❌ |
| **Account** (login, logout, updateProfile, role) | ❌ |
| **Device** (deviceName, deviceType, getDeviceInfo) | ⚠️ Minimal |
| **SmartExtension** (state, powerUsage, turnOn/Off) | ❌ |
| **Relay** (connectionStatus, open/closeConnection) | ❌ |
| **Admin** (manageUsers, viewSystemLogs, configureSystem) | ❌ |

---

## Gap Summary

**18 major gaps** between diagrams and code. The codebase only covers basic WebSocket connectivity and single-channel LED control. The diagrams envision a multi-user, multi-house smart home platform.

### Critical Missing Features
1. User authentication (Account with email/password/role)
2. House management (House entity, linking accounts)
3. Child accounts (restricted access)
4. Permission system (per-relay for children)
5. Device registration flow (server-side)
6. Relay entity (DB for channels)
7. SmartExtension entity (link ESP32 to device)
8. Messaging/Chat (MsgHistory)
9. Admin role (user management, logs, blocking)

---

## Phase 1: Database Schema Alignment

### Task 1.1–1.8: Create all ERD models
**File:** `software/server/models.py`

New models: **House**, **Account**, **Child**, **Device** (replaces DeviceState), **SmartExtension**, **Relay**, **Permission**, **MsgHistory**

Key design:
- `Device` replaces `DeviceState` — adds `house_id`, `status`, `price`
- `Relay` replaces `ch1/ch2/ch3` columns — each channel is a row
- `Account.role`: `parent | child | admin`
- `Permission` links `child_id` → `relay_id` with `is_allowed`

**Verify:** Delete `iot_data.db`, restart, all tables visible at `/db`.

---

## Phase 2: Authentication & House Management

### Task 2.1: Add auth deps
`passlib[bcrypt]`, `python-jose[cryptography]`

### Task 2.2: Auth module (`auth.py` — new)
- `hash_password`, `verify_password`, `create_access_token`, `get_current_user`

### Task 2.3: Auth endpoints

| Endpoint | Method | Use Case |
|----------|--------|----------|
| `/api/auth/register` | POST | Create account + house |
| `/api/auth/login` | POST | Log-in (returns JWT) |
| `/api/auth/me` | GET | Get profile |

### Task 2.4: House endpoints
`GET/PUT /api/houses/{id}`

### Task 2.5: Child management

| Endpoint | Method | Actor | Use Case |
|----------|--------|-------|----------|
| `/api/children` | POST | Parent | Register child |
| `/api/children` | GET | Parent | List children |
| `/api/children/{id}` | GET | Parent/Child | Get child data |
| `/api/children/{id}/login` | POST | Child | Login child |

---

## Phase 3: Device Registration, Permissions & Multi-Channel

### Task 3.1: Device registration

| Endpoint | Method | Use Case |
|----------|--------|----------|
| `/api/devices/register` | POST | Register device to house |
| `/api/devices` | GET | See device list (by house) |
| `/api/devices/{id}` | GET | Check status |
| `/api/devices/{id}/block` | POST | Block device (Admin) |

On register → auto-create 1 SmartExtension + 3 Relay rows.

### Task 3.2: Permission endpoints

| Endpoint | Method | Actor |
|----------|--------|-------|
| `/api/permissions` | POST | Parent — set |
| `/api/permissions` | GET | Parent — list |
| `/api/permissions/{id}` | PUT/DELETE | Parent — update/revoke |

### Task 3.3: Permission-checked commands
Modify `POST /api/devices/{id}/command`:
- Child → check Permission for relay → 403 if denied
- Parent/Admin → allow all

### Task 3.4–3.12: Original Plan Tasks 1–9
These stay **as-is** but adapted:
- ch state stored in `Relay` rows (not columns)
- Ack-waiting mechanism (asyncio.Future)
- Fix REST command (forward channel)
- Fix ack handler (update Relay.is_on)
- Fix heartbeat handler (sync Relay rows)
- Update status/list endpoints
- Update admin dashboard (3-channel UI)
- Verification & cleanup

---

## Phase 4: Messaging & Admin

### Task 4.1: Messaging

| Endpoint | Method | Use Case |
|----------|--------|----------|
| `/api/messages` | POST | Send message |
| `/api/messages` | GET | History (by house) |

### Task 4.2: Admin endpoints

| Endpoint | Method |
|----------|--------|
| `/api/admin/users` | GET |
| `/api/admin/users/{id}` | PUT/DELETE |
| `/api/admin/logs` | GET |

### Task 4.3: Enhanced admin dashboard
Add tabs: User management, Device blocking, Messages, Logs.

---

## Deferred (Agent-related)
- ChildData / activity tracking
- Agent monitoring
- Location tracking
- Remote wipe

---

## Files Modified

| File | Changes |
|------|---------|
| `models.py` | 8 models (House, Account, Child, Device, SmartExtension, Relay, Permission, MsgHistory) |
| `auth.py` | **New** — JWT auth |
| `main.py` | All endpoints + WebSocket fixes |
| `admin.html` | 3-channel + management UI |
| `requirements.txt` | passlib, python-jose |
| `iot_data.db` | Delete & recreate |

## Done When
- [ ] All 8 ERD entities exist as DB models
- [ ] Parent can register, login, manage children, set permissions
- [ ] Child can login with restricted access, use permitted relays only
- [ ] Devices register to houses, ch1/ch2/ch3 from Relay rows
- [ ] Messaging between parent/child works
- [ ] Admin can manage users, block devices, view logs
- [ ] Original Tasks 1–9 fully working
