"""Tests for expanded demo dataset."""

import json
from pathlib import Path

import pytest

from scinikel.graph.networkx_store import NetworkXGraphStore
from scinikel.ingest.loader import ingest_seed_data
from scinikel.ingest.xlsx_parser import parse_xlsx
from scinikel.query.engine import HybridQueryEngine
from scinikel.search.index import DocumentIndex

SEED = Path(__file__).resolve().parents[1] / "data" / "seed"


@pytest.fixture
def graph() -> NetworkXGraphStore:
    store = NetworkXGraphStore()
    ingest_seed_data(store, SEED)
    return store


def test_demo_experiment_count(graph: NetworkXGraphStore):
    assert graph.stats()["entity_Experiment"] == 15


def test_demo_references_loaded(graph: NetworkXGraphStore):
    stats = graph.stats()
    assert stats.get("entity_Material", 0) >= 5
    assert stats.get("entity_Equipment", 0) >= 9
    assert stats.get("entity_Team", 0) >= 6


def test_xlsx_matches_json():
    json_count = len(json.loads((SEED / "experiments.json").read_text(encoding="utf-8")))
    xlsx_path = SEED / "experiments.xlsx"
    if not xlsx_path.exists():
        pytest.skip("experiments.xlsx not built — run scripts/build_demo_xlsx.py")
    records = parse_xlsx(xlsx_path)
    assert len(records) == json_count


def test_hydro_query(graph: NetworkXGraphStore):
    engine = HybridQueryEngine(graph, DocumentIndex())
    result = engine.execute("Что делали по выщелачиванию Ni-Cu концентрата?")
    assert result.experiments
    assert any("EXP-2024-022" in str(e) for e in result.experiments)


def test_gaps_not_empty(graph: NetworkXGraphStore):
    gaps = graph.find_gaps()
    assert len(gaps) > 0
