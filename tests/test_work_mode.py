"""Tests for work mode presets and search mode."""

import pytest

from scinikel.services import llm_runtime as rt


@pytest.fixture(autouse=True)
def isolate_runtime(tmp_path, monkeypatch):
    path = tmp_path / "llm_runtime.json"
    monkeypatch.setattr(rt, "RUNTIME_PATH", path)
    yield


def test_lite_preset():
    payload = rt.apply_work_mode(rt.WORK_MODE_LITE)
    assert payload["work_mode"] == rt.WORK_MODE_LITE
    assert payload["answer_mode"] == rt.ANSWER_MODE_RULE
    assert payload["search_mode"] == rt.SEARCH_MODE_KEYWORD
    assert rt.should_use_llm() is False
    assert rt.vector_search_enabled() is False


def test_local_preset():
    payload = rt.apply_work_mode(rt.WORK_MODE_LOCAL)
    assert payload["work_mode"] == rt.WORK_MODE_LOCAL
    assert payload["answer_mode"] == rt.ANSWER_MODE_LLM
    assert payload["search_mode"] == rt.SEARCH_MODE_KEYWORD
    assert payload["provider"] == rt.PROVIDER_OLLAMA
    assert rt.vector_search_enabled() is False


def test_full_preset():
    payload = rt.apply_work_mode(rt.WORK_MODE_FULL)
    assert payload["work_mode"] == rt.WORK_MODE_FULL
    assert payload["answer_mode"] == rt.ANSWER_MODE_LLM
    assert payload["search_mode"] == rt.SEARCH_MODE_HYBRID
    assert payload["provider"] == rt.PROVIDER_PROXYAPI
    assert rt.vector_search_enabled() is True
    assert rt.hybrid_search_enabled() is True


def test_local_preset_ollama_model():
    payload = rt.apply_work_mode(rt.WORK_MODE_LOCAL)
    assert payload.get("ollama_model") == "qwen2.5:7b"


def test_custom_mode_detection():
    rt.set_runtime_config(
        provider=rt.PROVIDER_PROXYAPI,
        answer_mode=rt.ANSWER_MODE_LLM,
        search_mode=rt.SEARCH_MODE_KEYWORD,
    )
    assert rt.detect_work_mode() == rt.WORK_MODE_CUSTOM


def test_runtime_payload_includes_work_modes():
    payload = rt.runtime_payload()
    ids = {m["id"] for m in payload["work_modes"]}
    assert rt.WORK_MODE_LITE in ids
    assert rt.WORK_MODE_LOCAL in ids
    assert rt.WORK_MODE_FULL in ids
    assert "search_mode" in payload
    assert "vector_search_enabled" in payload
