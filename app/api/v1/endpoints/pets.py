"""등록/라벨된 반려동물 목록을 조회하는 엔드포인트 모듈."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, Query

from app.core.config import settings
from app.schemas.pets import PetListItem, PetsListResponse

router = APIRouter()


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
def list_pets(daycare_id: str = Query(...)):
    """List pet IDs used in this daycare, with optional display names."""
    meta_dir = Path(settings.storage_dir) / "meta"
    pet_name_map = _read_pet_name_map()
    agg: Dict[str, dict] = {}

    if meta_dir.exists():
        for p in meta_dir.glob("img_*.json"):
            try:
                meta = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            image = meta.get("image") or {}
            if str(image.get("daycare_id")) != daycare_id:
                continue

            image_id = str(image.get("image_id") or "")
            for inst in meta.get("instances") or []:
                pet_id = str(inst.get("pet_id") or "").strip()
                if not pet_id:
                    continue
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
