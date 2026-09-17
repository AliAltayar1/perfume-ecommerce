from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user, get_db
from app.core.security import clear_auth_cookies, get_password_hash
from app.models.user import User
from app.schemas.user import MessageResponse, UserResponse, UserUpdateMe

router = APIRouter()


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(
    current_user: User = Depends(get_current_user),
):
    """
    Get authenticated user's profile details.
    """
    return current_user


@router.put("/me", response_model=UserResponse)
@router.patch("/me", response_model=UserResponse)
async def update_current_user_profile(
    user_in: UserUpdateMe,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update authenticated user's profile info (name, phone, email, password).
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
async def delete_current_user_account(
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
