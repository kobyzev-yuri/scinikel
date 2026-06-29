"""Tests for runtime LLM provider switching."""

import json

import pytest

from scinikel.services import llm_runtime as rt


@pytest.fixture(autouse=True)
def isolate_runtime(tmp_path, monkeypatch):
    path = tmp_path / "llm_runtime.json"
    monkeypatch.setattr(rt, "RUNTIME_PATH", path)
    yield


def test_default_provider_from_env(monkeypatch):
    monkeypatch.setattr("scinikel.config.settings.llm_provider", "openai")
    cfg = rt.get_effective_config()
    assert cfg.provider == rt.PROVIDER_PROXYAPI


def test_set_ollama_provider():
    payload = rt.set_runtime_provider(rt.PROVIDER_OLLAMA, ollama_model="qwen3.6:27b")
    assert payload["provider"] == rt.PROVIDER_OLLAMA
    assert payload["ollama_model"] == "qwen3.6:27b"
    assert rt.RUNTIME_PATH.exists()
    saved = json.loads(rt.RUNTIME_PATH.read_text(encoding="utf-8"))
    assert saved["provider"] == "ollama"


def test_set_proxyapi_provider():
    payload = rt.set_runtime_provider(rt.PROVIDER_PROXYAPI, openai_model="gpt-4o-mini")
    assert payload["provider"] == rt.PROVIDER_PROXYAPI
    assert payload["openai_model"] == "gpt-4o-mini"


def test_rule_based_answer_mode():
    payload = rt.set_runtime_config(answer_mode=rt.ANSWER_MODE_RULE, search_mode=rt.SEARCH_MODE_KEYWORD)
    assert payload["answer_mode"] == rt.ANSWER_MODE_RULE
    assert payload["active_label"] == "rule-based (граф)"
    assert payload["work_mode"] == rt.WORK_MODE_LITE
    assert rt.should_use_llm() is False
    rt.set_runtime_config(answer_mode=rt.ANSWER_MODE_LLM, search_mode=rt.SEARCH_MODE_KEYWORD, provider=rt.PROVIDER_OLLAMA)
    assert rt.should_use_llm() is True
