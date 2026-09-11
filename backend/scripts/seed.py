import argparse
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sys

# Ensure backend root is on sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.security import get_password_hash
from app.db.base import Base
from app.models.affiliate import Affiliate
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Category, Product, ProductImage, ProductVariant
from app.models.user import User, UserRole


async def seed_database(db_url: str, force: bool = False) -> None:
    print(f"Connecting to database: {db_url}")
    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        # Check if admin user already exists
        admin_check = await session.execute(
            select(User).where(User.email == "admin@perfume.com")
        )
        existing_admin = admin_check.scalars().first()

        if existing_admin and not force:
            print("[INFO] Database already seeded (Admin exists). Use --force to override.")
            await engine.dispose()
            return

        if force:
            print("[INFO] Force flag detected. Cleaning existing records...")
            try:
                # Fast truncate for PostgreSQL
                await session.execute(
                    text(
                        "TRUNCATE TABLE order_items, orders, affiliates, "
                        "product_variants, product_images, products, categories, "
                        "refresh_tokens, users RESTART IDENTITY CASCADE;"
                    )
                )
                await session.commit()
            except Exception:
                await session.rollback()
                # Fallback for SQLite / engines without CASCADE TRUNCATE
                for tbl in [
                    "order_items",
                    "orders",
                    "affiliates",
                    "product_variants",
                    "product_images",
                    "products",
                    "categories",
                    "refresh_tokens",
                    "users",
                ]:
                    try:
                        await session.execute(text(f"DELETE FROM {tbl};"))
                    except Exception:
                        pass
                await session.commit()

        # -------------------------------------------------------------
        # 1. Seed Core Users
        # -------------------------------------------------------------
        print("[1/5] Seeding core users (Admin, Affiliate, Customer)...")
        admin_user = User(
            email="admin@perfume.com",
            hashed_password=get_password_hash("Admin@123456"),
            full_name="System Administrator",
            phone="+971501111000",
            role=UserRole.ADMIN,
            is_active=True,
        )
        affiliate_user = User(
            email="affiliate@perfume.com",
            hashed_password=get_password_hash("Affiliate@123"),
            full_name="Ali Perfume Promoters",
            phone="+971502222000",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        customer_user = User(
            email="customer@perfume.com",
            hashed_password=get_password_hash("Customer@123"),
            full_name="Tariq Al-Fahim",
            phone="+971503333000",
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        session.add_all([admin_user, affiliate_user, customer_user])
        await session.flush()

        # -------------------------------------------------------------
        # 2. Seed Affiliate Profile
        # -------------------------------------------------------------
        print("[2/5] Seeding Affiliate profile (code: ALI2026)...")
        affiliate_profile = Affiliate(
            user_id=affiliate_user.id,
            code="ALI2026",
            is_active=True,
        )
        session.add(affiliate_profile)
        await session.flush()

        # -------------------------------------------------------------
        # 3. Seed Categories
        # -------------------------------------------------------------
        print("[3/5] Seeding Categories...")
        cat_french = Category(
            name="French Perfumes",
            slug="french-perfumes",
        )
        cat_oud = Category(
            name="Oud & Oriental",
            slug="oud-oriental",
        )
        session.add_all([cat_french, cat_oud])
        await session.flush()

        # -------------------------------------------------------------
        # 4. Seed Products, Variants & Images
        # -------------------------------------------------------------
        print("[4/5] Seeding Products & Variants...")
        # Product 1: French
        p1 = Product(
            category_id=cat_french.id,
            name="Bleu de Grasse Eau de Parfum",
            slug="bleu-de-grasse-edp",
            description="An exquisite French aromatic fragrance featuring bergamot, lavender, crisp cedarwood, and rich ambergris.",
            is_active=True,
        )
        session.add(p1)
        await session.flush()

        img1 = ProductImage(
            product_id=p1.id,
            url="https://images.unsplash.com/photo-1592945403244-b3fbafd7f539?auto=format&fit=crop&w=800&q=80",
            alt_text="Bleu de Grasse Bottle Presentation",
            is_primary=True,
        )
        v1_1 = ProductVariant(
            product_id=p1.id,
            sku="BDG-50ML",
            size_or_volume="50ml",
            price=Decimal("85.00"),
            discount_price=None,
            stock=45,
            is_active=True,
        )
        v1_2 = ProductVariant(
            product_id=p1.id,
            sku="BDG-100ML",
            size_or_volume="100ml",
            price=Decimal("135.00"),
            discount_price=Decimal("115.00"),
            stock=30,
            is_active=True,
        )
        session.add_all([img1, v1_1, v1_2])

        # Product 2: French
        p2 = Product(
            category_id=cat_french.id,
            name="Rose Impériale Intense",
            slug="rose-imperiale-intense",
            description="Velvety Grasse roses infused with pink pepper, Moroccan neroli, bourbon vanilla, and white musk.",
            is_active=True,
        )
        session.add(p2)
        await session.flush()

        img2 = ProductImage(
            product_id=p2.id,
            url="https://images.unsplash.com/photo-1588405748880-12d1d2a59f75?auto=format&fit=crop&w=800&q=80",
            alt_text="Rose Impériale Intense Flacon",
            is_primary=True,
        )
        v2_1 = ProductVariant(
            product_id=p2.id,
            sku="RII-50ML",
            size_or_volume="50ml",
            price=Decimal("95.00"),
            discount_price=None,
            stock=25,
            is_active=True,
        )
        v2_2 = ProductVariant(
            product_id=p2.id,
            sku="RII-100ML",
            size_or_volume="100ml",
            price=Decimal("145.00"),
            discount_price=None,
            stock=20,
            is_active=True,
        )
        session.add_all([img2, v2_1, v2_2])

        # Product 3: Oud
        p3 = Product(
            category_id=cat_oud.id,
            name="Royal Cambodian Oud Blend",
            slug="royal-cambodian-oud-blend",
            description="Aged wild agarwood combined with Taif rose, warm spices, dark frankincense, and leathery undertones.",
            is_active=True,
        )
        session.add(p3)
        await session.flush()

        img3 = ProductImage(
            product_id=p3.id,
            url="https://images.unsplash.com/photo-1547887537-6158d64c35b3?auto=format&fit=crop&w=800&q=80",
            alt_text="Royal Cambodian Oud Crystal Bottle",
            is_primary=True,
        )
        v3_1 = ProductVariant(
            product_id=p3.id,
            sku="RCO-30ML",
            size_or_volume="30ml",
            price=Decimal("150.00"),
            discount_price=None,
            stock=15,
            is_active=True,
        )
        v3_2 = ProductVariant(
            product_id=p3.id,
            sku="RCO-50ML",
            size_or_volume="50ml",
            price=Decimal("230.00"),
            discount_price=Decimal("199.00"),
            stock=25,
            is_active=True,
        )
        v3_3 = ProductVariant(
            product_id=p3.id,
            sku="RCO-100ML",
            size_or_volume="100ml",
            price=Decimal("380.00"),
            discount_price=None,
            stock=12,
            is_active=True,
        )
        session.add_all([img3, v3_1, v3_2, v3_3])

        # Product 4: Oud
        p4 = Product(
            category_id=cat_oud.id,
            name="Amber & Musk Velvet Elixir",
            slug="amber-musk-velvet-elixir",
            description="Sublime golden amber enveloped in cashmere woods, silky white musk, and delicate Madagascar vanilla.",
            is_active=True,
        )
        session.add(p4)
        await session.flush()

        img4 = ProductImage(
            product_id=p4.id,
            url="https://images.unsplash.com/photo-1523293182086-7651a899d37f?auto=format&fit=crop&w=800&q=80",
            alt_text="Amber & Musk Velvet Elixir Luxury Bottle",
            is_primary=True,
        )
        v4_1 = ProductVariant(
            product_id=p4.id,
            sku="AMV-50ML",
            size_or_volume="50ml",
            price=Decimal("75.00"),
            discount_price=None,
            stock=50,
            is_active=True,
        )
        v4_2 = ProductVariant(
            product_id=p4.id,
            sku="AMV-100ML",
            size_or_volume="100ml",
            price=Decimal("120.00"),
            discount_price=Decimal("99.00"),
            stock=35,
            is_active=True,
        )
        session.add_all([img4, v4_1, v4_2])
        await session.flush()

        # -------------------------------------------------------------
        # 5. Seed Sample Orders
        # -------------------------------------------------------------
        print("[5/5] Seeding Sample Orders...")
        # Order 1: Pending order linked to affiliate ALI2026
        order1 = Order(
            user_id=customer_user.id,
            affiliate_id=affiliate_profile.id,
            status=OrderStatus.PENDING,
            total_amount=Decimal("200.00"),
            shipping_name="Sultan Al-Nuaimi",
            shipping_phone="+971554443322",
            shipping_city="Abu Dhabi",
            shipping_address="Al Bateen, Villa 14, Street 19",
            customer_notes="Please deliver between 4 PM and 8 PM.",
        )
        session.add(order1)
        await session.flush()

        item1_1 = OrderItem(
            order_id=order1.id,
            variant_id=v1_1.id,
            quantity=1,
            unit_price=Decimal("85.00"),
            product_name="Bleu de Grasse Eau de Parfum",
            variant_sku="BDG-50ML",
            size_or_volume="50ml",
        )
        item1_2 = OrderItem(
            order_id=order1.id,
            variant_id=v1_2.id,
            quantity=1,
            unit_price=Decimal("115.00"),
            product_name="Bleu de Grasse Eau de Parfum",
            variant_sku="BDG-100ML",
            size_or_volume="100ml",
        )
        session.add_all([item1_1, item1_2])

        # Order 2: Delivered order placed by customer
        order2 = Order(
            user_id=customer_user.id,
            affiliate_id=None,
            status=OrderStatus.DELIVERED,
            total_amount=Decimal("115.00"),
            shipping_name="Tariq Al-Fahim",
            shipping_phone="+971503333000",
            shipping_city="Dubai",
            shipping_address="Downtown Dubai, Boulevard Crescent, Tower 2, Apt 804",
            customer_notes="Leave with reception if not answering.",
        )
        session.add(order2)
        await session.flush()

        item2_1 = OrderItem(
            order_id=order2.id,
            variant_id=v1_2.id,
            quantity=1,
            unit_price=Decimal("115.00"),
            product_name="Bleu de Grasse Eau de Parfum",
            variant_sku="BDG-100ML",
            size_or_volume="100ml",
        )
        session.add(item2_1)

        await session.commit()

        print("\n[SUCCESS] Database seeding completed successfully!\n")
        print("Summary of Seeded Data:")
        print("  - Admin: admin@perfume.com / Admin@123456")
        print("  - Affiliate: affiliate@perfume.com / Affiliate@123 (Promoter Code: ALI2026)")
        print("  - Customer: customer@perfume.com / Customer@123")
        print("  - Categories: 2 (French Perfumes, Oud & Oriental)")
        print("  - Products: 4 (9 total variants, all stock > 10)")
        print("  - Orders: 2 sample orders (1 pending with ALI2026, 1 delivered)")

    await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Seed database with realistic initial e-commerce data.")
    parser.add_argument("--force", action="store_true", help="Force wipe and re-seed if database already populated.")
    parser.add_argument("--db-url", type=str, default=None, help="Custom database connection URL.")
    parser.add_argument("--sqlite", action="store_true", help="Use local SQLite database file (local_dev.db).")

    args = parser.parse_args()

    if args.sqlite:
        db_url = "sqlite+aiosqlite:///local_dev.db"
    elif args.db_url:
        db_url = args.db_url
    else:
        db_url = settings.async_database_url

    asyncio.run(seed_database(db_url=db_url, force=args.force))


if __name__ == "__main__":
    main()
