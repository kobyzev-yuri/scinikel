"""Semantic search: Qdrant + multilingual-e5 (3dtoday pattern) + keyword fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from scinikel.models.entities import Document, Entity

logger = logging.getLogger(__name__)


@dataclass
class SearchHit:
    id: str
    text: str
    score: float
    metadata: dict


class DocumentIndex:
    """
    Qdrant + e5 embeddings для документов.
    При недоступности Qdrant/модели — keyword fallback (как раньше с ChromaDB).
    """

    def __init__(self) -> None:
        self._fallback: list[dict] = []
        self._embeddings = None
        self._vector_db = None
        self._init_backends()

    def _init_backends(self) -> None:
        try:
            from scinikel.search.embeddings import get_embedding_service
            from scinikel.search.vector_db import get_vector_db

            self._embeddings = get_embedding_service()
            self._vector_db = get_vector_db()
            if not (self._embeddings.available and self._vector_db.available):
                logger.info("Vector search degraded to keyword fallback")
        except Exception as exc:
            logger.warning("Vector backends init failed: %s", exc)

    @property
    def backend(self) -> str:
        if (
            self._embeddings
            and self._vector_db
            and self._vector_db.available
            and self._embeddings.available
        ):
            return "qdrant+e5"
        return "keyword"

    def index_documents(self, documents: list[Document], texts: dict[str, str]) -> int:
        if not documents:
            return 0

        payloads = []
        for doc in documents:
            text = texts.get(doc.id) or doc.description or doc.name
            meta = {
                "title": doc.name,
                "doc_type": doc.attributes.get("doc_type", ""),
                "text": text,
            }
            payloads.append({"id": doc.id, "text": text, "metadata": meta})

        self._fallback = payloads
        indexed = 0

        if (
            self._embeddings
            and self._vector_db
            and self._embeddings.available
            and self._vector_db.available
        ):
            for item in payloads:
                try:
                    emb = self._embeddings.encode(item["text"])
                    if self._vector_db.upsert_document(item["id"], emb, item["metadata"]):
                        indexed += 1
                except Exception as exc:
                    logger.warning("Index failed for %s: %s", item["id"], exc)

        return indexed or len(payloads)

    def index_text(self, doc_id: str, text: str, metadata: dict | None = None) -> bool:
        meta = {"text": text, "title": metadata.get("title", doc_id) if metadata else doc_id}
        if metadata:
            meta.update(metadata)
        self._fallback.append({"id": doc_id, "text": text, "metadata": meta})

        if (
            self._embeddings
            and self._vector_db
            and self._embeddings.available
            and self._vector_db.available
        ):
            try:
                emb = self._embeddings.encode(text)
                return self._vector_db.upsert_document(doc_id, emb, meta)
            except Exception:
                return False
        return True

    def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        if (
            self._embeddings
            and self._vector_db
            and self._embeddings.available
            and self._vector_db.available
        ):
            try:
                emb = self._embeddings.encode_query(query)
                results = self._vector_db.search(emb, limit=limit)
                if results:
                    return [
                        SearchHit(
                            id=r["id"],
                            text=r.get("text") or r.get("metadata", {}).get("text", ""),
                            score=float(r.get("score", 0)),
                            metadata={k: v for k, v in r.get("metadata", {}).items() if k != "text"},
                        )
                        for r in results
                    ]
            except Exception as exc:
                logger.warning("Vector search failed: %s", exc)

        needle = query.lower()
        scored = []
        for item in self._fallback:
            text = item["text"].lower()
            score = sum(1 for word in needle.split() if word in text) / max(len(needle.split()), 1)
            if score > 0:
                scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            SearchHit(id=item["id"], text=item["text"], score=score, metadata=item["metadata"])
            for score, item in scored[:limit]
        ]


def entity_to_snippet(entity: Entity) -> str:
    parts = [entity.name]
    if entity.description:
        parts.append(entity.description)
    for key, val in entity.attributes.items():
        if val:
            parts.append(f"{key}: {val}")
    return " | ".join(parts)
