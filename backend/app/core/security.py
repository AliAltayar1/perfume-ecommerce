from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from typing import Any, Optional
import bcrypt
from fastapi import Response
import jwt
from app.core.config import settings


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain text password against a bcrypt-hashed password.
    """
    if isinstance(plain_password, str):
        plain_bytes = plain_password.encode("utf-8")
    else:
        plain_bytes = plain_password

    if isinstance(hashed_password, str):
        hashed_bytes = hashed_password.encode("utf-8")
    else:
        hashed_bytes = hashed_password

    return bcrypt.checkpw(plain_bytes, hashed_bytes)


def get_password_hash(password: str) -> str:
    """
    Hash a plain password using bcrypt with automatic salt generation.
    """
    if isinstance(password, str):
        pwd_bytes = password.encode("utf-8")
    else:
        pwd_bytes = password

    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def create_access_token(subject: int | str, role: str) -> str:
    """
    Generate a short-lived (e.g. 15 minutes) signed JWT access token.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(subject),
        "role": role,
        "type": "access",
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT access token.
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def hash_refresh_token(raw_token: str) -> str:
    """
    Compute SHA-256 hash of a raw refresh token for safe storage in the database.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_refresh_token(subject: int | str) -> tuple[str, str, datetime]:
    """
    Generate raw refresh token, SHA-256 hash for database storage, and expiration timestamp.
    Returns:
        (raw_token, token_hash, expires_at)
    """
    random_part = secrets.token_urlsafe(48)
    raw_token = f"{subject}_{random_part}"
    token_hash = hash_refresh_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    return raw_token, token_hash, expires_at


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """
    Set secure HttpOnly cookies on the HTTP response for access and refresh tokens.
    """
    access_max_age = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60  # e.g. 900 seconds
    refresh_max_age = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600  # e.g. 604800 seconds

    # Access token cookie (scoped to entire site)
    response.set_cookie(
        key="access_token",
        value=access_token,
        max_age=access_max_age,
        expires=access_max_age,
        path="/",
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
    )

    # Refresh token cookie (strictly scoped to /api/v1/auth)
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        max_age=refresh_max_age,
        expires=refresh_max_age,
        path="/api/v1/auth",
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
    )


def clear_auth_cookies(response: Response) -> None:
    """
    Clear authentication cookies with exact matching paths.
    """
    response.delete_cookie(
        key="access_token",
        path="/",
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
    )
    response.delete_cookie(
        key="refresh_token",
        path="/api/v1/auth",
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
    )
