from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import router as v1_router
from app.core.config import settings
from app.core.logging import setup_logging
from app.ml.embedder import Embedder
from app.vector_db.qdrant_store import QdrantStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.log_level)
    embedder = Embedder(settings)
    app.state.embedder = embedder

    # Vector DB
    store = QdrantStore(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        collection=settings.qdrant_collection,
        timeout_s=settings.qdrant_timeout_s,
    )
    # Ensure collection exists with correct vector size.
    if embedder.dim is None:
        raise RuntimeError("Failed to resolve embedding dimension")
    store.ensure_collection(embedder.dim)
    app.state.vector_store = store

    # Detector (optional)
    if settings.detector_enabled:
        from app.ml.detector import YoloDetector

        keep_ids = [int(x.strip()) for x in settings.yolo_class_ids.split(",") if x.strip()]
        det = YoloDetector(
            weights_path=settings.yolo_weights_path,
            device=settings.device,
            imgsz=settings.yolo_imgsz,
            conf=settings.yolo_conf,
            iou=settings.yolo_iou,
            keep_class_ids=keep_ids,
            task=settings.yolo_task,
        )
        app.state.detector = det
    yield
    # No explicit teardown for PoC


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.include_router(v1_router, prefix=settings.api_prefix)
admin_dir = Path(__file__).resolve().parents[1] / "for_admin"
if admin_dir.exists():
    app.mount("/admin", StaticFiles(directory=str(admin_dir), html=True), name="admin")


@app.get("/")
def root():
    return {
        "name": settings.app_name,
        "docs": "/docs",
        "health": f"{settings.api_prefix}/health",
    }
