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
from app.models.affiliate import Affiliate
from app.models.order import Order, OrderStatus
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
async def setup_data(db_session: AsyncSession):
    # 1. Admin
    admin = User(
        email="admin_orders@example.com",
        hashed_password=get_password_hash("AdminPass123!"),
        full_name="Orders Admin",
        role=UserRole.ADMIN,
        is_active=True,
    )
    # 2. Customer
    customer = User(
        email="customer_orders@example.com",
        hashed_password=get_password_hash("CustPass123!"),
        full_name="Loyal Shopper",
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    # 3. Affiliate User
    aff_user = User(
        email="promoter@example.com",
        hashed_password=get_password_hash("Promote123!"),
        full_name="Beauty Influencer",
        role=UserRole.AFFILIATE,
        is_active=True,
    )
    db_session.add_all([admin, customer, aff_user])
    await db_session.flush()

    # 4. Affiliate Record
    affiliate = Affiliate(
        user_id=aff_user.id,
        code="SUMMER26",
        is_active=True,
    )
    # 5. Category & Product & Variants
    category = Category(name="Amber Perfumes", slug="amber-perfumes")
    db_session.add_all([affiliate, category])
    await db_session.flush()

    product = Product(
        category_id=category.id,
        name="Royal Ambergris",
        slug="royal-ambergris",
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()

    # Variant with discount: regular $150, discount $120, stock 10
    v1 = ProductVariant(
        product_id=product.id,
        sku="AMB-100ML",
        size_or_volume="100ml",
        price=Decimal("150.00"),
        discount_price=Decimal("120.00"),
        stock=10,
        is_active=True,
    )
    # Variant without discount: regular $80, stock 5
    v2 = ProductVariant(
        product_id=product.id,
        sku="AMB-50ML",
        size_or_volume="50ml",
        price=Decimal("80.00"),
        discount_price=None,
        stock=5,
        is_active=True,
    )
    db_session.add_all([v1, v2])
    await db_session.commit()

    admin_token = create_access_token(subject=admin.id, role=admin.role.value)
    customer_token = create_access_token(subject=customer.id, role=customer.role.value)

    return {
        "admin_token": admin_token,
        "customer_token": customer_token,
        "admin_id": admin.id,
        "customer_id": customer.id,
        "variant1_id": v1.id,
        "variant2_id": v2.id,
        "affiliate_code": "SUMMER26",
        "affiliate_id": affiliate.id,
    }


@pytest.mark.asyncio
async def test_server_calculated_pricing_and_snapshots(client: AsyncClient, setup_data: dict, db_session: AsyncSession):
    v1_id = setup_data["variant1_id"]

    # Client submits ONLY variant_id and quantity (no client-side price accepted)
    checkout_payload = {
        "shipping_name": "Hamdan Al-Maktoum",
        "shipping_phone": "+971501112233",
        "shipping_city": "Dubai",
        "shipping_address": "Downtown Dubai, Tower 1, Apt 1402",
        "customer_notes": "Please deliver in the evening.",
        "items": [
            {"variant_id": v1_id, "quantity": 2},
        ],
    }

    res = await client.post("/api/v1/orders", json=checkout_payload)
    assert res.status_code == 201, res.text
    order_data = res.json()

    # Effective price for v1 is 120.00 (discount_price). 2 * 120 = 240.00
    assert Decimal(order_data["total_amount"]) == Decimal("240.00")
    assert order_data["status"] == "pending"

    # Verify frozen snapshot fields in OrderItem
    assert len(order_data["items"]) == 1
    item = order_data["items"][0]
    assert item["variant_id"] == v1_id
    assert Decimal(item["unit_price"]) == Decimal("120.00")
    assert item["quantity"] == 2
    assert Decimal(item["subtotal"]) == Decimal("240.00")
    assert item["product_name"] == "Royal Ambergris"
    assert item["variant_sku"] == "AMB-100ML"
    assert item["size_or_volume"] == "100ml"

    # Verify inventory was deducted: initial 10 - 2 = 8
    var_query = select(ProductVariant).where(ProductVariant.id == v1_id)
    variant = (await db_session.execute(var_query)).scalars().first()
    assert variant.stock == 8


@pytest.mark.asyncio
async def test_duplicate_variant_aggregation(client: AsyncClient, setup_data: dict, db_session: AsyncSession):
    v1_id = setup_data["variant1_id"]

    # Client accidentally or intentionally submits same variant multiple times
    checkout_payload = {
        "shipping_name": "Test Aggregation",
        "shipping_phone": "+971509998877",
        "shipping_city": "Abu Dhabi",
        "shipping_address": "Corniche Road",
        "items": [
            {"variant_id": v1_id, "quantity": 1},
            {"variant_id": v1_id, "quantity": 3},
        ],
    }

    res = await client.post("/api/v1/orders", json=checkout_payload)
    assert res.status_code == 201, res.text
    order_data = res.json()

    # Aggregated quantity must be 1 + 3 = 4
    assert len(order_data["items"]) == 1
    assert order_data["items"][0]["quantity"] == 4
    assert Decimal(order_data["total_amount"]) == Decimal("480.00")  # 4 * 120

    # Stock deducted: 10 - 4 = 6
    var_query = select(ProductVariant).where(ProductVariant.id == v1_id)
    variant = (await db_session.execute(var_query)).scalars().first()
    assert variant.stock == 6


@pytest.mark.asyncio
async def test_insufficient_stock_rejection(client: AsyncClient, setup_data: dict, db_session: AsyncSession):
    v2_id = setup_data["variant2_id"]  # Stock is only 5

    checkout_payload = {
        "shipping_name": "Excess Shopper",
        "shipping_phone": "+971500000000",
        "shipping_city": "Sharjah",
        "shipping_address": "Al Majaz",
        "items": [
            {"variant_id": v2_id, "quantity": 10},  # 10 > 5 available!
        ],
    }

    res = await client.post("/api/v1/orders", json=checkout_payload)
    assert res.status_code == 400
    assert "insufficient stock" in res.json()["error"]["message"].lower()

    # Stock must remain unchanged at 5
    var_query = select(ProductVariant).where(ProductVariant.id == v2_id)
    variant = (await db_session.execute(var_query)).scalars().first()
    assert variant.stock == 5


@pytest.mark.asyncio
async def test_affiliate_attribution(client: AsyncClient, setup_data: dict, db_session: AsyncSession):
    v1_id = setup_data["variant1_id"]
    affiliate_code = setup_data["affiliate_code"]
    affiliate_id = setup_data["affiliate_id"]
    admin_token = setup_data["admin_token"]

    # Checkout with affiliate code
    checkout_payload = {
        "shipping_name": "Affiliate Referred Customer",
        "shipping_phone": "+971507776655",
        "shipping_city": "Dubai",
        "shipping_address": "Marina",
        "affiliate_code": affiliate_code.lower(),  # test case-insensitivity
        "items": [
            {"variant_id": v1_id, "quantity": 1},
        ],
    }

    res = await client.post("/api/v1/orders", json=checkout_payload)
    assert res.status_code == 201
    order_data = res.json()
    assert order_data["affiliate_id"] == affiliate_id

    # Check admin affiliate stats endpoint
    client.cookies.set("access_token", admin_token)
    aff_res = await client.get("/api/v1/admin/affiliates")
    assert aff_res.status_code == 200
    affs = aff_res.json()
    our_aff = next(a for a in affs if a["id"] == affiliate_id)
    assert our_aff["total_referred_orders"] == 1
    assert Decimal(our_aff["total_referred_amount"]) == Decimal("120.00")


@pytest.mark.asyncio
async def test_idempotent_stock_restoration_on_cancel(
    client: AsyncClient,
    setup_data: dict,
    db_session: AsyncSession,
):
    admin_token = setup_data["admin_token"]
    v1_id = setup_data["variant1_id"]  # initial stock 10

    # 1. Create order for 3 items
    checkout_payload = {
        "shipping_name": "Cancel Customer",
        "shipping_phone": "+971501234321",
        "shipping_city": "Ajman",
        "shipping_address": "Al Nuaimia",
        "items": [{"variant_id": v1_id, "quantity": 3}],
    }
    order_res = await client.post("/api/v1/orders", json=checkout_payload)
    assert order_res.status_code == 201
    order_id = order_res.json()["id"]

    # Stock should be 10 - 3 = 7
    var_q = select(ProductVariant).where(ProductVariant.id == v1_id)
    v_after_order = (await db_session.execute(var_q)).scalars().first()
    assert v_after_order.stock == 7

    # 2. Admin cancels order -> stock restored to 10
    client.cookies.set("access_token", admin_token)
    cancel_res = await client.patch(
        f"/api/v1/admin/orders/{order_id}/status",
        json={"status": "cancelled"},
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "cancelled"

    await db_session.refresh(v_after_order)
    assert v_after_order.stock == 10

    # 3. Idempotency check: cancelling AGAIN must NOT restore stock twice!
    cancel_res2 = await client.patch(
        f"/api/v1/admin/orders/{order_id}/status",
        json={"status": "cancelled"},
    )
    assert cancel_res2.status_code == 200

    await db_session.refresh(v_after_order)
    assert v_after_order.stock == 10  # Still 10, not 13!


@pytest.mark.asyncio
async def test_order_access_and_guest_phone_verification(client: AsyncClient, setup_data: dict):
    customer_token = setup_data["customer_token"]
    v1_id = setup_data["variant1_id"]

    # 1. Customer creates an authenticated order
    client.cookies.set("access_token", customer_token)
    cust_order_res = await client.post(
        "/api/v1/orders",
        json={
            "shipping_name": "Customer User",
            "shipping_phone": "+971501111111",
            "shipping_city": "Dubai",
            "shipping_address": "JBR",
            "items": [{"variant_id": v1_id, "quantity": 1}],
        },
    )
    assert cust_order_res.status_code == 201
    cust_order_id = cust_order_res.json()["id"]

    # Customer sees it in /my-orders
    my_orders_res = await client.get("/api/v1/orders/my-orders")
    assert my_orders_res.status_code == 200
    assert any(o["id"] == cust_order_id for o in my_orders_res.json())

    # 2. Guest creates order
    client.cookies.clear()
    guest_order_res = await client.post(
        "/api/v1/orders",
        json={
            "shipping_name": "Guest User",
            "shipping_phone": "+971509876543",
            "shipping_city": "Dubai",
            "shipping_address": "Al Barsha",
            "items": [{"variant_id": v1_id, "quantity": 1}],
        },
    )
    assert guest_order_res.status_code == 201
    guest_order_id = guest_order_res.json()["id"]

    # Guest lookup WITHOUT phone -> 403 Forbidden
    no_phone_res = await client.get(f"/api/v1/orders/{guest_order_id}")
    assert no_phone_res.status_code == 403

    # Guest lookup with WRONG phone -> 403 Forbidden
    wrong_phone_res = await client.get(f"/api/v1/orders/{guest_order_id}?phone=+971500000000")
    assert wrong_phone_res.status_code == 403

    # Guest lookup with MATCHING phone -> 200 OK
    good_phone_res = await client.get(f"/api/v1/orders/{guest_order_id}?phone=+971509876543")
    assert good_phone_res.status_code == 200
    assert good_phone_res.json()["shipping_name"] == "Guest User"


@pytest.mark.asyncio
async def test_customer_forbidden_on_admin_orders(client: AsyncClient, setup_data: dict):
    customer_token = setup_data["customer_token"]
    client.cookies.set("access_token", customer_token)

    # Customer accessing /admin/orders -> 403
    res1 = await client.get("/api/v1/admin/orders")
    assert res1.status_code == 403

    # Customer accessing /admin/affiliates -> 403
    res2 = await client.get("/api/v1/admin/affiliates")
    assert res2.status_code == 403
