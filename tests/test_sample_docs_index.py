"""Auto-index demo PDFs (GIAB) for BM25 after API restart."""

from pathlib import Path

import pytest

from scinikel.search.index import DocumentIndex
from scinikel.search.sample_docs import SAMPLE_DOC_PDFS

GIAB = SAMPLE_DOC_PDFS.get("doc-giab-ni-cu-flotation-water")
DOC_ID = "doc-giab-ni-cu-flotation-water"


@pytest.mark.skipif(not GIAB or not GIAB.exists(), reason="GIAB sample PDF missing")
def test_ensure_doc_indexed_from_sample_pdf():
    idx = DocumentIndex(enable_vector=False)
    assert not idx.has_doc_chunks(DOC_ID)
    assert idx.ensure_doc_indexed(DOC_ID)
    assert idx.doc_chunk_count(DOC_ID) >= 20


@pytest.mark.skipif(not GIAB or not GIAB.exists(), reason="GIAB sample PDF missing")
def test_document_media_after_ensure():
    from scinikel.graph.networkx_store import NetworkXGraphStore
    from scinikel.ingest.loader import ingest_seed_data
    from scinikel.query.engine import HybridQueryEngine

    idx = DocumentIndex(enable_vector=False)
    graph = NetworkXGraphStore()
    ingest_seed_data(graph, Path(__file__).resolve().parents[1] / "data" / "seed")
    engine = HybridQueryEngine(graph, idx)

    q = (
        "doc-giab-ni-cu-flotation-water: какие графики и таблицы показывают "
        "влияние ионов жёсткости воды на флотацию?"
    )
    result = engine.execute(q)
    assert result.sources, "ensure_doc_indexed should load sample on query"
    assert result.sources[0]["id"] == DOC_ID
