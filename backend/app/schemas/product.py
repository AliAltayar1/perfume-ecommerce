from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


# --- Category Schemas ---
class CategoryBase(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Category display title",
        examples=["French Perfumes"],
    )
    slug: Optional[str] = Field(
        None,
        max_length=120,
        description="Custom URL slug (auto-generated if omitted)",
        examples=["french-perfumes"],
    )


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100, examples=["Luxury French Perfumes"])
    slug: Optional[str] = Field(None, max_length=120, examples=["luxury-french-perfumes"])


class CategoryResponse(BaseModel):
    id: int = Field(..., description="Unique category identifier", examples=[1])
    name: str = Field(..., description="Category name", examples=["French Perfumes"])
    slug: str = Field(..., description="SEO slug", examples=["french-perfumes"])
    created_at: datetime = Field(..., description="Creation timestamp")

    model_config = ConfigDict(from_attributes=True)


# --- Product Image Schemas ---
class ProductImageBase(BaseModel):
    url: str = Field(
        ...,
        max_length=500,
        description="Direct image CDN or public URL",
        examples=["https://images.unsplash.com/photo-1592945403244-b3fbafd7f539?w=800&q=80"],
    )
    alt_text: Optional[str] = Field(
        None,
        max_length=255,
        description="Accessibility alt text and SEO caption",
        examples=["Baccarat Rouge bottle on black marble"],
    )
    is_primary: bool = Field(
        default=False,
        description="Flag denoting the primary hero image for product cards",
        examples=[True],
    )
    display_order: int = Field(
        default=0,
        description="Ascending sort order for media galleries",
        examples=[1],
    )


class ProductImageCreate(ProductImageBase):
    pass


class ProductImageResponse(ProductImageBase):
    id: int = Field(..., description="Unique image identifier", examples=[1])
    product_id: int = Field(..., description="Foreign key linking to product", examples=[1])

    model_config = ConfigDict(from_attributes=True)


# --- Product Variant Schemas ---
class ProductVariantBase(BaseModel):
    sku: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique Stock Keeping Unit barcode identifier",
        examples=["BRE-100ML"],
    )
    size_or_volume: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Physical volume or container packaging size",
        examples=["100ml"],
    )
    price: Decimal = Field(
        ...,
        ge=0,
        decimal_places=2,
        description="Regular retail sales price",
        examples=["210.00"],
    )
    discount_price: Optional[Decimal] = Field(
        None,
        ge=0,
        decimal_places=2,
        description="Special promotional price (overrides price when present)",
        examples=["180.00"],
    )
    stock: int = Field(
        default=0,
        ge=0,
        description="Available on-hand physical warehouse stock",
        examples=[25],
    )
    image_url: Optional[str] = Field(
        None,
        max_length=500,
        description="Variant-specific packaging or bottle image URL",
        examples=["https://images.unsplash.com/photo-1592945403244-b3fbafd7f539?w=800&q=80"],
    )
    is_active: bool = Field(
        default=True,
        description="Whether this variant is available for purchase",
        examples=[True],
    )


class ProductVariantCreate(ProductVariantBase):
    pass


class ProductVariantUpdate(BaseModel):
    sku: Optional[str] = Field(None, min_length=1, max_length=100, examples=["BRE-100ML-V2"])
    size_or_volume: Optional[str] = Field(None, min_length=1, max_length=50, examples=["100ml"])
    price: Optional[Decimal] = Field(None, ge=0, decimal_places=2, examples=["220.00"])
    discount_price: Optional[Decimal] = Field(None, ge=0, decimal_places=2, examples=["195.00"])
    stock: Optional[int] = Field(None, ge=0, examples=[50])
    image_url: Optional[str] = Field(None, max_length=500)
    is_active: Optional[bool] = None


class ProductVariantResponse(ProductVariantBase):
    id: int = Field(..., description="Unique variant identifier", examples=[1])
    product_id: int = Field(..., description="Associated product ID", examples=[1])

    model_config = ConfigDict(from_attributes=True)


# --- Product Schemas ---
class ProductBase(BaseModel):
    category_id: int = Field(
        ...,
        description="Target category foreign key identifier",
        examples=[1],
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Product marketing name",
        examples=["Baccarat Rouge Elite"],
    )
    slug: Optional[str] = Field(
        None,
        max_length=255,
        description="Custom slug (auto-generated if omitted)",
        examples=["baccarat-rouge-elite"],
    )
    description: Optional[str] = Field(
        None,
        description="Detailed olfactory notes and fragrance description",
        examples=["An intoxicating blend of saffron, Egyptian jasmine, and warm amberwood."],
    )


class ProductCreate(ProductBase):
    is_active: bool = Field(
        default=True,
        description="Initial active catalog visibility",
        examples=[True],
    )
    images: List[ProductImageCreate] = Field(
        default=[],
        description="Initial image gallery to attach atomically",
    )
    variants: List[ProductVariantCreate] = Field(
        default=[],
        description="Initial variants (sizes/volumes) to attach atomically",
    )


class ProductUpdate(BaseModel):
    category_id: Optional[int] = Field(None, examples=[2])
    name: Optional[str] = Field(None, min_length=1, max_length=255, examples=["Royal Ambergris Oud"])
    slug: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ProductListResponse(BaseModel):
    id: int = Field(..., description="Unique product ID", examples=[1])
    category_id: int = Field(..., description="Category foreign key", examples=[1])
    name: str = Field(..., description="Product name", examples=["Baccarat Rouge Elite"])
    slug: str = Field(..., description="Unique URL slug", examples=["baccarat-rouge-elite"])
    description: Optional[str] = Field(None, description="Product summary")
    is_active: bool = Field(..., description="Active availability status", examples=[True])
    primary_image_url: Optional[str] = Field(
        None,
        description="Hero showcase image URL",
        examples=["https://images.unsplash.com/photo-1592945403244-b3fbafd7f539?w=800&q=80"],
    )
    min_price: Optional[Decimal] = Field(
        None,
        description="Lowest effective variant price across active inventory",
        examples=["110.00"],
    )
    max_price: Optional[Decimal] = Field(
        None,
        description="Highest effective variant price across active inventory",
        examples=["210.00"],
    )
    total_stock: int = Field(
        default=0,
        description="Cumulative stock units across all active variants",
        examples=[55],
    )
    category_name: Optional[str] = Field(
        None,
        description="Human-readable category name",
        examples=["French Perfumes"],
    )

    model_config = ConfigDict(from_attributes=True)


class ProductDetailResponse(BaseModel):
    id: int = Field(..., description="Product ID", examples=[1])
    category_id: int = Field(..., description="Category foreign key", examples=[1])
    name: str = Field(..., description="Product title", examples=["Baccarat Rouge Elite"])
    slug: str = Field(..., description="SEO slug", examples=["baccarat-rouge-elite"])
    description: Optional[str] = Field(None, description="Fragrance notes breakdown")
    is_active: bool = Field(..., description="Active visibility status", examples=[True])
    created_at: datetime = Field(..., description="Created timestamp")
    updated_at: datetime = Field(..., description="Last modified timestamp")
    category: Optional[CategoryResponse] = Field(None, description="Category metadata")
    variants: List[ProductVariantResponse] = Field(
        default=[],
        description="All active product variants sorted by volume/price",
    )
    images: List[ProductImageResponse] = Field(
        default=[],
        description="All product gallery images sorted by display_order",
    )

    model_config = ConfigDict(from_attributes=True)


# --- Backward-Compatibility Aliases ---
CategoryOut = CategoryResponse
ProductVariantOut = ProductVariantResponse
ProductImageOut = ProductImageResponse
ProductOut = ProductDetailResponse
