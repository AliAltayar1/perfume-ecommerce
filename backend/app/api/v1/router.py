from fastapi import APIRouter
from app.api.v1 import admin, auth, offers, orders, products, uploads, users

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(users.router, prefix="/users", tags=["Customer Information"])
api_router.include_router(products.router, prefix="/products", tags=["Products & Catalog"])
api_router.include_router(offers.router, prefix="/offers", tags=["Offers & Promotions"])
api_router.include_router(orders.router, prefix="/orders", tags=["Orders & Checkout"])
api_router.include_router(uploads.router, prefix="/uploads", tags=["Uploads & Media"])
api_router.include_router(admin.router, prefix="/admin", tags=["Administration"])
