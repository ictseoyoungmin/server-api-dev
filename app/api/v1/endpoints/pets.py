"""등록/라벨된 반려동물 목록을 조회하는 엔드포인트 모듈."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.schemas.pets import PetListItem, PetsListResponse
from app.vector_db.qdrant_store import QdrantStore, build_filter

router = APIRouter()


def _get_store(request: Request) -> QdrantStore:
    store = getattr(request.app.state, "vector_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Vector DB not ready")
    return store


def _read_pet_name_map() -> Dict[str, str]:
    """Load pet_id -> pet_name mapping from storage_dir/pets layout."""
    pets_root = Path(settings.storage_dir) / "pets"
    if not pets_root.exists():
        return {}

    out: Dict[str, str] = {}
    for pet_dir in pets_root.iterdir():
        if not pet_dir.is_dir():
            continue
        pet_id = pet_dir.name
        candidates = [c for c in pet_dir.iterdir() if c.is_dir()]
        if not candidates:
            continue
        # Preferred: human-readable pet-name folder (contains facebanks/trials)
        for c in candidates:
            has_expected = (c / "facebanks").exists() or (c / "trials").exists()
            if has_expected:
                out[pet_id] = c.name
                break
        if pet_id not in out:
            out[pet_id] = candidates[0].name
    return out


@router.get("/pets", response_model=PetsListResponse)
async def list_pets(request: Request, daycare_id: str = Query(...)):
    """List pet IDs used in this daycare, with optional display names."""
    store = _get_store(request)
    pet_name_map = _read_pet_name_map()
    agg: Dict[str, dict] = {}

    qf = build_filter(daycare_id=daycare_id)
    points = await run_in_threadpool(store.scroll_points, qf, 1000, False)
    for p in points:
        payload = p.payload or {}
        image_id = str(payload.get("image_id") or "")

        pet_ids = set()
        pet_id_label = str(payload.get("pet_id") or "").strip()
        pet_id_seed = str(payload.get("seed_pet_id") or "").strip()
        if pet_id_label:
            pet_ids.add(pet_id_label)
        if pet_id_seed:
            pet_ids.add(pet_id_seed)

        for pet_id in pet_ids:
            item = agg.setdefault(
                pet_id,
                {"pet_id": pet_id, "pet_name": pet_name_map.get(pet_id), "images": set(), "instances": 0},
            )
            if image_id:
                item["images"].add(image_id)
            item["instances"] += 1

    # Fallback: include storage_dir/pets entries even if no labeled meta yet.
    for pet_id, pet_name in pet_name_map.items():
        agg.setdefault(pet_id, {"pet_id": pet_id, "pet_name": pet_name, "images": set(), "instances": 0})

    items = [
        PetListItem(
            pet_id=v["pet_id"],
            pet_name=v.get("pet_name"),
            image_count=len(v["images"]),
            instance_count=int(v["instances"]),
        )
        for _k, v in sorted(agg.items(), key=lambda kv: kv[0])
    ]
    return PetsListResponse(daycare_id=daycare_id, count=len(items), items=items)
