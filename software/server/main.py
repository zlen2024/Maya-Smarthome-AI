import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
from database import engine, Base, get_db
from models import Heartbeat, DeviceState

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI()


class ConnectionManager:
    def __init__(self):
        # Maps device/client ID to WebSocket
        self.active_connections: dict[str, WebSocket] = {}
        # Keeps track of raw websockets if we don't know their ID yet
        self.unidentified_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.unidentified_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.unidentified_connections:
            self.unidentified_connections.remove(websocket)

        # Find and remove if it's an identified connection
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


manager = ConnectionManager()


@app.get("/device/{device_id}/status")
async def get_device_status(device_id: str, db: Session = Depends(get_db)):
    """Get current LED status for a device"""
    device_state = (
        db.query(DeviceState).filter(DeviceState.device_id == device_id).first()
    )
    if device_state:
        return {
            "device_id": device_id,
            "led_status": device_state.led_status,
            "updated_at": device_state.updated_at,
        }
    return {"device_id": device_id, "led_status": "unknown"}


@app.get("/db")
async def get_all_data(db: Session = Depends(get_db)):
    """Get all database records"""
    heartbeats = db.query(Heartbeat).all()
    device_states = db.query(DeviceState).all()
    return {
        "heartbeats": [
            {
                "id": h.id,
                "device_id": h.device_id,
                "uptime_ms": h.uptime_ms,
                "ip_address": h.ip_address,
                "timestamp": h.timestamp.isoformat() if h.timestamp else None,
            }
            for h in heartbeats
        ],
        "device_states": [
            {
                "id": d.id,
                "device_id": d.device_id,
                "led_status": d.led_status,
                "updated_at": d.updated_at.isoformat() if d.updated_at else None,
            }
            for d in device_states
        ],
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, db: Session = Depends(get_db)):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            print(f"Received data: {data}")

            try:
                json_data = json.loads(data)
                device_id = json_data.get("id")

                if not device_id:
                    print("Received message without 'id'")
                    continue

                # Identify the connection if not already done
                if websocket not in manager.active_connections.values():
                    manager.identify(websocket, device_id)

                # Handle heartbeat
                if json_data.get("type") == "heartbeat":
                    uptime = json_data.get("uptime_ms", 0)
                    print(f"Heartbeat from {device_id}, uptime: {uptime}ms")

                    # Log to DB
                    db_heartbeat = Heartbeat(device_id=device_id, uptime_ms=uptime)
                    db.add(db_heartbeat)
                    db.commit()

                # Handle initial connection status from ESP32
                elif json_data.get("status") == "online":
                    ip = json_data.get("ip")
                    print(f"Device {device_id} is online at {ip}")

                    # Log to DB
                    db_heartbeat = Heartbeat(device_id=device_id, ip_address=ip)
                    db.add(db_heartbeat)
                    db.commit()

                # Handle command routing (e.g. from Mobile app to ESP32)
                elif "cmd" in json_data:
                    target_id = json_data.get(
                        "target_id", device_id
                    )  # if mobile sends target_id, else assume direct

                    if target_id != device_id:
                        print(f"Routing command to {target_id}: {json_data}")
                        # Include PIN in command payload
                        cmd_payload = json.dumps(
                            {
                                "id": target_id,
                                "cmd": json_data["cmd"],
                                "pin": json_data.get("pin", ""),
                            }
                        )
                        success = await manager.send_personal_message(
                            cmd_payload, target_id
                        )
                        if not success:
                            print(f"Target device {target_id} not connected")
                    else:
                        print(f"Command intended for self?: {json_data}")

                # Handle ack from ESP32 back to mobile
                elif json_data.get("status") == "ok":
                    print(f"Ack from {device_id}: {json_data}")

                    # Update LED status in DB if present
                    if "led" in json_data:
                        led_state = (
                            db.query(DeviceState)
                            .filter(DeviceState.device_id == device_id)
                            .first()
                        )
                        if led_state:
                            led_state.led_status = json_data["led"]
                        else:
                            led_state = DeviceState(
                                device_id=device_id, led_status=json_data["led"]
                            )
                            db.add(led_state)
                        db.commit()
                        print(f"Updated LED status: {json_data['led']}")

            except json.JSONDecodeError:
                print(f"Failed to parse JSON: {data}")

    except WebSocketDisconnect:
        manager.disconnect(websocket)
