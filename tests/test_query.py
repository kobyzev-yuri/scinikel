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


def test_who_did_what_query(engine: HybridQueryEngine):
    result = engine.execute("Кто занимался электролизом и на какой установке?")
    assert result.experiments
    assert any(item.get("teams") for item in result.experiments)


def test_ambiguous_electrolysis_requires_clarification(engine: HybridQueryEngine):
    result = engine.execute("Что делали по электролизу?")
    assert result.needs_clarification
    assert len(result.clarification_options) >= 2
    assert any("Ni-Cu сплав" in opt["label"] for opt in result.clarification_options)


def test_electrolysis_material_then_mode_clarification(engine: HybridQueryEngine):
    first = engine.execute("Что делали по электролизу?")
    assert first.needs_clarification
    ni_option = next(opt for opt in first.clarification_options if "Ni-Cu сплав" in opt["label"])
    second = engine.execute(ni_option["suggestion"])
    assert second.needs_clarification
    assert any("220" in opt["label"] or "250" in opt["label"] for opt in second.clarification_options)


def test_electrolysis_resolved_after_mode_choice(engine: HybridQueryEngine):
    result = engine.execute("Что делали по электролиз 250°C для Ni-Cu сплава?")
    assert not result.needs_clarification
    assert result.experiments
    assert any(e["experiment"]["id"] == "EXP-2024-031" for e in result.experiments)


def test_compare_electrolysis_temperatures(engine: HybridQueryEngine):
    result = engine.execute("Сравни электролиз Ni-Cu сплава при 220°C и 250°C")
    assert not result.needs_clarification
    assert len(result.experiments) >= 2
    ids = {e["experiment"]["id"] for e in result.experiments}
    assert "EXP-2024-031" in ids
    assert "EXP-2024-028" in ids
    assert "сравн" in result.answer.lower()


def test_config_env_llm_enabled():
    from scinikel.config import CONFIG_ENV, settings

    if CONFIG_ENV.exists():
        assert settings.llm_enabled or settings.llm_provider == "ollama"


def test_graph_stats_after_seed():
    graph = NetworkXGraphStore()
    seed = Path(__file__).resolve().parents[1] / "data" / "seed"
    ingest_seed_data(graph, seed)
    stats = graph.stats()
    assert stats["entities"] > 5
    assert stats["relations"] > 5


def test_subgraph_edges_are_unique():
    graph = NetworkXGraphStore()
    seed = Path(__file__).resolve().parents[1] / "data" / "seed"
    ingest_seed_data(graph, seed)
    sg = graph.subgraph("EXP-2024-017", depth=2)
    edge_ids = [e["id"] for e in sg["edges"]]
    assert len(edge_ids) == len(set(edge_ids))


def test_subgraph_edges_reference_known_nodes():
    graph = NetworkXGraphStore()
    seed = Path(__file__).resolve().parents[1] / "data" / "seed"
    ingest_seed_data(graph, seed)
    sg = graph.subgraph("EXP-2023-044", depth=1)
    node_ids = {n["id"] for n in sg["nodes"]}
    assert node_ids
    for edge in sg["edges"]:
        assert edge["source"] in node_ids
        assert edge["target"] in node_ids


def test_obzhig_800_ash_query(engine: HybridQueryEngine):
    parsed = engine.parse_question(
        "Что показал обжиг Ni-Cu концентрата при 800°C по зольности?"
    )
    assert parsed.process == "обжиг"
    assert parsed.mode and "800" in parsed.mode
    assert parsed.property_name and "зольност" in parsed.property_name

    result = engine.execute(
        "Что показал обжиг Ni-Cu концентрата при 800°C по зольности?"
    )
    assert not result.needs_clarification
    assert len(result.experiments) == 1
    assert result.experiments[0]["experiment"]["id"] == "EXP-2023-044"
    assert result.subgraph
    assert result.subgraph["nodes"]
    node_ids = {n["id"] for n in result.subgraph["nodes"]}
    for edge in result.subgraph["edges"]:
        assert edge["source"] in node_ids
        assert edge["target"] in node_ids
