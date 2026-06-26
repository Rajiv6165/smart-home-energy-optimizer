"""
JWT Authentication utilities and FastAPI dependency.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlmodel import select

from .config import get_settings
from .database import session_scope
from .models import User

settings = get_settings()

import hashlib
import hmac

# Password hashing context — bcrypt 5.x raises ValueError for passwords >72 bytes.
# We pre-hash the password with SHA-256 (produces a fixed 64-char hex string,
# well under 72 bytes) before passing to bcrypt. Transparent to callers.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Bearer token extractor (auto_error=False so we can give a nice 401 message)
_bearer = HTTPBearer(auto_error=False)

_PEPPER = b"smarthome-energy-optimizer"


def _prehash(password: str) -> str:
    """SHA-256 prehash so bcrypt never sees >72 bytes (fixes bcrypt 5.x)."""
    return hashlib.sha256(password.encode("utf-8") + _PEPPER).hexdigest()



# ──────────────────────────────────────────────
# Password utilities
# ──────────────────────────────────────────────

def get_password_hash(password: str) -> str:
    return _pwd_context.hash(_prehash(password))


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(_prehash(plain), hashed)




# ──────────────────────────────────────────────
# JWT utilities
# ──────────────────────────────────────────────

def create_access_token(subject: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": subject, "exp": expire, "iat": datetime.utcnow()}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> Optional[str]:
    """Return the subject (email) if the token is valid, else None."""
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        return payload.get("sub")
    except JWTError:
        return None


# ──────────────────────────────────────────────
# User helpers
# ──────────────────────────────────────────────

def create_user(email: str, password: str) -> User:
    with session_scope() as session:
        existing = session.exec(select(User).where(User.email == email)).first()
        if existing:
            raise ValueError(f"Email '{email}' is already registered.")
        user = User(email=email, hashed_password=get_password_hash(password))
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


def authenticate_user(email: str, password: str) -> Optional[User]:
    with session_scope() as session:
        user = session.exec(select(User).where(User.email == email)).first()
        if not user:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user


# ──────────────────────────────────────────────
# FastAPI dependency
# ──────────────────────────────────────────────

def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> User:
    """
    Dependency that validates a Bearer JWT and returns the current User.
    Raises HTTP 401 if missing or invalid.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing. Use: Authorization: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    subject = decode_access_token(credentials.credentials)
    if subject is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    with session_scope() as session:
        user = session.exec(select(User).where(User.email == subject)).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user
