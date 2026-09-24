from typing import List, Optional
from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.api.deps import require_admin
from app.schemas.upload import BatchUploadResponse, UploadImageResponse
from app.services.image_service import ImageService

router = APIRouter(dependencies=[Depends(require_admin)])


@router.post(
    "/image",
    response_model=UploadImageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and process a single image",
    description=(
        "Uploads an image file to server disk, validates file type (JPEG, PNG, WebP, AVIF, HEIC, GIF, BMP, TIFF, ICO, SVG), "
        "applies unified sizing and aspect ratio handling, compresses to optimized WebP, and returns the stored URL path."
    ),
)
async def upload_single_image(
    file: UploadFile = File(..., description="Image file to upload and process"),
    folder: str = Form("products", description="Subfolder preset: 'products', 'offers', 'variants', 'general'"),
    fit_mode: str = Form("contain", description="Unified sizing fit mode: 'contain', 'cover', or 'scale'"),
    target_width: Optional[int] = Form(None, description="Optional explicit width override in pixels"),
    target_height: Optional[int] = Form(None, description="Optional explicit height override in pixels"),
    quality: Optional[int] = Form(None, ge=1, le=100, description="Optional WebP quality 1-100 (default 85)"),
):
    upload_result = await ImageService.save_image_to_disk(
        upload_file=file,
        folder=folder,
        fit_mode=fit_mode,
        target_width=target_width,
        target_height=target_height,
        quality=quality,
    )
    return upload_result


@router.post(
    "/images",
    response_model=BatchUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and process multiple images in batch",
    description="Batch upload multiple images (e.g. for product photo galleries) processed and saved to server disk.",
)
async def upload_multiple_images(
    files: List[UploadFile] = File(..., description="Array of image files to upload"),
    folder: str = Form("products", description="Subfolder preset: 'products', 'offers', 'variants', 'general'"),
    fit_mode: str = Form("contain", description="Unified sizing fit mode: 'contain', 'cover', or 'scale'"),
    quality: Optional[int] = Form(None, ge=1, le=100, description="Optional WebP quality 1-100 (default 85)"),
):
    results = []
    for file in files:
        res = await ImageService.save_image_to_disk(
            upload_file=file,
            folder=folder,
            fit_mode=fit_mode,
            quality=quality,
        )
        results.append(res)

    return {
        "uploaded": results,
        "total_count": len(results),
    }
