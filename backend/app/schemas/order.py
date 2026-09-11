from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, computed_field
from app.models.order import OrderStatus


# --- Order Item Schemas ---
class OrderItemCreate(BaseModel):
    variant_id: int = Field(
        ...,
        description="ID of the selected product variant",
        examples=[1],
    )
    quantity: int = Field(
        ...,
        gt=0,
        description="Quantity of units to order (must be at least 1)",
        examples=[2],
    )


class OrderItemResponse(BaseModel):
    id: int = Field(..., description="Unique order item ID", examples=[1])
    order_id: int = Field(..., description="Parent order foreign key", examples=[1])
    variant_id: Optional[int] = Field(None, description="Purchased variant ID", examples=[1])
    unit_price: Decimal = Field(
        ...,
        description="Frozen purchase unit price captured at checkout time",
        examples=["110.00"],
    )
    quantity: int = Field(..., description="Purchased quantity", examples=[2])
    # Frozen snapshot fields
    product_name: str = Field(..., description="Product name at purchase", examples=["Baccarat Rouge Elite"])
    variant_sku: str = Field(..., description="Variant SKU barcode", examples=["BRE-50ML"])
    size_or_volume: str = Field(..., description="Container size or volume", examples=["50ml"])

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def subtotal(self) -> Decimal:
        """
        Computed line item subtotal (unit_price * quantity).
        """
        return self.unit_price * self.quantity


# --- Order Schemas ---
class OrderCreate(BaseModel):
    shipping_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Full recipient name for courier delivery",
        examples=["Faris Al-Mansoor"],
    )
    shipping_phone: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Primary mobile phone number for WhatsApp dispatch confirmation",
        examples=["+971501112233"],
    )
    shipping_city: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Delivery city or emirate",
        examples=["Dubai"],
    )
    shipping_address: str = Field(
        ...,
        min_length=1,
        description="Detailed building, street, and apartment address",
        examples=["Downtown Dubai, Boulevard Crescent, Tower 2, Apt 804"],
    )
    customer_notes: Optional[str] = Field(
        None,
        description="Special instructions for courier or gift packaging",
        examples=["Please ring doorbell upon arrival and handle with care."],
    )
    affiliate_code: Optional[str] = Field(
        None,
        description="Optional promotional influencer code for referral attribution",
        examples=["ALI2026"],
    )
    items: List[OrderItemCreate] = Field(
        ...,
        min_length=1,
        description="List of items to purchase. Client prices are strictly ignored and server-calculated.",
    )


class OrderStatusUpdate(BaseModel):
    status: OrderStatus = Field(
        ...,
        description="New order status. Setting to 'cancelled' automatically triggers idempotent stock restoration.",
        examples=["shipped"],
    )


class OrderResponse(BaseModel):
    id: int = Field(..., description="Unique order reference identifier", examples=[1])
    user_id: Optional[int] = Field(None, description="Customer account ID (null for guest checkout)", examples=[1])
    affiliate_id: Optional[int] = Field(None, description="Attributed affiliate ID (if referred)", examples=[1])
    status: OrderStatus = Field(..., description="Current fulfillment status", examples=["pending"])
    total_amount: Decimal = Field(..., description="Grand total in AED/USD (Cash on Delivery)", examples=["220.00"])
    shipping_name: str = Field(..., description="Recipient name", examples=["Faris Al-Mansoor"])
    shipping_phone: str = Field(..., description="Recipient phone", examples=["+971501112233"])
    shipping_city: str = Field(..., description="City", examples=["Dubai"])
    shipping_address: str = Field(..., description="Street & building address", examples=["Downtown Dubai, Tower 2"])
    customer_notes: Optional[str] = Field(None, description="Delivery notes")
    created_at: datetime = Field(..., description="Order creation timestamp")
    updated_at: datetime = Field(..., description="Last modification timestamp")
    items: List[OrderItemResponse] = Field(default=[], description="Order line items with frozen price snapshots")

    model_config = ConfigDict(from_attributes=True)


# --- Backward-Compatibility Aliases ---
OrderItemOut = OrderItemResponse
OrderOut = OrderResponse
OrderUpdateStatus = OrderStatusUpdate
