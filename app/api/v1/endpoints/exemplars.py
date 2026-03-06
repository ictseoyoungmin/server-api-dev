"""관리자용 초기 등록 이미지(exemplar) CRUD 엔드포인트 모듈."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from qdrant_client.http import models as qm
from starlette.concurrency import run_in_threadpool

from app.api.v1.endpoints.ingest import ingest as ingest_image
from app.schemas.exemplars import (
    ExemplarCreateRequest,
    ExemplarFolderUploadItemResult,
    ExemplarFolderUploadResponse,
    ExemplarItem,
    ExemplarListResponse,
    ExemplarMutationResponse,
    ExemplarQuickRegisterResponse,
    ExemplarUpdateRequest,
)
from app.vector_db.qdrant_store import PointRecord, QdrantStore

router = APIRouter()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ts_to_dt(ts: Optional[object]) -> Optional[datetime]:
    try:
        if ts is None:
            return None
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except Exception:
        return None


def _get_store(request: Request) -> QdrantStore:
    store = getattr(request.app.state, "vector_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Vector DB not ready")
    return store


def _normalize_ids(instance_ids: Iterable[str]) -> List[str]:
    dedup = []
    seen = set()
    for iid in instance_ids:
        if iid in seen:
            continue
        seen.add(iid)
        dedup.append(iid)
    return dedup


def _to_exemplar_item(store: QdrantStore, p: PointRecord) -> ExemplarItem:
    payload = p.payload or {}
    instance_id = payload.get("instance_id")
    if not instance_id:
        instance_id = store.external_instance_id(p.point_id)

    return ExemplarItem(
        instance_id=str(instance_id),
        daycare_id=str(payload.get("daycare_id") or ""),
        image_id=(str(payload.get("image_id")) if payload.get("image_id") is not None else None),
        species=(str(payload.get("species")) if payload.get("species") is not None else None),
        pet_id=str(payload.get("seed_pet_id") or ""),
        active=bool(payload.get("seed_active", True)),
        rank=(int(payload["seed_rank"]) if payload.get("seed_rank") is not None else None),
        note=(str(payload.get("seed_note")) if payload.get("seed_note") is not None else None),
        created_at=_ts_to_dt(payload.get("seed_created_at_ts")),
        created_by=(str(payload.get("seed_created_by")) if payload.get("seed_created_by") is not None else None),
        updated_at=_ts_to_dt(payload.get("seed_updated_at_ts")),
        updated_by=(str(payload.get("seed_updated_by")) if payload.get("seed_updated_by") is not None else None),
        synced_label_pet_id=(str(payload.get("pet_id")) if payload.get("pet_id") is not None else None),
        synced_assignment_status=(
            str(payload.get("assignment_status")) if payload.get("assignment_status") is not None else None
        ),
    )


def _seed_filter(daycare_id: str, pet_id: Optional[str], active: Optional[bool]) -> qm.Filter:
    must: List[qm.FieldCondition] = [
        qm.FieldCondition(key="daycare_id", match=qm.MatchValue(value=daycare_id)),
        qm.FieldCondition(key="is_seed", match=qm.MatchValue(value=True)),
    ]
    if pet_id:
        must.append(qm.FieldCondition(key="seed_pet_id", match=qm.MatchValue(value=pet_id)))
    if active is not None:
        must.append(qm.FieldCondition(key="seed_active", match=qm.MatchValue(value=active)))
    return qm.Filter(must=must)


def _pet_id_from_name(pet_name: str) -> str:
    # Assumption for quick mode: pet names are globally unique and can be used as IDs.
    pet_id = pet_name.strip()
    if not pet_id:
        raise HTTPException(status_code=400, detail="pet_name is required")
    return pet_id


def _pet_name_from_relative_path(relative_path: str) -> str:
    # Supports either:
    # - root/pet_name/file.jpg
    # - pet_name/file.jpg
    parts = [p for p in str(relative_path).replace("\\", "/").split("/") if p]
    if len(parts) < 2:
        raise ValueError(f"Invalid relative path: {relative_path}")
    if len(parts) == 2:
        return parts[0]
    return parts[1]


async def _register_exemplar_from_uploaded_file(
    request: Request,
    store: QdrantStore,
    file: UploadFile,
    daycare_id: str,
    pet_name: str,
    updated_by: Optional[str],
    trainer_id: Optional[str],
    captured_at: Optional[str],
    sync_label: bool,
    apply_to_all_instances: bool,
) -> tuple[str, str, str, List[ExemplarItem]]:
    pet_id = _pet_id_from_name(pet_name)
    now = _utcnow()
    now_ts = int(now.timestamp())

    ingest_resp = await ingest_image(
        request=request,
        file=file,
        daycare_id=daycare_id,
        trainer_id=trainer_id,
        captured_at=captured_at,
        image_role="SEED",
        pet_name=pet_name,
        include_embedding=False,
    )
    instances = list(ingest_resp.instances or [])
    if not instances:
        raise HTTPException(status_code=400, detail="No detected instances in uploaded image")

    if apply_to_all_instances:
        selected = instances
    else:
        selected = [max(instances, key=lambda x: float(x.confidence))]

    updates: Dict[str, dict] = {}
    for inst in selected:
        payload = {
            "is_seed": True,
            "seed_pet_id": pet_id,
            "seed_active": True,
            "seed_rank": None,
            "seed_note": "quick_upload",
            "seed_created_at_ts": now_ts,
            "seed_created_by": updated_by,
            "seed_updated_at_ts": now_ts,
            "seed_updated_by": updated_by,
        }
        if sync_label:
            payload.update(
                {
                    "pet_id": pet_id,
                    "assignment_status": "ACCEPTED",
                    "label_source": "MANUAL",
                    "label_confidence": 1.0,
                    "labeled_at_ts": now_ts,
                    "labeled_by": updated_by,
                }
            )
        updates[str(inst.instance_id)] = payload

    for instance_id, payload in updates.items():
        await run_in_threadpool(store.set_payload, [instance_id], payload)

    updated_points = await run_in_threadpool(store.retrieve_points, updates.keys(), False)
    items = [_to_exemplar_item(store, p) for p in updated_points.values()]
    items.sort(key=lambda x: x.instance_id)
    return pet_id, pet_name.strip(), str(ingest_resp.image.image_id), items


@router.get("/exemplars", response_model=ExemplarListResponse)
async def list_exemplars(
    request: Request,
    daycare_id: str = Query(...),
    pet_id: Optional[str] = Query(default=None),
    species: Optional[str] = Query(default=None),
    active: Optional[bool] = Query(default=True),
    q: Optional[str] = Query(default=None, description="instance_id/image_id/note 부분 검색"),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
):
    store = _get_store(request)
    points = await run_in_threadpool(store.scroll_points, _seed_filter(daycare_id, pet_id, active), 1000, False)

    items = [_to_exemplar_item(store, p) for p in points]
    if species:
        species_upper = species.upper()
        items = [x for x in items if (x.species or "").upper() == species_upper]
    if q:
        needle = q.lower().strip()
        items = [
            x
            for x in items
            if (needle in x.instance_id.lower())
            or (needle in (x.image_id or "").lower())
            or (needle in (x.note or "").lower())
            or (needle in x.pet_id.lower())
        ]

    items.sort(
        key=lambda x: (
            -int(x.active),
            x.rank if x.rank is not None else 999999,
            (x.updated_at or datetime.fromtimestamp(0, tz=timezone.utc)),
        ),
        reverse=False,
    )
    sliced = items[offset : offset + limit]
    return ExemplarListResponse(daycare_id=daycare_id, count=len(sliced), items=sliced)


@router.post("/exemplars", response_model=ExemplarMutationResponse)
async def create_exemplars(request: Request, body: ExemplarCreateRequest):
    store = _get_store(request)
    now = _utcnow()
    now_ts = int(now.timestamp())

    raw_instance_ids = _normalize_ids([x.instance_id for x in body.items])
    instance_ids = [store.external_instance_id(x) for x in raw_instance_ids]
    points = await run_in_threadpool(store.retrieve_points, raw_instance_ids, False)
    if len(points) != len(instance_ids):
        missing = sorted(set(instance_ids) - set(points.keys()))
        raise HTTPException(status_code=404, detail=f"instance_ids not found: {missing}")

    updates: Dict[str, dict] = {}
    for item in body.items:
        key = store.external_instance_id(item.instance_id)
        p = points.get(key)
        if p is None:
            continue
        payload = p.payload or {}
        point_daycare_id = str(payload.get("daycare_id") or "")
        if point_daycare_id != body.daycare_id:
            raise HTTPException(
                status_code=400,
                detail=f"instance {key} belongs to daycare_id={point_daycare_id}, not {body.daycare_id}",
            )

        new_payload = {
            "is_seed": True,
            "seed_pet_id": item.pet_id,
            "seed_active": bool(item.active),
            "seed_rank": item.rank,
            "seed_note": item.note,
            "seed_created_at_ts": int(payload.get("seed_created_at_ts") or now_ts),
            "seed_created_by": payload.get("seed_created_by") or body.updated_by,
            "seed_updated_at_ts": now_ts,
            "seed_updated_by": body.updated_by,
        }
        if item.sync_label:
            new_payload.update(
                {
                    "pet_id": item.pet_id,
                    "assignment_status": "ACCEPTED",
                    "label_source": "MANUAL",
                    "label_confidence": 1.0,
                    "labeled_at_ts": now_ts,
                    "labeled_by": body.updated_by,
                }
            )
        updates[key] = new_payload

    for instance_id, payload in updates.items():
        await run_in_threadpool(store.set_payload, [instance_id], payload)

    updated_points = await run_in_threadpool(store.retrieve_points, updates.keys(), False)
    items = [_to_exemplar_item(store, p) for p in updated_points.values()]
    items.sort(key=lambda x: x.instance_id)
    return ExemplarMutationResponse(daycare_id=body.daycare_id, updated_at=now, count=len(items), items=items)


@router.post("/exemplars/upload", response_model=ExemplarQuickRegisterResponse)
async def upload_exemplar_quick(
    request: Request,
    file: UploadFile = File(...),
    daycare_id: Optional[str] = Form(default=None),
    daycare_id_alt: Optional[str] = Form(default=None, alias="daycareId"),
    pet_name: str = Form(...),
    updated_by: Optional[str] = Form(default=None),
    trainer_id: Optional[str] = Form(default=None),
    captured_at: Optional[str] = Form(default=None),
    sync_label: bool = Form(default=True),
    apply_to_all_instances: bool = Form(default=False),
):
    """Quick admin flow: upload image + pet name, then ingest and register exemplar(s)."""
    resolved_daycare_id = (daycare_id or daycare_id_alt or "").strip()
    if not resolved_daycare_id:
        raise HTTPException(status_code=400, detail="daycare_id is required")

    now = _utcnow()
    store = _get_store(request)
    pet_id, pet_name_clean, image_id, items = await _register_exemplar_from_uploaded_file(
        request=request,
        store=store,
        file=file,
        daycare_id=resolved_daycare_id,
        pet_name=pet_name,
        updated_by=updated_by,
        trainer_id=trainer_id,
        captured_at=captured_at,
        sync_label=sync_label,
        apply_to_all_instances=apply_to_all_instances,
    )

    return ExemplarQuickRegisterResponse(
        daycare_id=resolved_daycare_id,
        pet_id=pet_id,
        pet_name=pet_name_clean,
        image_id=image_id,
        updated_at=now,
        count=len(items),
        items=items,
    )


@router.post("/exemplars/upload-folder", response_model=ExemplarFolderUploadResponse)
async def upload_exemplar_folder(
    request: Request,
    files: List[UploadFile] = File(...),
    relative_paths: List[str] = Form(...),
    daycare_id: Optional[str] = Form(default=None),
    daycare_id_alt: Optional[str] = Form(default=None, alias="daycareId"),
    updated_by: Optional[str] = Form(default=None),
    trainer_id: Optional[str] = Form(default=None),
    captured_at: Optional[str] = Form(default=None),
    sync_label: bool = Form(default=True),
    apply_to_all_instances: bool = Form(default=False),
    skip_on_error: bool = Form(default=True),
):
    """Batch folder upload for admin dashboard.

    Expected structure:
    - root/pet_name/image.ext
    - pet_name/image.ext
    """
    resolved_daycare_id = (daycare_id or daycare_id_alt or "").strip()
    if not resolved_daycare_id:
        raise HTTPException(status_code=400, detail="daycare_id is required")
    if len(files) != len(relative_paths):
        raise HTTPException(status_code=400, detail="files and relative_paths count mismatch")

    store = _get_store(request)
    now = _utcnow()
    results: List[ExemplarFolderUploadItemResult] = []
    succeeded = 0
    failed = 0

    for upload, rel_path in zip(files, relative_paths):
        try:
            pet_name = _pet_name_from_relative_path(rel_path)
            pet_id, _pet_name_clean, image_id, items = await _register_exemplar_from_uploaded_file(
                request=request,
                store=store,
                file=upload,
                daycare_id=resolved_daycare_id,
                pet_name=pet_name,
                updated_by=updated_by,
                trainer_id=trainer_id,
                captured_at=captured_at,
                sync_label=sync_label,
                apply_to_all_instances=apply_to_all_instances,
            )
            succeeded += 1
            results.append(
                ExemplarFolderUploadItemResult(
                    relative_path=rel_path,
                    pet_name=pet_name,
                    pet_id=pet_id,
                    image_id=image_id,
                    registered_instances=len(items),
                    status="ok",
                )
            )
        except Exception as e:
            failed += 1
            results.append(
                ExemplarFolderUploadItemResult(
                    relative_path=rel_path,
                    status="failed",
                    error=str(e),
                )
            )
            if not skip_on_error:
                raise HTTPException(status_code=400, detail=f"Failed at {rel_path}: {e}") from e

    return ExemplarFolderUploadResponse(
        daycare_id=resolved_daycare_id,
        updated_at=now,
        total_files=len(files),
        succeeded=succeeded,
        failed=failed,
        results=results,
    )


@router.patch("/exemplars/{instance_id}", response_model=ExemplarMutationResponse)
async def update_exemplar(request: Request, instance_id: str, body: ExemplarUpdateRequest):
    store = _get_store(request)
    now = _utcnow()
    now_ts = int(now.timestamp())

    points = await run_in_threadpool(store.retrieve_points, [instance_id], False)
    key = store.external_instance_id(instance_id)
    point = points.get(key)
    if point is None:
        raise HTTPException(status_code=404, detail="instance not found")

    payload = point.payload or {}
    if str(payload.get("daycare_id") or "") != body.daycare_id:
        raise HTTPException(status_code=400, detail="instance daycare_id mismatch")
    if not bool(payload.get("is_seed", False)):
        raise HTTPException(status_code=400, detail="instance is not an exemplar")

    patch: Dict[str, object] = {
        "seed_updated_at_ts": now_ts,
        "seed_updated_by": body.updated_by,
    }
    if body.pet_id is not None:
        patch["seed_pet_id"] = body.pet_id
    if body.note is not None:
        patch["seed_note"] = body.note
    if body.clear_note:
        patch["seed_note"] = None
    if body.rank is not None:
        patch["seed_rank"] = body.rank
    if body.active is not None:
        patch["seed_active"] = body.active
    if body.sync_label and body.pet_id is not None:
        patch.update(
            {
                "pet_id": body.pet_id,
                "assignment_status": "ACCEPTED",
                "label_source": "MANUAL",
                "label_confidence": 1.0,
                "labeled_at_ts": now_ts,
                "labeled_by": body.updated_by,
            }
        )

    await run_in_threadpool(store.set_payload, [key], patch)
    updated = await run_in_threadpool(store.retrieve_points, [key], False)
    item = updated.get(key)
    if item is None:
        raise HTTPException(status_code=404, detail="instance not found after update")
    exemplar = _to_exemplar_item(store, item)
    return ExemplarMutationResponse(daycare_id=body.daycare_id, updated_at=now, count=1, items=[exemplar])


@router.delete("/exemplars/{instance_id}", response_model=ExemplarMutationResponse)
async def delete_exemplar(
    request: Request,
    instance_id: str,
    daycare_id: str = Query(...),
    updated_by: Optional[str] = Query(default=None),
):
    store = _get_store(request)
    now = _utcnow()

    points = await run_in_threadpool(store.retrieve_points, [instance_id], False)
    key = store.external_instance_id(instance_id)
    point = points.get(key)
    if point is None:
        raise HTTPException(status_code=404, detail="instance not found")

    payload = point.payload or {}
    if str(payload.get("daycare_id") or "") != daycare_id:
        raise HTTPException(status_code=400, detail="instance daycare_id mismatch")

    patch = {
        "is_seed": False,
        "seed_pet_id": None,
        "seed_active": None,
        "seed_rank": None,
        "seed_note": None,
        "seed_updated_at_ts": int(now.timestamp()),
        "seed_updated_by": updated_by,
    }
    await run_in_threadpool(store.set_payload, [key], patch)

    return ExemplarMutationResponse(daycare_id=daycare_id, updated_at=now, count=0, items=[])
