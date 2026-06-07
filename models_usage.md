# Maya Smarthome AI - Database Models & Endpoints Usage Mapping

This document provides a detailed mapping of all database tables defined in [models.py](file:///c:/dev/fyp/Maya-Smarthome-AI/software/server/models.py) to their usage in the server's API endpoints ([main.py](file:///c:/dev/fyp/Maya-Smarthome-AI/software/server/main.py)), the ESP32 hardware client ([smartextension.ino](file:///c:/dev/fyp/Maya-Smarthome-AI/hardware/smartextension/smartextension.ino)), and the Flutter mobile application ([software/mobile/lib](file:///c:/dev/fyp/Maya-Smarthome-AI/software/mobile/lib/)).

> [!NOTE]
> All 9 tables defined in the SQLAlchemy schema are actively used by the Maya Smarthome AI ecosystem. There are no orphaned or unused database models.

---

## 📊 Summary Mapping Table

| Database Model / Table | Table Name | Key Fields | Server Endpoint(s) / WebSocket Handler | Client Location (Consumer) | Usage Purpose |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`Account`** | `accounts` | `acc_id`, `house_id`, `email`, `password`, `name`, `role`, `is_master` | `/api/auth/register`<br>`/api/auth/login`<br>`/api/auth/me`<br>`/api/admin/users`<br>`/api/admin/users/{user_id}`<br>`/db` | **Mobile App** (User Auth)<br>**Web App / Admin Dashboard** (Admin management) | User identity, authentication, role-based authorization (Parent, Admin, Child). |
| **`House`** | `houses` | `house_id`, `location`, `created_at` | `/api/auth/register`<br>`/api/houses/{house_id}`<br>`/db` | **Mobile App** (Registered during sign-up)<br>**Web App / Admin Dashboard** (Admin viewing) | Groups user accounts, devices, and child profiles into physical households. |
| **`Child`** | `children` | `child_id`, `house_id`, `name`, `pin`, `is_home` | `/api/children`<br>`/api/children/{child_id}`<br>`/api/children/{child_id}/login`<br>`/db` | **Mobile App** (Add/login child profile via PIN) | Child profile details, PIN authentication, and permission scope binding. |
| **`Device`** | `devices` | `device_id`, `house_id`, `name`, `status`, `price`, `blocked` | `/api/devices/register`<br>`/api/devices`<br>`/api/devices/{device_id}`<br>`/api/devices/{device_id}/block`<br>`/api/devices/{device_id}/command`<br>`/db`<br>WebSocket Handler (`/ws`) | **Mobile App** (Registration, list, control)<br>**Hardware Client** (Online state update)<br>**Web App / Admin Dashboard** (Block/Unblock) | Tracks physical smart extensions, their active state, connectivity, and block status. |
| **`SmartExtension`** | `smart_extensions` | `se_id`, `device_id`, `name` | `/api/devices/register`<br>`/api/devices`<br>`/api/devices/{device_id}`<br>`/api/devices/{device_id}/command`<br>`/api/permissions`<br>WebSocket Handler (`/ws`) | **Mobile App** (Device provisioning, control)<br>**Hardware Client** (State updates via WS) | Logical linking model between a registered physical Device and its Relay channels. |
| **`Relay`** | `relays` | `relay_id`, `se_id`, `name`, `channel_number`, `is_on` | `/api/devices/register`<br>`/api/devices`<br>`/api/devices/{device_id}`<br>`/api/devices/{device_id}/command`<br>`/api/permissions`<br>WebSocket Handler (`/ws`) | **Mobile App** (Individual output switch)<br>**Hardware Client** (Receives toggles, syncs state) | Stores individual channel/outlet states (CH1, CH2, CH3) for a Smart Extension. |
| **`Permission`** | `permissions` | `permission_id`, `child_id`, `relay_id`, `is_allowed` | `/api/devices/{device_id}/command`<br>`/api/permissions`<br>`/api/permissions/{permission_id}` | **Mobile App** (Parent manages permissions; Child controls outputs) | Restricts/allows child profiles from toggling specific relay channels. |
| **`MsgHistory`** | `msg_history` | `msg_id`, `house_id`, `sender_id`, `sender_type`, `message` | `/api/messages` | **Mobile App** (Household chat room/logs) | Logs message and chat history within a household. |
| **`Heartbeat`** | `heartbeats` | `id`, `device_id`, `uptime_ms`, `ip_address`, `ch1`, `ch2`, `ch3` | `/api/devices`<br>`/api/devices/{device_id}`<br>`/api/admin/logs`<br>`/db`<br>WebSocket Handler (`/ws`) | **Hardware Client** (Pushes heartbeats)<br>**Web App / Admin Dashboard** (Admin logs viewing) | Audits device network connectivity, uptime, and historic channel status. |

---

## 🔍 Detailed Usage Analysis by Table

### 1. Account Table (`Account` Model)
* **Definition File:** [models.py (Line 14-27)](file:///c:/dev/fyp/Maya-Smarthome-AI/software/server/models.py#L14-L27)
* **FastAPI Backend Usage:**
  * `register()`: Inserts a new parent account (registers email, hashed password, and details).
  * `login()`: Queries accounts by email to verify password hashes.
  * `get_me()`: Feeds account metadata back to the authenticated user.
  * `admin_list_users()`: Queries all accounts for global user administration.
  * `admin_update_user()` / `admin_delete_user()`: Updates properties (name, role, password) or deletes users from the database.
* **Client Consumers:**
  * **Mobile App:** [auth_screen.dart](file:///c:/dev/fyp/Maya-Smarthome-AI/software/mobile/lib/screens/auth_screen.dart) performs POST requests to `/api/auth/register` and `/api/auth/login` to sign in parents.
  * **Web App / Admin Dashboard:** The dashboard in `admin.html` calls `/api/admin/users` to view and modify user listings.

### 2. House Table (`House` Model)
* **Definition File:** [models.py (Line 30-41)](file:///c:/dev/fyp/Maya-Smarthome-AI/software/server/models.py#L30-L41)
* **FastAPI Backend Usage:**
  * `register()`: Automatically inserts a new house entry when a new parent registers.
  * `get_house()` / `update_house()`: Fetches or updates household locations.
* **Client Consumers:**
  * **Mobile App:** Calls `/api/auth/register` which implicitly creates a `House` block.
  * **Web App / Admin Dashboard:** The admin interface displays `house_id` associations for devices and accounts.

### 3. Child Table (`Child` Model)
* **Definition File:** [models.py (Line 43-55)](file:///c:/dev/fyp/Maya-Smarthome-AI/software/server/models.py#L43-L55)
* **FastAPI Backend Usage:**
  * `create_child()`: Creates a new child profile under the parent's house with a hashed PIN.
  * `list_children()`: Queries all children registered under a parent's household.
  * `child_login()`: Verifies a child's PIN to issue restricted access tokens.
* **Client Consumers:**
  * **Mobile App:** Parents create child profiles. Children select their profile and enter their PIN to login via `/api/children/{child_id}/login`.

### 4. Device Table (`Device` Model)
* **Definition File:** [models.py (Line 57-70)](file:///c:/dev/fyp/Maya-Smarthome-AI/software/server/models.py#L57-L70)
* **FastAPI Backend Usage:**
  * `register_device()`: Assigns a physical hardware device to a specific house.
  * `get_devices()` / `get_device_status()`: Queries device attributes to check if it is online, what IP it has, and if it is blocked.
  * `block_device()`: Updates the `blocked` status flag to restrict controls.
  * `_handle_websocket()`: When the device identifies itself with `status: online`, the server updates the device status to `"online"`.
* **Client Consumers:**
  * **Mobile App:** Fetches current states through `/api/devices` and submits commands to `/api/devices/{device_id}/command`.
  * **Hardware Client:** [smartextension.ino](file:///c:/dev/fyp/Maya-Smarthome-AI/hardware/smartextension/smartextension.ino) connects to `/ws` and fires `status: online` on startup, registering/updating itself.
  * **Web App / Admin Dashboard:** Admin triggers `/api/devices/{device_id}/block` to prevent device usage.

### 5. SmartExtension Table (`SmartExtension` Model)
* **Definition File:** [models.py (Line 72-82)](file:///c:/dev/fyp/Maya-Smarthome-AI/software/server/models.py#L72-L82)
* **FastAPI Backend Usage:**
  * `register_device()`: Ensures a logical `SmartExtension` object is created and linked to the hardware `device_id`.
  * `_handle_websocket()` / `send_device_command()` / `get_devices()`: Acts as the structural relation to query associated `Relay` channels for a device.
* **Client Consumers:**
  * **Mobile App:** Indirectly consumed through device discovery, commands, and registration.
  * **Hardware Client:** Dictates the logical setup when registering channels.

### 6. Relay Table (`Relay` Model)
* **Definition File:** [models.py (Line 84-98)](file:///c:/dev/fyp/Maya-Smarthome-AI/software/server/models.py#L84-L98)
* **FastAPI Backend Usage:**
  * `register_device()`: Populates 3 relay records (representing the 3 extension sockets/channels) in the database upon device registration.
  * `get_devices()` / `get_device_status()`: Checks individual relay states to report whether each socket is currently `"on"` or `"off"`.
  * `_handle_websocket()`: Syncs the database states with reports from WebSocket heartbeats, online packets, or command receipts.
* **Client Consumers:**
  * **Mobile App:** [control_screen.dart](file:///c:/dev/fyp/Maya-Smarthome-AI/software/mobile/lib/screens/control_screen.dart) reads individual channel statuses (`ch1`, `ch2`, `ch3`) and sends toggles.
  * **Hardware Client:** Relates directly to physical output pins (GPIO 2, 4, 5). Toggled outputs report updated states back to the server, which update the database.

### 7. Permission Table (`Permission` Model)
* **Definition File:** [models.py (Line 100-113)](file:///c:/dev/fyp/Maya-Smarthome-AI/software/server/models.py#L100-L113)
* **FastAPI Backend Usage:**
  * `send_device_command()`: Performs query validation. If the caller has a `child` role, it checks the `Permission` table. If `is_allowed` is false or missing, control is denied.
  * `create_permission()` / `list_permissions()` / `update_permission()` / `delete_permission()`: Standard CRUD actions for parents to govern child access.
* **Client Consumers:**
  * **Mobile App:** Parents manage permissions via the configuration screens. Children encounter permission restrictions if they try to turn on unauthorized extension channels.

### 8. MsgHistory Table (`MsgHistory` Model)
* **Definition File:** [models.py (Line 115-126)](file:///c:/dev/fyp/Maya-Smarthome-AI/software/server/models.py#L115-L126)
* **FastAPI Backend Usage:**
  * `send_message()`: Inserts household logs or chat messages sent by family members.
  * `get_messages()`: Fetches the message history feed for a particular home.
* **Client Consumers:**
  * **Mobile App:** Reads and sends messages to household communication channels.

### 9. Heartbeat Table (`Heartbeat` Model)
* **Definition File:** [models.py (Line 128-139)](file:///c:/dev/fyp/Maya-Smarthome-AI/software/server/models.py#L128-L139)
* **FastAPI Backend Usage:**
  * `_handle_websocket()`: WebSocket processes `heartbeat` or `online` JSON structures from the ESP32 and appends a `Heartbeat` entry.
  * `admin_get_logs()`: Queries recent heartbeats to build logs view.
  * `get_devices()`: Fetches the most recent heartbeat for a device to supply the `last_heartbeat` timestamp.
* **Client Consumers:**
  * **Hardware Client:** [smartextension.ino](file:///c:/dev/fyp/Maya-Smarthome-AI/hardware/smartextension/smartextension.ino) issues WebSocket telemetry every 30 seconds:
    ```json
    {"id": "esp32-9f83b1c1", "type": "heartbeat", "uptime_ms": 30000, "ch1": "off", "ch2": "off", "ch3": "off"}
    ```
  * **Web App / Admin Dashboard:** Renders the telemetry logs in a table view showing timestamps, IP addresses, uptime, and channel statuses.
