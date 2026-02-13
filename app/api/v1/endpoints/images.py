"""저장된 이미지 목록/원본/메타를 제공하는 엔드포인트 모듈."""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.core.config import settings
from app.schemas.images import GalleryImageItem, ImageMetaResponse, ImagesListResponse
from app.schemas.ingest import BBox, InstanceOut

router = APIRouter()


def _meta_path(image_id: str) -> Path:
    return Path(settings.storage_dir) / "meta" / f"{image_id}.json"


def _read_meta(image_id: str) -> dict:
    p = _meta_path(image_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Image meta not found")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse meta: {e}") from e


def _build_item(meta: dict) -> GalleryImageItem:
    img = meta.get("image") or {}
    instances = meta.get("instances") or []
    return GalleryImageItem(
        image_id=str(img.get("image_id")),
        daycare_id=str(img.get("daycare_id")),
        trainer_id=img.get("trainer_id"),
        captured_at=img.get("captured_at"),
        uploaded_at=img.get("uploaded_at"),
        width=int(img.get("width") or 0),
        height=int(img.get("height") or 0),
        raw_url=str(img.get("raw_url") or ""),
        thumb_url=str(img.get("thumb_url") or ""),
        instance_count=int(img.get("instance_count") or len(instances)),
    )


@router.get("/images", response_model=ImagesListResponse)
def list_images(
    daycare_id: str = Query(...),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
):
    """List server-stored images (PoC local storage)."""

    meta_dir = Path(settings.storage_dir) / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)

    metas: List[dict] = []
    for p in meta_dir.glob("img_*.json"):
        try:
            meta = json.loads(p.read_text(encoding="utf-8"))
            img = meta.get("image") or {}
            if str(img.get("daycare_id")) != daycare_id:
                continue
            metas.append(meta)
        except Exception:
            continue

    def _sort_key(m: dict):
        img = m.get("image") or {}
        return int(img.get("captured_at_ts") or img.get("uploaded_at_ts") or 0)

    metas.sort(key=_sort_key, reverse=True)
    sliced = metas[offset : offset + limit]

    items = [_build_item(m) for m in sliced]
    return ImagesListResponse(daycare_id=daycare_id, count=len(items), items=items)


@router.get("/images/{image_id}")
def get_image(
    image_id: str,
    variant: str = Query(default="raw", description="raw|thumb"),
):
    """Serve raw or thumbnail image bytes."""

    meta = _read_meta(image_id)
    img = meta.get("image") or {}
    variant = variant.lower()
    if variant not in ("raw", "thumb"):
        raise HTTPException(status_code=400, detail="variant must be raw or thumb")

    path_str = img.get("raw_path") if variant == "raw" else img.get("thumb_path")
    if not path_str:
        raise HTTPException(status_code=404, detail="Image file path not found")
    p = Path(path_str)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Image file not found")

    media_type, _ = mimetypes.guess_type(str(p))
    return FileResponse(path=p, media_type=media_type or "application/octet-stream")


@router.get("/images/{image_id}/meta", response_model=ImageMetaResponse)
def get_image_meta(image_id: str):
    meta = _read_meta(image_id)
    item = _build_item(meta)

    insts_out: List[InstanceOut] = []
    for i in meta.get("instances") or []:
        bb = i.get("bbox") or {}
        bbox_obj: Optional[BBox] = None
        if isinstance(bb, dict) and all(k in bb for k in ("x1", "y1", "x2", "y2")):
            bbox_obj = BBox(**bb)
        if bbox_obj is None:
            continue

        insts_out.append(
            InstanceOut(
                instance_id=str(i.get("instance_id")),
                class_id=int(i.get("class_id") or 0),
                species=str(i.get("species") or "UNKNOWN"),
                confidence=float(i.get("confidence") or 0.0),
                bbox=bbox_obj,
                pet_id=i.get("pet_id"),
                embedding=None,
                embedding_meta=None,
            )
        )

    return ImageMetaResponse(image=item, instances=insts_out)
