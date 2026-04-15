from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime
from database import Base


class Heartbeat(Base):
    __tablename__ = "heartbeats"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True)
    uptime_ms = Column(Integer)
    ip_address = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)


class DeviceState(Base):
    __tablename__ = "device_states"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, unique=True, index=True)
    led_status = Column(String, default="off")
    updated_at = Column(DateTime, default=datetime.utcnow)
