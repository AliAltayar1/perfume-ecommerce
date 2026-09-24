from decimal import Decimal
import re
from typing import List, Optional
import unicodedata
from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.models.product import Category, Product, ProductImage, ProductVariant
from app.schemas.product import (
    CategoryCreate,
    CategoryUpdate,
    ProductCreate,
    ProductListResponse,
    ProductUpdate,
    ProductVariantCreate,
    ProductVariantUpdate,
)


def slugify(text: str) -> str:
    """
    Generate an SEO-friendly URL slug supporting alphanumeric characters and dashes.
    """
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    slug = re.sub(r"[-\s]+", "-", text)
    return slug or "item"


async def generate_unique_category_slug(
    session: AsyncSession,
    name: str,
    requested_slug: Optional[str] = None,
    exclude_id: Optional[int] = None,
) -> str:
    candidate = slugify(requested_slug) if requested_slug else slugify(name)
    slug = candidate
    counter = 1
    while True:
        query = select(Category).where(Category.slug == slug)
        if exclude_id:
            query = query.where(Category.id != exclude_id)
        res = await session.execute(query)
        if not res.scalars().first():
            return slug
        counter += 1
        slug = f"{candidate}-{counter}"


async def generate_unique_product_slug(
    session: AsyncSession,
    name: str,
    requested_slug: Optional[str] = None,
    exclude_id: Optional[int] = None,
) -> str:
    candidate = slugify(requested_slug) if requested_slug else slugify(name)
    slug = candidate
    counter = 1
    while True:
        query = select(Product).where(Product.slug == slug)
        if exclude_id:
            query = query.where(Product.id != exclude_id)
        res = await session.execute(query)
        if not res.scalars().first():
            return slug
        counter += 1
        slug = f"{candidate}-{counter}"


class ProductService:
    # ---------------------------------------------------------
    # Public Storefront Operations
    # ---------------------------------------------------------
    @staticmethod
    async def list_categories(session: AsyncSession) -> List[Category]:
        """
        List all product categories ordered by name.
        """
        query = select(Category).order_by(Category.name.asc())
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def list_products(
        session: AsyncSession,
        category_slug: Optional[str] = None,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> List[ProductListResponse]:
        """
        List active products with eager loaded variants and images.
        Computes effective min/max prices (incorporating active discounts),
        total stock, and primary image URL.
        """
        query = (
            select(Product)
            .where(Product.is_active == True)  # noqa: E712
            .options(
                selectinload(Product.category),
                selectinload(Product.variants),
                selectinload(Product.images),
            )
            .order_by(Product.created_at.desc())
        )

        if category_slug:
            query = query.join(Product.category).where(Category.slug == category_slug)

        if search and search.strip():
            term = f"%{search.strip()}%"
            query = query.where(or_(Product.name.ilike(term), Product.description.ilike(term)))

        query = query.offset(skip).limit(limit)
        result = await session.execute(query)
        products = result.scalars().all()

        response_items: List[ProductListResponse] = []
        for p in products:
            # 1. Effective prices among active variants
            active_variants = [v for v in p.variants if v.is_active]
            effective_prices: List[Decimal] = [
                v.discount_price if v.discount_price is not None else v.price
                for v in active_variants
            ]
            min_price = min(effective_prices) if effective_prices else None
            max_price = max(effective_prices) if effective_prices else None
            total_stock = sum(v.stock for v in active_variants)

            # 2. Primary image resolution
            primary_img = next((img.url for img in p.images if img.is_primary), None)
            if not primary_img and p.images:
                primary_img = p.images[0].url
            if not primary_img and active_variants:
                primary_img = next((v.image_url for v in active_variants if v.image_url), None)

            response_items.append(
                ProductListResponse(
                    id=p.id,
                    category_id=p.category_id,
                    name=p.name,
                    slug=p.slug,
                    description=p.description,
                    is_active=p.is_active,
                    primary_image_url=primary_img,
                    min_price=min_price,
                    max_price=max_price,
                    total_stock=total_stock,
                    category_name=p.category.name if p.category else None,
                )
            )

        return response_items

    @staticmethod
    async def get_product_by_slug(session: AsyncSession, slug: str) -> Optional[Product]:
        """
        Fetch single active product with all active variants and sorted images.
        """
        query = (
            select(Product)
            .where(Product.slug == slug, Product.is_active == True)  # noqa: E712
            .options(
                selectinload(Product.category),
                selectinload(Product.variants),
                selectinload(Product.images),
            )
        )
        result = await session.execute(query)
        product = result.scalars().first()
        if product:
            # Sort images by display_order
            product.images.sort(key=lambda img: img.display_order)
            # Filter active variants
            product.variants = [v for v in product.variants if v.is_active]
        return product

    @staticmethod
    async def get_product_by_id(session: AsyncSession, product_id: int) -> Optional[Product]:
        """
        Fetch single product by primary key ID with all variants and sorted images.
        """
        query = (
            select(Product)
            .where(Product.id == product_id)
            .options(
                selectinload(Product.category),
                selectinload(Product.variants),
                selectinload(Product.images),
            )
        )
        result = await session.execute(query)
        product = result.scalars().first()
        if product:
            product.images.sort(key=lambda img: img.display_order)
        return product

    # ---------------------------------------------------------
    # Admin Category Operations
    # ---------------------------------------------------------
    @staticmethod
    async def create_category(session: AsyncSession, category_in: CategoryCreate) -> Category:
        slug = await generate_unique_category_slug(
            session=session,
            name=category_in.name,
            requested_slug=category_in.slug,
        )
        category = Category(name=category_in.name, slug=slug)
        session.add(category)
        await session.commit()
        await session.refresh(category)
        return category

    @staticmethod
    async def update_category(
        session: AsyncSession,
        category_id: int,
        category_in: CategoryUpdate,
    ) -> Category:
        query = select(Category).where(Category.id == category_id)
        res = await session.execute(query)
        category = res.scalars().first()
        if not category:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Category with ID {category_id} not found",
            )

        if category_in.name is not None:
            category.name = category_in.name

        if category_in.slug is not None or category_in.name is not None:
            category.slug = await generate_unique_category_slug(
                session=session,
                name=category.name,
                requested_slug=category_in.slug,
                exclude_id=category.id,
            )

        await session.commit()
        await session.refresh(category)
        return category

    @staticmethod
    async def delete_category(session: AsyncSession, category_id: int) -> None:
        query = select(Category).where(Category.id == category_id)
        res = await session.execute(query)
        category = res.scalars().first()
        if not category:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Category with ID {category_id} not found",
            )

        # Check if products reference this category
        prod_check = select(Product).where(Product.category_id == category_id)
        has_prods = (await session.execute(prod_check)).scalars().first()
        if has_prods:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete category because it contains existing products. Reassign or delete products first.",
            )

        await session.delete(category)
        await session.commit()

    # ---------------------------------------------------------
    # Admin Product Operations (Atomic Transactions)
    # ---------------------------------------------------------
    @staticmethod
    async def list_admin_products(
        session: AsyncSession,
        skip: int = 0,
        limit: int = 50,
        category_id: Optional[int] = None,
    ) -> List[Product]:
        """
        List all products (both active and inactive) for admin inventory control.
        """
        query = (
            select(Product)
            .options(
                selectinload(Product.category),
                selectinload(Product.variants),
                selectinload(Product.images),
            )
            .order_by(Product.id.desc())
        )

        if category_id:
            query = query.where(Product.category_id == category_id)

        query = query.offset(skip).limit(limit)
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def create_product(session: AsyncSession, product_in: ProductCreate) -> Product:
        """
        Atomic transaction: validates category, validates SKUs, generates unique slug,
        and persists product with all initial variants and images.
        """
        # 1. Verify Category exists
        cat_query = select(Category).where(Category.id == product_in.category_id)
        category = (await session.execute(cat_query)).scalars().first()
        if not category:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Category with ID {product_in.category_id} does not exist.",
            )

        # 2. Check SKU uniqueness for all initial variants
        variant_skus = [v.sku for v in product_in.variants]
        if len(variant_skus) != len(set(variant_skus)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Duplicate SKUs found within the payload variants list.",
            )

        for sku in variant_skus:
            sku_check = select(ProductVariant).where(ProductVariant.sku == sku)
            if (await session.execute(sku_check)).scalars().first():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Product variant with SKU '{sku}' already exists.",
                )

        # 3. Generate unique slug
        slug = await generate_unique_product_slug(
            session=session,
            name=product_in.name,
            requested_slug=product_in.slug,
        )

        try:
            # 4. Create Product
            product = Product(
                category_id=product_in.category_id,
                name=product_in.name,
                slug=slug,
                description=product_in.description,
                is_active=product_in.is_active,
            )

            # 5. Attach initial variants
            for v_in in product_in.variants:
                variant = ProductVariant(
                    sku=v_in.sku,
                    size_or_volume=v_in.size_or_volume,
                    price=v_in.price,
                    discount_price=v_in.discount_price,
                    stock=v_in.stock,
                    image_url=v_in.image_url,
                    is_active=v_in.is_active,
                )
                product.variants.append(variant)

            # 6. Attach initial images
            for img_in in product_in.images:
                image = ProductImage(
                    url=img_in.url,
                    alt_text=img_in.alt_text,
                    is_primary=img_in.is_primary,
                    display_order=img_in.display_order,
                )
                product.images.append(image)

            session.add(product)
            await session.commit()
            await session.refresh(product, ["category", "variants", "images"])
            return product
        except Exception:
            await session.rollback()
            raise

    @staticmethod
    async def update_product(
        session: AsyncSession,
        product_id: int,
        product_in: ProductUpdate,
    ) -> Product:
        """
        Update core product fields.
        """
        query = (
            select(Product)
            .where(Product.id == product_id)
            .options(
                selectinload(Product.category),
                selectinload(Product.variants),
                selectinload(Product.images),
            )
        )
        product = (await session.execute(query)).scalars().first()
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product with ID {product_id} not found.",
            )

        if product_in.category_id is not None:
            cat_query = select(Category).where(Category.id == product_in.category_id)
            if not (await session.execute(cat_query)).scalars().first():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Category with ID {product_in.category_id} does not exist.",
                )
            product.category_id = product_in.category_id

        if product_in.name is not None:
            product.name = product_in.name

        if product_in.slug is not None:
            product.slug = await generate_unique_product_slug(
                session=session,
                name=product.name,
                requested_slug=product_in.slug,
                exclude_id=product.id,
            )

        if product_in.description is not None:
            product.description = product_in.description

        if product_in.is_active is not None:
            product.is_active = product_in.is_active

        await session.commit()
        await session.refresh(product, ["category", "variants", "images"])
        return product

    @staticmethod
    async def delete_product(session: AsyncSession, product_id: int) -> Product:
        """
        Soft-delete product by marking is_active = False (preserves past order items).
        """
        query = (
            select(Product)
            .where(Product.id == product_id)
            .options(
                selectinload(Product.category),
                selectinload(Product.variants),
                selectinload(Product.images),
            )
        )
        product = (await session.execute(query)).scalars().first()
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product with ID {product_id} not found.",
            )

        product.is_active = False
        await session.commit()
        await session.refresh(product)
        return product

    # ---------------------------------------------------------
    # Admin Variant Operations
    # ---------------------------------------------------------
    @staticmethod
    async def create_variant(
        session: AsyncSession,
        product_id: int,
        variant_in: ProductVariantCreate,
    ) -> ProductVariant:
        """
        Add a new variant to an existing product with SKU uniqueness verification.
        """
        # 1. Verify product exists
        prod_query = select(Product).where(Product.id == product_id)
        if not (await session.execute(prod_query)).scalars().first():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product with ID {product_id} not found.",
            )

        # 2. Verify SKU uniqueness
        sku_check = select(ProductVariant).where(ProductVariant.sku == variant_in.sku)
        if (await session.execute(sku_check)).scalars().first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Product variant with SKU '{variant_in.sku}' already exists.",
            )

        variant = ProductVariant(
            product_id=product_id,
            sku=variant_in.sku,
            size_or_volume=variant_in.size_or_volume,
            price=variant_in.price,
            discount_price=variant_in.discount_price,
            stock=variant_in.stock,
            image_url=variant_in.image_url,
            is_active=variant_in.is_active,
        )
        session.add(variant)
        await session.commit()
        await session.refresh(variant)
        return variant

    @staticmethod
    async def update_variant(
        session: AsyncSession,
        variant_id: int,
        variant_in: ProductVariantUpdate,
    ) -> ProductVariant:
        query = select(ProductVariant).where(ProductVariant.id == variant_id)
        variant = (await session.execute(query)).scalars().first()
        if not variant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product variant with ID {variant_id} not found.",
            )

        if variant_in.sku is not None and variant_in.sku != variant.sku:
            sku_check = select(ProductVariant).where(
                ProductVariant.sku == variant_in.sku,
                ProductVariant.id != variant_id,
            )
            if (await session.execute(sku_check)).scalars().first():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Product variant with SKU '{variant_in.sku}' already exists.",
                )
            variant.sku = variant_in.sku

        if variant_in.size_or_volume is not None:
            variant.size_or_volume = variant_in.size_or_volume
        if variant_in.price is not None:
            variant.price = variant_in.price
        if variant_in.discount_price is not None:
            variant.discount_price = variant_in.discount_price
        if variant_in.stock is not None:
            variant.stock = variant_in.stock
        if variant_in.image_url is not None:
            variant.image_url = variant_in.image_url
        if variant_in.is_active is not None:
            variant.is_active = variant_in.is_active

        await session.commit()
        await session.refresh(variant)
        return variant

    @staticmethod
    async def delete_variant(session: AsyncSession, variant_id: int) -> ProductVariant:
        """
        Soft delete variant by toggling is_active = False.
        """
        query = select(ProductVariant).where(ProductVariant.id == variant_id)
        variant = (await session.execute(query)).scalars().first()
        if not variant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product variant with ID {variant_id} not found.",
            )

        variant.is_active = False
        await session.commit()
        await session.refresh(variant)
        return variant

    # ---------------------------------------------------------
    # Product Image Management
    # ---------------------------------------------------------
    @staticmethod
    async def add_product_image(
        session: AsyncSession,
        product_id: int,
        url: str,
        alt_text: Optional[str] = None,
        is_primary: bool = False,
        display_order: int = 0,
    ) -> ProductImage:
        """
        Add an image to a product. If marked as primary, demotes existing primary images.
        """
        # Verify product exists
        product_check = await session.execute(
            select(Product).where(Product.id == product_id)
        )
        if not product_check.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product with ID {product_id} not found.",
            )

        if is_primary:
            # Demote any current primary images
            existing_primary_res = await session.execute(
                select(ProductImage).where(
                    ProductImage.product_id == product_id,
                    ProductImage.is_primary == True,  # noqa: E712
                )
            )
            for existing_img in existing_primary_res.scalars().all():
                existing_img.is_primary = False

        new_image = ProductImage(
            product_id=product_id,
            url=url,
            alt_text=alt_text,
            is_primary=is_primary,
            display_order=display_order,
        )
        session.add(new_image)
        await session.commit()
        await session.refresh(new_image)
        return new_image

    @staticmethod
    async def delete_product_image(
        session: AsyncSession,
        product_id: int,
        image_id: int,
    ) -> str:
        """
        Delete a product image from the database and return its URL for disk cleanup.
        """
        query = select(ProductImage).where(
            ProductImage.id == image_id,
            ProductImage.product_id == product_id,
        )
        image = (await session.execute(query)).scalars().first()
        if not image:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product image with ID {image_id} not found for product {product_id}.",
            )

        image_url = image.url
        was_primary = image.is_primary

        await session.delete(image)

        # If deleted image was primary, promote next available image
        if was_primary:
            next_img_res = await session.execute(
                select(ProductImage)
                .where(ProductImage.product_id == product_id, ProductImage.id != image_id)
                .order_by(ProductImage.display_order.asc(), ProductImage.id.asc())
            )
            next_img = next_img_res.scalars().first()
            if next_img:
                next_img.is_primary = True

        await session.commit()
        return image_url

    @staticmethod
    async def set_primary_product_image(
        session: AsyncSession,
        product_id: int,
        image_id: int,
    ) -> ProductImage:
        """
        Promote a specific image to be the primary showcase hero image for the product.
        """
        # Find target image
        query = select(ProductImage).where(
            ProductImage.id == image_id,
            ProductImage.product_id == product_id,
        )
        target_image = (await session.execute(query)).scalars().first()
        if not target_image:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product image with ID {image_id} not found for product {product_id}.",
            )

        # Unset all other primary images
        all_imgs_res = await session.execute(
            select(ProductImage).where(
                ProductImage.product_id == product_id,
                ProductImage.id != image_id,
                ProductImage.is_primary == True,  # noqa: E712
            )
        )
        for img in all_imgs_res.scalars().all():
            img.is_primary = False

        target_image.is_primary = True
        await session.commit()
        await session.refresh(target_image)
        return target_image

    @staticmethod
    async def update_variant_image(
        session: AsyncSession,
        variant_id: int,
        image_url: str,
    ) -> tuple[ProductVariant, Optional[str]]:
        """
        Update the image URL for a variant and return old image URL for disk cleanup.
        """
        query = select(ProductVariant).where(ProductVariant.id == variant_id)
        variant = (await session.execute(query)).scalars().first()
        if not variant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product variant with ID {variant_id} not found.",
            )

        old_url = variant.image_url
        variant.image_url = image_url
        await session.commit()
        await session.refresh(variant)
        return variant, old_url
