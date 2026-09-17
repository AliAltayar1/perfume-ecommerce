from decimal import Decimal
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, get_password_hash
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.product import Category, Product
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
async def tokens(db_session: AsyncSession):
    admin = User(
        email="offer_admin@example.com",
        hashed_password=get_password_hash("AdminPass123!"),
        full_name="Offer Admin",
        phone="+971501112244",
        role=UserRole.ADMIN,
        is_active=True,
    )
    customer = User(
        email="offer_cust@example.com",
        hashed_password=get_password_hash("CustPass123!"),
        full_name="Offer Customer",
        phone="+971502223355",
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db_session.add_all([admin, customer])
    await db_session.commit()
    await db_session.refresh(admin)
    await db_session.refresh(customer)

    return {
        "admin_token": create_access_token(admin.id, admin.role.value),
        "customer_token": create_access_token(customer.id, customer.role.value),
    }


@pytest.mark.asyncio
async def test_admin_offer_crud_lifecycle(client: AsyncClient, tokens: dict, db_session: AsyncSession):
    """
    Test full CRUD lifecycle of offers by admin: Create, Read, Update, Delete.
    """
    admin_token = tokens["admin_token"]
    client.cookies.set("access_token", admin_token)

    # 1. CREATE OFFER via POST /api/v1/offers
    create_payload = {
        "title": "Eid Al-Adha Luxury Sale",
        "description": "Up to 25% off selected oud fragrances",
        "discount_percentage": "25.00",
        "discount_amount": None,
        "code": "EID25",
        "banner_url": "https://cdn.example.com/eid-sale.jpg",
        "is_active": True,
    }
    create_res = await client.post("/api/v1/offers", json=create_payload)
    assert create_res.status_code == 201, create_res.text
    offer = create_res.json()
    assert offer["title"] == "Eid Al-Adha Luxury Sale"
    assert offer["code"] == "EID25"
    assert Decimal(offer["discount_percentage"]) == Decimal("25.00")
    offer_id = offer["id"]

    # 2. READ OFFER by ID via GET /api/v1/offers/{id}
    client.cookies.delete("access_token")  # public access
    get_res = await client.get(f"/api/v1/offers/{offer_id}")
    assert get_res.status_code == 200
    assert get_res.json()["title"] == "Eid Al-Adha Luxury Sale"

    # 3. LIST OFFERS via GET /api/v1/offers
    list_res = await client.get("/api/v1/offers?active_only=true")
    assert list_res.status_code == 200
    offers = list_res.json()
    assert len(offers) == 1
    assert offers[0]["id"] == offer_id

    # 4. UPDATE OFFER via PUT /api/v1/offers/{id}
    client.cookies.set("access_token", admin_token)
    update_payload = {
        "title": "Eid Grand Finale Sale",
        "discount_percentage": "30.00",
        "is_active": True,
    }
    update_res = await client.put(f"/api/v1/offers/{offer_id}", json=update_payload)
    assert update_res.status_code == 200
    updated = update_res.json()
    assert updated["title"] == "Eid Grand Finale Sale"
    assert Decimal(updated["discount_percentage"]) == Decimal("30.00")

    # 5. DELETE OFFER via DELETE /api/v1/offers/{id}
    del_res = await client.delete(f"/api/v1/offers/{offer_id}")
    assert del_res.status_code == 200
    assert del_res.json()["message"] == "Offer deleted successfully"

    # Verify deleted
    get_after_del = await client.get(f"/api/v1/offers/{offer_id}")
    assert get_after_del.status_code == 404


@pytest.mark.asyncio
async def test_admin_dashboard_offers_endpoints(client: AsyncClient, tokens: dict):
    """
    Test offer operations under /api/v1/admin/offers.
    """
    admin_token = tokens["admin_token"]
    client.cookies.set("access_token", admin_token)

    # 1. Create offer via /admin/offers
    payload = {
        "title": "Winter Amber Promo",
        "description": "Flat 50 AED off",
        "discount_amount": "50.00",
        "code": "AMBER50",
        "is_active": True,
    }
    res = await client.post("/api/v1/admin/offers", json=payload)
    assert res.status_code == 201
    offer_id = res.json()["id"]

    # 2. List offers via /admin/offers
    list_res = await client.get("/api/v1/admin/offers")
    assert list_res.status_code == 200
    assert any(o["id"] == offer_id for o in list_res.json())

    # 3. Patch offer via /admin/offers/{id}
    patch_res = await client.patch(
        f"/api/v1/admin/offers/{offer_id}",
        json={"discount_amount": "60.00"},
    )
    assert patch_res.status_code == 200
    assert Decimal(patch_res.json()["discount_amount"]) == Decimal("60.00")

    # 4. Delete offer via /admin/offers/{id}
    del_res = await client.delete(f"/api/v1/admin/offers/{offer_id}")
    assert del_res.status_code == 200


@pytest.mark.asyncio
async def test_offers_authorization(client: AsyncClient, tokens: dict):
    """
    Ensure unauthenticated users and customers cannot create, edit, or delete offers.
    """
    cust_token = tokens["customer_token"]

    offer_payload = {"title": "Unauthorized Offer", "is_active": True}

    # 1. Unauthenticated POST -> 401
    res1 = await client.post("/api/v1/offers", json=offer_payload)
    assert res1.status_code == 401

    # 2. Customer POST -> 403
    client.cookies.set("access_token", cust_token)
    res2 = await client.post("/api/v1/offers", json=offer_payload)
    assert res2.status_code == 403

    # 3. Customer PUT -> 403
    res3 = await client.put("/api/v1/offers/1", json={"title": "Hacked"})
    assert res3.status_code == 403

    # 4. Customer DELETE -> 403
    res4 = await client.delete("/api/v1/offers/1")
    assert res4.status_code == 403


@pytest.mark.asyncio
async def test_offer_validations(client: AsyncClient, tokens: dict, db_session: AsyncSession):
    """
    Test duplicate code rejection and non-existent product reference rejection.
    """
    admin_token = tokens["admin_token"]
    client.cookies.set("access_token", admin_token)

    # 1. Create first offer with code VIP10
    await client.post(
        "/api/v1/offers",
        json={"title": "VIP Club", "code": "VIP10", "is_active": True},
    )

    # 2. Attempt duplicate code -> 400
    dup_res = await client.post(
        "/api/v1/offers",
        json={"title": "Another VIP", "code": "VIP10", "is_active": True},
    )
    assert dup_res.status_code == 400
    assert "already exists" in dup_res.json()["error"]["message"].lower()

    # 3. Attempt referencing non-existent product_id -> 400
    bad_prod_res = await client.post(
        "/api/v1/offers",
        json={"title": "Ghost Offer", "product_id": 99999, "is_active": True},
    )
    assert bad_prod_res.status_code == 400
    assert "product" in bad_prod_res.json()["error"]["message"].lower()
