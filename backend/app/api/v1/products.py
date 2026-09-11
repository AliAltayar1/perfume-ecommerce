from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db
from app.schemas.product import (
    CategoryResponse,
    ProductDetailResponse,
    ProductListResponse,
)
from app.services.product_service import ProductService

router = APIRouter()


@router.get("/categories", response_model=List[CategoryResponse])
async def list_categories(db: AsyncSession = Depends(get_db)):
    """
    Public endpoint: List all product categories ordered alphabetically.
    """
    return await ProductService.list_categories(session=db)


@router.get("", response_model=List[ProductListResponse])
async def list_products(
    category_slug: Optional[str] = Query(None, description="Filter products by category slug"),
    search: Optional[str] = Query(None, description="Search term for name or description"),
    skip: int = Query(0, ge=0, description="Offset for pagination"),
    limit: int = Query(20, ge=1, le=100, description="Items per page limit"),
    db: AsyncSession = Depends(get_db),
):
    """
    Public storefront endpoint to browse active perfume & personal care products.
    Calculates effective price ranges (using discount prices if active), total stock, and primary image.
    """
    return await ProductService.list_products(
        session=db,
        category_slug=category_slug,
        search=search,
        skip=skip,
        limit=limit,
    )


@router.get("/{slug}", response_model=ProductDetailResponse)
async def get_product_detail(slug: str, db: AsyncSession = Depends(get_db)):
    """
    Public endpoint: Full product details including active variants, sorted images, and category info.
    """
    product = await ProductService.get_product_by_slug(session=db, slug=slug)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )
    return product
