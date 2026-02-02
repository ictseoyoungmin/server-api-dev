from __future__ import annotations

from pathlib import Path

import logging

import torch

logger = logging.getLogger(__name__)


def load_embedding_model(model_name: str, cache_dir: Path) -> torch.nn.Module:
    """Load an embedding model.

    Supported:
      - miewid (conservationxlabs/miewid-msv3)
      - mega-t, mega-l, mega-l-224 (BVRA MegaDescriptor)
      - clip, dinov2 (BVRA MegaDescriptor variants)

    Note: for PoC we rely on hf-hub downloads via timm/transformers caches.
    """

    name = model_name.lower().strip()
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    if name == "miewid":
        from transformers import AutoModel

        logger.info("Loading miewid model from HuggingFace (cached at %s)", cache_dir)
        # trust_remote_code=True is needed by the model repo.
        model = AutoModel.from_pretrained(
            "conservationxlabs/miewid-msv3",
            trust_remote_code=True,
            cache_dir=str(cache_dir),
        )
        return model

    # timm models
    import timm

    timm_name_map = {
        "mega-t": "hf-hub:BVRA/MegaDescriptor-T-224",
        "mega-l": "hf-hub:BVRA/MegaDescriptor-L-384",
        "mega-l-224": "hf-hub:BVRA/MegaDescriptor-L-224",
        "clip": "hf-hub:BVRA/MegaDescriptor-CLIP-336",
        "dinov2": "hf-hub:BVRA/MegaDescriptor-DINOv2-518",
    }

    if name not in timm_name_map:
        raise ValueError(f"Unsupported model_name: {model_name}")

    timm_id = timm_name_map[name]
    logger.info("Loading timm model %s (cached at %s)", timm_id, cache_dir)

    # Most of these provide pretrained weights via hf-hub.
    model = timm.create_model(timm_id, pretrained=True, cache_dir=str(cache_dir))
    return model
