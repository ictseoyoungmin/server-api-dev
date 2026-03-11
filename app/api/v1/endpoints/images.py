"""저장된 이미지 목록/원본/메타를 제공하는 엔드포인트 모듈."""

from __future__ import annotations

import json
import mimetypes
from datetime import date as date_type
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.schemas.images import GalleryImageItem, ImageMetaResponse, ImagesListResponse
from app.schemas.ingest import BBox, InstanceOut
from app.vector_db.qdrant_store import QdrantStore, build_filter

router = APIRouter()


def _get_store(request: Request) -> QdrantStore:
    store = getattr(request.app.state, "vector_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Vector DB not ready")
    return store


def _meta_path(image_id: str) -> Path:
    return Path(settings.reid_storage_dir) / "meta" / f"{image_id}.json"


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
    image_role = str(img.get("image_role") or "DAILY").upper()
    if image_role not in ("DAILY", "SEED"):
        image_role = "DAILY"
    pet_ids = sorted(
        {
            str(i.get("pet_id") or "").strip()
            for i in instances
            if str(i.get("assignment_status") or "").upper() == "ACCEPTED" and str(i.get("pet_id") or "").strip()
        }
    )
    return GalleryImageItem(
        image_id=str(img.get("image_id")),
        daycare_id=str(img.get("daycare_id")),
        image_role=image_role,
        trainer_id=img.get("trainer_id"),
        captured_at=img.get("captured_at"),
        uploaded_at=img.get("uploaded_at"),
        width=int(img.get("width") or 0),
        height=int(img.get("height") or 0),
        raw_url=str(img.get("raw_url") or ""),
        thumb_url=str(img.get("thumb_url") or ""),
        instance_count=int(img.get("instance_count") or len(instances)),
        pet_ids=pet_ids,
    )


def _read_meta_safe(image_id: str) -> Optional[dict]:
    p = _meta_path(image_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _meta_day_utc(meta: dict) -> str:
    img = meta.get("image") or {}
    ts = img.get("captured_at_ts") or img.get("uploaded_at_ts")
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat()
    except Exception:
        return ""


def _is_unclassified(meta: dict) -> bool:
    instances = meta.get("instances") or []
    if not instances:
        return True
    for i in instances:
        if (i.get("assignment_status") == "ACCEPTED") and i.get("pet_id"):
            continue
        return True
    return False


def _matches_tab(meta: dict, tab: Literal["ALL", "UNCLASSIFIED", "PET"], pet_id: Optional[str]) -> bool:
    if tab == "ALL":
        return True
    if tab == "UNCLASSIFIED":
        return _is_unclassified(meta)
    instances = meta.get("instances") or []
    return any((i.get("assignment_status") == "ACCEPTED") and (i.get("pet_id") == pet_id) for i in instances)


def _is_seed_image(meta: dict) -> bool:
    img = meta.get("image") or {}
    return str(img.get("image_role") or "DAILY").upper() == "SEED"


def _day_range_ts(day: date_type) -> tuple[int, int]:
    tz = ZoneInfo(settings.business_tz)
    start_local = datetime.combine(day, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)
    return int(start_utc.timestamp()), int(end_utc.timestamp())


def _build_item_from_db(image_id: str, agg: dict, meta: Optional[dict]) -> GalleryImageItem:
    pet_ids = sorted([str(x).strip() for x in (agg.get("pet_hits") or set()) if str(x).strip()])
    if meta is not None:
        item = _build_item(meta)
        item.instance_count = int(agg.get("instance_count") or item.instance_count)
        if pet_ids:
            item.pet_ids = pet_ids
        return item

    cap_ts = agg.get("captured_at_ts")
    captured_at = None
    uploaded_at = datetime.now(timezone.utc)
    if cap_ts is not None:
        try:
            cap_dt = datetime.fromtimestamp(int(cap_ts), tz=timezone.utc)
            captured_at = cap_dt
            uploaded_at = cap_dt
        except Exception:
            pass

    return GalleryImageItem(
        image_id=image_id,
        daycare_id=str(agg.get("daycare_id") or ""),
        image_role=str(agg.get("image_role") or "DAILY"),
        trainer_id=agg.get("trainer_id"),
        captured_at=captured_at,
        uploaded_at=uploaded_at,
        width=0,
        height=0,
        raw_url=f"{settings.api_prefix}/images/{image_id}?variant=raw",
        thumb_url=f"{settings.api_prefix}/images/{image_id}?variant=thumb",
        instance_count=int(agg.get("instance_count") or 0),
        pet_ids=pet_ids,
    )


@router.get("/images", response_model=ImagesListResponse)
async def list_images(
    request: Request,
    daycare_id: str = Query(...),
    date: Optional[str] = Query(default=None, description="Business timezone date filter (YYYY-MM-DD)"),
    tab: Literal["ALL", "UNCLASSIFIED", "PET"] = Query(default="ALL"),
    pet_id: Optional[str] = Query(default=None),
    include_seed: bool = Query(default=False, description="Include seed(exemplar) images in results."),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
):
    """List images using Qdrant payload as source-of-truth."""
    if date:
        try:
            day_obj = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid date: {date}. Expected YYYY-MM-DD") from e
    else:
        day_obj = None
    if tab == "PET" and not pet_id:
        raise HTTPException(status_code=400, detail="pet_id is required when tab=PET")

    store = _get_store(request)
    from_ts: Optional[int] = None
    to_ts: Optional[int] = None
    if day_obj is not None:
        from_ts, to_ts = _day_range_ts(day_obj)

    qf = build_filter(daycare_id=daycare_id, captured_from_ts=from_ts, captured_to_ts=to_ts)
    points = await run_in_threadpool(store.scroll_points, qf, 1000, False)

    by_image: Dict[str, dict] = {}
    for p in points:
        payload = p.payload or {}
        image_id = str(payload.get("image_id") or "")
        if not image_id:
            continue

        image_role = str(payload.get("image_role") or "DAILY").upper()
        if image_role not in ("DAILY", "SEED"):
            image_role = "DAILY"
        if (not include_seed) and image_role == "SEED":
            continue

        entry = by_image.setdefault(
            image_id,
            {
                "image_id": image_id,
                "daycare_id": daycare_id,
                "image_role": image_role,
                "trainer_id": payload.get("trainer_id"),
                "captured_at_ts": payload.get("captured_at_ts"),
                "instance_count": 0,
                "has_unclassified": False,
                "pet_hits": set(),
            },
        )
        entry["instance_count"] += 1
        if entry.get("captured_at_ts") is None and payload.get("captured_at_ts") is not None:
            entry["captured_at_ts"] = payload.get("captured_at_ts")

        status = str(payload.get("assignment_status") or "").upper()
        p_pet_id = str(payload.get("pet_id") or "").strip()
        if status == "ACCEPTED" and p_pet_id:
            entry["pet_hits"].add(p_pet_id)
        else:
            entry["has_unclassified"] = True

    filtered: List[dict] = []
    for _img_id, entry in by_image.items():
        if tab == "ALL":
            filtered.append(entry)
            continue
        if tab == "UNCLASSIFIED":
            if entry["has_unclassified"]:
                filtered.append(entry)
            continue
        if pet_id in entry["pet_hits"]:
            filtered.append(entry)

    filtered.sort(key=lambda x: int(x.get("captured_at_ts") or 0), reverse=True)
    sliced = filtered[offset : offset + limit]

    items: List[GalleryImageItem] = []
    for e in sliced:
        meta = _read_meta_safe(str(e["image_id"]))
        items.append(_build_item_from_db(str(e["image_id"]), e, meta))

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
