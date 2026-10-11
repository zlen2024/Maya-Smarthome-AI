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
    house_id = Column(Integer, ForeignKey("houses.house_id"), nullable=True)  # active house
    email = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    name = Column(String, nullable=False)
    role = Column(SAEnum(AccountRole), default=AccountRole.parent, nullable=False)
    is_master = Column(Boolean, default=False)  # kept for backward compat; canonical source is AccountHouse.is_master
    is_home = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    house = relationship("House", back_populates="accounts")
    house_associations = relationship("AccountHouse", back_populates="account", cascade="all, delete-orphan")


class House(Base):
    __tablename__ = "houses"

    house_id = Column(Integer, primary_key=True, index=True)
    location = Column(String, default="")
    join_pin = Column(String(6), nullable=True)  # 6-digit random PIN for joining
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    accounts = relationship("Account", back_populates="house")
    account_associations = relationship("AccountHouse", back_populates="house", cascade="all, delete-orphan")
    children = relationship("Child", back_populates="house")
    devices = relationship("Device", back_populates="house")
    messages = relationship("MsgHistory", back_populates="house")


class AccountHouse(Base):
    """Many-to-many association between accounts and houses."""
    __tablename__ = "account_houses"
    __table_args__ = (
        UniqueConstraint('acc_id', 'house_id', name='_acc_house_uc'),
    )

    id = Column(Integer, primary_key=True, index=True)
    acc_id = Column(Integer, ForeignKey("accounts.acc_id"), nullable=False)
    house_id = Column(Integer, ForeignKey("houses.house_id"), nullable=False)
    is_master = Column(Boolean, default=False)
    can_manage_devices = Column(Boolean, default=False)  # master-granted right to add/remove devices
    joined_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    account = relationship("Account", back_populates="house_associations")
    house = relationship("House", back_populates="account_associations")


class Child(Base):
    __tablename__ = "children"

    child_id = Column(Integer, primary_key=True, index=True)
    house_id = Column(Integer, ForeignKey("houses.house_id"), nullable=False)
    name = Column(String, nullable=False)
    # bcrypt hash of the sign-in PIN, never the digits. No default: a child row
    # created without one used to get "0000" here, and a caller that forgets the
    # PIN should fail loudly rather than inherit a known one. create_child
    # validates it through validators.normalize_child_pin.
    pin = Column(String, nullable=False)
    is_home = Column(Boolean, default=False)
    last_lat = Column(Float, nullable=True)
    last_lng = Column(Float, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    daily_screen_limit_min = Column(Integer, nullable=True)  # null = no limit
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    house = relationship("House", back_populates="children")
    capability_grants = relationship("CapabilityGrant", back_populates="child",
                                     cascade="all, delete-orphan")
    homework = relationship("Homework", back_populates="child", cascade="all, delete-orphan")


class Device(Base):
    __tablename__ = "devices"

    device_id = Column(String, primary_key=True, index=True)
    house_id = Column(Integer, ForeignKey("houses.house_id"), nullable=True)
    name = Column(String, default="Smart Extension")
    # Device security PIN, set at provisioning and verified on WS identify. Stored
    # in cleartext because the firmware holds its own copy and presents it on
    # connect. No default: "0000" here is exactly what made the identify check
    # decorative (wiki/pages/security-notes.md §7).
    pin = Column(String, nullable=False)
    status = Column(String, default="offline")
    price = Column(Float, default=0.0)
    blocked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    # ─ Protocol 2 (PROTOCOL.md §4-§5) ─
    # What the device said about itself at identify. `proto` 1 means it said
    # nothing and the server synthesised a 3-switch descriptor on its behalf, so
    # every device has a descriptor whether or not its firmware knows the word.
    proto = Column(Integer, default=1)
    model = Column(String, nullable=True)       # e.g. "smart_extension_3ch"
    fw = Column(String, nullable=True)          # firmware version string
    # Seconds the device intends to wait between reports. Null for a device that
    # holds a socket open; set by sleepy devices so the server can tell one that
    # is napping on schedule from one that has died (§5.8).
    report_every = Column(Integer, nullable=True)
    # WiFi station MAC from identify (§7.1). Pairing needs it: a receiver matches
    # the radio-level source address against the peer's MAC. Null until the
    # device has said, and a device without one cannot be paired.
    mac = Column(String, nullable=True)
    # May this device ask Maya to act (§8.2)? Off by default, set only by a person
    # who can manage devices, and re-read before every action a request takes.
    can_invoke_agent = Column(Boolean, default=False, nullable=False)
    # §5.9: a device that says it can carry other devices' reports. Self-declared at
    # identify, and it grants nothing by itself - a relay needs a person's pairing.
    is_hub = Column(Boolean, default=False, nullable=False)
    hub_channel = Column(Integer, nullable=True)   # the hub's WiFi channel, as it last reported

    house = relationship("House", back_populates="devices")
    extensions = relationship("SmartExtension", back_populates="device", cascade="all, delete-orphan")
    capabilities = relationship("DeviceCapability", back_populates="device",
                                cascade="all, delete-orphan",
                                order_by="DeviceCapability.position")
    capability_states = relationship("CapabilityState", back_populates="device",
                                     cascade="all, delete-orphan")


class SmartExtension(Base):
    __tablename__ = "smart_extensions"

    se_id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, ForeignKey("devices.device_id"), nullable=False)
    name = Column(String, default="Extension")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    device = relationship("Device", back_populates="extensions")
    relays = relationship("Relay", back_populates="extension", cascade="all, delete-orphan")


class DeviceCapability(Base):
    """One capability a device declared about itself (PROTOCOL.md §5.1).

    This table is what makes new hardware possible without a server change: the
    server stores what arrives instead of knowing device types in advance. It
    replaces nothing yet — `Relay` still drives today's three toggles — but a
    protocol-1 device gets three shimmed rows here too, so there is one shape to
    read for every device.

    Rows are rewritten wholesale on each identify: the firmware is the authority
    on what a device *can* do, and a capability that disappears from a new
    firmware build must disappear here.
    """
    __tablename__ = "device_capabilities"
    __table_args__ = (
        UniqueConstraint("device_id", "key", name="_device_capability_uc"),
    )

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, ForeignKey("devices.device_id"), nullable=False, index=True)
    key = Column(String(24), nullable=False)        # §5.1 [a-z0-9_], the permission + history key
    kind = Column(String, nullable=False)           # §5.2, closed set of ten
    label = Column(String, nullable=False)
    access = Column(String, default="rw")           # rw | r | w
    unit = Column(String, nullable=True)            # display suffix only, never parsed
    group = Column(String, nullable=True)
    # JSON array for enum options. A child table for a dropdown's choices would
    # be three joins to render one widget.
    options = Column(String, nullable=True)
    min = Column(Float, nullable=True)
    max = Column(Float, nullable=True)
    step = Column(Float, nullable=True)
    history = Column(Boolean, default=False)
    agent = Column(String, default="allow")         # §5.4 — allow | deny, unknown means deny
    confirm = Column(Boolean, default=False)
    position = Column(Integer, default=0)           # declaration order, which is display order
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    device = relationship("Device", back_populates="capabilities")


class CapabilityState(Base):
    """The current value of one capability.

    Appendix B named `Relay.is_on` as the single most load-bearing assumption in
    the codebase: it is a `Boolean`, so a number, a string or a colour cannot be
    stored in it at all. Hence a separate table, and hence `value` being JSON
    text rather than a typed column — one column holds `"on"`, `27.5`, `"#ff8800"`
    or `{"lat":…,"lng":…}`, and `descriptor.coerce_value` has already guaranteed
    the shape matches the capability's kind before it is written.
    """
    __tablename__ = "capability_state"
    __table_args__ = (
        UniqueConstraint("device_id", "key", name="_capability_state_uc"),
    )

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, ForeignKey("devices.device_id"), nullable=False, index=True)
    key = Column(String(24), nullable=False)
    value = Column(String, nullable=True)           # JSON-encoded, typed per kind
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    device = relationship("Device", back_populates="capability_states")


class CapabilityGrant(Base):
    """What a child may write, keyed on the capability key (PROTOCOL.md §5.10).

    Replaces `Permission`, which keyed on `relay_id` and so could only ever
    express "may use channel 2 of a 3-channel extension". The key is the unit
    because it is the only identifier a device promises never to renumber, and
    because "may use the fan" is not the same as "may press the fan's reset
    button".

    Three rules live in the code that writes this table, not in the schema:
    a capability the server has not seen before is denied to every child, so a
    firmware update can never widen a child's reach; a grant is deleted when its
    capability leaves the descriptor; and the grant governs *writing* only —
    reading state is house-wide.
    """
    __tablename__ = "capability_grants"
    __table_args__ = (
        UniqueConstraint("child_id", "device_id", "key", name="_child_capability_uc"),
    )

    grant_id = Column(Integer, primary_key=True, index=True)
    child_id = Column(Integer, ForeignKey("children.child_id"), nullable=False, index=True)
    device_id = Column(String, ForeignKey("devices.device_id"), nullable=False, index=True)
    key = Column(String(24), nullable=False)
    is_allowed = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    child = relationship("Child", back_populates="capability_grants")


class CapabilityLabel(Base):
    """A name a house member gave a capability (PROTOCOL.md §5.11).

    Kept out of `device_capabilities` on purpose: that table is rewritten
    wholesale on every identify, and §5.11 makes it a MUST that a firmware update
    never overwrites a name a person chose. Separate rows survive the rewrite
    without any preserve-this-column special case.

    Precedence, resolved in `capability_store.descriptor_payload`: this label,
    else the firmware's, else the key. Clearing the row *is* the reset — there is
    no third state.
    """
    __tablename__ = "capability_labels"
    __table_args__ = (
        UniqueConstraint("device_id", "key", name="_device_capability_label_uc"),
    )

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, ForeignKey("devices.device_id"), nullable=False, index=True)
    key = Column(String(24), nullable=False)
    label = Column(String, nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


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


class MsgHistory(Base):
    __tablename__ = "msg_history"

    msg_id = Column(Integer, primary_key=True, index=True)
    house_id = Column(Integer, ForeignKey("houses.house_id"), nullable=False)
    sender_id = Column(Integer, nullable=False)
    sender_type = Column(String, nullable=False)  # "parent" or "child"
    sender_name = Column(String, default="")  # denormalized for quick display
    message = Column(String, nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    house = relationship("House", back_populates="messages")


class Homework(Base):
    __tablename__ = "homework"

    hw_id = Column(Integer, primary_key=True, index=True)
    house_id = Column(Integer, ForeignKey("houses.house_id"), nullable=False)
    child_id = Column(Integer, ForeignKey("children.child_id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(String, default="")
    due_date = Column(String, nullable=True)  # "YYYY-MM-DD", display-only
    is_done = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    child = relationship("Child", back_populates="homework")


class ScreenTime(Base):
    """One row per child per local calendar day — upserted, not appended."""
    __tablename__ = "screen_time"
    __table_args__ = (
        UniqueConstraint('child_id', 'date', name='_child_date_uc'),
    )

    id = Column(Integer, primary_key=True, index=True)
    child_id = Column(Integer, ForeignKey("children.child_id"), nullable=False, index=True)
    date = Column(String(10), nullable=False)  # "YYYY-MM-DD" in the child device's timezone
    total_min = Column(Integer, default=0)
    limit_notified = Column(Boolean, default=False)  # fired the daily-limit alert for this row already
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Order(Base):
    """Mock-checkout marketplace order — no real payment involved."""
    __tablename__ = "orders"

    order_id = Column(Integer, primary_key=True, index=True)
    house_id = Column(Integer, ForeignKey("houses.house_id"), nullable=False)
    acc_id = Column(Integer, ForeignKey("accounts.acc_id"), nullable=False)
    sku = Column(String, nullable=False)
    item_name = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    status = Column(String, default="confirmed")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ApiKey(Base):
    """House-scoped key for the public Open API. Only the SHA-256 of the key
    is stored; the plaintext is shown once at creation."""
    __tablename__ = "api_keys"

    key_id = Column(Integer, primary_key=True, index=True)
    house_id = Column(Integer, ForeignKey("houses.house_id"), nullable=False)
    name = Column(String, default="API Key")
    prefix = Column(String(12), nullable=False)  # first chars, for display only
    key_hash = Column(String(64), unique=True, index=True, nullable=False)
    created_by = Column(Integer, ForeignKey("accounts.acc_id"), nullable=False)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ActivityLog(Base):
    """One row per meaningful house-member activity (device switches, homework,
    joins, logins, Maya-driven actions). High-frequency noise (location pings,
    heartbeats) is deliberately NOT logged here."""
    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True, index=True)
    house_id = Column(Integer, ForeignKey("houses.house_id"), nullable=False, index=True)
    actor_type = Column(String, nullable=False)   # parent | child | ai | system
    actor_id = Column(Integer, nullable=True)     # acc_id or child_id (null for system)
    actor_name = Column(String, default="")
    action = Column(String, nullable=False)       # device_switch | homework_assigned | ...
    summary = Column(String, nullable=False)      # human-readable, e.g. 'Ali turned ON "Television"'
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class Mention(Base):
    """A message that @-mentions a specific house member. Marked unseen until the
    target opens the chat. One row per (message, target)."""
    __tablename__ = "mentions"

    id = Column(Integer, primary_key=True, index=True)
    msg_id = Column(Integer, ForeignKey("msg_history.msg_id"), nullable=False, index=True)
    house_id = Column(Integer, ForeignKey("houses.house_id"), nullable=False, index=True)
    target_type = Column(String, nullable=False)  # parent | child
    target_id = Column(Integer, nullable=False)    # acc_id or child_id
    seen = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


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


class PeerGrant(Base):
    """One device may address another over the local link (PROTOCOL.md §7.1).

    One-way: `from_device` may send to `to_device`, within `scope`, which names
    the *receiver's* capability keys. The 32-byte key is stored because the
    server must re-send it when a device reconnects; it is never returned by any
    API, only pushed down the device's own authenticated WebSocket.

    Revoking sets `revoked_at` rather than deleting, so the audit of what the
    pairing did outlives the pairing.
    """
    __tablename__ = "peer_grants"

    grant_id = Column(Integer, primary_key=True, index=True)
    house_id = Column(Integer, ForeignKey("houses.house_id"), nullable=False, index=True)
    from_device = Column(String, ForeignKey("devices.device_id"), nullable=False, index=True)
    to_device = Column(String, ForeignKey("devices.device_id"), nullable=False, index=True)
    key = Column(String, nullable=False)          # base64, 32 random bytes
    scope = Column(String, nullable=False)        # JSON list of the receiver's capability keys
    expires_at = Column(DateTime, nullable=False)
    created_by = Column(Integer, nullable=True)   # acc_id of the member who paired them
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    revoked_at = Column(DateTime, nullable=True)
    # §7.5: "control" lets the sender `set` the receiver's keys; "relay" lets the
    # receiver (a hub) carry the sender's `report` frames to the server, and then
    # `scope` names the SENDER's keys, and the key is known only to the sender and
    # this server - the hub is never given it - so the server authenticates relayed
    # frames itself and keeps the highest (ep, seq) it has accepted.
    purpose = Column(String, default="control", nullable=False)
    relay_ep = Column(Integer, default=0, nullable=False)
    relay_seq = Column(Integer, default=0, nullable=False)


class PeerLogEntry(Base):
    """One audit line a device reported about a grant (§7.3). Bounded per house
    by the code that writes it: a device must not be able to fill the database."""
    __tablename__ = "peer_log"

    id = Column(Integer, primary_key=True, index=True)
    house_id = Column(Integer, nullable=False, index=True)
    grant_id = Column(Integer, nullable=False, index=True)
    reporter = Column(String, nullable=False)     # the device that said it
    dir = Column(String, nullable=False)          # "in" or "out"
    ep = Column(Integer, nullable=False, default=0)
    seq = Column(Integer, nullable=False, default=0)
    count = Column(Integer, nullable=False, default=1)
    kind = Column(String, nullable=True)
    peer = Column(String, nullable=True)
    summary = Column(String, nullable=True)
    result = Column(String, nullable=True)
    received_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class PeerLogCounter(Base):
    """What each side claims, per (grant, reporter, dir, epoch): the highest seq,
    the frames logged and the entries it admitted to dropping. The unexplained
    gap `claimed - logged - dropped` is what §7.3 asks an operator to read."""
    __tablename__ = "peer_log_counters"
    __table_args__ = (
        UniqueConstraint("grant_id", "reporter", "dir", "ep", name="_peer_counter_uc"),
    )

    id = Column(Integer, primary_key=True)
    grant_id = Column(Integer, nullable=False, index=True)
    reporter = Column(String, nullable=False)
    dir = Column(String, nullable=False)
    ep = Column(Integer, nullable=False, default=0)
    claimed = Column(Integer, nullable=False, default=0)
    logged = Column(Integer, nullable=False, default=0)
    dropped = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

