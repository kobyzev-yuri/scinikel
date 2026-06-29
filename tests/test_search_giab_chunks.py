"""BM25 chunk search on real GIAB PDF (offline, без API)."""

from pathlib import Path

from scinikel.ingest.pdf_parser import parse_pdf
from scinikel.search.index import DocumentIndex

GIAB = Path(__file__).resolve().parents[1] / "data" / "samples" / "giab-ni-cu-flotation-water.pdf"
DOC_ID = "doc-giab-ni-cu-flotation-water"


def test_giab_pdf_chunks_count():
    parsed = parse_pdf(GIAB, max_pages=20)
    assert parsed and len(parsed["content"]) > 1000
    idx = DocumentIndex(enable_vector=False)
    idx.index_text(
        DOC_ID,
        parsed["content"],
        {"title": "giab-ni-cu-flotation-water", "doc_type": "report"},
    )
    assert idx.chunk_count >= 20, "ожидалось много чанков из 16-стр. PDF"


def test_giab_hardness_water_flotation_chunk():
    parsed = parse_pdf(GIAB, max_pages=20)
    idx = DocumentIndex(enable_vector=False)
    idx.index_text(DOC_ID, parsed["content"], {"title": "giab-ni-cu-flotation-water"})
    hits = idx.search("ионы жесткости воды флотация", limit=5)
    assert hits
    assert hits[0].metadata["doc_id"] == DOC_ID
    giab_hits = [h for h in hits if h.metadata["doc_id"] == DOC_ID]
    assert any("жесткост" in h.text.lower() for h in giab_hits[:5])


def test_giab_nickel_extraction_chunk():
    parsed = parse_pdf(GIAB, max_pages=20)
    idx = DocumentIndex(enable_vector=False)
    idx.index_text(DOC_ID, parsed["content"], {"title": "giab-ni-cu-flotation-water"})
    hits = idx.search("извлечение никеля медно-никелевые", limit=3)
    assert hits[0].metadata["doc_id"] == DOC_ID
    assert "никел" in hits[0].text.lower()
