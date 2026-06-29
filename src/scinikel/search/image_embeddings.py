"""OpenCLIP embeddings для поиска по изображениям (паттерн 3dtoday/openclip_embeddings.py)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from scinikel.config import settings

logger = logging.getLogger(__name__)

OPENCLIP_AVAILABLE = False
_torch = None
_open_clip = None
_Image = None

try:
    import torch as _torch
    import open_clip as _open_clip
    from PIL import Image as _Image

    OPENCLIP_AVAILABLE = True
except ImportError:
    pass


class OpenCLIPEmbeddings:
    def __init__(
        self,
        model_name: str | None = None,
        pretrained: str | None = None,
        device: str | None = None,
    ) -> None:
        if not OPENCLIP_AVAILABLE:
            raise ImportError("Install multimodal extras: pip install -e '.[multimodal]'")

        self.model_name = model_name or settings.openclip_model
        self.pretrained = pretrained or settings.openclip_pretrained
        self.device = device or ("cuda" if _torch.cuda.is_available() else "cpu")

        self.model, _, self.preprocess = _open_clip.create_model_and_transforms(
            self.model_name,
            pretrained=self.pretrained,
            device=self.device,
        )
        self.tokenizer = _open_clip.get_tokenizer(self.model_name)
        self.model.eval()

        with _torch.no_grad():
            dummy_img = _torch.zeros(1, 3, 224, 224).to(self.device)
            dummy_txt = self.tokenizer(["test"]).to(self.device)
            self.embedding_dim = int(self.model.encode_image(dummy_img).shape[1])

        logger.info(
            "OpenCLIP ready: %s/%s dim=%s device=%s",
            self.model_name,
            self.pretrained,
            self.embedding_dim,
            self.device,
        )

    def encode_image(self, image_path: str | Path, *, normalize: bool = True) -> list[float]:
        path = Path(image_path)
        if not path.exists():
            return [0.0] * self.embedding_dim
        image = _Image.open(path).convert("RGB")
        tensor = self.preprocess(image).unsqueeze(0).to(self.device)
        with _torch.no_grad():
            emb = self.model.encode_image(tensor)
            if normalize:
                emb = emb / emb.norm(dim=-1, keepdim=True)
        return emb.cpu().numpy().tolist()[0]

    def encode_text(self, text: str, *, normalize: bool = True) -> list[float]:
        if not text.strip():
            return [0.0] * self.embedding_dim
        tokens = self.tokenizer([text]).to(self.device)
        with _torch.no_grad():
            emb = self.model.encode_text(tokens)
            if normalize:
                emb = emb / emb.norm(dim=-1, keepdim=True)
        return emb.cpu().numpy().tolist()[0]


_clip: OpenCLIPEmbeddings | None = None


def get_openclip_embeddings() -> OpenCLIPEmbeddings | None:
    global _clip
    if not settings.clip_enabled:
        return None
    if not OPENCLIP_AVAILABLE:
        return None
    if _clip is None:
        try:
            _clip = OpenCLIPEmbeddings()
        except Exception as exc:
            logger.warning("OpenCLIP init failed: %s", exc)
            return None
    return _clip


def clip_status() -> dict[str, Any]:
    if not settings.clip_enabled:
        return {"available": False, "message": "CLIP disabled (CLIP_ENABLED=false)"}
    if not OPENCLIP_AVAILABLE:
        return {"available": False, "message": "open-clip-torch not installed"}
    clip = get_openclip_embeddings()
    if clip is None:
        return {"available": False, "message": "OpenCLIP failed to load"}
    return {
        "available": True,
        "model": clip.model_name,
        "pretrained": clip.pretrained,
        "dimension": clip.embedding_dim,
        "device": clip.device,
        "collection": settings.qdrant_image_collection,
    }
