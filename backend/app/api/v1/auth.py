from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.core.security import (
    clear_auth_cookies,
    create_access_token,
    create_refresh_token,
    get_password_hash,
    hash_refresh_token,
    set_auth_cookies,
    verify_password,
)
from app.models.user import RefreshToken, User, UserRole
from app.schemas.user import (
    MessageResponse,
    UserLogin,
    UserRegister,
    UserResponse,
    UserUpdateMe,
)

router = APIRouter()


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_in: UserRegister,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    Register a new customer account, persist tokens, and set HttpOnly cookies.
    """
    query = select(User).where(User.email == user_in.email)
    existing = (await db.execute(query)).scalars().first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists.",
        )

    user = User(
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        full_name=user_in.full_name,
        phone=user_in.phone,
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db.add(user)
    await db.flush()  # Populates user.id

    # Generate token pair
    access_token = create_access_token(subject=user.id, role=user.role.value)
    raw_refresh, token_hash, expires_at = create_refresh_token(subject=user.id)

    db_refresh = RefreshToken(
        user_id=user.id,
        token=token_hash,
        expires_at=expires_at,
        is_revoked=False,
    )
    db.add(db_refresh)
    await db.commit()
    await db.refresh(user)

    set_auth_cookies(response, access_token=access_token, refresh_token=raw_refresh)
    return user


@router.post("/login", response_model=UserResponse)
async def login(
    credentials: UserLogin,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    Authenticate user, generate access + refresh token pair, store refresh token, and set HttpOnly cookies.
    """
    query = select(User).where(User.email == credentials.email)
    user = (await db.execute(query)).scalars().first()

    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account",
        )

    access_token = create_access_token(subject=user.id, role=user.role.value)
    raw_refresh, token_hash, expires_at = create_refresh_token(subject=user.id)

    db_refresh = RefreshToken(
        user_id=user.id,
        token=token_hash,
        expires_at=expires_at,
        is_revoked=False,
    )
    db.add(db_refresh)
    await db.commit()

    set_auth_cookies(response, access_token=access_token, refresh_token=raw_refresh)
    return user


@router.post("/refresh", response_model=UserResponse)
async def refresh_tokens(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    Rotate refresh token and issue a new access + refresh token pair via HttpOnly cookies.
    """
    raw_refresh = request.cookies.get("refresh_token")
    if not raw_refresh:
        raw_refresh = request.headers.get("X-Refresh-Token")

    if not raw_refresh:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing",
        )

    token_hash = hash_refresh_token(raw_refresh)
    query = (
        select(RefreshToken)
        .where(RefreshToken.token == token_hash)
        .options(selectinload(RefreshToken.user))
    )
    result = await db.execute(query)
    db_token = result.scalars().first()

    if not db_token:
        clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    # Detect token reuse attack
    if db_token.is_revoked:
        clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has already been revoked. Please log in again.",
        )

    now_utc = datetime.now(timezone.utc)
    token_expires_at = db_token.expires_at
    if token_expires_at.tzinfo is None:
        token_expires_at = token_expires_at.replace(tzinfo=timezone.utc)

    if token_expires_at < now_utc:
        db_token.is_revoked = True
        await db.commit()
        clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired",
        )

    user = db_token.user
    if not user or not user.is_active:
        clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive or deleted",
        )

    # Token Rotation: Revoke old token and issue new token pair
    db_token.is_revoked = True

    new_access_token = create_access_token(subject=user.id, role=user.role.value)
    new_raw_refresh, new_token_hash, new_expires_at = create_refresh_token(subject=user.id)

    new_db_token = RefreshToken(
        user_id=user.id,
        token=new_token_hash,
        expires_at=new_expires_at,
        is_revoked=False,
    )
    db.add(new_db_token)
    await db.commit()

    set_auth_cookies(response, access_token=new_access_token, refresh_token=new_raw_refresh)
    return user


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    Revoke current refresh token in database and clear HttpOnly cookies with exact paths.
    """
    raw_refresh = request.cookies.get("refresh_token") or request.headers.get("X-Refresh-Token")
    if raw_refresh:
        token_hash = hash_refresh_token(raw_refresh)
        query = select(RefreshToken).where(RefreshToken.token == token_hash)
        result = await db.execute(query)
        db_token = result.scalars().first()
        if db_token and not db_token.is_revoked:
            db_token.is_revoked = True
            await db.commit()

    # Clear access_token (path="/") and refresh_token (path="/api/v1/auth")
    clear_auth_cookies(response)

    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """
    Return currently authenticated user profile.
    """
    return current_user


@router.put("/me", response_model=UserResponse)
@router.patch("/me", response_model=UserResponse)
async def update_me(
    user_in: UserUpdateMe,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update profile information (full_name, phone, email, password) for the authenticated user.
    """
    if user_in.email is not None and user_in.email != current_user.email:
        query = select(User).where(User.email == user_in.email, User.id != current_user.id)
        existing = (await db.execute(query)).scalars().first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A user with this email already exists.",
            )
        current_user.email = user_in.email

    if user_in.full_name is not None:
        current_user.full_name = user_in.full_name

    if user_in.phone is not None:
        current_user.phone = user_in.phone

    if user_in.password is not None:
        current_user.hashed_password = get_password_hash(user_in.password)

    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.delete("/me", response_model=MessageResponse)
async def delete_me(
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete the authenticated user's account and clear authentication cookies.
    """
    await db.delete(current_user)
    await db.commit()
    clear_auth_cookies(response)
    return {"message": "User account deleted successfully"}
