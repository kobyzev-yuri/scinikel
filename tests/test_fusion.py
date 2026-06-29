"""Tests for RRF fusion."""

from scinikel.search.fusion import reciprocal_rank_fusion


def _row(chunk_id: str, score: float, backend: str) -> dict:
    return {
        "id": chunk_id,
        "score": score,
        "text": f"text-{chunk_id}",
        "metadata": {"chunk_id": chunk_id, "doc_id": "doc-1"},
        "backend": backend,
    }


def test_rrf_merges_two_lists():
    bm25 = [_row("a", 10.0, "bm25"), _row("b", 5.0, "bm25")]
    dense = [_row("b", 0.92, "qdrant+e5"), _row("c", 0.88, "qdrant+e5")]
    fused = reciprocal_rank_fusion([bm25, dense], top_k=3)
    ids = [r["metadata"]["chunk_id"] for r in fused]
    assert ids[0] == "b"
    assert fused[0]["backend"] == "rrf"
    assert "bm25" in fused[0]["metadata"]["fusion_sources"]


def test_rrf_single_list_passthrough():
    rows = [_row("x", 1.0, "bm25")]
    assert reciprocal_rank_fusion([rows]) == rows
