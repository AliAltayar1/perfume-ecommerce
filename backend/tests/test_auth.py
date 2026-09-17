import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import select

from app.main import app
from app.db.base import Base
from app.db.session import get_db
from app.models.user import User, UserRole, RefreshToken
from app.core.security import hash_refresh_token, get_password_hash, create_access_token

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
async def test_register_flow(client: AsyncClient, db_session: AsyncSession):
    register_payload = {
        "email": "customer@example.com",
        "password": "SecurePassword123!",
        "full_name": "Perfume Enthusiast",
        "phone": "+1234567890",
    }
    response = await client.post("/api/v1/auth/register", json=register_payload)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["email"] == "customer@example.com"
    assert data["role"] == "customer"
    assert "password" not in data

    # Verify HttpOnly cookies
    cookies = response.cookies
    assert "access_token" in cookies
    assert "refresh_token" in cookies

    # Check Set-Cookie headers for security attributes
    set_cookie_headers = response.headers.get_list("set-cookie")
    access_cookie_header = next(h for h in set_cookie_headers if "access_token=" in h)
    refresh_cookie_header = next(h for h in set_cookie_headers if "refresh_token=" in h)

    assert "HttpOnly" in access_cookie_header
    assert "HttpOnly" in refresh_cookie_header
    assert "Path=/api/v1/auth" in refresh_cookie_header

    # Verify refresh token in database
    raw_refresh = cookies.get("refresh_token")
    token_hash = hash_refresh_token(raw_refresh)
    query = select(RefreshToken).where(RefreshToken.token == token_hash)
    db_token = (await db_session.execute(query)).scalars().first()
    assert db_token is not None
    assert db_token.is_revoked is False
    assert db_token.user_id == data["id"]


@pytest.mark.asyncio
async def test_login_flow(client: AsyncClient, db_session: AsyncSession):
    # Create user
    user = User(
        email="shopper@example.com",
        hashed_password=get_password_hash("ValidPass99!"),
        full_name="Fragrance Buyer",
        phone="+971509998877",
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    # Attempt login with invalid password
    bad_res = await client.post(
        "/api/v1/auth/login",
        json={"email": "shopper@example.com", "password": "WrongPassword!"},
    )
    assert bad_res.status_code == 401

    # Attempt login with valid password
    good_res = await client.post(
        "/api/v1/auth/login",
        json={"email": "shopper@example.com", "password": "ValidPass99!"},
    )
    assert good_res.status_code == 200
    user_data = good_res.json()
    assert user_data["email"] == "shopper@example.com"
    assert "access_token" in good_res.cookies
    assert "refresh_token" in good_res.cookies


@pytest.mark.asyncio
async def test_get_me_with_cookie_and_header(client: AsyncClient, db_session: AsyncSession):
    # Create user
    user = User(
        email="me@example.com",
        hashed_password=get_password_hash("Password123!"),
        full_name="Myself",
        phone="+971508887766",
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    # 1. Access without credentials -> 401
    unauth_res = await client.get("/api/v1/auth/me")
    assert unauth_res.status_code == 401

    # 2. Access with cookie
    access_token = create_access_token(user.id, user.role.value)
    client.cookies.set("access_token", access_token)
    cookie_res = await client.get("/api/v1/auth/me")
    assert cookie_res.status_code == 200
    assert cookie_res.json()["email"] == "me@example.com"

    # 3. Access with Authorization header fallback
    client.cookies.delete("access_token")
    header_res = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert header_res.status_code == 200
    assert header_res.json()["email"] == "me@example.com"


@pytest.mark.asyncio
async def test_refresh_token_rotation_and_revocation(client: AsyncClient, db_session: AsyncSession):
    # Register to get initial cookies
    reg_res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "rotator@example.com",
            "password": "Password123!",
            "full_name": "Rotation User",
            "phone": "+971507776655",
        },
    )
    assert reg_res.status_code == 201
    old_raw_refresh = reg_res.cookies.get("refresh_token")
    old_token_hash = hash_refresh_token(old_raw_refresh)

    # Perform refresh
    client.cookies.set("refresh_token", old_raw_refresh)
    refresh_res = await client.post("/api/v1/auth/refresh")
    assert refresh_res.status_code == 200
    assert refresh_res.json()["email"] == "rotator@example.com"

    new_raw_refresh = refresh_res.cookies.get("refresh_token")
    assert new_raw_refresh != old_raw_refresh
    new_token_hash = hash_refresh_token(new_raw_refresh)

    # Verify old token is marked revoked in DB
    query_old = select(RefreshToken).where(RefreshToken.token == old_token_hash)
    old_db_token = (await db_session.execute(query_old)).scalars().first()
    assert old_db_token.is_revoked is True

    # Verify new token is stored and active in DB
    query_new = select(RefreshToken).where(RefreshToken.token == new_token_hash)
    new_db_token = (await db_session.execute(query_new)).scalars().first()
    assert new_db_token.is_revoked is False

    # Attempt to REUSE old revoked token -> must fail with 401
    client.cookies.set("refresh_token", old_raw_refresh)
    reuse_res = await client.post("/api/v1/auth/refresh")
    assert reuse_res.status_code == 401
    assert "revoked" in reuse_res.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_logout_clears_cookies_and_revokes_token(client: AsyncClient, db_session: AsyncSession):
    # Register user
    reg_res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "logout@example.com",
            "password": "Password123!",
            "full_name": "Logout User",
            "phone": "+971506665544",
        },
    )
    raw_refresh = reg_res.cookies.get("refresh_token")
    token_hash = hash_refresh_token(raw_refresh)

    # Logout
    client.cookies.set("refresh_token", raw_refresh)
    logout_res = await client.post("/api/v1/auth/logout")
    assert logout_res.status_code == 200
    assert logout_res.json()["message"] == "Logged out successfully"

    # Verify token is revoked in DB
    query = select(RefreshToken).where(RefreshToken.token == token_hash)
    db_token = (await db_session.execute(query)).scalars().first()
    assert db_token.is_revoked is True

    # Verify cookies are cleared with exact paths
    set_cookie_headers = logout_res.headers.get_list("set-cookie")
    refresh_cookie_header = next(h for h in set_cookie_headers if "refresh_token=" in h)
    assert "Path=/api/v1/auth" in refresh_cookie_header
    assert 'max-age=0' in refresh_cookie_header.lower() or 'expires=' in refresh_cookie_header.lower()


@pytest.mark.asyncio
async def test_role_based_access_control(client: AsyncClient, db_session: AsyncSession):
    # Create customer and admin
    customer = User(
        email="cust@example.com",
        hashed_password=get_password_hash("Pass123!"),
        full_name="Regular Customer",
        phone="+971505554433",
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    admin = User(
        email="admin@example.com",
        hashed_password=get_password_hash("AdminPass123!"),
        full_name="Site Administrator",
        phone="+971504443322",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add_all([customer, admin])
    await db_session.commit()

    # Customer tries to access /api/v1/admin/orders -> 403 Forbidden
    cust_token = create_access_token(customer.id, customer.role.value)
    client.cookies.set("access_token", cust_token)
    forbidden_res = await client.get("/api/v1/admin/orders")
    assert forbidden_res.status_code == 403
    assert "Administrator access required" in forbidden_res.json()["error"]["message"]

    # Admin accesses /api/v1/admin/orders -> 200 OK
    admin_token = create_access_token(admin.id, admin.role.value)
    client.cookies.set("access_token", admin_token)
    admin_res = await client.get("/api/v1/admin/orders")
    assert admin_res.status_code == 200
    assert isinstance(admin_res.json(), list)
