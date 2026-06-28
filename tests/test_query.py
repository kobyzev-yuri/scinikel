"""Tests for hybrid query engine."""

import json
from pathlib import Path

import pytest

from scinikel.graph.networkx_store import NetworkXGraphStore
from scinikel.ingest.loader import ingest_seed_data
from scinikel.query.engine import HybridQueryEngine
from scinikel.search.index import DocumentIndex


@pytest.fixture
def engine() -> HybridQueryEngine:
    graph = NetworkXGraphStore()
    seed = Path(__file__).resolve().parents[1] / "data" / "seed"
    ingest_seed_data(graph, seed)
    doc_index = DocumentIndex()
    doc_path = seed / "documents.json"
    if doc_path.exists():
        from scinikel.models.entities import Document

        raw = json.loads(doc_path.read_text(encoding="utf-8"))
        docs = [Document(id=d["id"], name=d["title"], description=d.get("abstract")) for d in raw]
        texts = {d["id"]: d.get("text", "") for d in raw}
        doc_index.index_documents(docs, texts)
    return HybridQueryEngine(graph, doc_index)


def test_alloy_mode_query(engine: HybridQueryEngine):
    result = engine.execute(
        "Что делали по Ni-Cu концентрату при флотации pH 10.5 и какой эффект на извлечение Ni?"
    )
    assert result.experiments
    assert "EXP-2024-017" in result.answer or any(
        e["experiment"]["id"] == "EXP-2024-017" for e in result.experiments
    )


def test_gaps_query(engine: HybridQueryEngine):
    result = engine.execute("Какие комбинации материал×режим ещё не исследованы?")
    assert result.gaps is not None


def test_graph_stats_after_seed():
    graph = NetworkXGraphStore()
    seed = Path(__file__).resolve().parents[1] / "data" / "seed"
    ingest_seed_data(graph, seed)
    stats = graph.stats()
    assert stats["entities"] > 5
    assert stats["relations"] > 5
