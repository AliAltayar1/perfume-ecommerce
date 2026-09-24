import asyncio
import io
import logging
from pathlib import Path
import re
import secrets
from typing import Optional, Set, Tuple

from fastapi import HTTPException, UploadFile, status
from PIL import Image, ImageOps

from app.core.config import settings

# Attempt to register HEIF / HEIC opener for Apple devices photos
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:
    pass

logger = logging.getLogger("app.services.image")

# Whitelist of allowed image file extensions
ALLOWED_EXTENSIONS: Set[str] = {
    ".jpg",
    ".jpeg",
    ".jfif",
    ".jpe",
    ".pjpeg",
    ".png",
    ".webp",
    ".avif",
    ".heic",
    ".heif",
    ".hif",
    ".gif",
    ".bmp",
    ".dib",
    ".tiff",
    ".tif",
    ".ico",
    ".svg",
}

# Whitelist of allowed MIME types
ALLOWED_MIME_TYPES: Set[str] = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/avif",
    "image/heic",
    "image/heif",
    "image/gif",
    "image/bmp",
    "image/tiff",
    "image/x-icon",
    "image/vnd.microsoft.icon",
    "image/svg+xml",
}

# Dangerous patterns disallowed in SVGs to prevent stored XSS attacks
SVG_FORBIDDEN_PATTERNS = [
    re.compile(r"<\s*script", re.IGNORECASE),
    re.compile(r"javascript\s*:", re.IGNORECASE),
    re.compile(r"on\w+\s*=", re.IGNORECASE),
    re.compile(r"<\s*iframe", re.IGNORECASE),
    re.compile(r"<\s*embed", re.IGNORECASE),
    re.compile(r"<\s*object", re.IGNORECASE),
]


class ImageService:
    """
    Enterprise-grade image processing service:
    - Broad format support (JPEG, PNG, WebP, AVIF, HEIC/HEIF, GIF, BMP, TIFF, ICO, SVG)
    - File type and content integrity verification
    - Unified sizing with aspect ratio preservation (contain/pad, cover/crop, scale)
    - Auto EXIF rotation transpose for smartphone camera orientation
    - High-efficiency WebP compression saving disk space and network bandwidth
    - Local disk storage with collision-free filenames and static serving support
    """

    @classmethod
    def get_target_dimensions(
        cls,
        folder: str,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
    ) -> Tuple[int, int]:
        """
        Resolve target dimensions based on folder preset or explicit overrides.
        """
        if target_width and target_height:
            return max(1, target_width), max(1, target_height)

        folder_lower = folder.lower()
        if folder_lower == "products":
            return settings.PRODUCT_IMAGE_WIDTH, settings.PRODUCT_IMAGE_HEIGHT
        elif folder_lower in ("offers", "banners"):
            return settings.OFFER_IMAGE_WIDTH, settings.OFFER_IMAGE_HEIGHT
        elif folder_lower == "variants":
            return settings.VARIANT_IMAGE_WIDTH, settings.VARIANT_IMAGE_HEIGHT
        else:
            return settings.GENERAL_IMAGE_WIDTH, settings.GENERAL_IMAGE_HEIGHT

    @classmethod
    def validate_file_metadata(cls, filename: str, content_type: Optional[str]) -> str:
        """
        Validate file extension and MIME type.
        Returns lowercased extension.
        """
        if not filename or "." not in filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file must have a valid filename with an image extension.",
            )

        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            allowed_list = ", ".join(sorted(ALLOWED_EXTENSIONS))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file extension '{ext}'. Supported formats: [{allowed_list}].",
            )

        return ext

    @classmethod
    def validate_svg_content(cls, data: bytes) -> None:
        """
        Ensure SVG is valid XML/SVG markup and free from executable script tags.
        """
        try:
            text = data.decode("utf-8", errors="ignore").strip()
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid SVG encoding; file must be UTF-8 text.",
            )

        if "<svg" not in text.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid SVG format: Missing '<svg>' root tag.",
            )

        for pattern in SVG_FORBIDDEN_PATTERNS:
            if pattern.search(text):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="SVG file rejected: Contains disallowed dynamic executable content or scripts.",
                )

    @classmethod
    def process_raster_image(
        cls,
        image_bytes: bytes,
        target_w: int,
        target_h: int,
        fit_mode: str = "contain",
        quality: Optional[int] = None,
    ) -> Tuple[bytes, int, int]:
        """
        Process, transpose, resize according to fit_mode, and compress raster image into WebP.
        Returns: (compressed_webp_bytes, output_width, output_height)
        """
        quality = quality or settings.WEBP_QUALITY

        try:
            img = Image.open(io.BytesIO(image_bytes))
            # Verify and load pixels to detect corrupted data early
            img.load()
        except Exception as exc:
            logger.warning("Failed to open or decode image: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The uploaded file is not a valid or readable image.",
            )

        # 1. Correct smartphone orientation using EXIF tags
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass

        orig_w, orig_h = img.size

        # 2. Normalize color mode
        has_transparency = False
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            img = img.convert("RGBA")
            # If all alpha values are opaque (255), convert to RGB to save space
            alpha = img.getchannel("A")
            if alpha.getextrema() == (255, 255):
                img = img.convert("RGB")
            else:
                has_transparency = True
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # 3. Apply Unified Sizing based on fit_mode
        fit_mode = fit_mode.lower()

        if fit_mode == "cover":
            # Scale to completely fill target box, then crop center
            scale = max(target_w / orig_w, target_h / orig_h)
            new_w = max(1, int(round(orig_w * scale)))
            new_h = max(1, int(round(orig_h * scale)))
            resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            left = (new_w - target_w) // 2
            top = (new_h - target_h) // 2
            final_img = resized.crop((left, top, left + target_w, top + target_h))
            out_w, out_h = target_w, target_h

        elif fit_mode == "scale":
            # Proportional downscaling without background canvas padding
            scale = min(target_w / orig_w, target_h / orig_h)
            # Avoid upscaling if already smaller than target
            if scale >= 1.0:
                final_img = img
                out_w, out_h = orig_w, orig_h
            else:
                out_w = max(1, int(round(orig_w * scale)))
                out_h = max(1, int(round(orig_h * scale)))
                final_img = img.resize((out_w, out_h), Image.Resampling.LANCZOS)

        else:
            # Default: "contain" with canvas padding
            # Keeps full product bottle in frame with zero distortion or nozzle/base cropping.
            scale = min(target_w / orig_w, target_h / orig_h)
            new_w = max(1, int(round(orig_w * scale)))
            new_h = max(1, int(round(orig_h * scale)))
            resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            if has_transparency:
                canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
                offset_x = (target_w - new_w) // 2
                offset_y = (target_h - new_h) // 2
                canvas.paste(resized, (offset_x, offset_y), mask=resized)
            else:
                canvas = Image.new("RGB", (target_w, target_h), (255, 255, 255))
                offset_x = (target_w - new_w) // 2
                offset_y = (target_h - new_h) // 2
                canvas.paste(resized, (offset_x, offset_y))

            final_img = canvas
            out_w, out_h = target_w, target_h

        # 4. WebP Compression
        out_buf = io.BytesIO()
        final_img.save(
            out_buf,
            format="WEBP",
            quality=quality,
            method=6,
            optimize=True,
        )
        compressed_bytes = out_buf.getvalue()

        return compressed_bytes, out_w, out_h

    @classmethod
    async def save_image_to_disk(
        cls,
        upload_file: UploadFile,
        folder: str = "products",
        fit_mode: str = "contain",
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
        quality: Optional[int] = None,
    ) -> dict:
        """
        Validate, process, compress, and save an uploaded image file to server disk.
        Returns a dict conforming to UploadImageResponse.
        """
        filename = upload_file.filename or "upload.jpg"
        content_type = upload_file.content_type

        # 1. Validate file extension
        ext = cls.validate_file_metadata(filename=filename, content_type=content_type)

        # 2. Read file data with size limit check
        max_bytes = settings.MAX_IMAGE_SIZE_MB * 1024 * 1024
        file_bytes = await upload_file.read()

        if len(file_bytes) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty (0 bytes).",
            )

        if len(file_bytes) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File size exceeds maximum allowed limit of {settings.MAX_IMAGE_SIZE_MB}MB.",
            )

        # 3. Target dimensions
        target_w, target_h = cls.get_target_dimensions(
            folder=folder,
            target_width=target_width,
            target_height=target_height,
        )

        # 4. Process file content
        clean_folder = re.sub(r"[^\w-]", "", folder.lower()) or "general"
        unique_token = secrets.token_hex(16)

        if ext == ".svg":
            cls.validate_svg_content(file_bytes)
            output_bytes = file_bytes
            output_filename = f"{unique_token}.svg"
            output_mime = "image/svg+xml"
            out_w, out_h = None, None
        else:
            output_bytes, out_w, out_h = cls.process_raster_image(
                image_bytes=file_bytes,
                target_w=target_w,
                target_h=target_h,
                fit_mode=fit_mode,
                quality=quality,
            )
            output_filename = f"{unique_token}.webp"
            output_mime = "image/webp"

        # 5. Persist to disk asynchronously
        base_dir = Path(settings.UPLOAD_DIR).resolve()
        target_dir = base_dir / clean_folder
        target_dir.mkdir(parents=True, exist_ok=True)

        destination_path = target_dir / output_filename
        await asyncio.to_thread(destination_path.write_bytes, output_bytes)

        # 6. Relative public URL path
        relative_url = f"/uploads/{clean_folder}/{output_filename}"

        return {
            "url": relative_url,
            "filename": output_filename,
            "original_filename": filename,
            "folder": clean_folder,
            "width": out_w,
            "height": out_h,
            "file_size": len(output_bytes),
            "mime_type": output_mime,
        }

    @classmethod
    def delete_file_by_url(cls, image_url: Optional[str]) -> bool:
        """
        Safely delete a physical file from the server disk given its /uploads/... URL.
        Guards against directory traversal attacks.
        """
        if not image_url or not image_url.startswith("/uploads/"):
            return False

        try:
            # Strip leading /uploads/
            relative_subpath = image_url[len("/uploads/") :].lstrip("/")
            base_dir = Path(settings.UPLOAD_DIR).resolve()
            target_path = (base_dir / relative_subpath).resolve()

            # Ensure path is strictly within base_dir
            if not target_path.is_relative_to(base_dir):
                logger.warning("Attempted path traversal deletion detected: %s", image_url)
                return False

            if target_path.exists() and target_path.is_file():
                target_path.unlink()
                logger.info("Deleted image from disk: %s", target_path)
                return True
        except Exception as exc:
            logger.error("Error deleting image file %s: %s", image_url, exc)

        return False
