from __future__ import annotations

from pathlib import Path

import logging

import torch

logger = logging.getLogger(__name__)


def _resolve_hf_local_source(source: str) -> str:
    """Resolve a HuggingFace local cache path to a loadable snapshot directory.

    Handles inputs like:
      /.../.cache/hf/models--org--repo
    by mapping to:
      /.../.cache/hf/models--org--repo/snapshots/<revision>
    """

    p = Path(source)
    if not p.exists() or not p.is_dir():
        return source

    # Already a concrete model directory.
    if (p / "config.json").exists():
        return str(p)

    snapshots_dir = p / "snapshots"
    refs_main = p / "refs" / "main"
    if not snapshots_dir.exists() or not snapshots_dir.is_dir():
        return source

    # Prefer the revision pointed by refs/main if available.
    if refs_main.exists():
        rev = refs_main.read_text(encoding="utf-8").strip()
        if rev:
            candidate = snapshots_dir / rev
            if (candidate / "config.json").exists():
                return str(candidate)

    # Fallback: choose the newest snapshot that has config.json.
    candidates = [d for d in snapshots_dir.iterdir() if d.is_dir() and (d / "config.json").exists()]
    if not candidates:
        return source
    candidates.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    return str(candidates[0])


def load_embedding_model(model_name: str, cache_dir: Path, miewid_model_source: str = "conservationxlabs/miewid-msv3") -> torch.nn.Module:
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

        resolved_source = _resolve_hf_local_source(miewid_model_source)
        logger.info(
            "Loading miewid model from HuggingFace/local source=%s (cached at %s)",
            resolved_source,
            cache_dir,
        )
        # trust_remote_code=True is needed by the model repo.
        model = AutoModel.from_pretrained(
            resolved_source,
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
