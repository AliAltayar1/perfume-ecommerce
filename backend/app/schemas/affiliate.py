from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class AffiliateBase(BaseModel):
    code: str = Field(
        ...,
        min_length=3,
        max_length=50,
        description="Unique alphanumeric promotional code",
        examples=["ALI2026"],
    )
    is_active: bool = Field(
        default=True,
        description="Whether this affiliate link is active and tracking referrals",
        examples=[True],
    )


class AffiliateCreate(BaseModel):
    user_id: int = Field(
        ...,
        description="User account ID to be assigned promoter status",
        examples=[2],
    )
    code: str = Field(
        ...,
        min_length=3,
        max_length=50,
        description="Desired unique promotional tracking code",
        examples=["ALI2026"],
    )


class AffiliateUpdate(BaseModel):
    code: Optional[str] = Field(None, min_length=3, max_length=50, examples=["ALI2026-VIP"])
    is_active: Optional[bool] = Field(None, examples=[True])


class AffiliateResponse(BaseModel):
    id: int = Field(..., description="Unique affiliate record ID", examples=[1])
    code: str = Field(..., description="Promotional code", examples=["ALI2026"])
    user_id: int = Field(..., description="Linked promoter user ID", examples=[2])
    is_active: bool = Field(..., description="Active referral tracking status", examples=[True])
    created_at: datetime = Field(..., description="Record creation timestamp")
    total_referred_orders: int = Field(
        default=0,
        description="Count of successfully placed orders linked to this affiliate",
        examples=[14],
    )
    total_referred_amount: Decimal = Field(
        default=Decimal("0.00"),
        description="Gross total sales volume generated through this referral code",
        examples=["3480.00"],
    )

    model_config = ConfigDict(from_attributes=True)


# --- Backward-Compatibility Aliases ---
AffiliateOut = AffiliateResponse
