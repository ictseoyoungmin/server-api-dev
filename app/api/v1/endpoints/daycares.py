"""daycare_id 목록/요약 정보를 조회하는 엔드포인트 모듈."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from qdrant_client.http import models as qm
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.schemas.daycares import DaycareListItem, DaycaresListResponse
from app.vector_db.qdrant_store import QdrantStore

router = APIRouter()


def _get_store(request: Request) -> QdrantStore:
    store = getattr(request.app.state, "vector_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Vector DB not ready")
    return store


def _ts_to_dt(ts: Optional[object]) -> Optional[datetime]:
    try:
        if ts is None:
            return None
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except Exception:
        return None


def _prune_empty_dirs(root: Path) -> None:
    if not root.exists() or not root.is_dir():
        return
    for p in sorted(root.rglob("*"), reverse=True):
        if p.is_dir():
            try:
                p.rmdir()
            except OSError:
                pass


def _delete_daycare_from_storage(daycare_id: str) -> dict:
    base_dir = Path(settings.reid_storage_dir)
    meta_dir = base_dir / "meta"
    buckets_dir = base_dir / "buckets" / daycare_id
    deleted_meta = 0
    deleted_raw = 0
    deleted_thumb = 0
    skipped_meta = 0

    if meta_dir.exists():
        for meta_path in meta_dir.glob("*.json"):
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                skipped_meta += 1
                continue

            img = data.get("image") or {}
            if str(img.get("daycare_id") or "") != daycare_id:
                continue

            raw_path = Path(str(img.get("raw_path") or ""))
            thumb_path = Path(str(img.get("thumb_path") or ""))
            if raw_path.exists():
                raw_path.unlink()
                deleted_raw += 1
            if thumb_path.exists():
                thumb_path.unlink()
                deleted_thumb += 1
            if meta_path.exists():
                meta_path.unlink()
                deleted_meta += 1

    if buckets_dir.exists():
        shutil.rmtree(buckets_dir, ignore_errors=True)

    _prune_empty_dirs(base_dir / "images" / "seed")
    _prune_empty_dirs(base_dir / "thumbs" / "seed")
    _prune_empty_dirs(base_dir / "images" / "daily")
    _prune_empty_dirs(base_dir / "thumbs" / "daily")

    return {
        "deleted_meta_files": deleted_meta,
        "deleted_raw_files": deleted_raw,
        "deleted_thumb_files": deleted_thumb,
        "skipped_meta_files": skipped_meta,
        "deleted_buckets_dir": buckets_dir.exists() is False,
    }


def _delete_daycare_from_qdrant(store: QdrantStore, daycare_id: str) -> int:
    flt = qm.Filter(
        must=[qm.FieldCondition(key="daycare_id", match=qm.MatchValue(value=daycare_id))]
    )
    points = store.scroll_points(flt, 1000, False)
    ids = [p.point_id for p in points]
    if not ids:
        return 0
    store.client.delete(
        collection_name=store.collection,
        points_selector=qm.PointIdsList(points=ids),
        wait=True,
    )
    return len(ids)


@router.get("/daycares", response_model=DaycaresListResponse)
async def list_daycares(
    request: Request,
    q: Optional[str] = Query(default=None, description="daycare_id substring"),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
):
    store = _get_store(request)
    points = await run_in_threadpool(store.scroll_points, None, 1000, False)
    agg: Dict[str, dict] = {}

    for p in points:
        payload = p.payload or {}
        daycare_id = str(payload.get("daycare_id") or "").strip()
        if not daycare_id:
            continue
        image_id = str(payload.get("image_id") or "").strip()
        image_role = str(payload.get("image_role") or "DAILY").upper()
        if image_role not in ("DAILY", "SEED"):
            image_role = "DAILY"
        captured_at_ts = payload.get("captured_at_ts")

        entry = agg.setdefault(
            daycare_id,
            {
                "daycare_id": daycare_id,
                "images": set(),
                "seed_images": set(),
                "daily_images": set(),
                "instance_count": 0,
                "pets": set(),
                "last_captured_at_ts": None,
            },
        )
        if image_id:
            entry["images"].add(image_id)
            if image_role == "SEED":
                entry["seed_images"].add(image_id)
            else:
                entry["daily_images"].add(image_id)
        entry["instance_count"] += 1

        pet_id = str(payload.get("pet_id") or "").strip()
        seed_pet_id = str(payload.get("seed_pet_id") or "").strip()
        if pet_id:
            entry["pets"].add(pet_id)
        if seed_pet_id:
            entry["pets"].add(seed_pet_id)

        try:
            ts_val = int(captured_at_ts)
            prev = entry.get("last_captured_at_ts")
            if prev is None or ts_val > int(prev):
                entry["last_captured_at_ts"] = ts_val
        except Exception:
            pass

    rows = []
    needle = (q or "").strip().lower()
    for daycare_id, v in agg.items():
        if needle and needle not in daycare_id.lower():
            continue
        rows.append(
            DaycareListItem(
                daycare_id=daycare_id,
                image_count=len(v["images"]),
                instance_count=int(v["instance_count"]),
                seed_image_count=len(v["seed_images"]),
                daily_image_count=len(v["daily_images"]),
                pet_count=len(v["pets"]),
                last_captured_at=_ts_to_dt(v.get("last_captured_at_ts")),
            )
        )

    rows.sort(key=lambda x: x.daycare_id)
    sliced = rows[offset : offset + limit]
    return DaycaresListResponse(count=len(sliced), items=sliced)


@router.delete("/daycares/{daycare_id}")
async def delete_daycare(
    request: Request,
    daycare_id: str,
    delete_qdrant: bool = Query(default=True),
    delete_storage: bool = Query(default=True),
):
    """Delete one daycare's data from Qdrant and/or local storage artifacts."""
    store = _get_store(request)
    deleted_qdrant_points = 0
    storage_result: dict = {}

    if delete_qdrant:
        deleted_qdrant_points = await run_in_threadpool(_delete_daycare_from_qdrant, store, daycare_id)
    if delete_storage:
        storage_result = await run_in_threadpool(_delete_daycare_from_storage, daycare_id)

    return {
        "status": "ok",
        "daycare_id": daycare_id,
        "deleted_qdrant_points": deleted_qdrant_points,
        "storage": storage_result,
    }
