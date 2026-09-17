from decimal import Decimal
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, get_password_hash
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.product import Category, Product, ProductVariant
from app.models.user import User, UserRole

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@pytest_asyncio.fixture(scope="function")
async def db_session():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def auth_tokens(db_session: AsyncSession):
    # Admin user
    admin = User(
        email="admin_catalog@example.com",
        hashed_password=get_password_hash("AdminPass123!"),
        full_name="Admin Catalog User",
        phone="+971501110011",
        role=UserRole.ADMIN,
        is_active=True,
    )
    # Customer user
    customer = User(
        email="customer_catalog@example.com",
        hashed_password=get_password_hash("CustPass123!"),
        full_name="Customer Catalog User",
        phone="+971502220022",
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db_session.add_all([admin, customer])
    await db_session.commit()
    await db_session.refresh(admin)
    await db_session.refresh(customer)

    admin_token = create_access_token(subject=admin.id, role=admin.role.value)
    customer_token = create_access_token(subject=customer.id, role=customer.role.value)

    return {
        "admin_token": admin_token,
        "customer_token": customer_token,
        "admin_id": admin.id,
        "customer_id": customer.id,
    }


@pytest.mark.asyncio
async def test_admin_category_crud(client: AsyncClient, auth_tokens: dict):
    admin_token = auth_tokens["admin_token"]
    client.cookies.set("access_token", admin_token)

    # 1. Create Category
    create_res = await client.post(
        "/api/v1/admin/categories",
        json={"name": "Oriental Perfumes", "slug": "oriental-perfumes"},
    )
    assert create_res.status_code == 201, create_res.text
    cat_data = create_res.json()
    assert cat_data["name"] == "Oriental Perfumes"
    assert cat_data["slug"] == "oriental-perfumes"
    cat_id = cat_data["id"]

    # 2. Update Category
    update_res = await client.put(
        f"/api/v1/admin/categories/{cat_id}",
        json={"name": "Luxury Oriental Perfumes"},
    )
    assert update_res.status_code == 200
    assert update_res.json()["name"] == "Luxury Oriental Perfumes"

    # 3. Public list categories
    client.cookies.delete("access_token")
    public_res = await client.get("/api/v1/products/categories")
    assert public_res.status_code == 200
    names = [c["name"] for c in public_res.json()]
    assert "Luxury Oriental Perfumes" in names


@pytest.mark.asyncio
async def test_admin_atomic_product_creation(client: AsyncClient, auth_tokens: dict, db_session: AsyncSession):
    admin_token = auth_tokens["admin_token"]
    client.cookies.set("access_token", admin_token)

    # Create category first
    category = Category(name="Floral", slug="floral")
    db_session.add(category)
    await db_session.commit()
    await db_session.refresh(category)

    # 1. Create product with initial variants and images atomically
    prod_payload = {
        "category_id": category.id,
        "name": "Velvet Rose & Oud",
        "description": "Exquisite damask rose wrapped with smoky oud wood.",
        "is_active": True,
        "images": [
            {
                "url": "https://cdn.example.com/rose-primary.jpg",
                "alt_text": "Bottle front view",
                "is_primary": True,
                "display_order": 1,
            },
            {
                "url": "https://cdn.example.com/rose-packaging.jpg",
                "alt_text": "Luxury velvet gift box",
                "is_primary": False,
                "display_order": 2,
            },
        ],
        "variants": [
            {
                "sku": "ROSE-50ML",
                "size_or_volume": "50ml",
                "price": "120.00",
                "discount_price": "99.00",
                "stock": 25,
                "is_active": True,
            },
            {
                "sku": "ROSE-100ML",
                "size_or_volume": "100ml",
                "price": "180.00",
                "discount_price": None,
                "stock": 10,
                "is_active": True,
            },
        ],
    }

    res = await client.post("/api/v1/admin/products", json=prod_payload)
    assert res.status_code == 201, res.text
    prod_data = res.json()
    assert prod_data["name"] == "Velvet Rose & Oud"
    assert prod_data["slug"] == "velvet-rose-oud"
    assert len(prod_data["variants"]) == 2
    assert len(prod_data["images"]) == 2

    # 2. Test duplicate SKU rejection
    duplicate_sku_payload = {
        "category_id": category.id,
        "name": "Another Rose Perfume",
        "variants": [
            {
                "sku": "ROSE-50ML",  # already exists!
                "size_or_volume": "50ml",
                "price": "110.00",
            }
        ],
    }
    dup_res = await client.post("/api/v1/admin/products", json=duplicate_sku_payload)
    assert dup_res.status_code == 400
    assert "already exists" in dup_res.json()["error"]["message"].lower()

    # 3. Test non-existent category rejection
    bad_cat_payload = {
        "category_id": 99999,
        "name": "Ghost Perfume",
    }
    bad_cat_res = await client.post("/api/v1/admin/products", json=bad_cat_payload)
    assert bad_cat_res.status_code == 400
    assert "category" in bad_cat_res.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_admin_variant_crud(client: AsyncClient, auth_tokens: dict, db_session: AsyncSession):
    admin_token = auth_tokens["admin_token"]
    client.cookies.set("access_token", admin_token)

    # Setup category and product
    category = Category(name="Citrus", slug="citrus")
    db_session.add(category)
    await db_session.flush()

    product = Product(
        category_id=category.id,
        name="Mediterranean Neroli",
        slug="mediterranean-neroli",
        is_active=True,
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)

    # 1. Add variant to existing product
    var_payload = {
        "sku": "NEROLI-50ML",
        "size_or_volume": "50ml",
        "price": "95.00",
        "discount_price": "85.00",
        "stock": 15,
        "is_active": True,
    }
    add_res = await client.post(f"/api/v1/admin/products/{product.id}/variants", json=var_payload)
    assert add_res.status_code == 201, add_res.text
    var_data = add_res.json()
    assert var_data["sku"] == "NEROLI-50ML"
    assert var_data["stock"] == 15
    variant_id = var_data["id"]

    # 2. Patch variant (update stock and price)
    patch_res = await client.patch(
        f"/api/v1/admin/variants/{variant_id}",
        json={"stock": 30, "price": "90.00"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["stock"] == 30
    assert Decimal(patch_res.json()["price"]) == Decimal("90.00")

    # 3. Soft-delete variant
    del_res = await client.delete(f"/api/v1/admin/variants/{variant_id}")
    assert del_res.status_code == 200
    assert del_res.json()["is_active"] is False


@pytest.mark.asyncio
async def test_public_storefront_listing_and_effective_prices(
    client: AsyncClient,
    auth_tokens: dict,
    db_session: AsyncSession,
):
    admin_token = auth_tokens["admin_token"]
    client.cookies.set("access_token", admin_token)

    category = Category(name="Woody", slug="woody")
    db_session.add(category)
    await db_session.commit()

    # Create active product with 2 variants:
    # Variant A: regular $150, discount $125
    # Variant B: regular $220, no discount
    # -> Effective price range must be $125 (min) to $220 (max)
    active_prod = {
        "category_id": category.id,
        "name": "Cedar & Sandalwood",
        "slug": "cedar-sandalwood",
        "description": "Rich cedarwood combined with Australian sandalwood.",
        "is_active": True,
        "images": [{"url": "https://cdn.example.com/cedar.jpg", "is_primary": True}],
        "variants": [
            {
                "sku": "CEDAR-50ML",
                "size_or_volume": "50ml",
                "price": "150.00",
                "discount_price": "125.00",
                "stock": 20,
            },
            {
                "sku": "CEDAR-100ML",
                "size_or_volume": "100ml",
                "price": "220.00",
                "discount_price": None,
                "stock": 15,
            },
        ],
    }
    await client.post("/api/v1/admin/products", json=active_prod)

    # Create inactive product (must NOT appear in public listing)
    inactive_prod = {
        "category_id": category.id,
        "name": "Archived Amber",
        "slug": "archived-amber",
        "description": "Old batch amber",
        "is_active": False,
        "variants": [{"sku": "AMBER-OLD", "size_or_volume": "50ml", "price": "80.00", "stock": 5}],
    }
    await client.post("/api/v1/admin/products", json=inactive_prod)

    # Switch to unauthenticated public client
    client.cookies.delete("access_token")

    # 1. Public List
    list_res = await client.get("/api/v1/products")
    assert list_res.status_code == 200
    items = list_res.json()
    assert len(items) == 1  # Only active product!

    item = items[0]
    assert item["slug"] == "cedar-sandalwood"
    assert Decimal(item["min_price"]) == Decimal("125.00")  # Uses effective discount price!
    assert Decimal(item["max_price"]) == Decimal("220.00")
    assert item["total_stock"] == 35
    assert item["primary_image_url"] == "https://cdn.example.com/cedar.jpg"
    assert item["category_name"] == "Woody"

    # 2. Public Detail by slug
    detail_res = await client.get("/api/v1/products/cedar-sandalwood")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["name"] == "Cedar & Sandalwood"
    assert len(detail["variants"]) == 2
    assert len(detail["images"]) == 1

    # 3. Filter by category
    filter_res = await client.get("/api/v1/products?category_slug=woody")
    assert filter_res.status_code == 200
    assert len(filter_res.json()) == 1

    empty_res = await client.get("/api/v1/products?category_slug=non-existent")
    assert empty_res.status_code == 200
    assert len(empty_res.json()) == 0

    # 4. Filter by search term
    search_res = await client.get("/api/v1/products?search=sandalwood")
    assert search_res.status_code == 200
    assert len(search_res.json()) == 1

    # 5. Non-existent slug -> 404
    missing_res = await client.get("/api/v1/products/unknown-product")
    assert missing_res.status_code == 404


@pytest.mark.asyncio
async def test_customer_forbidden_on_admin_endpoints(client: AsyncClient, auth_tokens: dict):
    # Customer token
    cust_token = auth_tokens["customer_token"]
    client.cookies.set("access_token", cust_token)

    # 1. POST /admin/categories -> 403
    res1 = await client.post("/api/v1/admin/categories", json={"name": "Forbidden Category"})
    assert res1.status_code == 403

    # 2. POST /admin/products -> 403
    res2 = await client.post(
        "/api/v1/admin/products",
        json={"category_id": 1, "name": "Forbidden Product"},
    )
    assert res2.status_code == 403

    # 3. PUT /admin/products/1 -> 403
    res3 = await client.put("/api/v1/admin/products/1", json={"name": "Forbidden Update"})
    assert res3.status_code == 403

    # 4. DELETE /admin/products/1 -> 403
    res4 = await client.delete("/api/v1/admin/products/1")
    assert res4.status_code == 403

    # 5. POST /admin/products/1/variants -> 403
    res5 = await client.post(
        "/api/v1/admin/products/1/variants",
        json={"sku": "FORBID-50ML", "size_or_volume": "50ml", "price": "100.00"},
    )
    assert res5.status_code == 403

    # 6. Unauthenticated guest -> 401
    client.cookies.delete("access_token")
    guest_res = await client.get("/api/v1/admin/products")
    assert guest_res.status_code == 401
