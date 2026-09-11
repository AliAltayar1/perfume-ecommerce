from decimal import Decimal
from typing import Dict, List, Optional
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.models.affiliate import Affiliate
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import ProductVariant
from app.models.user import User
from app.schemas.affiliate import AffiliateCreate, AffiliateResponse
from app.schemas.order import OrderCreate


class OrderService:
    @staticmethod
    async def create_order(
        session: AsyncSession,
        order_in: OrderCreate,
        user_id: Optional[int] = None,
    ) -> Order:
        """
        Atomic checkout transaction:
        1. Validates and links affiliate code if provided.
        2. Merges/aggregates duplicate variant_ids submitted by the client.
        3. Sorts variants to guarantee deadlock-free row-level locking (SELECT ... FOR UPDATE).
        4. Validates active status and verifies sufficient stock.
        5. Atomically deducts inventory stock.
        6. Derives server-calculated effective prices (using discount_price if active).
        7. Creates Order and frozen OrderItem snapshots.
        """
        # 1. Resolve and validate affiliate code
        affiliate_id: Optional[int] = None
        if order_in.affiliate_code and order_in.affiliate_code.strip():
            clean_code = order_in.affiliate_code.strip().upper()
            aff_query = select(Affiliate).where(
                Affiliate.code == clean_code,
                Affiliate.is_active == True,  # noqa: E712
            )
            aff_res = await session.execute(aff_query)
            affiliate = aff_res.scalars().first()
            if not affiliate:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Affiliate code '{order_in.affiliate_code}' is invalid or inactive.",
                )
            affiliate_id = affiliate.id

        # 2. Merge/aggregate duplicate variant_ids submitted by client
        variant_quantities: Dict[int, int] = {}
        for item in order_in.items:
            variant_quantities[item.variant_id] = (
                variant_quantities.get(item.variant_id, 0) + item.quantity
            )

        # 3. Sort variant IDs to ensure deadlock-free row locking order
        sorted_variant_ids = sorted(variant_quantities.keys())

        total_amount = Decimal("0.00")
        order_items: List[OrderItem] = []

        try:
            for v_id in sorted_variant_ids:
                qty = variant_quantities[v_id]

                # Lock variant row
                variant_query = (
                    select(ProductVariant)
                    .where(ProductVariant.id == v_id)
                    .options(selectinload(ProductVariant.product))
                    .with_for_update()
                )
                variant_res = await session.execute(variant_query)
                variant = variant_res.scalars().first()

                if not variant or not variant.is_active or not variant.product.is_active:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Product variant with ID {v_id} is unavailable or inactive.",
                    )

                if variant.stock < qty:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"Insufficient stock for '{variant.product.name}' "
                            f"({variant.size_or_volume}). Requested: {qty}, Available: {variant.stock}."
                        ),
                    )

                # Atomically deduct stock
                variant.stock -= qty

                # Resolve effective price from database
                unit_price = (
                    variant.discount_price
                    if variant.discount_price is not None
                    else variant.price
                )
                total_amount += unit_price * qty

                # Create historical frozen snapshot
                order_item = OrderItem(
                    variant_id=variant.id,
                    unit_price=unit_price,
                    quantity=qty,
                    product_name=variant.product.name,
                    variant_sku=variant.sku,
                    size_or_volume=variant.size_or_volume,
                )
                order_items.append(order_item)

            # 4. Create Order record
            order = Order(
                user_id=user_id,
                affiliate_id=affiliate_id,
                status=OrderStatus.PENDING,
                total_amount=total_amount,
                shipping_name=order_in.shipping_name,
                shipping_phone=order_in.shipping_phone,
                shipping_city=order_in.shipping_city,
                shipping_address=order_in.shipping_address,
                customer_notes=order_in.customer_notes,
                items=order_items,
            )

            session.add(order)
            await session.commit()

            # Eagerly re-fetch complete order with items
            fetch_query = (
                select(Order)
                .where(Order.id == order.id)
                .options(selectinload(Order.items))
            )
            result = await session.execute(fetch_query)
            return result.scalars().first()

        except Exception:
            await session.rollback()
            raise

    @staticmethod
    async def get_user_orders(
        session: AsyncSession,
        user_id: int,
        skip: int = 0,
        limit: int = 20,
    ) -> List[Order]:
        """
        Retrieve order history for an authenticated customer.
        """
        query = (
            select(Order)
            .where(Order.user_id == user_id)
            .options(selectinload(Order.items))
            .order_by(Order.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_order_by_id(session: AsyncSession, order_id: int) -> Optional[Order]:
        """
        Fetch full order details including items.
        """
        query = (
            select(Order)
            .where(Order.id == order_id)
            .options(
                selectinload(Order.items),
                selectinload(Order.user),
                selectinload(Order.affiliate),
            )
        )
        result = await session.execute(query)
        return result.scalars().first()

    @staticmethod
    async def list_admin_orders(
        session: AsyncSession,
        status_filter: Optional[OrderStatus] = None,
        affiliate_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Order]:
        """
        Admin order review with optional status and affiliate filtering.
        """
        query = (
            select(Order)
            .options(selectinload(Order.items), selectinload(Order.affiliate))
            .order_by(Order.created_at.desc())
        )

        if status_filter:
            query = query.where(Order.status == status_filter)

        if affiliate_id:
            query = query.where(Order.affiliate_id == affiliate_id)

        query = query.offset(skip).limit(limit)
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def update_order_status(
        session: AsyncSession,
        order_id: int,
        new_status: OrderStatus,
    ) -> Order:
        """
        Update order status.
        Idempotent stock restoration: if moving to CANCELLED from an active state,
        restore reserved stock for each variant.
        """
        query = (
            select(Order)
            .where(Order.id == order_id)
            .options(selectinload(Order.items))
            .with_for_update()
        )
        result = await session.execute(query)
        order = result.scalars().first()

        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Order with ID {order_id} not found.",
            )

        previous_status = order.status

        # Strictly idempotent stock restoration:
        # Only restore stock if previous status was NOT already CANCELLED
        if new_status == OrderStatus.CANCELLED and previous_status != OrderStatus.CANCELLED:
            for item in order.items:
                if item.variant_id:
                    var_query = (
                        select(ProductVariant)
                        .where(ProductVariant.id == item.variant_id)
                        .with_for_update()
                    )
                    var_res = await session.execute(var_query)
                    variant = var_res.scalars().first()
                    if variant:
                        variant.stock += item.quantity

        order.status = new_status
        await session.commit()

        # Eagerly re-fetch complete order with items
        fetch_query = (
            select(Order)
            .where(Order.id == order_id)
            .options(selectinload(Order.items))
        )
        result = await session.execute(fetch_query)
        return result.scalars().first()

    # ---------------------------------------------------------
    # Affiliate Management
    # ---------------------------------------------------------
    @staticmethod
    async def create_affiliate(
        session: AsyncSession,
        affiliate_in: AffiliateCreate,
    ) -> Affiliate:
        clean_code = affiliate_in.code.strip().upper()

        # Check user exists
        user_query = select(User).where(User.id == affiliate_in.user_id)
        if not (await session.execute(user_query)).scalars().first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User with ID {affiliate_in.user_id} does not exist.",
            )

        # Check code uniqueness
        existing_query = select(Affiliate).where(Affiliate.code == clean_code)
        if (await session.execute(existing_query)).scalars().first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Affiliate code '{clean_code}' is already in use.",
            )

        affiliate = Affiliate(
            user_id=affiliate_in.user_id,
            code=clean_code,
        )
        session.add(affiliate)
        await session.commit()
        await session.refresh(affiliate)
        return affiliate

    @staticmethod
    async def list_admin_affiliates(session: AsyncSession) -> List[AffiliateResponse]:
        """
        List affiliates along with aggregate referred order stats.
        """
        query = select(Affiliate).order_by(Affiliate.created_at.desc())
        result = await session.execute(query)
        affiliates = result.scalars().all()

        responses: List[AffiliateResponse] = []
        for aff in affiliates:
            # Query referred non-cancelled orders count & total amount
            stats_query = (
                select(
                    func.count(Order.id).label("total_orders"),
                    func.coalesce(func.sum(Order.total_amount), Decimal("0.00")).label("total_amount"),
                )
                .where(
                    Order.affiliate_id == aff.id,
                    Order.status != OrderStatus.CANCELLED,
                )
            )
            stats_res = await session.execute(stats_query)
            row = stats_res.first()
            total_orders = row[0] if row else 0
            total_amount = row[1] if row else Decimal("0.00")

            responses.append(
                AffiliateResponse(
                    id=aff.id,
                    code=aff.code,
                    user_id=aff.user_id,
                    is_active=aff.is_active,
                    created_at=aff.created_at,
                    total_referred_orders=total_orders,
                    total_referred_amount=total_amount,
                )
            )

        return responses
