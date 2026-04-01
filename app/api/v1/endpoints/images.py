"""저장된 이미지 목록/원본/메타를 제공하는 엔드포인트 모듈."""

from __future__ import annotations

import json
import re
import zipfile
import mimetypes
from datetime import date as date_type
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Literal, Optional
from app.utils.timezone import business_tz

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
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
        image_role=image_role,
        trainer_id=img.get("trainer_id"),
        captured_at=img.get("captured_at"),
        uploaded_at=img.get("uploaded_at"),
        width=int(img.get("width") or 0),
        height=int(img.get("height") or 0),
        raw_url=str(img.get("raw_url") or ""),
        thumb_url=str(img.get("thumb_url") or ""),
        img_name=(str(img.get("original_filename") or "").strip() or None),
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


def _is_unclassified(meta: dict) -> bool:
    instances = meta.get("instances") or []
    if not instances:
        return True
    for i in instances:
        if (i.get("assignment_status") == "ACCEPTED") and i.get("pet_id"):
            continue
        return True
    return False


def _is_seed_image(meta: dict) -> bool:
    img = meta.get("image") or {}
    return str(img.get("image_role") or "DAILY").upper() == "SEED"


def _safe_archive_name(name: Optional[str], default: str = "unknown") -> str:
    raw = (name or "").strip()
    if not raw:
        raw = default
    safe = re.sub(r'[\/:*?"<>|]+', '_', raw)
    safe = safe.replace('..', '_').strip().strip('.')
    return safe or default


def _zip_temp_path(prefix: str) -> Path:
    export_dir = Path(settings.reid_storage_dir) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir / f"{prefix}_{int(datetime.now(timezone.utc).timestamp())}.zip"


def _day_range_ts(day: date_type) -> tuple[int, int]:
    tz = business_tz()
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
        image_role=str(agg.get("image_role") or "DAILY"),
        trainer_id=agg.get("trainer_id"),
        captured_at=captured_at,
        uploaded_at=uploaded_at,
        width=0,
        height=0,
        raw_url=f"{settings.api_prefix}/images/{image_id}?variant=raw",
        thumb_url=f"{settings.api_prefix}/images/{image_id}?variant=thumb",
        img_name=(str((meta or {}).get("image", {}).get("original_filename") or "").strip() or None) if meta is not None else None,
        instance_count=int(agg.get("instance_count") or 0),
        pet_ids=pet_ids,
    )


@router.get("/images", response_model=ImagesListResponse)
async def list_images(
    request: Request,
    date: Optional[str] = Query(default=None, description="Business timezone date filter (YYYY-MM-DD)"),
    tab: Literal["ALL", "UNCLASSIFIED", "PET"] = Query(default="ALL"),
    pet_id: Optional[str] = Query(default=None),
    include_seed: bool = Query(default=False, description="Include seed(exemplar) images in results."),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
):
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

    qf = build_filter(captured_from_ts=from_ts, captured_to_ts=to_ts)
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

    return ImagesListResponse(count=len(items), items=items)


@router.get("/daily/{day}/zip")
async def download_daily_zip(
    day: date_type,
    root_folder_name: Optional[str] = Query(default=None, description="Archive root folder name"),
):
    root_name = _safe_archive_name(root_folder_name, day.isoformat())
    zip_path = _zip_temp_path(f"daily_{day.isoformat()}")
    written = 0
    used_paths = set()

    meta_dir = Path(settings.reid_storage_dir) / "meta"
    if not meta_dir.exists():
        raise HTTPException(status_code=404, detail="No daily image files available for zip export")

    for meta_path in meta_dir.glob("img_*.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        img = meta.get("image") or {}
        role = str(img.get("image_role") or "DAILY").upper()
        if role == "SEED":
            continue
        ts = img.get("captured_at_ts") or img.get("uploaded_at_ts")
        try:
            biz_day = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(business_tz()).date()
        except Exception:
            continue
        if biz_day != day:
            continue
        src = Path(str(img.get("raw_path") or ""))
        if not src.exists():
            continue
        base_name = str(img.get("original_filename") or "").strip() or src.name
        file_name = _safe_archive_name(base_name, src.name)
        arcname = f"{root_name}/{file_name}"
        image_id = str(img.get("image_id") or "")
        if arcname in used_paths:
            file_name = _safe_archive_name(f"{image_id}_{base_name}", f"{image_id}_{src.name}")
            arcname = f"{root_name}/{file_name}"
        used_paths.add(arcname)
        mode = 'a' if written else 'w'
        with zipfile.ZipFile(zip_path, mode, compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(src, arcname)
        written += 1

    if written == 0:
        raise HTTPException(status_code=404, detail="No daily image files available for zip export")

    return FileResponse(
        path=zip_path,
        media_type='application/zip',
        filename=f"{root_name}.zip",
        background=BackgroundTask(zip_path.unlink, missing_ok=True),
    )


@router.get("/images/{image_id}")
def get_image(
    image_id: str,
    variant: str = Query(default="raw", description="raw|thumb"),
):
    meta = _read_meta(image_id)
    img = meta.get("image") or {}
    if variant == "thumb":
        path = img.get("thumb_path")
    else:
        path = img.get("raw_path")
    if not path:
        raise HTTPException(status_code=404, detail="Image file not found")
    p = Path(str(path))
    if not p.exists():
        raise HTTPException(status_code=404, detail="Image file missing on disk")
    media_type, _ = mimetypes.guess_type(str(p))
    return FileResponse(p, media_type=media_type or "application/octet-stream")


@router.get("/images/{image_id}/meta", response_model=ImageMetaResponse)
def get_image_meta(image_id: str):
    meta = _read_meta(image_id)
    item = _build_item(meta)
    instances = []
    for x in meta.get("instances") or []:
        bb = x.get("bbox") or {}
        instances.append(
            InstanceOut(
                instance_id=str(x.get("instance_id")),
                class_id=int(x.get("class_id") or 0),
                species=str(x.get("species") or "UNKNOWN"),
                confidence=float(x.get("confidence") or 0.0),
                bbox=BBox(
                    x1=float(bb.get("x1") or 0.0),
                    y1=float(bb.get("y1") or 0.0),
                    x2=float(bb.get("x2") or 0.0),
                    y2=float(bb.get("y2") or 0.0),
                ),
                pet_id=(str(x.get("pet_id")) if x.get("pet_id") is not None else None),
            )
        )
    return ImageMetaResponse(image=item, instances=instances)
