from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class OfferBase(BaseModel):
    title: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Offer title or headline",
        examples=["Summer Perfume Sale - 20% Off"],
    )
    description: Optional[str] = Field(
        None,
        description="Detailed description or terms of the offer",
        examples=["Get 20% off across all French perfumes this week."],
    )
    discount_percentage: Optional[Decimal] = Field(
        None,
        ge=0,
        le=100,
        description="Discount percentage between 0 and 100",
        examples=[Decimal("20.00")],
    )
    discount_amount: Optional[Decimal] = Field(
        None,
        ge=0,
        description="Fixed discount amount",
        examples=[Decimal("15.00")],
    )
    code: Optional[str] = Field(
        None,
        max_length=50,
        description="Optional promo or coupon code",
        examples=["SUMMER20"],
    )
    banner_url: Optional[str] = Field(
        None,
        max_length=500,
        description="Promotional banner image URL",
        examples=["https://cdn.example.com/banners/summer-sale.jpg"],
    )
    product_id: Optional[int] = Field(
        None,
        description="Optional specific product to which this offer applies",
        examples=[1],
    )
    is_active: bool = Field(
        default=True,
        description="Whether this offer is currently active",
        examples=[True],
    )
    start_date: Optional[datetime] = Field(
        None,
        description="When the offer becomes active",
    )
    end_date: Optional[datetime] = Field(
        None,
        description="When the offer expires",
    )


class OfferCreate(OfferBase):
    pass


class OfferUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    discount_percentage: Optional[Decimal] = Field(None, ge=0, le=100)
    discount_amount: Optional[Decimal] = Field(None, ge=0)
    code: Optional[str] = Field(None, max_length=50)
    banner_url: Optional[str] = Field(None, max_length=500)
    product_id: Optional[int] = None
    is_active: Optional[bool] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class OfferResponse(OfferBase):
    id: int = Field(..., description="Unique offer identifier", examples=[1])
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    model_config = ConfigDict(from_attributes=True)
