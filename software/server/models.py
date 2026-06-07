import enum
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, ForeignKey, Enum as SAEnum, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from database import Base


class AccountRole(str, enum.Enum):
    parent = "parent"
    admin = "admin"
    child = "child"


class Account(Base):
    __tablename__ = "accounts"

    acc_id = Column(Integer, primary_key=True, index=True)
    house_id = Column(Integer, ForeignKey("houses.house_id"), nullable=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    name = Column(String, nullable=False)
    role = Column(SAEnum(AccountRole), default=AccountRole.parent, nullable=False)
    is_master = Column(Boolean, default=False)
    is_home = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    house = relationship("House", back_populates="accounts")


class House(Base):
    __tablename__ = "houses"

    house_id = Column(Integer, primary_key=True, index=True)
    location = Column(String, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    accounts = relationship("Account", back_populates="house")
    children = relationship("Child", back_populates="house")
    devices = relationship("Device", back_populates="house")
    messages = relationship("MsgHistory", back_populates="house")


class Child(Base):
    __tablename__ = "children"

    child_id = Column(Integer, primary_key=True, index=True)
    house_id = Column(Integer, ForeignKey("houses.house_id"), nullable=False)
    name = Column(String, nullable=False)
    pin = Column(String, default="0000")
    is_home = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    house = relationship("House", back_populates="children")
    permissions = relationship("Permission", back_populates="child", cascade="all, delete-orphan")


class Device(Base):
    __tablename__ = "devices"

    device_id = Column(String, primary_key=True, index=True)
    house_id = Column(Integer, ForeignKey("houses.house_id"), nullable=True)
    name = Column(String, default="Smart Extension")
    status = Column(String, default="offline")
    price = Column(Float, default=0.0)
    blocked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    house = relationship("House", back_populates="devices")
    extensions = relationship("SmartExtension", back_populates="device", cascade="all, delete-orphan")


class SmartExtension(Base):
    __tablename__ = "smart_extensions"

    se_id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, ForeignKey("devices.device_id"), nullable=False)
    name = Column(String, default="Extension")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    device = relationship("Device", back_populates="extensions")
    relays = relationship("Relay", back_populates="extension", cascade="all, delete-orphan")


class Relay(Base):
    __tablename__ = "relays"
    __table_args__ = (
        UniqueConstraint('se_id', 'channel_number', name='_se_channel_uc'),
    )

    relay_id = Column(Integer, primary_key=True, index=True)
    se_id = Column(Integer, ForeignKey("smart_extensions.se_id"), nullable=False)
    name = Column(String, default="Relay")
    channel_number = Column(Integer, nullable=False)
    is_on = Column(Boolean, default=False)

    extension = relationship("SmartExtension", back_populates="relays")
    permissions = relationship("Permission", back_populates="relay", cascade="all, delete-orphan")


class Permission(Base):
    __tablename__ = "permissions"
    __table_args__ = (
        UniqueConstraint('child_id', 'relay_id', name='_child_relay_uc'),
    )

    permission_id = Column(Integer, primary_key=True, index=True)
    child_id = Column(Integer, ForeignKey("children.child_id"), nullable=False)
    relay_id = Column(Integer, ForeignKey("relays.relay_id"), nullable=False)
    is_allowed = Column(Boolean, default=True)

    child = relationship("Child", back_populates="permissions")
    relay = relationship("Relay", back_populates="permissions")


class MsgHistory(Base):
    __tablename__ = "msg_history"

    msg_id = Column(Integer, primary_key=True, index=True)
    house_id = Column(Integer, ForeignKey("houses.house_id"), nullable=False)
    sender_id = Column(Integer, nullable=False)
    sender_type = Column(String, nullable=False)
    message = Column(String, nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    house = relationship("House", back_populates="messages")


class Heartbeat(Base):
    __tablename__ = "heartbeats"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True)
    uptime_ms = Column(Integer)
    ip_address = Column(String)
    ch1 = Column(String, default="off")
    ch2 = Column(String, default="off")
    ch3 = Column(String, default="off")
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
