from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
def health(request: Request):
    embedder = getattr(request.app.state, "embedder", None)
    info = None
    if embedder is not None:
        info = {
            "model_name": embedder.model_info.model_name,
            "model_version": embedder.model_info.model_version,
            "input_size": embedder.model_info.input_size,
            "dim": embedder.dim,
            "device": str(embedder.device),
        }

    return {
        "status": "ok",
        "model": info,
    }
