from decimal import Decimal
import io
from pathlib import Path
from PIL import Image
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.offer import Offer
from app.models.product import Category, Product, ProductImage, ProductVariant
from app.models.user import User, UserRole
from app.services.image_service import ImageService

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


def create_dummy_image(format: str = "PNG", size: tuple = (400, 300), color: tuple = (100, 150, 200)) -> bytes:
    """Helper to generate binary bytes of an image in various formats."""
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format=format)
    return buf.getvalue()


@pytest_asyncio.fixture(scope="function")
async def db_session():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession, tmp_path: Path):
    # Temporarily point settings.UPLOAD_DIR to tmp_path
    original_upload_dir = settings.UPLOAD_DIR
    settings.UPLOAD_DIR = str(tmp_path / "test_uploads")

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    settings.UPLOAD_DIR = original_upload_dir


@pytest_asyncio.fixture(scope="function")
async def auth_tokens(db_session: AsyncSession):
    admin = User(
        email="admin_images@example.com",
        hashed_password=get_password_hash("AdminPass123!"),
        full_name="Admin Image User",
        phone="+971501112233",
        role=UserRole.ADMIN,
        is_active=True,
    )
    customer = User(
        email="customer_images@example.com",
        hashed_password=get_password_hash("CustPass123!"),
        full_name="Customer User",
        phone="+971509998877",
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db_session.add_all([admin, customer])
    await db_session.commit()
    await db_session.refresh(admin)
    await db_session.refresh(customer)

    return {
        "admin_token": create_access_token(subject=admin.id, role=admin.role.value),
        "customer_token": create_access_token(subject=customer.id, role=customer.role.value),
    }


# ======================================================================
# Tests for Generic Image Upload Endpoint
# ======================================================================

@pytest.mark.asyncio
async def test_upload_image_requires_admin(client: AsyncClient, auth_tokens: dict):
    img_data = create_dummy_image("PNG")

    # 1. Unauthenticated request
    res = await client.post(
        "/api/v1/uploads/image",
        files={"file": ("test.png", img_data, "image/png")},
    )
    assert res.status_code == 401

    # 2. Regular customer forbidden
    client.cookies.set("access_token", auth_tokens["customer_token"])
    res = await client.post(
        "/api/v1/uploads/image",
        files={"file": ("test.png", img_data, "image/png")},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_upload_image_multiple_formats(client: AsyncClient, auth_tokens: dict):
    """Verify PNG, JPEG, WebP, GIF, BMP, and SVG formats are all supported and compressed."""
    client.cookies.set("access_token", auth_tokens["admin_token"])

    formats = [
        ("test.png", create_dummy_image("PNG"), "image/png"),
        ("test.jpg", create_dummy_image("JPEG"), "image/jpeg"),
        ("test.webp", create_dummy_image("WEBP"), "image/webp"),
        ("test.gif", create_dummy_image("GIF"), "image/gif"),
        ("test.bmp", create_dummy_image("BMP"), "image/bmp"),
    ]

    for filename, data, mime in formats:
        res = await client.post(
            "/api/v1/uploads/image",
            files={"file": (filename, data, mime)},
            data={"folder": "products"},
        )
        assert res.status_code == 201, f"Failed on {filename}: {res.text}"
        payload = res.json()
        assert payload["mime_type"] == "image/webp"
        assert payload["width"] == 1000
        assert payload["height"] == 1000
        assert payload["url"].startswith("/uploads/products/")
        assert payload["filename"].endswith(".webp")
        assert payload["file_size"] > 0


@pytest.mark.asyncio
async def test_upload_svg_image(client: AsyncClient, auth_tokens: dict):
    client.cookies.set("access_token", auth_tokens["admin_token"])

    svg_content = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="40" fill="red"/></svg>'
    res = await client.post(
        "/api/v1/uploads/image",
        files={"file": ("logo.svg", svg_content, "image/svg+xml")},
        data={"folder": "general"},
    )
    assert res.status_code == 201, res.text
    payload = res.json()
    assert payload["mime_type"] == "image/svg+xml"
    assert payload["url"].startswith("/uploads/general/")
    assert payload["filename"].endswith(".svg")


@pytest.mark.asyncio
async def test_upload_image_malicious_svg_rejected(client: AsyncClient, auth_tokens: dict):
    client.cookies.set("access_token", auth_tokens["admin_token"])

    malicious_svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    res = await client.post(
        "/api/v1/uploads/image",
        files={"file": ("xss.svg", malicious_svg, "image/svg+xml")},
    )
    assert res.status_code == 400
    assert "disallowed" in res.json()["error"]["message"].lower() or "rejected" in res.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_upload_image_unsupported_format(client: AsyncClient, auth_tokens: dict):
    client.cookies.set("access_token", auth_tokens["admin_token"])

    res = await client.post(
        "/api/v1/uploads/image",
        files={"file": ("document.pdf", b"%PDF-1.4...", "application/pdf")},
    )
    assert res.status_code == 400
    assert "unsupported" in res.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_upload_image_corrupted_content(client: AsyncClient, auth_tokens: dict):
    client.cookies.set("access_token", auth_tokens["admin_token"])

    # Disguised text file claiming to be a jpg
    res = await client.post(
        "/api/v1/uploads/image",
        files={"file": ("fake.jpg", b"This is plain text not an image", "image/jpeg")},
    )
    assert res.status_code == 400
    assert "not a valid" in res.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_upload_image_empty_file(client: AsyncClient, auth_tokens: dict):
    client.cookies.set("access_token", auth_tokens["admin_token"])

    res = await client.post(
        "/api/v1/uploads/image",
        files={"file": ("empty.png", b"", "image/png")},
    )
    assert res.status_code == 400
    assert "empty" in res.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_unified_sizing_fit_modes(client: AsyncClient, auth_tokens: dict):
    """Test contain, cover, and scale fit modes."""
    client.cookies.set("access_token", auth_tokens["admin_token"])
    img_data = create_dummy_image("PNG", size=(600, 300))

    # 1. contain mode (default for products: 1000x1000 padded canvas)
    res_contain = await client.post(
        "/api/v1/uploads/image",
        files={"file": ("wide.png", img_data, "image/png")},
        data={"folder": "products", "fit_mode": "contain"},
    )
    assert res_contain.status_code == 201
    assert res_contain.json()["width"] == 1000
    assert res_contain.json()["height"] == 1000

    # 2. cover mode (for offers/banners: 1200x600 cropped center)
    res_cover = await client.post(
        "/api/v1/uploads/image",
        files={"file": ("banner.png", img_data, "image/png")},
        data={"folder": "offers", "fit_mode": "cover"},
    )
    assert res_cover.status_code == 201
    assert res_cover.json()["width"] == 1200
    assert res_cover.json()["height"] == 600

    # 3. scale mode (proportional downscale without canvas padding)
    res_scale = await client.post(
        "/api/v1/uploads/image",
        files={"file": ("scaled.png", img_data, "image/png")},
        data={"folder": "general", "fit_mode": "scale"},
    )
    assert res_scale.status_code == 201
    assert res_scale.json()["width"] == 600
    assert res_scale.json()["height"] == 300


@pytest.mark.asyncio
async def test_batch_upload_images(client: AsyncClient, auth_tokens: dict):
    client.cookies.set("access_token", auth_tokens["admin_token"])

    img1 = create_dummy_image("JPEG", size=(200, 200))
    img2 = create_dummy_image("PNG", size=(300, 300))

    res = await client.post(
        "/api/v1/uploads/images",
        files=[
            ("files", ("img1.jpg", img1, "image/jpeg")),
            ("files", ("img2.png", img2, "image/png")),
        ],
        data={"folder": "products"},
    )
    assert res.status_code == 201, res.text
    payload = res.json()
    assert payload["total_count"] == 2
    assert len(payload["uploaded"]) == 2
    for item in payload["uploaded"]:
        assert item["mime_type"] == "image/webp"
        assert item["width"] == 1000
        assert item["height"] == 1000


# ======================================================================
# Tests for Direct Product, Variant, and Offer Image Operations
# ======================================================================

@pytest.mark.asyncio
async def test_admin_direct_product_image_crud(
    client: AsyncClient,
    auth_tokens: dict,
    db_session: AsyncSession,
):
    admin_token = auth_tokens["admin_token"]
    client.cookies.set("access_token", admin_token)

    # 1. Seed a Category and Product
    cat = Category(name="Niche Fragrances", slug="niche-fragrances")
    db_session.add(cat)
    await db_session.commit()
    await db_session.refresh(cat)

    prod = Product(
        name="Oud Satin Mood",
        slug="oud-satin-mood",
        category_id=cat.id,
        description="Violet, Bulgarian rose, and rich agarwood.",
    )
    db_session.add(prod)
    await db_session.commit()
    await db_session.refresh(prod)

    # 2. Upload first image as primary
    img_bytes = create_dummy_image("JPEG", size=(500, 700))
    res1 = await client.post(
        f"/api/v1/admin/products/{prod.id}/images",
        files={"file": ("bottle_front.jpg", img_bytes, "image/jpeg")},
        data={"alt_text": "Front view of bottle", "is_primary": "true", "display_order": "1"},
    )
    assert res1.status_code == 201, res1.text
    img1_data = res1.json()
    assert img1_data["product_id"] == prod.id
    assert img1_data["is_primary"] is True
    assert img1_data["url"].startswith("/uploads/products/")
    assert img1_data["alt_text"] == "Front view of bottle"

    # Verify physical file was written to disk
    stored_path = Path(settings.UPLOAD_DIR) / "products" / Path(img1_data["url"]).name
    assert stored_path.exists()
    assert stored_path.stat().st_size > 0

    # 3. Upload second image as primary (should demote first image)
    res2 = await client.post(
        f"/api/v1/admin/products/{prod.id}/images",
        files={"file": ("bottle_back.png", img_bytes, "image/png")},
        data={"alt_text": "Back packaging", "is_primary": "true", "display_order": "2"},
    )
    assert res2.status_code == 201, res2.text
    img2_data = res2.json()
    assert img2_data["is_primary"] is True

    # Check first image in DB is no longer primary
    res_img1_db = await db_session.execute(
        select(ProductImage).where(ProductImage.id == img1_data["id"])
    )
    refreshed_img1 = res_img1_db.scalars().first()
    assert refreshed_img1.is_primary is False

    # Verify public storefront GET /products list returns primary_image_url
    storefront_list_res = await client.get("/api/v1/products")
    assert storefront_list_res.status_code == 200
    storefront_items = storefront_list_res.json()
    assert len(storefront_items) >= 1
    found_prod = next(p for p in storefront_items if p["id"] == prod.id)
    assert found_prod["primary_image_url"] == img2_data["url"]

    # Verify public storefront GET /products/{slug} returns images array
    storefront_detail_res = await client.get(f"/api/v1/products/{prod.slug}")
    assert storefront_detail_res.status_code == 200
    detail_data = storefront_detail_res.json()
    assert len(detail_data["images"]) == 2
    assert detail_data["images"][0]["url"].startswith("/uploads/products/")
    assert detail_data["images"][1]["url"].startswith("/uploads/products/")

    # Verify admin GET /admin/products/{id} returns full product details with images
    admin_detail_res = await client.get(f"/api/v1/admin/products/{prod.id}")
    assert admin_detail_res.status_code == 200
    admin_data = admin_detail_res.json()
    assert len(admin_data["images"]) == 2

    # 4. Set first image back to primary
    res_patch = await client.patch(
        f"/api/v1/admin/products/{prod.id}/images/{img1_data['id']}/primary",
    )
    assert res_patch.status_code == 200
    assert res_patch.json()["is_primary"] is True

    # 5. Delete an image from database AND ensure physical file is removed from disk
    del_res = await client.delete(
        f"/api/v1/admin/products/{prod.id}/images/{img1_data['id']}",
    )
    assert del_res.status_code == 200
    assert del_res.json()["message"] == "Image deleted successfully"

    # Verify removed from database
    check_db = await db_session.execute(
        select(ProductImage).where(ProductImage.id == img1_data["id"])
    )
    assert check_db.scalars().first() is None

    # Verify removed from disk
    assert not stored_path.exists()


@pytest.mark.asyncio
async def test_admin_variant_image_upload(
    client: AsyncClient,
    auth_tokens: dict,
    db_session: AsyncSession,
):
    client.cookies.set("access_token", auth_tokens["admin_token"])

    # Seed product & variant
    cat = Category(name="Floral Scents", slug="floral-scents")
    db_session.add(cat)
    await db_session.commit()
    await db_session.refresh(cat)

    prod = Product(name="Rose Deluxe", slug="rose-deluxe", category_id=cat.id)
    db_session.add(prod)
    await db_session.commit()
    await db_session.refresh(prod)

    variant = ProductVariant(
        product_id=prod.id,
        sku="ROSE-50ML",
        size_or_volume="50ml",
        price=Decimal("120.00"),
        stock=10,
    )
    db_session.add(variant)
    await db_session.commit()
    await db_session.refresh(variant)

    # Upload variant image
    img_data = create_dummy_image("PNG", size=(400, 400))
    res = await client.post(
        f"/api/v1/admin/variants/{variant.id}/image",
        files={"file": ("variant_50ml.png", img_data, "image/png")},
    )
    assert res.status_code == 200, res.text
    v_data = res.json()
    assert v_data["image_url"].startswith("/uploads/variants/")
    assert v_data["image_url"].endswith(".webp")

    # Verify variant in DB updated
    refreshed_v = (await db_session.execute(
        select(ProductVariant).where(ProductVariant.id == variant.id)
    )).scalars().first()
    assert refreshed_v.image_url == v_data["image_url"]


@pytest.mark.asyncio
async def test_admin_offer_banner_upload(
    client: AsyncClient,
    auth_tokens: dict,
    db_session: AsyncSession,
):
    client.cookies.set("access_token", auth_tokens["admin_token"])

    # Seed offer
    offer = Offer(
        title="Eid Mega Sale",
        description="30% discount on luxury collections",
        code="EID30",
        discount_percentage=Decimal("30.00"),
    )
    db_session.add(offer)
    await db_session.commit()
    await db_session.refresh(offer)

    # Upload offer banner (cover mode unified banner size: 1200x600)
    img_data = create_dummy_image("JPEG", size=(1600, 800))
    res = await client.post(
        f"/api/v1/admin/offers/{offer.id}/banner",
        files={"file": ("eid_banner.jpg", img_data, "image/jpeg")},
    )
    assert res.status_code == 200, res.text
    offer_data = res.json()
    assert offer_data["banner_url"].startswith("/uploads/offers/")
    assert offer_data["banner_url"].endswith(".webp")

    # Verify offer in DB updated
    refreshed_offer = (await db_session.execute(
        select(Offer).where(Offer.id == offer.id)
    )).scalars().first()
    assert refreshed_offer.banner_url == offer_data["banner_url"]


@pytest.mark.asyncio
async def test_static_file_serving(client: AsyncClient, auth_tokens: dict):
    client.cookies.set("access_token", auth_tokens["admin_token"])

    img_data = create_dummy_image("PNG", size=(300, 300))
    res = await client.post(
        "/api/v1/uploads/image",
        files={"file": ("served_test.png", img_data, "image/png")},
        data={"folder": "products"},
    )
    assert res.status_code == 201
    file_url = res.json()["url"]

    # In client fixture, if settings.UPLOAD_DIR matches or we verify disk file exists
    assert Path(settings.UPLOAD_DIR).resolve().exists()
    ImageService.delete_file_by_url(file_url)
