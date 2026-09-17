from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from app.models.user import UserRole


class UserBase(BaseModel):
    email: EmailStr = Field(
        ...,
        description="Unique email address for user account",
        examples=["customer@perfume.com"],
    )
    full_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Full name of the user",
        examples=["Sarah Connor"],
    )
    phone: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Primary contact number (international format recommended)",
        examples=["+971501234567"],
    )
    role: UserRole = Field(
        default=UserRole.CUSTOMER,
        description="Account authorization role",
        examples=["customer"],
    )
    is_active: bool = Field(
        default=True,
        description="Whether the user account is active",
        examples=[True],
    )


class UserRegister(BaseModel):
    email: EmailStr = Field(
        ...,
        description="Unique email address for registration",
        examples=["sarah@example.com"],
    )
    password: str = Field(
        ...,
        min_length=6,
        description="Plain text account password (minimum 6 characters)",
        examples=["SecretPass123!"],
    )
    full_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Full legal or display name",
        examples=["Sarah Connor"],
    )
    phone: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Contact phone number",
        examples=["+971501234567"],
    )


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    phone: str
    role: UserRole = UserRole.CUSTOMER


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=1, max_length=255)
    phone: Optional[str] = Field(None, min_length=1, max_length=50)
    email: Optional[EmailStr] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=6)


class UserUpdateMe(BaseModel):
    full_name: Optional[str] = Field(None, min_length=1, max_length=255)
    phone: Optional[str] = Field(None, min_length=1, max_length=50)
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=6)


class UserLogin(BaseModel):
    email: EmailStr = Field(
        ...,
        description="Registered user account email",
        examples=["customer@perfume.com"],
    )
    password: str = Field(
        ...,
        description="Account password",
        examples=["Customer@123"],
    )


class UserResponse(BaseModel):
    id: int = Field(..., description="Unique user identifier", examples=[1])
    email: EmailStr = Field(..., description="User email address", examples=["customer@perfume.com"])
    full_name: str = Field(..., description="User full name", examples=["Sarah Connor"])
    phone: str = Field(..., description="Contact phone", examples=["+971501234567"])
    role: UserRole = Field(..., description="Assigned role", examples=["customer"])
    is_active: bool = Field(..., description="Account active status", examples=[True])
    created_at: datetime = Field(..., description="Account creation timestamp")

    model_config = ConfigDict(from_attributes=True)


class UserOut(UserResponse):
    pass


class Token(BaseModel):
    access_token: str = Field(..., description="Signed JWT access token")
    token_type: str = Field(default="bearer", description="Token scheme")


class TokenPayload(BaseModel):
    sub: Optional[str] = None
    role: Optional[str] = None
    type: Optional[str] = None
    exp: Optional[int] = None
    iat: Optional[int] = None


class MessageResponse(BaseModel):
    message: str = Field(..., description="Status feedback message", examples=["Operation completed successfully"])
