from datetime import datetime, timezone
from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.offer import Offer
from app.models.product import Product
from app.schemas.offer import OfferCreate, OfferUpdate


class OfferService:
    @staticmethod
    async def create_offer(session: AsyncSession, offer_in: OfferCreate) -> Offer:
        """
        Create a new promotional offer with optional product association and promo code.
        """
        # Validate unique promo code if provided
        if offer_in.code:
            existing = await session.execute(
                select(Offer).where(Offer.code == offer_in.code)
            )
            if existing.scalars().first():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"An offer with code '{offer_in.code}' already exists.",
                )

        # Validate product reference if provided
        if offer_in.product_id is not None:
            prod = await session.execute(
                select(Product).where(Product.id == offer_in.product_id)
            )
            if not prod.scalars().first():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Referenced product with ID {offer_in.product_id} does not exist.",
                )

        # Validate date range if both provided
        if offer_in.start_date and offer_in.end_date and offer_in.start_date > offer_in.end_date:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Offer start date must be before or equal to end date.",
            )

        offer = Offer(
            title=offer_in.title,
            description=offer_in.description,
            discount_percentage=offer_in.discount_percentage,
            discount_amount=offer_in.discount_amount,
            code=offer_in.code,
            banner_url=offer_in.banner_url,
            product_id=offer_in.product_id,
            is_active=offer_in.is_active,
            start_date=offer_in.start_date,
            end_date=offer_in.end_date,
        )
        session.add(offer)
        await session.commit()
        await session.refresh(offer)
        return offer

    @staticmethod
    async def get_offer_by_id(session: AsyncSession, offer_id: int) -> Optional[Offer]:
        """
        Retrieve offer by primary key ID.
        """
        query = select(Offer).where(Offer.id == offer_id)
        result = await session.execute(query)
        return result.scalars().first()

    @staticmethod
    async def list_offers(
        session: AsyncSession,
        active_only: bool = False,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Offer]:
        """
        List offers with optional active status filter and pagination.
        """
        query = select(Offer)
        if active_only:
            now_utc = datetime.now(timezone.utc)
            query = query.where(
                Offer.is_active.is_(True),
                or_(Offer.start_date.is_(None), Offer.start_date <= now_utc),
                or_(Offer.end_date.is_(None), Offer.end_date >= now_utc),
            )
        query = query.order_by(Offer.created_at.desc()).offset(skip).limit(limit)
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def update_offer(
        session: AsyncSession,
        offer_id: int,
        offer_in: OfferUpdate,
    ) -> Offer:
        """
        Update fields of an existing offer.
        """
        offer = await OfferService.get_offer_by_id(session, offer_id=offer_id)
        if not offer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Offer with ID {offer_id} not found.",
            )

        update_data = offer_in.model_dump(exclude_unset=True)

        # Check code uniqueness if changing code
        if "code" in update_data and update_data["code"]:
            existing = await session.execute(
                select(Offer).where(Offer.code == update_data["code"], Offer.id != offer_id)
            )
            if existing.scalars().first():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"An offer with code '{update_data['code']}' already exists.",
                )

        # Check product existence if updating product_id
        if "product_id" in update_data and update_data["product_id"] is not None:
            prod = await session.execute(
                select(Product).where(Product.id == update_data["product_id"])
            )
            if not prod.scalars().first():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Referenced product with ID {update_data['product_id']} does not exist.",
                )

        # Validate date consistency if both dates will be present
        new_start = update_data.get("start_date", offer.start_date)
        new_end = update_data.get("end_date", offer.end_date)
        if new_start and new_end and new_start > new_end:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Offer start date must be before or equal to end date.",
            )

        for field, val in update_data.items():
            setattr(offer, field, val)

        await session.commit()
        await session.refresh(offer)
        return offer

    @staticmethod
    async def delete_offer(session: AsyncSession, offer_id: int) -> bool:
        """
        Delete an offer from database.
        """
        offer = await OfferService.get_offer_by_id(session, offer_id=offer_id)
        if not offer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Offer with ID {offer_id} not found.",
            )

        await session.delete(offer)
        await session.commit()
        return True
