"""
Author: sizhchan
Org: dgaudit
Version: v0.1
Date: 2026-05-27
"""

"""Authentication module — password hashing and JWT tokens."""

import os
import logging
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

# ---- Config ----
SECRET_KEY = os.environ.get("PADDLEOCR_SECRET", "paddleocr-dev-secret-change-in-production")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security_scheme = HTTPBearer(auto_error=False)  # Allow optional auth via query param


# ---- Password helpers ----
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ---- Token helpers ----
def create_token(user_id: int, username: str, is_admin: bool = False) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": str(user_id),
        "username": username,
        "is_admin": is_admin,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )


# ---- FastAPI dependency ----
from fastapi import Query

async def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    token: str = Query(default=None),
) -> dict:
    """
    Extract and validate the current user from Bearer token.

    Accepts token from Authorization header or ?token= query parameter.
    At least one must be provided.
    """
    # Try query param first, then header
    token_value = token
    if not token_value and credentials:
        token_value = credentials.credentials
    if not token_value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Provide ?token= or Authorization header.",
        )
    payload = decode_token(token_value)
    user_id = payload.get("sub")
    username = payload.get("username")
    is_admin = payload.get("is_admin", False)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload.",
        )
    return {"id": int(user_id), "username": username, "is_admin": bool(is_admin)}


async def admin_required(
    user: dict = Depends(current_user),
) -> dict:
    """Only allow admin users."""
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required.",
        )
    return user
