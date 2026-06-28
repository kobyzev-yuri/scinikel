"""Tests for ingest parsers and curator heuristics."""

import json
from pathlib import Path

import pandas as pd
import pytest

from scinikel.agent.curator import CuratorAgent
from scinikel.graph.networkx_store import NetworkXGraphStore
from scinikel.ingest.graph_materializer import materialize_extraction
from scinikel.ingest.loader import load_experiments
from scinikel.ingest.xlsx_parser import parse_xlsx
from scinikel.models.entities import ExperimentRecord


SAMPLE_TEXT = """
Отчёт EXP-2024-099: Ni-Cu сульфидный концентрат, флотация pH 10.5.
Извлечение Ni составило 88.0% (+0.7% vs контроль). Установка FML-8.
Лаборатория обогащения.
"""


@pytest.fixture
def graph() -> NetworkXGraphStore:
    store = NetworkXGraphStore()
    seed = Path(__file__).resolve().parents[1] / "data" / "seed"
    load_experiments(store, seed / "experiments.json")
    return store


def test_xlsx_parser_roundtrip(tmp_path: Path):
    rows = [
        {
            "id": "EXP-TEST-001",
            "title": "Test experiment",
            "material": "Ni-Cu сплав",
            "mode": "электролиз 250°C",
            "property_name": "содержание Ni",
            "property_value": "99.0%",
            "team": "Test Lab",
        }
    ]
    df = pd.DataFrame(rows)
    xlsx_path = tmp_path / "experiments.xlsx"
    df.to_excel(xlsx_path, index=False)

    records = parse_xlsx(xlsx_path)
    assert len(records) == 1
    assert records[0].id == "EXP-TEST-001"
    assert records[0].material == "Ni-Cu сплав"


@pytest.mark.asyncio
async def test_curator_heuristic_extract(graph: NetworkXGraphStore):
    curator = CuratorAgent(graph)
    result = await curator.review_and_extract("Отчёт по флотации Ni-Cu", SAMPLE_TEXT)
    assert result["relevance_score"] > 0
    assert result.get("experiments")


@pytest.mark.asyncio
async def test_curator_ingest(graph: NetworkXGraphStore):
    curator = CuratorAgent(graph)
    before = graph.stats()["entities"]
    extraction = curator._heuristic_extract("Ni-Cu флотация", SAMPLE_TEXT, source="test", doc_type="report")
    extraction["decision"] = "approve"
    stats = materialize_extraction(graph, extraction)
    assert stats["experiments"] >= 1
    assert graph.stats()["entities"] > before


def test_materialize_from_json_schema(graph: NetworkXGraphStore):
    payload = json.loads(
        (Path(__file__).parents[1] / "data" / "seed" / "experiments.json").read_text(encoding="utf-8")
    )[0]
    extraction = {
        "document": {"id": "DOC-T", "title": "Test", "abstract": "x"},
        "experiments": [
            {
                **payload,
                "property_name": payload["property_name"],
                "property_value": payload["property_value"],
            }
        ],
    }
    stats = materialize_extraction(graph, extraction)
    assert stats["experiments"] == 1
