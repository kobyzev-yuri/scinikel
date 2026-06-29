"""Semantic search: Qdrant + e5 по чанкам (3dtoday pattern) + BM25 fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scinikel.models.entities import Document, Entity
from scinikel.search.bm25 import BM25Index
from scinikel.search.chunking import TextChunk, chunk_text
from scinikel.search.dedup import dedup_search_results
from scinikel.search.fusion import reciprocal_rank_fusion
from scinikel.search.metadata_boost import apply_metadata_boost
from scinikel.search.rerank import rerank_enabled, rerank_results

logger = logging.getLogger(__name__)


def _hard_search_filters(filters: dict | None) -> dict | None:
    """Жёсткие Qdrant-фильтры: только doc_ids/doc_type. experiment_ids — только boost."""
    if not filters:
        return None
    hard: dict = {}
    if filters.get("doc_ids"):
        hard["doc_ids"] = filters["doc_ids"]
    if filters.get("doc_type"):
        hard["doc_type"] = filters["doc_type"]
    return hard or None


@dataclass
class SearchHit:
    id: str
    text: str
    score: float
    metadata: dict


class DocumentIndex:
    """
    Индекс документов по чанкам: Qdrant + multilingual-e5.
    Fallback: BM25 in-memory (этап 1 roadmap), не naive overlap.
    """

    def __init__(self, *, enable_vector: bool = True) -> None:
        self._chunks: list[dict] = []
        self._bm25 = BM25Index()
        self._embeddings = None
        self._vector_db = None
        self._enable_vector = enable_vector
        self._init_backends()

    def _init_backends(self) -> None:
        if not self._enable_vector:
            logger.info("Vector search disabled by runtime config (BM25/keyword only)")
            return
        try:
            from scinikel.search.embeddings import get_embedding_service
            from scinikel.search.vector_db import get_vector_db

            self._embeddings = get_embedding_service()
            self._vector_db = get_vector_db()
            if not (self._embeddings.available and self._vector_db.available):
                logger.info("Vector search degraded to BM25 fallback")
        except Exception as exc:
            logger.warning("Vector backends init failed: %s", exc)

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    @property
    def backend(self) -> str:
        from scinikel.services.llm_runtime import (
            SEARCH_MODE_HYBRID,
            SEARCH_MODE_VECTOR,
            get_search_mode,
        )

        mode = get_search_mode()
        if mode == SEARCH_MODE_HYBRID and self._vector_ok() and self._chunks:
            return "hybrid+rrf"
        if mode == SEARCH_MODE_VECTOR and self._vector_ok():
            return "qdrant+e5+chunks"
        if self._chunks:
            return "bm25"
        return "empty"

    def backends_active(self) -> list[str]:
        from scinikel.services.llm_runtime import get_search_mode

        active = ["bm25"] if self._chunks else []
        if self._vector_ok():
            active.append("qdrant+e5")
        mode = get_search_mode()
        if mode == "hybrid" and len(active) == 2:
            active.append("rrf")
        return active

    def _vector_ok(self) -> bool:
        return bool(
            self._embeddings
            and self._vector_db
            and self._embeddings.available
            and self._vector_db.available
        )

    @staticmethod
    def _chunk_to_store(chunk: TextChunk) -> dict:
        # Паттерн 3dtoday/article_indexer: title + content для поиска
        index_text = f"{chunk.title}\n\n{chunk.text}" if chunk.title else chunk.text
        meta = {
            "text": chunk.text,
            "title": chunk.title,
            "doc_id": chunk.doc_id,
            "chunk_id": chunk.chunk_id,
            "chunk_index": chunk.chunk_index,
            "page": chunk.page,
            "doc_type": chunk.doc_type,
            "experiment_ids": chunk.experiment_ids,
            "experiment_id": chunk.experiment_ids[0] if chunk.experiment_ids else None,
        }
        return {
            "id": chunk.chunk_id,
            "text": chunk.text,
            "index_text": index_text,
            "metadata": meta,
        }

    def _remove_doc_chunks(self, doc_id: str) -> None:
        self._chunks = [c for c in self._chunks if (c.get("metadata") or {}).get("doc_id") != doc_id]

    def _rebuild_bm25(self) -> None:
        self._bm25.rebuild(self._chunks)

    def _upsert_chunk_vector(self, store_row: dict) -> bool:
        if not self._vector_ok():
            return False
        meta = store_row["metadata"]
        chunk_id = meta["chunk_id"]
        try:
            emb = self._embeddings.encode(store_row.get("index_text") or store_row["text"])
            return self._vector_db.upsert_chunk(chunk_id, emb, meta)
        except Exception as exc:
            logger.warning("Chunk vector index failed for %s: %s", chunk_id, exc)
            return False

    def _index_chunk_list(self, chunks: list[TextChunk]) -> int:
        if not chunks:
            return 0
        indexed_vectors = 0
        for chunk in chunks:
            row = self._chunk_to_store(chunk)
            self._chunks.append(row)
            if self._upsert_chunk_vector(row):
                indexed_vectors += 1
        self._rebuild_bm25()
        return indexed_vectors or len(chunks)

    def index_documents(self, documents: list[Document], texts: dict[str, str]) -> int:
        if not documents:
            return 0

        self._chunks = []
        total = 0
        for doc in documents:
            text = texts.get(doc.id) or doc.description or doc.name
            meta = {
                "title": doc.name,
                "doc_type": doc.attributes.get("doc_type", ""),
            }
            chunks = chunk_text(doc.id, text, metadata=meta)
            total += self._index_chunk_list(chunks)

        return total

    def index_text(self, doc_id: str, text: str, metadata: dict | None = None) -> bool:
        self._remove_doc_chunks(doc_id)
        meta = {"title": metadata.get("title", doc_id) if metadata else doc_id}
        if metadata:
            meta.update(metadata)
        chunks = chunk_text(doc_id, text, metadata=meta)
        return self._index_chunk_list(chunks) > 0

    def has_doc_chunks(self, doc_id: str) -> bool:
        return any((c.get("metadata") or {}).get("doc_id") == doc_id for c in self._chunks)

    def doc_chunk_count(self, doc_id: str) -> int:
        return sum(1 for c in self._chunks if (c.get("metadata") or {}).get("doc_id") == doc_id)

    def rehydrate_doc_from_qdrant(self, doc_id: str) -> int:
        """Восстановить in-memory BM25 из Qdrant (после restart API)."""
        if not self._vector_ok() or self.has_doc_chunks(doc_id):
            return 0
        rows = self._vector_db.scroll_doc_chunks(doc_id)
        if not rows:
            return 0
        added = 0
        for row in rows:
            meta = dict(row.get("metadata") or {})
            meta.setdefault("doc_id", doc_id)
            chunk_id = meta.get("chunk_id") or row["id"]
            index_text = meta.get("title")
            text = row.get("text") or meta.get("text", "")
            if index_text:
                index_text = f"{index_text}\n\n{text}"
            else:
                index_text = text
            self._chunks.append(
                {
                    "id": chunk_id,
                    "text": text,
                    "index_text": index_text,
                    "metadata": meta,
                }
            )
            added += 1
        if added:
            self._rebuild_bm25()
            logger.info("Rehydrated %s chunks for %s from Qdrant", added, doc_id)
        return added

    def ensure_doc_indexed(self, doc_id: str) -> bool:
        """BM25: Qdrant rehydrate или демо-PDF с диска (без блокирующего CLIP/Vision)."""
        if self.has_doc_chunks(doc_id):
            return True
        if self.rehydrate_doc_from_qdrant(doc_id) > 0:
            return True
        from scinikel.search.sample_docs import SAMPLE_DOC_META, SAMPLE_DOC_PDFS

        pdf_path = SAMPLE_DOC_PDFS.get(doc_id)
        if not pdf_path or not pdf_path.exists():
            return False
        try:
            from scinikel.ingest.pdf_parser import parse_pdf
            from scinikel.search.pdf_images import persist_pdf_images

            parsed = parse_pdf(pdf_path, max_pages=50)
            meta = dict(SAMPLE_DOC_META.get(doc_id) or {})
            meta.setdefault("title", pdf_path.stem)
            meta.setdefault("doc_type", "report")
            persist_pdf_images(doc_id, parsed.get("images") or [])
            return self.index_text(doc_id, parsed["content"], meta)
        except Exception as exc:
            logger.warning("Sample PDF index failed for %s: %s", doc_id, exc)
            return False

    def doc_image_count(self, doc_id: str) -> int:
        try:
            from scinikel.search.vector_db import get_vector_db

            vdb = get_vector_db()
            if vdb.image_available:
                return vdb.count_doc_images(doc_id)
        except Exception:
            pass
        from scinikel.search.pdf_images import image_cache_dir

        cache = image_cache_dir(doc_id)
        if cache.exists():
            return len(list(cache.glob(f"{doc_id}-p*")))
        return 0

    def ensure_doc_images_indexed(self, doc_id: str, *, analyze_images: bool = False) -> int:
        """CLIP-индекс рисунков демо-PDF. Vision — только при analyze_images=True (ingest API)."""
        from scinikel.search.pdf_images import has_stale_image_ids

        try:
            from scinikel.search.vector_db import get_vector_db

            vdb = get_vector_db()
            if vdb.image_available:
                n = vdb.count_doc_images(doc_id)
                if n > 0 and not has_stale_image_ids(doc_id):
                    return n
                if n > 0 and has_stale_image_ids(doc_id):
                    vdb.delete_doc_images(doc_id)
        except Exception:
            pass
        from scinikel.search.sample_docs import SAMPLE_DOC_META, SAMPLE_DOC_PDFS

        pdf_path = SAMPLE_DOC_PDFS.get(doc_id)
        if not pdf_path or not pdf_path.exists():
            return 0
        try:
            from scinikel.ingest.pdf_parser import parse_pdf
            from scinikel.search.pdf_images import analyze_pdf_images, persist_pdf_images

            parsed = parse_pdf(pdf_path, max_pages=50)
            meta = dict(SAMPLE_DOC_META.get(doc_id) or {})
            title = meta.get("title") or pdf_path.stem
            persist_pdf_images(doc_id, parsed.get("images") or [])
            image_analyses = None
            if analyze_images:
                image_analysis = analyze_pdf_images(parsed.get("images") or [])
                image_analyses = (image_analysis or {}).get("image_analyses")
            return self._index_parsed_images(
                doc_id,
                parsed,
                title,
                analyze_images=analyze_images,
                image_analyses=image_analyses,
            )
        except Exception as exc:
            logger.warning("Sample PDF images failed for %s: %s", doc_id, exc)
            return 0

    def _index_parsed_images(
        self,
        doc_id: str,
        parsed: dict,
        title: str,
        *,
        analyze_images: bool = False,
        image_analyses: list[dict[str, Any]] | None = None,
    ) -> int:
        images = parsed.get("images") or []
        if not images:
            return 0
        from scinikel.search.pdf_images import index_pdf_images

        return index_pdf_images(
            self,
            doc_id,
            images,
            title,
            analyze_images=analyze_images,
            image_analyses=image_analyses,
        )

    def index_image(
        self,
        image_id: str,
        image_path: str | Path,
        metadata: dict | None = None,
    ) -> bool:
        """CLIP-индекс изображения в Qdrant (этап 6a, паттерн 3dtoday)."""
        try:
            from scinikel.search.image_embeddings import get_openclip_embeddings
            from scinikel.search.vector_db import get_vector_db

            clip = get_openclip_embeddings()
            vdb = get_vector_db()
            if clip is None or not vdb.image_available:
                return False
            emb = clip.encode_image(str(image_path))
            meta = dict(metadata or {})
            meta.setdefault("alt", meta.get("title", image_id))
            return vdb.upsert_image(image_id, emb, meta)
        except Exception as exc:
            logger.warning("Image index failed for %s: %s", image_id, exc)
            return False

    def search_images(
        self, query: str, limit: int = 5, *, doc_id: str | None = None
    ) -> list[SearchHit]:
        try:
            from scinikel.search.image_embeddings import get_openclip_embeddings
            from scinikel.search.vector_db import get_vector_db

            clip = get_openclip_embeddings()
            vdb = get_vector_db()
            if clip is None or not vdb.image_available:
                return []
            emb = clip.encode_text(query)
            filters = {"doc_ids": [doc_id]} if doc_id else None
            fetch = limit * 3 if doc_id else limit
            rows = vdb.search_images(emb, limit=fetch, filters=filters)
            if doc_id:
                rows = [r for r in rows if (r.get("metadata") or {}).get("doc_id") == doc_id]
            rows = rows[:limit]
            return [
                SearchHit(
                    id=row["id"],
                    text=row.get("text", ""),
                    score=float(row.get("score", 0)),
                    metadata={k: v for k, v in (row.get("metadata") or {}).items()},
                )
                for row in rows
            ]
        except Exception as exc:
            logger.warning("Image search failed: %s", exc)
            return []

    def search(
        self,
        query: str,
        limit: int = 5,
        *,
        filters: dict | None = None,
        use_rerank: bool | None = None,
        retrieve_k: int = 20,
        collapse_by_doc: bool | None = None,
    ) -> list[SearchHit]:
        hard_filters = _hard_search_filters(filters)
        raw = self._search_raw(query, retrieve_k=retrieve_k, filters=hard_filters)
        if collapse_by_doc is None:
            doc_ids = (filters or {}).get("doc_ids") or []
            # Один PDF — нужны несколько чанков, не один «лучший» на весь doc_id
            collapse_by_doc = len(doc_ids) != 1
        raw = dedup_search_results(raw, collapse_by_doc=collapse_by_doc)
        raw = apply_metadata_boost(raw, filters)
        if use_rerank if use_rerank is not None else rerank_enabled():
            raw = rerank_results(query, raw, top_k=limit)
        else:
            raw = raw[:limit]
        return [
            SearchHit(
                id=row["id"],
                text=row.get("text") or (row.get("metadata") or {}).get("text", ""),
                score=float(row.get("score", 0)),
                metadata={k: v for k, v in (row.get("metadata") or row).items() if k != "text"},
            )
            for row in raw
        ]

    def _search_raw(
        self,
        query: str,
        *,
        retrieve_k: int,
        filters: dict | None,
    ) -> list[dict]:
        from scinikel.services.llm_runtime import (
            SEARCH_MODE_HYBRID,
            SEARCH_MODE_KEYWORD,
            SEARCH_MODE_VECTOR,
            get_search_mode,
        )

        mode = get_search_mode()
        bm25_rows = self._bm25.search(query, limit=retrieve_k)

        if mode == SEARCH_MODE_KEYWORD:
            return bm25_rows

        vector_rows: list[dict] = []
        if self._vector_ok():
            try:
                emb = self._embeddings.encode_query(query)
                vector_rows = self._vector_db.search(
                    emb,
                    limit=retrieve_k,
                    score_threshold=0.0,
                    filters=filters,
                )
                for row in vector_rows:
                    row.setdefault("backend", "qdrant+e5")
            except Exception as exc:
                logger.warning("Vector search failed: %s", exc)

        if mode == SEARCH_MODE_VECTOR:
            return vector_rows or bm25_rows

        if mode == SEARCH_MODE_HYBRID:
            if vector_rows:
                return reciprocal_rank_fusion(
                    [bm25_rows, vector_rows],
                    top_k=retrieve_k,
                )
            return bm25_rows

        return bm25_rows


def entity_to_snippet(entity: Entity) -> str:
    parts = [entity.name]
    if entity.description:
        parts.append(entity.description)
    for key, val in entity.attributes.items():
        if val:
            parts.append(f"{key}: {val}")
    return " | ".join(parts)
