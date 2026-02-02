from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.schemas.labels import LabelRequest, LabelResponse, LabelResponseItem
from app.vector_db.qdrant_store import QdrantStore

router = APIRouter()


def _get_store(request: Request) -> QdrantStore:
    store = getattr(request.app.state, "vector_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Vector DB not ready")
    return store


@router.post("/labels", response_model=LabelResponse)
async def set_labels(request: Request, body: LabelRequest):
    """Assign (instance_id -> pet_id) labels.

    For this PoC, labels are stored in Qdrant payload.
    """

    store = _get_store(request)
    now = datetime.now(timezone.utc)
    now_ts = int(now.timestamp())

    items = []
    for a in body.assignments:
        payload = {
            "pet_id": a.pet_id,
            "label_source": a.source,
            "label_confidence": float(a.confidence),
            "labeled_by": body.labeled_by,
            "labeled_at_ts": now_ts,
        }
        try:
            await run_in_threadpool(store.set_payload, [a.instance_id], payload)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        items.append(LabelResponseItem(instance_id=a.instance_id, pet_id=a.pet_id, updated=True))

    return LabelResponse(labeled_at=now, items=items)
