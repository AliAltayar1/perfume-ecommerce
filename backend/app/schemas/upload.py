from typing import List, Optional
from pydantic import BaseModel, Field


class UploadImageResponse(BaseModel):
    url: str = Field(
        ...,
        description="Public HTTP URL or relative path to the uploaded image",
        examples=["/uploads/products/d3b07384d113edec49eaa6238ad5ff00.webp"],
    )
    filename: str = Field(
        ...,
        description="Generated unique file name on server disk",
        examples=["d3b07384d113edec49eaa6238ad5ff00.webp"],
    )
    original_filename: str = Field(
        ...,
        description="Original uploaded file name",
        examples=["luxury_perfume.png"],
    )
    folder: str = Field(
        ...,
        description="Storage subfolder classification",
        examples=["products"],
    )
    width: Optional[int] = Field(
        None,
        description="Processed image width in pixels",
        examples=[1000],
    )
    height: Optional[int] = Field(
        None,
        description="Processed image height in pixels",
        examples=[1000],
    )
    file_size: int = Field(
        ...,
        description="Size of stored file on disk in bytes",
        examples=[85412],
    )
    mime_type: str = Field(
        ...,
        description="Output MIME type",
        examples=["image/webp"],
    )


class BatchUploadResponse(BaseModel):
    uploaded: List[UploadImageResponse] = Field(
        ...,
        description="List of successfully processed and uploaded images",
    )
    total_count: int = Field(
        ...,
        description="Total number of uploaded files",
        examples=[3],
    )
