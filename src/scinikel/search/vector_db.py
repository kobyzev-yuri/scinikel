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
        self.image_collection = settings.qdrant_image_collection
        self.embedding_dim = settings.embedding_dimension
        self.image_embedding_dim = settings.image_embedding_dimension
        self._available = False
        self._image_available = False
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
            if self.image_collection not in names:
                self.client.create_collection(
                    collection_name=self.image_collection,
                    vectors_config=VectorParams(
                        size=self.image_embedding_dim,
                        distance=Distance.COSINE,
                    ),
                )
                self._image_available = True
            elif self.image_collection in names:
                self._image_available = True
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

    @property
    def image_available(self) -> bool:
        self._try_connect()
        return self._image_available and self.client is not None

    def upsert_image(
        self,
        image_id: str,
        embedding: list[float],
        payload: dict[str, Any],
    ) -> bool:
        if not self.image_available:
            return False
        if len(embedding) != self.image_embedding_dim:
            logger.error("Image embedding dim mismatch: %s vs %s", len(embedding), self.image_embedding_dim)
            return False
        try:
            from qdrant_client.models import PointStruct

            point_id = abs(hash(image_id)) % (2**63)
            point = PointStruct(
                id=point_id,
                vector=embedding,
                payload={
                    **payload,
                    "image_id": image_id,
                    "content_type": "image",
                },
            )
            self.client.upsert(collection_name=self.image_collection, points=[point])
            return True
        except Exception as exc:
            logger.error("Qdrant image upsert failed: %s", exc)
            return False

    def search_images(
        self,
        query_embedding: list[float],
        limit: int = 5,
        score_threshold: float = 0.0,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if not self.image_available:
            return []
        if len(query_embedding) != self.image_embedding_dim:
            return []
        try:
            qdrant_filter = _build_qdrant_filter(filters)
            response = self.client.query_points(
                collection_name=self.image_collection,
                query=query_embedding,
                limit=limit,
                score_threshold=score_threshold,
                query_filter=qdrant_filter,
            )
            results = []
            for point in response.points:
                payload = dict(point.payload or {})
                results.append(
                    {
                        "id": payload.get("image_id") or str(point.id),
                        "score": point.score,
                        "text": (
                            payload.get("librarian_annotation")
                            or payload.get("content")
                            or payload.get("abstract")
                            or payload.get("alt", "")
                            or payload.get("title", "")
                        ),
                        "metadata": payload,
                    }
                )
            return results
        except Exception as exc:
            logger.error("Qdrant image search failed: %s", exc)
            return []

    def upsert_chunk(
        self,
        chunk_id: str,
        embedding: list[float],
        payload: dict[str, Any],
    ) -> bool:
        """Индекс одного чанка — point id по chunk_id, doc_id в payload (как article_id в 3dtoday)."""
        if not self.available:
            return False
        try:
            from qdrant_client.models import PointStruct

            point_id = abs(hash(chunk_id)) % (2**63)
            doc_id = payload.get("doc_id") or chunk_id
            point = PointStruct(
                id=point_id,
                vector=embedding,
                payload={
                    **payload,
                    "chunk_id": chunk_id,
                    "doc_id": doc_id,
                    "original_id": doc_id,
                },
            )
            self.client.upsert(collection_name=self.collection, points=[point])
            return True
        except Exception as exc:
            logger.error("Qdrant chunk upsert failed: %s", exc)
            return False

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
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if not self.available:
            return []
        try:
            qdrant_filter = _build_qdrant_filter(filters)
            response = self.client.query_points(
                collection_name=self.collection,
                query=query_embedding,
                limit=limit,
                score_threshold=score_threshold,
                query_filter=qdrant_filter,
            )
            results = []
            for point in response.points:
                payload = dict(point.payload or {})
                chunk_id = payload.get("chunk_id")
                doc_id = payload.get("doc_id") or payload.get("original_id")
                results.append(
                    {
                        "id": chunk_id or doc_id or str(point.id),
                        "score": point.score,
                        "text": payload.get("text", ""),
                        "metadata": payload,
                    }
                )
            return results
        except Exception as exc:
            logger.error("Qdrant search failed: %s", exc)
            return []


    def scroll_doc_chunks(self, doc_id: str, *, limit: int = 256) -> list[dict[str, Any]]:
        """Все чанки документа из Qdrant — для восстановления BM25 после restart."""
        if not self.available:
            return []
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            doc_filter = Filter(
                must=[FieldCondition(key="doc_id", match=MatchValue(value=str(doc_id)))]
            )
            points, _ = self.client.scroll(
                collection_name=self.collection,
                scroll_filter=doc_filter,
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
            rows: list[dict[str, Any]] = []
            for point in points:
                payload = dict(point.payload or {})
                chunk_id = payload.get("chunk_id")
                if not chunk_id:
                    continue
                rows.append(
                    {
                        "id": chunk_id,
                        "text": payload.get("text", ""),
                        "metadata": payload,
                    }
                )
            return rows
        except Exception as exc:
            logger.error("Qdrant scroll failed for %s: %s", doc_id, exc)
            return []

    def count_doc_chunks(self, doc_id: str) -> int:
        return len(self.scroll_doc_chunks(doc_id))

    def count_doc_images(self, doc_id: str) -> int:
        return len(self.scroll_doc_images(doc_id))

    def scroll_doc_images(self, doc_id: str, *, limit: int = 128) -> list[dict[str, Any]]:
        """Все рисунки документа из image-коллекции Qdrant."""
        if not self.image_available:
            return []
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            doc_filter = Filter(
                must=[FieldCondition(key="doc_id", match=MatchValue(value=str(doc_id)))]
            )
            points, _ = self.client.scroll(
                collection_name=self.image_collection,
                scroll_filter=doc_filter,
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
            rows: list[dict[str, Any]] = []
            for point in points:
                payload = dict(point.payload or {})
                image_id = payload.get("image_id")
                if not image_id:
                    continue
                rows.append(
                    {
                        "id": image_id,
                        "text": payload.get("alt", "") or payload.get("title", ""),
                        "metadata": payload,
                    }
                )
            return rows
        except Exception as exc:
            logger.error("Qdrant image scroll failed for %s: %s", doc_id, exc)
            return []

    def get_image_payload(self, image_id: str) -> dict[str, Any] | None:
        if not self.image_available:
            return None
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            img_filter = Filter(
                must=[FieldCondition(key="image_id", match=MatchValue(value=str(image_id)))]
            )
            points, _ = self.client.scroll(
                collection_name=self.image_collection,
                scroll_filter=img_filter,
                limit=1,
                with_payload=True,
                with_vectors=False,
            )
            if not points:
                return None
            return dict(points[0].payload or {})
        except Exception as exc:
            logger.debug("Qdrant get_image_payload %s: %s", image_id, exc)
            return None

    def delete_doc_images(self, doc_id: str) -> int:
        """Удалить все рисунки документа перед переиндексацией."""
        if not self.image_available:
            return 0
        rows = self.scroll_doc_images(doc_id)
        if not rows:
            return 0
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            doc_filter = Filter(
                must=[FieldCondition(key="doc_id", match=MatchValue(value=str(doc_id)))]
            )
            self.client.delete(collection_name=self.image_collection, points_selector=doc_filter)
            return len(rows)
        except Exception as exc:
            logger.warning("Qdrant delete_doc_images %s: %s", doc_id, exc)
            return 0

    def delete_doc_chunks(self, doc_id: str) -> int:
        """Удалить все текстовые чанки документа из Qdrant перед переиндексацией."""
        if not self.available:
            return 0
        rows = self.scroll_doc_chunks(doc_id)
        if not rows:
            return 0
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            doc_filter = Filter(
                must=[FieldCondition(key="doc_id", match=MatchValue(value=str(doc_id)))]
            )
            self.client.delete(collection_name=self.collection, points_selector=doc_filter)
            return len(rows)
        except Exception as exc:
            logger.warning("Qdrant delete_doc_chunks %s: %s", doc_id, exc)
            return 0


def get_vector_db() -> VectorDBService:
    global _vector_db
    if _vector_db is None:
        _vector_db = VectorDBService()
    return _vector_db


def _build_qdrant_filter(filters: dict[str, Any] | None):
    """Qdrant payload filters — паттерн 3dtoday/vector_db.py."""
    if not filters:
        return None
    from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

    conditions = []
    if filters.get("doc_type"):
        conditions.append(
            FieldCondition(key="doc_type", match=MatchValue(value=filters["doc_type"]))
        )
    doc_ids = filters.get("doc_ids")
    if doc_ids:
        conditions.append(
            FieldCondition(key="doc_id", match=MatchAny(any=[str(x) for x in doc_ids]))
        )
    experiment_ids = filters.get("experiment_ids")
    if experiment_ids:
        conditions.append(
            FieldCondition(
                key="experiment_id",
                match=MatchAny(any=[str(x) for x in experiment_ids]),
            )
        )
    return Filter(must=conditions) if conditions else None
