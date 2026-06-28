"""Эмбеддинги — паттерн из 3dtoday/rag_service.py (multilingual-e5-base)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from scinikel.config import settings

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

_embedding_service: "EmbeddingService | None" = None


class EmbeddingService:
    def __init__(self) -> None:
        self._model: SentenceTransformer | None = None
        self._available = False
        self._initialized = False

    def _ensure_model(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        try:
            import torch
            from sentence_transformers import SentenceTransformer

            device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info("Loading embedding model %s on %s", settings.hf_model_name, device)
            self._model = SentenceTransformer(settings.hf_model_name, device=device)
            self._available = True
        except Exception as exc:
            logger.warning("Embedding model unavailable: %s", exc)
            self._model = None
            self._available = False

    @property
    def available(self) -> bool:
        self._ensure_model()
        return self._available and self._model is not None

    @property
    def dimension(self) -> int:
        return settings.embedding_dimension

    def encode(self, text: str) -> list[float]:
        self._ensure_model()
        if not self._model:
            raise RuntimeError("Embedding model not loaded")
        prefixed = f"passage: {text}" if not text.startswith(("query:", "passage:")) else text
        vector = self._model.encode(prefixed, normalize_embeddings=True)
        return vector.tolist()

    def encode_query(self, query: str) -> list[float]:
        self._ensure_model()
        if not self._model:
            raise RuntimeError("Embedding model not loaded")
        prefixed = query if query.startswith("query:") else f"query: {query}"
        vector = self._model.encode(prefixed, normalize_embeddings=True)
        return vector.tolist()


def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
