"""BM25 + chunk search relevance (этап 1 roadmap)."""

import json
from pathlib import Path

import pytest

from scinikel.models.entities import Document
from scinikel.search.index import DocumentIndex


@pytest.fixture
def chunk_index() -> DocumentIndex:
    """BM25-only index (без Qdrant) для детерминированных тестов."""
    idx = DocumentIndex(enable_vector=False)
    seed = Path(__file__).resolve().parents[1] / "data" / "seed" / "documents.json"
    raw = json.loads(seed.read_text(encoding="utf-8"))
    docs = [
        Document(
            id=d["id"],
            name=d["title"],
            description=d.get("abstract"),
            attributes={"doc_type": d.get("doc_type", "")},
        )
        for d in raw
    ]
    texts = {d["id"]: d.get("text", "") for d in raw}
    idx.index_documents(docs, texts)
    return idx


def test_index_creates_chunks_for_seed_corpus(chunk_index: DocumentIndex):
    seed_len = len(json.loads(
        (Path(__file__).resolve().parents[1] / "data" / "seed" / "documents.json").read_text()
    ))
    assert chunk_index.chunk_count >= seed_len
    assert chunk_index.backend == "bm25"


def test_250c_electrolysis_finds_exp031_chunk(chunk_index: DocumentIndex):
    hits = chunk_index.search("250°C электролиз Ni-Cu")
    assert hits, "ожидался хотя бы один чанк"
    top = hits[0]
    assert top.metadata.get("doc_id") == "DOC-2024-089"
    assert "250" in top.text
    assert "EXP-2024-031" in top.text


def test_exp_id_exact_match(chunk_index: DocumentIndex):
    hits = chunk_index.search("EXP-2024-031")
    assert hits
    assert any("EXP-2024-031" in h.text for h in hits[:3])
    assert hits[0].metadata.get("doc_id") == "DOC-2024-089"


def test_flotation_ph_finds_right_doc(chunk_index: DocumentIndex):
    hits = chunk_index.search("флотация pH 10.5 извлечение никеля")
    assert hits[0].metadata.get("doc_id") == "DOC-2024-112"
    assert "EXP-2024-017" in hits[0].text or any("EXP-2024-017" in h.text for h in hits[:2])


def test_chunk_snippet_not_document_start(chunk_index: DocumentIndex):
    """Чанк должен содержать релевантные термы, а не только abstract-начало."""
    hits = chunk_index.search("250°C")
    assert any("250" in h.text for h in hits[:3])
