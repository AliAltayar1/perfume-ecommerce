# Perfume & Personal Care E-Commerce Backend API

A high-performance, asynchronous RESTful API engineered for luxury perfumes and personal care products built with **FastAPI**, **SQLAlchemy (asyncio)**, **PostgreSQL / SQLite**, **Pydantic v2**, and **Pillow**.

---

## Interactive API Documentation

Once the server is running, the interactive Swagger UI and ReDoc documentation are available at:
- **Swagger UI**: `http://localhost:8000/api/v1/docs`
- **ReDoc**: `http://localhost:8000/api/v1/redoc`
- **OpenAPI JSON**: `http://localhost:8000/api/v1/openapi.json`

---

## Image & Media Management Subsystem

### 1. Broad Format Support & Validation
The media pipeline accepts and processes a wide variety of formats:
- **Supported Formats**: `JPEG`, `JPG`, `PNG`, `WebP`, `AVIF`, `HEIC` / `HEIF` (native iPhone camera format), `GIF`, `BMP`, `TIFF`, `ICO`, and `SVG`.
- **Integrity Validation**:
  - Whitelist validation of extensions and MIME types.
  - Deep byte-level decoding using Pillow to detect corrupted or disguised non-image files.
  - SVG sanitizer ensuring vector graphics contain no dynamic `<script>`, `javascript:`, or inline event triggers (`onload`, `onerror`).
  - Size limit enforcement (`MAX_IMAGE_SIZE_MB = 15`).

### 2. Unified Sizing Logic
To maintain aesthetic consistency across storefront catalog cards and detail views, images are uniformly standardized:
- **Presets**:
  - **Products & Variants**: `1000 x 1000 px` square.
  - **Offers & Banners**: `1200 x 600 px` banner.
  - **General**: Proportional scaling up to `1000 x 1000 px`.
- **Fit Modes**:
  - `contain` (*Default for products*): Preserves original bottle/product aspect ratio, scales to fit inside the target box, and centers it on a clean white or transparent canvas. **Products are never cropped, distorted, or stretched.**
  - `cover` (*Standard for banners*): Scales to fill the entire box and center-crops excess edges.
  - `scale`: Proportional downscale without canvas padding.
- **EXIF Auto-Transpose**: Photos taken on smartphones are automatically oriented using EXIF tags so they never appear sideways or upside down.

### 3. Space-Saving WebP Compression
- All raster images are converted to modern **WebP** (`quality=85`, `method=6`) with Lanczos resampling.
- EXIF metadata and camera GPS tags are stripped to save storage bytes and preserve user privacy.
- Transparency (alpha channel) is preserved for transparent PNG/WebP product shots.
- Typically yields **80% to 95% reduction in disk file size** compared to raw camera uploads.

### 4. Server Disk Storage Layout
Images are stored locally on server disk under the configured `UPLOAD_DIR` (default: `uploads/`):
```
uploads/
├── products/     # Product gallery showcase images
├── offers/       # Promotional deal banners
├── variants/     # Specific bottle packaging/size images
└── general/      # General assets, logos, and miscellaneous media
```
- Filenames use collision-free, cryptographically secure 128-bit hex tokens (`<token>.webp` or `<token>.svg`).
- The directory is mounted at `/uploads`, allowing the browser to load images directly via HTTP: `http://<server-domain>/uploads/...`.

---

## API Endpoints Reference

### 1. Upload Endpoints (`Uploads & Media`)
| Method | Path | Auth | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/uploads/image` | Admin | Upload and process a single image. Accepts `file`, `folder`, `fit_mode`, optional `target_width`, `target_height`, and `quality`. |
| `POST` | `/api/v1/uploads/images` | Admin | Batch upload and process multiple images simultaneously. |

#### Upload Response Schema (`UploadImageResponse`)
```json
{
  "url": "/uploads/products/d3b07384d113edec49eaa6238ad5ff00.webp",
  "filename": "d3b07384d113edec49eaa6238ad5ff00.webp",
  "original_filename": "dior_sauvage.jpg",
  "folder": "products",
  "width": 1000,
  "height": 1000,
  "file_size": 84210,
  "mime_type": "image/webp"
}
```

### 2. Product Image Endpoints (`Administration`)
| Method | Path | Auth | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/admin/products/{product_id}/images` | Admin | Upload image file directly for a product. Automatically resizes to `1000x1000`, compresses to WebP, stores on disk, and creates a database row. |
| `DELETE` | `/api/v1/admin/products/{product_id}/images/{image_id}` | Admin | Deletes the image record from the database **and removes the physical file from disk**. |
| `PATCH` | `/api/v1/admin/products/{product_id}/images/{image_id}/primary` | Admin | Sets target image as primary showcase hero image for catalog cards. |

### 3. Variant Image Endpoints (`Administration`)
| Method | Path | Auth | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/admin/variants/{variant_id}/image` | Admin | Upload bottle/packaging image for a variant. Updates `ProductVariant.image_url` and cleans up old file from disk. |

### 4. Offer Banner Endpoints (`Administration`)
| Method | Path | Auth | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/admin/offers/{offer_id}/banner` | Admin | Upload banner image for an offer. Resizes to unified `1200x600`, updates `Offer.banner_url`, and cleans up old file from disk. |

### 5. Product Retrieval Endpoints (`Products & Catalog`)
| Method | Path | Auth | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/products` | Public | Storefront catalog list. Returns `primary_image_url`, price ranges, and stock. |
| `GET` | `/api/v1/products/{slug}` | Public | Full product detail. Returns `images` array (sorted by `display_order`) and `variants` (each with `image_url`). |
| `GET` | `/api/v1/admin/products` | Admin | Admin product list including all gallery images and variants. |
| `GET` | `/api/v1/admin/products/{product_id}` | Admin | Single product by ID with all images and variants. |

### 6. Offer Retrieval Endpoints (`Offers & Promotions`)
| Method | Path | Auth | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/offers` | Public | List active deals, promotional banners, and discount coupons with `banner_url`. |
| `GET` | `/api/v1/offers/{offer_id}` | Public | Specific offer details with `banner_url`. |
| `GET` | `/api/v1/admin/offers` | Admin | List all promotional offers. |
| `GET` | `/api/v1/admin/offers/{offer_id}` | Admin | Detailed offer by ID. |

---

## Response Payloads

### Storefront Catalog (`GET /api/v1/products`)
```json
[
  {
    "id": 1,
    "category_id": 2,
    "name": "Baccarat Rouge Elite",
    "slug": "baccarat-rouge-elite",
    "description": "Luxury floral amber fragrance.",
    "is_active": true,
    "primary_image_url": "/uploads/products/d3b07384d113edec49eaa6238ad5ff00.webp",
    "min_price": "110.00",
    "max_price": "210.00",
    "total_stock": 55,
    "category_name": "French Perfumes"
  }
]
```

### Product Details (`GET /api/v1/products/{slug}`)
```json
{
  "id": 1,
  "category_id": 2,
  "name": "Baccarat Rouge Elite",
  "slug": "baccarat-rouge-elite",
  "description": "Luxury floral amber fragrance.",
  "is_active": true,
  "images": [
    {
      "id": 10,
      "product_id": 1,
      "url": "/uploads/products/d3b07384d113edec49eaa6238ad5ff00.webp",
      "alt_text": "Front bottle view",
      "is_primary": true,
      "display_order": 1
    },
    {
      "id": 11,
      "product_id": 1,
      "url": "/uploads/products/a58f9210c49efb0129a0081dbeef4910.webp",
      "alt_text": "Packaging luxury box",
      "is_primary": false,
      "display_order": 2
    }
  ],
  "variants": [
    {
      "id": 101,
      "product_id": 1,
      "sku": "BRE-50ML",
      "size_or_volume": "50ml",
      "price": "120.00",
      "discount_price": "110.00",
      "stock": 25,
      "image_url": "/uploads/variants/71e3d9021a8bf92c4b01eec9912048aa.webp",
      "is_active": true
    }
  ]
}
```

### Promotional Offer (`GET /api/v1/offers/{offer_id}`)
```json
{
  "id": 5,
  "title": "Eid Mega Sale - 30% Off",
  "description": "30% off all French luxury perfumes this week.",
  "discount_percentage": "30.00",
  "code": "EID30",
  "banner_url": "/uploads/offers/f81c9a02beef437190ad01889efc11a0.webp",
  "is_active": true
}
```

---

## Frontend Integration Guide

### 1. Upload Button Implementation (JavaScript / TypeScript)
```typescript
// Generic upload handler (e.g. for multi-step creation form)
async function uploadMedia(file: File, folder: 'products' | 'offers' | 'variants' | 'general' = 'products') {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('folder', folder);
  formData.append('fit_mode', 'contain'); // 'contain' for products, 'cover' for banners

  const response = await fetch('/api/v1/uploads/image', {
    method: 'POST',
    body: formData,
    credentials: 'include', // Sends admin HttpOnly cookie
  });

  if (!response.ok) {
    const errorData = await response.json();
    throw new Error(errorData.error?.message || 'Upload failed');
  }

  const data = await response.json();
  return data.url; // e.g. "/uploads/products/d3b07384...webp"
}

// Direct product gallery upload button
async function uploadProductImageDirect(productId: number, file: File, isPrimary = false, altText = '') {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('is_primary', String(isPrimary));
  formData.append('alt_text', altText);

  const response = await fetch(`/api/v1/admin/products/${productId}/images`, {
    method: 'POST',
    body: formData,
    credentials: 'include',
  });

  return await response.json();
}
```

### 2. Displaying Images in UI Components (React / Next.js)
```tsx
// 1. Product Grid Card
export function ProductCard({ product }) {
  return (
    <div className="product-card">
      <img
        src={product.primary_image_url || '/placeholder.png'}
        alt={product.name}
        className="w-full h-64 object-contain rounded-lg"
      />
      <h3>{product.name}</h3>
      <p>{product.category_name}</p>
      <span>${product.min_price}</span>
    </div>
  );
}

// 2. Product Gallery with Thumbnails
export function ProductGallery({ images }) {
  const [selected, setSelected] = useState(images[0]?.url);

  return (
    <div className="gallery">
      <img src={selected} alt="Selected perfume" className="main-image w-96 h-96 object-contain" />
      <div className="thumbnails flex gap-2 mt-4">
        {images.map((img) => (
          <img
            key={img.id}
            src={img.url}
            alt={img.alt_text}
            onClick={() => setSelected(img.url)}
            className={`w-16 h-16 object-cover cursor-pointer rounded ${selected === img.url ? 'ring-2 ring-primary' : ''}`}
          />
        ))}
      </div>
    </div>
  );
}
```

---

## Testing & Quality Assurance

Run the automated test suite with pytest:
```bash
# Run all tests
pytest

# Run image management test suite only
pytest tests/test_images.py -v
```
All 45 tests verify:
- JPEG, PNG, WebP, AVIF, HEIC, GIF, BMP, TIFF, and SVG upload processing.
- Unified sizing (`contain`, `cover`, `scale`) calculation.
- Corrupted file rejection and SVG script attack prevention.
- Disk saving, URL resolution, and physical file deletion on database record removal.
- Direct product, variant, and offer banner upload operations.
