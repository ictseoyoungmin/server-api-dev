from __future__ import annotations

from datetime import datetime
from typing import Literal, List, Optional

from pydantic import BaseModel, Field

from app.schemas.ingest import InstanceOut


class GalleryImageItem(BaseModel):
    image_id: str
    daycare_id: str
    image_role: Literal["DAILY", "SEED"] = "DAILY"
    trainer_id: Optional[str] = None
    captured_at: Optional[datetime] = None
    uploaded_at: datetime
    width: int
    height: int
    raw_url: str = Field(..., description="Relative URL for original image bytes")
    thumb_url: str = Field(..., description="Relative URL for thumbnail image bytes")
    instance_count: int = 0
    pet_ids: List[str] = []


class ImagesListResponse(BaseModel):
    daycare_id: str
    count: int
    items: List[GalleryImageItem]


class ImageMetaResponse(BaseModel):
    image: GalleryImageItem
    instances: List[InstanceOut]
