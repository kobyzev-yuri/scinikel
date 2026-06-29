"""Hybrid search mode (RRF) integration."""

import pytest

from scinikel.search.index import DocumentIndex
from scinikel.services import llm_runtime as rt


@pytest.fixture(autouse=True)
def isolate_runtime(tmp_path, monkeypatch):
    path = tmp_path / "llm_runtime.json"
    monkeypatch.setattr(rt, "RUNTIME_PATH", path)
    yield


def test_hybrid_falls_back_to_bm25_without_qdrant():
    rt.set_runtime_config(search_mode=rt.SEARCH_MODE_HYBRID)
    idx = DocumentIndex(enable_vector=False)
    idx.index_text(
        "doc-a",
        "При температуре 250°C содержание Ni в катоде достигает 99.2% (EXP-2024-031).",
        {"title": "Электролиз"},
    )
    assert idx.backend == "bm25"
    hits = idx.search("250°C электролиз", limit=3)
    assert hits
    assert "250" in hits[0].text


def test_full_preset_uses_hybrid():
    payload = rt.apply_work_mode(rt.WORK_MODE_FULL)
    assert payload["search_mode"] == rt.SEARCH_MODE_HYBRID
    assert rt.vector_search_enabled() is True
    assert rt.hybrid_search_enabled() is True
