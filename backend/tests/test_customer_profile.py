import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, get_password_hash
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.order import Order, OrderStatus
from app.models.user import User, UserRole
from decimal import Decimal

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


@pytest.mark.asyncio
async def test_phone_is_required_on_registration(client: AsyncClient):
    """
    Verify registration fails with 422 if phone number is omitted.
    """
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "nophone@example.com",
            "password": "Password123!",
            "full_name": "No Phone User",
        },
    )
    assert res.status_code == 422
    data = res.json()
    assert data["success"] is False
    assert any(d["field"] == "phone" for d in data["error"]["details"])


@pytest.mark.asyncio
async def test_customer_edit_profile_auth_me(client: AsyncClient, db_session: AsyncSession):
    """
    Test customer editing full_name, phone, email, and password via PATCH/PUT /api/v1/auth/me.
    """
    user = User(
        email="original@example.com",
        hashed_password=get_password_hash("OldPassword123!"),
        full_name="Original Name",
        phone="+971500000001",
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = create_access_token(user.id, user.role.value)
    client.cookies.set("access_token", token)

    # 1. Edit name and phone
    patch_res = await client.patch(
        "/api/v1/auth/me",
        json={"full_name": "Updated Name", "phone": "+971509999999"},
    )
    assert patch_res.status_code == 200, patch_res.text
    patched = patch_res.json()
    assert patched["full_name"] == "Updated Name"
    assert patched["phone"] == "+971509999999"
    assert patched["email"] == "original@example.com"

    # 2. Edit email and password via PUT
    put_res = await client.put(
        "/api/v1/auth/me",
        json={"email": "newemail@example.com", "password": "NewSecretPassword123!"},
    )
    assert put_res.status_code == 200, put_res.text
    assert put_res.json()["email"] == "newemail@example.com"

    # 3. Verify login works with new credentials
    client.cookies.delete("access_token")
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": "newemail@example.com", "password": "NewSecretPassword123!"},
    )
    assert login_res.status_code == 200


@pytest.mark.asyncio
async def test_customer_edit_profile_users_me(client: AsyncClient, db_session: AsyncSession):
    """
    Test customer editing profile via /api/v1/users/me endpoint.
    """
    user = User(
        email="usersme@example.com",
        hashed_password=get_password_hash("Pass123!"),
        full_name="Users Me Customer",
        phone="+971501112233",
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = create_access_token(user.id, user.role.value)
    client.cookies.set("access_token", token)

    # GET /users/me
    get_res = await client.get("/api/v1/users/me")
    assert get_res.status_code == 200
    assert get_res.json()["email"] == "usersme@example.com"

    # PATCH /users/me
    patch_res = await client.patch(
        "/api/v1/users/me",
        json={"full_name": "Renamed Users Me", "phone": "+971504445566"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["full_name"] == "Renamed Users Me"
    assert patch_res.json()["phone"] == "+971504445566"


@pytest.mark.asyncio
async def test_customer_edit_email_conflict(client: AsyncClient, db_session: AsyncSession):
    """
    Verify customer cannot change email to one already registered.
    """
    user1 = User(
        email="user1@example.com",
        hashed_password=get_password_hash("Pass123!"),
        full_name="User One",
        phone="+971501111111",
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    user2 = User(
        email="user2@example.com",
        hashed_password=get_password_hash("Pass123!"),
        full_name="User Two",
        phone="+971502222222",
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db_session.add_all([user1, user2])
    await db_session.commit()

    token1 = create_access_token(user1.id, user1.role.value)
    client.cookies.set("access_token", token1)

    # Attempt to take user2's email
    res = await client.patch(
        "/api/v1/auth/me",
        json={"email": "user2@example.com"},
    )
    assert res.status_code == 400
    assert "already exists" in res.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_customer_delete_account_clears_cookies_and_preserves_orders(
    client: AsyncClient, db_session: AsyncSession
):
    """
    Verify DELETE /api/v1/auth/me deletes the user account, clears cookies,
    and preserves historical orders by setting order.user_id = NULL.
    """
    user = User(
        email="delete_me@example.com",
        hashed_password=get_password_hash("Pass123!"),
        full_name="Delete Me User",
        phone="+971503333333",
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    # Create an order linked to this user
    order = Order(
        user_id=user.id,
        status=OrderStatus.PENDING,
        total_amount=Decimal("150.00"),
        shipping_name="Delete Me User",
        shipping_phone="+971503333333",
        shipping_city="Dubai",
        shipping_address="Downtown Dubai",
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(user)
    await db_session.refresh(order)

    token = create_access_token(user.id, user.role.value)
    client.cookies.set("access_token", token)

    # Delete customer account
    del_res = await client.delete("/api/v1/auth/me")
    assert del_res.status_code == 200
    assert del_res.json()["message"] == "User account deleted successfully"

    # Verify cookies cleared
    set_cookie_headers = del_res.headers.get_list("set-cookie")
    assert any("access_token=" in h for h in set_cookie_headers)

    # Verify user no longer exists in DB
    user_check = await db_session.execute(select(User).where(User.id == user.id))
    assert user_check.scalars().first() is None

    # Verify order is still preserved with user_id NULL
    order_check = await db_session.execute(select(Order).where(Order.id == order.id))
    persisted_order = order_check.scalars().first()
    assert persisted_order is not None
    assert persisted_order.user_id is None
