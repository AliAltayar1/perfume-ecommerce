from fastapi import APIRouter
from app.api.v1 import admin, auth, orders, products

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(products.router, prefix="/products", tags=["Products & Catalog"])
api_router.include_router(orders.router, prefix="/orders", tags=["Orders & Checkout"])
api_router.include_router(admin.router, prefix="/admin", tags=["Administration"])
