from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from app.core.config import Settings
from app.ml.model_loader import load_embedding_model
from app.ml.preprocess import ModelSpec, get_model_spec, preprocess_batch

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelInfo:
    model_name: str
    model_version: str
    input_size: int


class Embedder:
    """GPU embedder loaded once per process.

    Concurrency is limited via an asyncio.Semaphore to protect GPU memory.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

        # Resolve device
        self.device = self._resolve_device(settings.device)
        self.spec: ModelSpec = get_model_spec(settings.model_name, settings.input_size)

        self.model = load_embedding_model(settings.model_name, settings.hf_cache_dir)
        self.model.eval()
        self.model.to(self.device)

        self.semaphore = asyncio.Semaphore(settings.max_concurrency)

        # Warmup can reduce first-request latency.
        # Also compute embedding dimension once to avoid per-request dummy forwards.
        self._dim: Optional[int] = None
        self._warmup_and_resolve_dim()

        self.model_info = ModelInfo(
            model_name=settings.model_name,
            model_version=settings.model_name,  # PoC: treat model_name as version
            input_size=self.spec.input_size,
        )

        logger.info(
            "Embedder ready | model=%s | device=%s | input=%s",
            settings.model_name,
            self.device,
            self.spec.input_size,
        )

    @staticmethod
    def _resolve_device(device_str: str) -> torch.device:
        ds = device_str.strip().lower()
        if ds.startswith("cuda"):
            if torch.cuda.is_available():
                return torch.device(device_str)
            logger.warning("CUDA requested but not available. Falling back to CPU.")
            return torch.device("cpu")
        return torch.device(device_str)

    def _warmup(self) -> None:
        try:
            dummy = torch.zeros((1, 3, self.spec.input_size, self.spec.input_size), device=self.device)
            with torch.no_grad():
                _ = self._forward(dummy)
            if self.device.type == "cuda":
                torch.cuda.synchronize(self.device)
        except Exception:
            logger.exception("Warmup failed (non-fatal).")

    def _warmup_and_resolve_dim(self) -> None:
        """Warm up GPU kernels and cache embedding dimension."""
        try:
            dummy = torch.zeros((1, 3, self.spec.input_size, self.spec.input_size), device=self.device)
            with torch.no_grad():
                feat = self._forward(dummy)
                feat = torch.flatten(feat, 1)
            self._dim = int(feat.shape[1])
            if self.device.type == "cuda":
                torch.cuda.synchronize(self.device)
        except Exception:
            logger.exception("Warmup/dim resolution failed (non-fatal).")

    def _forward(self, x: torch.Tensor) -> torch.Tensor:
        """Run model forward and return a tensor suitable for flattening."""
        out = self.model(x)

        # transformers ModelOutput
        if hasattr(out, "last_hidden_state"):
            return out.last_hidden_state
        if isinstance(out, dict) and "last_hidden_state" in out:
            return out["last_hidden_state"]

        # some models return tuple/list
        if isinstance(out, (list, tuple)):
            return out[0]

        return out

    def _resize_and_pad(self, img: Image.Image) -> Image.Image:
        """Resize with aspect ratio preserved and pad to a square input."""
        target = self.spec.input_size
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        if w == target and h == target:
            return img
        scale = min(target / w, target / h)
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        if (new_w, new_h) != (w, h):
            img = img.resize((new_w, new_h), Image.BILINEAR)
        canvas = Image.new("RGB", (target, target), (0, 0, 0))
        left = (target - new_w) // 2
        top = (target - new_h) // 2
        canvas.paste(img, (left, top))
        return canvas

    def embed_pil_images(self, images: List[Image.Image]) -> np.ndarray:
        """Embed a batch of PIL images.

        Returns:
            np.ndarray shape (N, D), float32, L2 normalized.
        """

        if not images:
            return np.zeros((0, 0), dtype=np.float32)

        # Convert to a float tensor in [0,1]
        arrs = []
        for img in images:
            img = self._resize_and_pad(img)
            a = np.asarray(img, dtype=np.uint8)
            # (H,W,3) -> (3,H,W)
            a = np.transpose(a, (2, 0, 1))
            arrs.append(a)

        batch_u8 = np.stack(arrs, axis=0)  # (N,3,H,W)
        batch = torch.from_numpy(batch_u8).to(self.device)
        batch = batch.float() / 255.0

        # Preprocess
        batch = preprocess_batch(batch, self.spec)

        with torch.no_grad():
            feat = self._forward(batch)
            feat = torch.flatten(feat, 1)
            # Ensure float32 for normalization stability
            feat = feat.float()
            feat = F.normalize(feat, p=2, dim=1)

        return feat.detach().cpu().numpy().astype(np.float32)

    def embed_one(self, image: Image.Image) -> np.ndarray:
        return self.embed_pil_images([image])[0]

    @property
    def dim(self) -> Optional[int]:
        return self._dim
