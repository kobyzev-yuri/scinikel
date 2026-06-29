"""Tests for 3dtoday-ported search helpers."""

from scinikel.search.dedup import dedup_search_results
from scinikel.search.metadata_boost import apply_metadata_boost


"""Tests for 3dtoday-ported search helpers."""

import pytest

from scinikel.search.dedup import dedup_search_results
from scinikel.search.index import DocumentIndex
from scinikel.search.metadata_boost import apply_metadata_boost


def test_dedup_collapses_chunks_per_doc():
    rows = [
        {"id": "doc-a#c0", "score": 0.9, "metadata": {"doc_id": "doc-a", "chunk_id": "doc-a#c0"}},
        {"id": "doc-a#c1", "score": 0.8, "metadata": {"doc_id": "doc-a", "chunk_id": "doc-a#c1"}},
        {"id": "doc-b#c0", "score": 0.7, "metadata": {"doc_id": "doc-b", "chunk_id": "doc-b#c0"}},
    ]
    out = dedup_search_results(rows)
    assert len(out) == 2
    assert out[0]["id"] == "doc-a#c0"
    assert out[1]["id"] == "doc-b#c0"


def test_single_doc_search_returns_multiple_chunks():
    from scinikel.ingest.pdf_parser import parse_pdf
    from scinikel.search.sample_docs import SAMPLE_DOC_PDFS

    giab = SAMPLE_DOC_PDFS["doc-giab-ni-cu-flotation-water"]
    if not giab.exists():
        pytest.skip("GIAB sample PDF missing")

    idx = DocumentIndex(enable_vector=False)
    idx.index_text(
        "doc-giab-ni-cu-flotation-water",
        parse_pdf(giab, max_pages=20)["content"],
        {"title": "giab", "doc_type": "report"},
    )
    hits = idx.search(
        "ионы жесткости кальция таблица",
        limit=5,
        filters={"doc_ids": ["doc-giab-ni-cu-flotation-water"]},
    )
    chunk_ids = {h.metadata.get("chunk_id") for h in hits}
    assert len(chunk_ids) >= 3
    assert any(cid and "c30" in cid for cid in chunk_ids)


def test_metadata_boost_experiment_id():
    rows = [
        {"id": "1", "score": 0.5, "metadata": {"experiment_id": "EXP-2024-031"}},
        {"id": "2", "score": 0.6, "metadata": {"experiment_id": "EXP-2024-028"}},
    ]
    boosted = apply_metadata_boost(rows, {"experiment_ids": ["EXP-2024-031"]})
    assert boosted[0]["id"] == "1"
    assert boosted[0]["score"] > 0.5
    assert boosted[0].get("boost_applied", 0) > 0


def test_hard_search_filters_excludes_experiment_ids():
    from scinikel.search.index import _hard_search_filters

    assert _hard_search_filters({"experiment_ids": ["EXP-1"], "doc_ids": ["doc-a"]}) == {
        "doc_ids": ["doc-a"]
    }
    assert _hard_search_filters({"experiment_ids": ["EXP-1"]}) is None
