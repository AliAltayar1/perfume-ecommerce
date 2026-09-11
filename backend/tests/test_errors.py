import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app
from app.db.base import Base
from app.db.session import get_db

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
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_validation_error_format(client):
    """
    Verify that 422 RequestValidationError adheres to:
    {
      "success": false,
      "error": {
        "code": "VALIDATION_ERROR",
        "message": "Validation error",
        "details": [{"field": ..., "issue": ..., "type": ...}]
      }
    }
    """
    response = await client.post("/api/v1/auth/login", json={})
    assert response.status_code == 422
    data = response.json()

    assert data["success"] is False
    assert "error" in data
    error = data["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["message"] == "Validation error"
    assert isinstance(error["details"], list)
    assert len(error["details"]) >= 2

    fields = [d["field"] for d in error["details"]]
    assert "email" in fields
    assert "password" in fields
    for d in error["details"]:
        assert "field" in d
        assert "issue" in d
        assert "type" in d


@pytest.mark.asyncio
async def test_not_found_error_format(client):
    """
    Verify that 404 HTTPException adheres to:
    {
      "success": false,
      "error": {
        "code": "NOT_FOUND",
        "message": "<detail>",
        "details": []
      }
    }
    """
    response = await client.get("/api/v1/products/non-existent-product-slug-xyz")
    assert response.status_code == 404
    data = response.json()

    assert data["success"] is False
    assert "error" in data
    error = data["error"]
    assert error["code"] == "NOT_FOUND"
    assert "Product not found" in error["message"]
    assert error["details"] == []


@pytest.mark.asyncio
async def test_unauthorized_error_format(client):
    """
    Verify that 401 HTTPException adheres to:
    {
      "success": false,
      "error": {
        "code": "UNAUTHORIZED",
        "message": "<detail>",
        "details": []
      }
    }
    """
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    data = response.json()

    assert data["success"] is False
    assert "error" in data
    error = data["error"]
    assert error["code"] == "UNAUTHORIZED"
    assert error["details"] == []
    assert len(error["message"]) > 0


@pytest.mark.asyncio
async def test_create_error_response_contract():
    """
    Directly test create_error_response helper output structure.
    """
    from app.core.errors import create_error_response
    import json

    res = create_error_response(
        status_code=409,
        code="DATABASE_CONFLICT",
        message="Duplicate key error",
        details=[],
    )
    assert res.status_code == 409
    body = json.loads(res.body)
    assert body == {
        "success": False,
        "error": {
            "code": "DATABASE_CONFLICT",
            "message": "Duplicate key error",
            "details": [],
        },
    }

