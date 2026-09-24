from typing import List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, require_admin
from app.models.order import OrderStatus
from app.schemas.affiliate import (
    AffiliateCreate,
    AffiliateResponse,
)
from app.schemas.order import (
    OrderResponse,
    OrderStatusUpdate,
)
from app.schemas.product import (
    CategoryCreate,
    CategoryResponse,
    CategoryUpdate,
    ProductCreate,
    ProductDetailResponse,
    ProductImageResponse,
    ProductUpdate,
    ProductVariantCreate,
    ProductVariantResponse,
    ProductVariantUpdate,
)
from app.schemas.offer import (
    OfferCreate,
    OfferResponse,
    OfferUpdate,
)
from app.schemas.user import MessageResponse
from app.services.image_service import ImageService
from app.services.offer_service import OfferService
from app.services.order_service import OrderService
from app.services.product_service import ProductService

router = APIRouter(dependencies=[Depends(require_admin)])


# ----------------------------------------------------------------------
# Category Management
# ----------------------------------------------------------------------
@router.post("/categories", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    category_in: CategoryCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new product category.
    """
    return await ProductService.create_category(session=db, category_in=category_in)


@router.put("/categories/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: int,
    category_in: CategoryUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    Update category name or slug.
    """
    return await ProductService.update_category(
        session=db,
        category_id=category_id,
        category_in=category_in,
    )


@router.delete("/categories/{category_id}", response_model=MessageResponse)
async def delete_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Delete category if no products are associated with it.
    """
    await ProductService.delete_category(session=db, category_id=category_id)
    return {"message": "Category deleted successfully"}


# ----------------------------------------------------------------------
# Product Management
# ----------------------------------------------------------------------
@router.get("/products", response_model=List[ProductDetailResponse])
async def list_admin_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    category_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    List all products (active and inactive) for inventory management.
    """
    return await ProductService.list_admin_products(
        session=db,
        skip=skip,
        limit=limit,
        category_id=category_id,
    )


@router.get("/products/{product_id}", response_model=ProductDetailResponse)
async def get_admin_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Get full product details including variants, images, and category by product ID.
    """
    product = await ProductService.get_product_by_id(session=db, product_id=product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} not found.",
        )
    return product


@router.post("/products", response_model=ProductDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    product_in: ProductCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Atomically create a product with its initial variants and images.
    """
    return await ProductService.create_product(session=db, product_in=product_in)


@router.put("/products/{product_id}", response_model=ProductDetailResponse)
async def update_product(
    product_id: int,
    product_in: ProductUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    Update core product attributes (name, slug, description, category, is_active).
    """
    return await ProductService.update_product(
        session=db,
        product_id=product_id,
        product_in=product_in,
    )


@router.delete("/products/{product_id}", response_model=ProductDetailResponse)
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Soft-delete product (sets is_active=False) preserving order histories.
    """
    return await ProductService.delete_product(session=db, product_id=product_id)


# ----------------------------------------------------------------------
# Product Image Management
# ----------------------------------------------------------------------
@router.post(
    "/products/{product_id}/images",
    response_model=ProductImageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload image directly for a product",
    description="Uploads, uniformly resizes (1000x1000), compresses to WebP, stores on server disk, and creates a product_image record in database.",
)
async def upload_product_image(
    product_id: int,
    file: UploadFile = File(..., description="Image file to upload"),
    alt_text: Optional[str] = Form(None, description="Accessibility alt text"),
    is_primary: bool = Form(False, description="Set as the primary hero image for product cards"),
    display_order: int = Form(0, description="Gallery display order"),
    fit_mode: str = Form("contain", description="Unified sizing mode: 'contain', 'cover', or 'scale'"),
    quality: Optional[int] = Form(None, ge=1, le=100, description="Optional compression quality (default 85)"),
    db: AsyncSession = Depends(get_db),
):
    upload_res = await ImageService.save_image_to_disk(
        upload_file=file,
        folder="products",
        fit_mode=fit_mode,
        quality=quality,
    )
    return await ProductService.add_product_image(
        session=db,
        product_id=product_id,
        url=upload_res["url"],
        alt_text=alt_text,
        is_primary=is_primary,
        display_order=display_order,
    )


@router.delete(
    "/products/{product_id}/images/{image_id}",
    response_model=MessageResponse,
    summary="Delete product image from database and disk",
)
async def delete_product_image(
    product_id: int,
    image_id: int,
    db: AsyncSession = Depends(get_db),
):
    deleted_url = await ProductService.delete_product_image(
        session=db,
        product_id=product_id,
        image_id=image_id,
    )
    ImageService.delete_file_by_url(deleted_url)
    return {"message": "Image deleted successfully"}


@router.patch(
    "/products/{product_id}/images/{image_id}/primary",
    response_model=ProductImageResponse,
    summary="Set image as primary showcase hero image",
)
async def set_primary_product_image(
    product_id: int,
    image_id: int,
    db: AsyncSession = Depends(get_db),
):
    return await ProductService.set_primary_product_image(
        session=db,
        product_id=product_id,
        image_id=image_id,
    )


# ----------------------------------------------------------------------
# Variant Management
# ----------------------------------------------------------------------
@router.post("/products/{product_id}/variants", response_model=ProductVariantResponse, status_code=status.HTTP_201_CREATED)
async def create_variant(
    product_id: int,
    variant_in: ProductVariantCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Add a new variant (e.g. 50ml, 100ml) to an existing product with SKU validation.
    """
    return await ProductService.create_variant(
        session=db,
        product_id=product_id,
        variant_in=variant_in,
    )


@router.patch("/variants/{variant_id}", response_model=ProductVariantResponse)
async def update_variant(
    variant_id: int,
    variant_in: ProductVariantUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    Update variant pricing, discount price, stock quantity, or active status.
    """
    return await ProductService.update_variant(
        session=db,
        variant_id=variant_id,
        variant_in=variant_in,
    )


@router.delete("/variants/{variant_id}", response_model=ProductVariantResponse)
async def delete_variant(
    variant_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Soft-delete variant (sets is_active=False).
    """
    return await ProductService.delete_variant(session=db, variant_id=variant_id)


@router.post(
    "/variants/{variant_id}/image",
    response_model=ProductVariantResponse,
    summary="Upload image directly for a product variant",
    description="Uploads, processes, compresses, and stores variant packaging/bottle image on disk, updating variant record in database.",
)
async def upload_variant_image(
    variant_id: int,
    file: UploadFile = File(..., description="Variant bottle/packaging image"),
    fit_mode: str = Form("contain", description="Unified sizing mode: 'contain', 'cover', or 'scale'"),
    quality: Optional[int] = Form(None, ge=1, le=100, description="Optional compression quality (default 85)"),
    db: AsyncSession = Depends(get_db),
):
    upload_res = await ImageService.save_image_to_disk(
        upload_file=file,
        folder="variants",
        fit_mode=fit_mode,
        quality=quality,
    )
    variant, old_url = await ProductService.update_variant_image(
        session=db,
        variant_id=variant_id,
        image_url=upload_res["url"],
    )
    if old_url:
        ImageService.delete_file_by_url(old_url)
    return variant


# ----------------------------------------------------------------------
# Order Management
# ----------------------------------------------------------------------
@router.get("/orders", response_model=List[OrderResponse])
async def list_admin_orders(
    status: Optional[OrderStatus] = Query(None, description="Filter orders by status"),
    affiliate_id: Optional[int] = Query(None, description="Filter orders by affiliate ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """
    Admin: Review orders with filters and pagination.
    """
    return await OrderService.list_admin_orders(
        session=db,
        status_filter=status,
        affiliate_id=affiliate_id,
        skip=skip,
        limit=limit,
    )


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_admin_order_detail(
    order_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Admin: Full order details with customer phone number prominent for WhatsApp order confirmation.
    """
    order = await OrderService.get_order_by_id(session=db, order_id=order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order with ID {order_id} not found.",
        )
    return order


@router.patch("/orders/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: int,
    status_update: OrderStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    Admin: Update order status. If transitioning to CANCELLED from an active status,
    automatically restores reserved stock back to the variants.
    """
    return await OrderService.update_order_status(
        session=db,
        order_id=order_id,
        new_status=status_update.status,
    )


# ----------------------------------------------------------------------
# Affiliate Management
# ----------------------------------------------------------------------
@router.post("/affiliates", response_model=AffiliateResponse, status_code=status.HTTP_201_CREATED)
async def create_affiliate(
    aff_in: AffiliateCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Admin: Create an affiliate record for a promoter/influencer user.
    """
    return await OrderService.create_affiliate(session=db, affiliate_in=aff_in)


@router.get("/affiliates", response_model=List[AffiliateResponse])
async def list_admin_affiliates(
    db: AsyncSession = Depends(get_db),
):
    """
    Admin: List all affiliates with aggregate performance statistics (referred orders & sales volume).
    """
    return await OrderService.list_admin_affiliates(session=db)


# ----------------------------------------------------------------------
# Offer Management
# ----------------------------------------------------------------------
@router.get("/offers", response_model=List[OfferResponse])
async def list_admin_offers(
    active_only: bool = Query(False, description="Filter for currently active offers only"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """
    Admin: List all promotional offers.
    """
    return await OfferService.list_offers(
        session=db,
        active_only=active_only,
        skip=skip,
        limit=limit,
    )


@router.get("/offers/{offer_id}", response_model=OfferResponse)
async def get_admin_offer(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Admin: Get detailed information for a specific offer.
    """
    offer = await OfferService.get_offer_by_id(session=db, offer_id=offer_id)
    if not offer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Offer with ID {offer_id} not found.",
        )
    return offer


@router.post("/offers", response_model=OfferResponse, status_code=status.HTTP_201_CREATED)
async def create_admin_offer(
    offer_in: OfferCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Admin: Create a new promotional offer or discount coupon.
    """
    return await OfferService.create_offer(session=db, offer_in=offer_in)


@router.put("/offers/{offer_id}", response_model=OfferResponse)
@router.patch("/offers/{offer_id}", response_model=OfferResponse)
async def update_admin_offer(
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


@router.delete("/offers/{offer_id}", response_model=MessageResponse)
async def delete_admin_offer(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Admin: Delete an offer.
    """
    await OfferService.delete_offer(session=db, offer_id=offer_id)
    return {"message": "Offer deleted successfully"}


@router.post(
    "/offers/{offer_id}/banner",
    response_model=OfferResponse,
    summary="Upload banner image directly for a promotional offer",
    description="Uploads, processes to unified banner size (1200x600), compresses to WebP, and stores on disk, updating offer banner in database.",
)
async def upload_offer_banner(
    offer_id: int,
    file: UploadFile = File(..., description="Offer banner image file"),
    fit_mode: str = Form("cover", description="Banner sizing mode: 'cover', 'contain', or 'scale'"),
    quality: Optional[int] = Form(None, ge=1, le=100, description="Optional compression quality (default 85)"),
    db: AsyncSession = Depends(get_db),
):
    upload_res = await ImageService.save_image_to_disk(
        upload_file=file,
        folder="offers",
        fit_mode=fit_mode,
        quality=quality,
    )
    offer, old_url = await OfferService.update_offer_banner(
        session=db,
        offer_id=offer_id,
        banner_url=upload_res["url"],
    )
    if old_url:
        ImageService.delete_file_by_url(old_url)
    return offer
