import json
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
from database import engine, Base, get_db
from models import Heartbeat

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
                    target_id = json_data.get("target_id", device_id) # if mobile sends target_id, else assume direct

                    if target_id != device_id:
                        print(f"Routing command to {target_id}: {json_data}")
                        # If routing to another device, ensure it contains 'id' for the target device
                        cmd_payload = json.dumps({"id": target_id, "cmd": json_data["cmd"]})
                        success = await manager.send_personal_message(cmd_payload, target_id)
                        if not success:
                            print(f"Target device {target_id} not connected")
                    else:
                        print(f"Command intended for self?: {json_data}")

                # Handle ack from ESP32 back to mobile
                elif json_data.get("status") == "ok":
                    # For now, just log acks
                    print(f"Ack from {device_id}: {json_data}")

            except json.JSONDecodeError:
                print(f"Failed to parse JSON: {data}")

    except WebSocketDisconnect:
        manager.disconnect(websocket)
