"""Tests for KB catalog and reindex."""

from pathlib import Path

from scinikel.kb.catalog import kb_document_catalog, seed_document_text
from scinikel.search.index import DocumentIndex


def test_seed_document_text():
    seed_path = Path(__file__).resolve().parents[1] / "data" / "seed" / "documents.json"
    if not seed_path.is_file():
        return
    row = seed_document_text("DOC-2024-112")
    assert row is not None
    text, meta = row
    assert "EXP-2024-017" in text
    assert meta["title"]


def test_kb_document_catalog_includes_seed_and_sample():
    idx = DocumentIndex(enable_vector=False)
    idx.index_documents([], {})
    from scinikel.search.sample_docs import SAMPLE_DOC_PDFS

    catalog = kb_document_catalog(idx)
    ids = {row["doc_id"] for row in catalog}
    assert "DOC-2024-112" in ids
    for doc_id in SAMPLE_DOC_PDFS:
        assert doc_id in ids


def test_reindex_document_from_seed():
    idx = DocumentIndex(enable_vector=False)
    result = idx.reindex_document("DOC-2024-112")
    assert result["source"] == "seed"
    assert result["chunks_indexed"] > 0
    assert idx.has_doc_chunks("DOC-2024-112")


def test_reindex_all_documents():
    idx = DocumentIndex(enable_vector=False)
    result = idx.reindex_all_documents()
    assert result["chunk_count"] > 0
    assert len(result["documents"]) >= 1
    errors = [d for d in result["documents"] if d.get("error")]
    assert not errors


def test_remove_document_from_index():
    idx = DocumentIndex(enable_vector=False)
    idx.reindex_document("DOC-2024-112")
    assert idx.has_doc_chunks("DOC-2024-112")
    removed = idx.remove_document_from_index("DOC-2024-112")
    assert removed["chunks_removed"] > 0
    assert not idx.has_doc_chunks("DOC-2024-112")


def test_list_reindexable_doc_ids():
    from scinikel.kb.catalog import list_reindexable_doc_ids

    ids = list_reindexable_doc_ids()
    assert "DOC-2024-112" in ids
