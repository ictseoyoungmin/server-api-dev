from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import (
    embedding,
    health,
    images,
    ingest,
    labels,
    search,
    sync_images,
    trials,
)

router = APIRouter()

router.include_router(health.router, tags=["health"])
router.include_router(embedding.router, tags=["embedding"])
router.include_router(ingest.router, tags=["ingest"])
router.include_router(images.router, tags=["images"])
router.include_router(search.router, tags=["search"])
router.include_router(labels.router, tags=["labels"])
router.include_router(sync_images.router, tags=["sync-images"])
router.include_router(trials.router, tags=["trials"])
