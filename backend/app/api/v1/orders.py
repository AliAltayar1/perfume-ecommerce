from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user, get_db, get_optional_current_user
from app.models.user import User, UserRole
from app.schemas.order import OrderCreate, OrderResponse
from app.services.order_service import OrderService

router = APIRouter()


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    order_in: OrderCreate,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Cash on Delivery (COD) Checkout Endpoint:
    - Merges duplicate variant quantities.
    - Locks rows to avoid stock race conditions.
    - Server derives all prices (discount-aware).
    - Captures historical snapshot on OrderItems.
    - Supports both authenticated users and guest checkouts.
    """
    user_id = current_user.id if current_user else None
    order = await OrderService.create_order(session=db, order_in=order_in, user_id=user_id)
    return order


@router.get("/my-orders", response_model=List[OrderResponse])
async def get_my_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve past order history for the authenticated customer.
    """
    return await OrderService.get_user_orders(
        session=db,
        user_id=current_user.id,
        skip=skip,
        limit=limit,
    )


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order_by_id(
    order_id: int,
    phone: Optional[str] = Query(None, description="Phone verification for guest order lookup"),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve specific order details:
    - Authenticated users can view their own orders.
    - Administrators can view any order.
    - Guest orders can be viewed by providing the matching shipping phone number.
    """
    order = await OrderService.get_order_by_id(session=db, order_id=order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order with ID {order_id} not found.",
        )

    # 1. Admin access
    if current_user and current_user.role == UserRole.ADMIN:
        return order

    # 2. Authenticated customer matching their own order
    if current_user and order.user_id == current_user.id:
        return order

    # 3. Phone verification (for guest checkout or tracking verification)
    if phone:
        clean_input = phone.replace(" ", "").replace("-", "").replace("+", "")
        clean_saved = order.shipping_phone.replace(" ", "").replace("-", "").replace("+", "")
        if clean_input == clean_saved:
            return order

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Authentication or phone verification required to view this order.",
    )
