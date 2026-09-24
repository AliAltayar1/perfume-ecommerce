# Perfume & Personal Care E-Commerce Project

A full-featured, luxury perfume and personal care e-commerce platform with a high-performance asynchronous backend and modern media processing pipeline.

- **Backend API Documentation**: See [backend/README.md](file:///c:/Users/alias/OneDrive/%D8%B3%D8%B7%D8%AD%20%D8%A7%D9%84%D9%85%D9%83%D8%AA%D8%A8/ecommerce%20project/backend/README.md)
- **Interactive Swagger UI**: `http://localhost:8000/api/v1/docs`
- **Interactive ReDoc**: `http://localhost:8000/api/v1/redoc`

---

## Key Features & Highlights

1. **Dual-Token HttpOnly Authentication**: Short-lived access token + long-lived rotating refresh token with database blacklisting.
2. **Automated Media Processing Pipeline**:
   - Universal format support: `JPEG`, `PNG`, `WebP`, `AVIF`, `HEIC`/`HEIF` (iPhone camera format), `GIF`, `BMP`, `TIFF`, `ICO`, and `SVG`.
   - Unified sizing logic: `1000x1000` square for products/variants, `1200x600` for promotional banners.
   - Non-cropping `contain` padding to ensure perfume bottles are never cropped or distorted.
   - High-efficiency `WebP` compression reducing file size by 80–95%.
   - Direct disk storage under `/uploads` with static serving.
3. **Pessimistic Inventory Locking**: `SELECT ... FOR UPDATE` with sorted keys preventing race conditions and deadlocks.
4. **Server-Derived Pricing**: Active promotional discounts evaluated directly by the server.
5. **Cash on Delivery (COD) & WhatsApp Orders**: Historical checkout snapshots and customer phone attribution.
