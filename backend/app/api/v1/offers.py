from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, require_admin
from app.schemas.offer import OfferCreate, OfferResponse, OfferUpdate
from app.schemas.user import MessageResponse
from app.services.offer_service import OfferService

router = APIRouter()


@router.get("", response_model=List[OfferResponse])
@router.get("/", response_model=List[OfferResponse], include_in_schema=False)
async def list_offers(
    active_only: bool = Query(False, description="Filter for currently active offers only"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """
    List offers with optional active status filter and pagination.
    """
    return await OfferService.list_offers(
        session=db,
        active_only=active_only,
        skip=skip,
        limit=limit,
    )


@router.get("/{offer_id}", response_model=OfferResponse)
async def get_offer(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Get detailed information for a specific offer.
    """
    offer = await OfferService.get_offer_by_id(session=db, offer_id=offer_id)
    if not offer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Offer with ID {offer_id} not found.",
        )
    return offer


@router.post("", response_model=OfferResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
@router.post("/", response_model=OfferResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False, dependencies=[Depends(require_admin)])
async def create_offer(
    offer_in: OfferCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Admin: Create a new promotional offer or discount coupon.
    """
    return await OfferService.create_offer(session=db, offer_in=offer_in)


@router.put("/{offer_id}", response_model=OfferResponse, dependencies=[Depends(require_admin)])
@router.patch("/{offer_id}", response_model=OfferResponse, dependencies=[Depends(require_admin)])
async def update_offer(
    offer_id: int,
    offer_in: OfferUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    Admin: Update existing offer attributes.
    """
    return await OfferService.update_offer(
        session=db,
        offer_id=offer_id,
        offer_in=offer_in,
    )


@router.delete("/{offer_id}", response_model=MessageResponse, dependencies=[Depends(require_admin)])
async def delete_offer(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Admin: Delete an offer from the system.
    """
    await OfferService.delete_offer(session=db, offer_id=offer_id)
    return {"message": "Offer deleted successfully"}
