from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import Depends, FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import ErrorResponse, register_exception_handlers
from app.db.session import async_engine, get_db

description = """
### Perfume & Personal Care E-Commerce Backend API

A high-performance, asynchronous RESTful API engineered for luxury perfumes and personal care products.

---

#### Architecture & Invariant Highlights
- **Secure Dual-Token Authentication**: Delivered strictly via HttpOnly, SameSite cookies with automatic token rotation and server-side database revocation.
- **Server-Derived Pricing**: Clients submit only `variant_id` and `quantity`. The backend evaluates effective promotional discounts directly from database records.
- **Concurrency-Safe Inventory**: Uses pessimistic row-level locking (`SELECT ... FOR UPDATE`) with sorted keys to prevent stock race conditions and deadlocks.
- **Historical Purchasing Snapshots**: Every line item captures frozen snapshots of unit price, product name, volume, and SKU at purchase time.
- **Cash on Delivery (COD) & Affiliate Attribution**: Built-in support for guest checkouts, WhatsApp order dispatch confirmations, and affiliate influencer referral tracking.
- **Automated Media Pipeline & Disk Storage**: Universal format validation (JPEG, PNG, WebP, AVIF, HEIC/HEIF, GIF, BMP, TIFF, SVG), auto-transposed EXIF rotation, unified aspect ratio handling (contain/cover/scale), and high-efficiency WebP compression stored directly on server disk.
"""

tags_metadata = [
    {
        "name": "Authentication",
        "description": "User registration, login, token rotation, and session management using secure HttpOnly dual cookies.",
    },
    {
        "name": "Customer Information",
        "description": "Customer self-service endpoints to view, update, and delete account profiles.",
    },
    {
        "name": "Products & Catalog",
        "description": "Public storefront catalog endpoints to browse categories, active products with effective pricing, and full product details.",
    },
    {
        "name": "Offers & Promotions",
        "description": "Public storefront and promotional offer endpoints for active coupons, discounts, and banners.",
    },
    {
        "name": "Orders & Checkout",
        "description": "Cash on Delivery (COD) checkout supporting both guest checkouts and registered customers with historical snapshotting and stock locking.",
    },
    {
        "name": "Administration",
        "description": "Admin dashboard endpoints for managing categories, products, inventory variants, offers, orders, and affiliate promoters.",
    },
    {
        "name": "Uploads & Media",
        "description": "Image and media file upload, automated unified resizing, and WebP compression endpoints.",
    },
    {
        "name": "Health",
        "description": "Operational health probes for container orchestrators and connection pool monitoring.",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Application startup
    yield
    # Application shutdown: Dispose async engine connection pools
    await async_engine.dispose()


app = FastAPI(
    title="Perfume & Care E-Commerce API",
    version="1.0.0",
    description=description,
    openapi_tags=tags_metadata,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
    lifespan=lifespan,
)

# Register centralized exception handlers for uniform error contract
register_exception_handlers(app)


def custom_openapi():
    """
    Overrides the default OpenAPI schema generation:
    - Registers ErrorResponse schema and nested definitions in components/schemas.
    - Replaces default HTTPValidationError and ValidationError with unified ErrorResponse.
    - Ensures standard error responses (400, 401, 403, 422) point to ErrorResponse schema.
    """
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
    )

    components = openapi_schema.setdefault("components", {})
    schemas = components.setdefault("schemas", {})

    # Register ErrorResponse and submodels in components/schemas
    error_response_schema = ErrorResponse.model_json_schema(
        ref_template="#/components/schemas/{model}"
    )
    defs = error_response_schema.pop("$defs", {})
    for def_name, def_schema in defs.items():
        schemas[def_name] = def_schema
    schemas["ErrorResponse"] = error_response_schema

    # Replace FastAPI's default HTTPValidationError and ValidationError
    schemas["HTTPValidationError"] = {
        "$ref": "#/components/schemas/ErrorResponse"
    }
    if "ErrorDetail" in schemas:
        schemas["ValidationError"] = {
            "$ref": "#/components/schemas/ErrorDetail"
        }

    # Standard error responses for 400, 401, 403, and 422
    error_schema_ref = {"$ref": "#/components/schemas/ErrorResponse"}
    standard_error_content = {"application/json": {"schema": error_schema_ref}}

    standard_errors = {
        "400": {
            "description": "Bad Request",
            "content": standard_error_content,
        },
        "401": {
            "description": "Unauthorized",
            "content": standard_error_content,
        },
        "403": {
            "description": "Forbidden",
            "content": standard_error_content,
        },
        "422": {
            "description": "Validation Error",
            "content": standard_error_content,
        },
    }

    for path, path_item in openapi_schema.get("paths", {}).items():
        for method, operation in path_item.items():
            if method.lower() in ("get", "post", "put", "patch", "delete"):
                responses = operation.setdefault("responses", {})
                for status_code, default_err in standard_errors.items():
                    if status_code not in responses:
                        responses[status_code] = default_err
                    else:
                        existing = responses[status_code]
                        # Replace default FastAPI 422 HTTPValidationError with ErrorResponse
                        if (
                            status_code == "422"
                            and isinstance(existing, dict)
                            and "content" in existing
                            and "application/json" in existing["content"]
                        ):
                            existing["content"]["application/json"]["schema"] = error_schema_ref
                            existing["description"] = "Validation Error"

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

# Set up CORS middleware (strict non-wildcard origins for HttpOnly cookies)
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Mount static files directory for local uploads
upload_dir = Path(settings.UPLOAD_DIR).resolve()
upload_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(upload_dir)), name="uploads")

# Include API v1 router
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health", tags=["Health"], status_code=status.HTTP_200_OK)
async def health_check(
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    Database-aware health probe verifying API runtime and database connection health.
    """
    try:
        await db.execute(text("SELECT 1"))
        db_status = "connected"
        is_healthy = True
    except Exception as exc:
        db_status = f"unhealthy: {str(exc)}"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        is_healthy = False

    return {
        "status": "ok" if is_healthy else "degraded",
        "database": db_status,
        "app": "Perfume & Care E-Commerce API",
        "version": "1.0.0",
        "environment": settings.ENVIRONMENT,
    }


@app.get("/", tags=["Health"])
async def root():
    return {
        "app": "Perfume & Care E-Commerce API",
        "version": "1.0.0",
        "documentation": f"{settings.API_V1_STR}/docs",
        "health": "/health",
    }
