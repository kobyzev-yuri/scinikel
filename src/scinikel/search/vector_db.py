"""Qdrant vector store — адаптация 3dtoday/vector_db.py."""

from __future__ import annotations

import logging
from typing import Any

from scinikel.config import settings

logger = logging.getLogger(__name__)

_vector_db: "VectorDBService | None" = None


class VectorDBService:
    def __init__(self) -> None:
        self.client = None
        self.collection = settings.qdrant_collection
        self.embedding_dim = settings.embedding_dimension
        self._available = False
        self._initialized = False

    def _try_connect(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams

            self.client = QdrantClient(
                host=settings.qdrant_host,
                port=settings.qdrant_port,
            )
            self.client.get_collections()
            names = [c.name for c in self.client.get_collections().collections]
            if self.collection not in names:
                self.client.create_collection(
                    collection_name=self.collection,
                    vectors_config=VectorParams(size=self.embedding_dim, distance=Distance.COSINE),
                )
            self._available = True
            logger.info(
                "Qdrant connected: %s:%s collection=%s",
                settings.qdrant_host,
                settings.qdrant_port,
                self.collection,
            )
        except Exception as exc:
            logger.warning("Qdrant unavailable: %s", exc)
            self.client = None
            self._available = False

    @property
    def available(self) -> bool:
        self._try_connect()
        return self._available and self.client is not None

    def upsert_document(
        self,
        doc_id: str,
        embedding: list[float],
        payload: dict[str, Any],
    ) -> bool:
        if not self.available:
            return False
        try:
            from qdrant_client.models import PointStruct

            point_id = abs(hash(doc_id)) % (2**63)
            point = PointStruct(
                id=point_id,
                vector=embedding,
                payload={**payload, "doc_id": doc_id, "original_id": doc_id},
            )
            self.client.upsert(collection_name=self.collection, points=[point])
            return True
        except Exception as exc:
            logger.error("Qdrant upsert failed: %s", exc)
            return False

    def search(
        self,
        query_embedding: list[float],
        limit: int = 5,
        score_threshold: float = 0.0,
    ) -> list[dict[str, Any]]:
        if not self.available:
            return []
        try:
            response = self.client.query_points(
                collection_name=self.collection,
                query=query_embedding,
                limit=limit,
                score_threshold=score_threshold,
            )
            results = []
            for point in response.points:
                payload = dict(point.payload or {})
                results.append(
                    {
                        "id": payload.get("doc_id") or payload.get("original_id"),
                        "score": point.score,
                        "text": payload.get("text", ""),
                        "metadata": payload,
                    }
                )
            return results
        except Exception as exc:
            logger.error("Qdrant search failed: %s", exc)
            return []


def get_vector_db() -> VectorDBService:
    global _vector_db
    if _vector_db is None:
        _vector_db = VectorDBService()
    return _vector_db
