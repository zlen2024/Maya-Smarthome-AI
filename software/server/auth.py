import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from database import get_db
from models import Account, ApiKey, Child, House

# No fallback literal. A shipped default key is a silent trap: anyone who forks
# this repo and deploys it would sign tokens with a key that is public, and
# nothing would look wrong. Missing in development is answered with a random
# per-process key instead — tokens then die on restart, which is annoying but
# never shared.
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    SECRET_KEY = secrets.token_urlsafe(32)
    print("WARNING: SECRET_KEY is not set. Generated an ephemeral signing key — "
          "every restart invalidates all sessions. Set SECRET_KEY in production.")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    if "sub" in to_encode:
        to_encode["sub"] = str(to_encode["sub"])
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> Account:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        if sub is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    if isinstance(sub, str) and sub.startswith("child_"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Child accounts cannot access this endpoint")
    try:
        acc_id = int(sub)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject")
    user = db.query(Account).filter(Account.acc_id == acc_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user


def get_current_user_or_child(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> dict:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        if sub is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    
    if isinstance(sub, str) and sub.startswith("child_"):
        try:
            child_id = int(sub.split("_")[1])
        except (ValueError, IndexError):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid child token subject")
        child = db.query(Child).filter(Child.child_id == child_id).first()
        if child is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return {"type": "child", "child": child, "house_id": child.house_id, "role": "child"}
    
    try:
        acc_id = int(sub)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject")
    user = db.query(Account).filter(Account.acc_id == acc_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return {"type": "user", "user": user, "house_id": user.house_id, "role": user.role.value}

# ─── Open API keys ─────────────────────────────────────────────
api_key_header = APIKeyHeader(name="X-API-Key", description="House-scoped Maya Open API key")


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def get_api_key_row(
    x_api_key: str = Security(api_key_header),
    db: Session = Depends(get_db),
) -> ApiKey:
    """Resolve an X-API-Key header to the key. A revoked or unknown one is a 401, and
    the same 401: which of the two it was is not the caller's to learn."""
    row = db.query(ApiKey).filter(
        ApiKey.key_hash == hash_api_key(x_api_key),
        ApiKey.revoked == False,  # noqa: E712 — SQLAlchemy needs the comparison
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return row


def get_api_key_house(
    row: ApiKey = Depends(get_api_key_row),
    db: Session = Depends(get_db),
) -> House:
    """Resolve an X-API-Key header to the house it is scoped to."""
    house = db.query(House).filter(House.house_id == row.house_id).first()
    if house is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key house no longer exists")
    return house
