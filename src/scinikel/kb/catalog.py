"""Каталог документов KB: seed, samples, статус индекса."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scinikel.config import SEED_DIR
from scinikel.search.index import DocumentIndex
from scinikel.search.sample_docs import SAMPLE_DOC_IMAGE_EXPECTED, SAMPLE_DOC_META, SAMPLE_DOC_PDFS

_DOC_TYPE_LABELS = {
    "internal_report": "отчёт",
    "report": "отчёт",
    "article": "статья",
    "protocol": "протокол",
}


def _load_seed_documents() -> list[dict[str, Any]]:
    path = SEED_DIR / "documents.json"
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def list_reindexable_doc_ids() -> list[str]:
    """doc_id, которые можно переиндексировать из seed или sample PDF."""
    ids: list[str] = []
    for row in _load_seed_documents():
        if row.get("id"):
            ids.append(row["id"])
    for doc_id, pdf_path in SAMPLE_DOC_PDFS.items():
        if pdf_path.is_file() and doc_id not in ids:
            ids.append(doc_id)
    return ids


def seed_document_text(doc_id: str) -> tuple[str, dict[str, Any]] | None:
    """Текст и метаданные seed-документа для переиндексации."""
    for row in _load_seed_documents():
        if row.get("id") == doc_id:
            meta = {
                "title": row.get("title") or doc_id,
                "doc_type": row.get("doc_type", "report"),
                "year": row.get("year"),
            }
            text = row.get("text") or row.get("abstract") or ""
            return text, meta
    return None


def _qdrant_chunk_count(doc_id: str) -> int | None:
    try:
        from scinikel.search.vector_db import get_vector_db

        vdb = get_vector_db()
        if vdb.available:
            return vdb.count_doc_chunks(doc_id)
    except Exception:
        pass
    return None


def kb_document_catalog(doc_index: DocumentIndex) -> list[dict[str, Any]]:
    """Все известные документы KB со статусом чанков и рисунков."""
    entries: dict[str, dict[str, Any]] = {}

    for row in _load_seed_documents():
        doc_id = row["id"]
        entries[doc_id] = {
            "doc_id": doc_id,
            "title": row.get("title") or doc_id,
            "doc_type": row.get("doc_type", "report"),
            "doc_type_label": _DOC_TYPE_LABELS.get(row.get("doc_type", ""), row.get("doc_type", "")),
            "source": "seed",
            "has_pdf": False,
            "reindexable": True,
        }

    for doc_id, meta in SAMPLE_DOC_META.items():
        pdf_path = SAMPLE_DOC_PDFS.get(doc_id)
        entries[doc_id] = {
            "doc_id": doc_id,
            "title": meta.get("title") or doc_id,
            "doc_type": meta.get("doc_type", "report"),
            "doc_type_label": _DOC_TYPE_LABELS.get(meta.get("doc_type", ""), meta.get("doc_type", "")),
            "source": "sample",
            "has_pdf": bool(pdf_path and pdf_path.is_file()),
            "reindexable": bool(pdf_path and pdf_path.is_file()),
            "images_expected": SAMPLE_DOC_IMAGE_EXPECTED.get(doc_id, 0),
        }

    for row in doc_index._chunks:
        meta = row.get("metadata") or {}
        doc_id = meta.get("doc_id")
        if not doc_id or doc_id in entries:
            continue
        entries[doc_id] = {
            "doc_id": doc_id,
            "title": meta.get("title") or doc_id,
            "doc_type": meta.get("doc_type", "report"),
            "doc_type_label": _DOC_TYPE_LABELS.get(meta.get("doc_type", ""), "загружен"),
            "source": "ingest",
            "has_pdf": False,
            "reindexable": False,
        }

    out: list[dict[str, Any]] = []
    for doc_id, ent in entries.items():
        chunk_count = doc_index.doc_chunk_count(doc_id)
        qdrant_chunks = _qdrant_chunk_count(doc_id)
        ent["chunk_count"] = chunk_count
        ent["qdrant_chunk_count"] = qdrant_chunks
        ent["image_count"] = doc_index.doc_image_count(doc_id)
        ent["indexed"] = doc_index.has_doc_chunks(doc_id)
        ent["vectors_synced"] = (
            qdrant_chunks is not None and chunk_count > 0 and qdrant_chunks >= chunk_count
        )
        ent["deletable"] = ent["source"] == "ingest"
        out.append(ent)

    out.sort(key=lambda x: (0 if x["source"] == "sample" else 1 if x["source"] == "seed" else 2, x["title"]))
    return out
