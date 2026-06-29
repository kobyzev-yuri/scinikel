"""Tests for dialog context in ResearchAgent."""

from pathlib import Path

import pytest

from scinikel.agent.assistant import ChatMessage, ResearchAgent
from scinikel.graph.networkx_store import NetworkXGraphStore
from scinikel.ingest.loader import ingest_seed_data
from scinikel.query.engine import HybridQueryEngine
from scinikel.search.index import DocumentIndex

SEED = Path(__file__).resolve().parents[1] / "data" / "seed"


@pytest.fixture
def agent() -> ResearchAgent:
    store = NetworkXGraphStore()
    ingest_seed_data(store, SEED)
    return ResearchAgent(HybridQueryEngine(store, DocumentIndex()))


def test_document_media_uses_rule_answer_not_experiment_table():
    from scinikel.ingest.pdf_parser import parse_pdf

    giab = Path(__file__).resolve().parents[1] / "data" / "samples" / "giab-ni-cu-flotation-water.pdf"
    if not giab.exists():
        pytest.skip("GIAB sample PDF not present")

    store = NetworkXGraphStore()
    ingest_seed_data(store, SEED)
    doc_index = DocumentIndex(enable_vector=False)
    parsed_pdf = parse_pdf(giab, max_pages=20)
    doc_index.index_text(
        "doc-giab-ni-cu-flotation-water",
        parsed_pdf["content"],
        {"title": "giab-ni-cu-flotation-water", "doc_type": "report"},
    )
    agent = ResearchAgent(HybridQueryEngine(store, doc_index))

    q = (
        "doc-giab-ni-cu-flotation-water: какие графики и таблицы показывают "
        "влияние ионов жёсткости воды на флотацию медно-никелевых руд?"
    )
    resp = agent.chat(q)
    assert resp.query_result is not None
    assert resp.query_result.scoped_doc_id == "doc-giab-ni-cu-flotation-water"
    assert "EXP-2024-017" not in resp.message
    assert "Рисунки из PDF" in resp.message or "Таблица 4" in resp.message
    assert "резуль -" not in resp.message
    assert not resp.llm_used


def test_document_media_with_prior_history_not_llm_table():
    from scinikel.ingest.pdf_parser import parse_pdf

    giab = Path(__file__).resolve().parents[1] / "data" / "samples" / "giab-ni-cu-flotation-water.pdf"
    if not giab.exists():
        pytest.skip("GIAB sample PDF not present")

    store = NetworkXGraphStore()
    ingest_seed_data(store, SEED)
    doc_index = DocumentIndex(enable_vector=False)
    parsed_pdf = parse_pdf(giab, max_pages=20)
    doc_index.index_text(
        "doc-giab-ni-cu-flotation-water",
        parsed_pdf["content"],
        {"title": "giab-ni-cu-flotation-water", "doc_type": "report"},
    )
    agent = ResearchAgent(HybridQueryEngine(store, doc_index))

    q = (
        "doc-giab-ni-cu-flotation-water: какие графики и таблицы показывают "
        "влияние ионов жёсткости воды на флотацию медно-никелевых руд?"
    )
    history = [
        ChatMessage(
            role="user",
            content="Что делали по флотация pH 10.5 для ni-cu сульфидный концентрат?",
        ),
        ChatMessage(
            role="assistant",
            content="По Ni-Cu сульфидному концентрату при флотации pH 10.5 извлечение Ni 87.3%.",
        ),
    ]
    resp = agent.chat(q, history=history)
    assert not resp.llm_used
    assert "Таблица 4" in resp.message or "27,52" in resp.message
    assert "резуль -" not in resp.message
    assert "EXP-2024-001" not in resp.message
    assert "#c30" in resp.message or "Оптимум кальция" in resp.message
    resp = agent.chat("Что делали по электролизу?")
    assert resp.query_result is not None
    assert resp.query_result.needs_clarification
    assert "уточн" in resp.message.lower()


def test_chat_accepts_prior_history(agent: ResearchAgent):
    first = agent.chat("Что известно про электролиз Ni-Cu сплава при 250°C?")
    history = [
        ChatMessage(role="user", content="Что известно про электролиз Ni-Cu сплава при 250°C?"),
        ChatMessage(role="assistant", content=first.message),
    ]
    second = agent.chat("А кто это делал?", history=history)
    assert second.message
    assert second.query_result is not None


def test_follow_up_resolves_query_from_context(agent: ResearchAgent):
    anchor = "Что известно про электролиз Ni-Cu сплава при 250°C?"
    history = [
        ChatMessage(role="user", content=anchor),
        ChatMessage(role="assistant", content="ответ"),
    ]
    resolved = agent._resolve_query_text("А кто это делал?", history)
    assert anchor in resolved
    assert "Уточнение" in resolved


def test_standalone_question_not_merged(agent: ResearchAgent):
    history = [
        ChatMessage(role="user", content="Что делали по флотации?"),
        ChatMessage(role="assistant", content="ответ"),
    ]
    question = "Какой результат дала магнитная сепарация вольфрамового шлама?"
    assert agent._resolve_query_text(question, history) == question


def test_affirmative_compare_expands_from_dialog(agent: ResearchAgent):
    history = [
        ChatMessage(role="user", content="Что делали по электролиз 250°C для Ni-Cu сплава?"),
        ChatMessage(
            role="assistant",
            content="При 250°C содержание Ni 99.2%. Могу сравнить 220°C vs 250°C.",
        ),
    ]
    expanded = agent._resolve_query_text("да, сравни", history)
    assert "сравни" in expanded.lower()
    assert "220" in expanded and "250" in expanded


def test_affirmative_compare_does_not_loop_clarification(agent: ResearchAgent):
    history = [
        ChatMessage(role="user", content="Что делали по электролиз 250°C для Ni-Cu сплава?"),
        ChatMessage(
            role="assistant",
            content="При 250°C — 99.2% Ni. При 220°C — 98.4%. Могу сравнить режимы.",
        ),
    ]
    resp = agent.chat("да, сравни", history=history)
    assert not resp.query_result.needs_clarification
    assert len(resp.query_result.experiments) >= 2
    assert "сравн" in resp.message.lower() or "220" in resp.message


def test_detail_followup_keeps_anode_nickel_context(agent: ResearchAgent):
    history = [
        ChatMessage(
            role="user",
            content="Что делали по электролиз для анодный никель?",
        ),
        ChatMessage(
            role="assistant",
            content=(
                "По анодному никелю делали электролитическое рафинирование.\n"
                "- Материал: анодный никель\n"
                "- Режим: электролиз при 250°C\n"
                "- Результат: чистота катода 99.8%\n"
                "Могу объяснить, что именно улучшает 250°C по этому эксперименту."
            ),
        ),
    ]
    resolved = agent._resolve_query_text("что именно улучшает 250°C", history)
    assert "анодн" in resolved.lower()
    resp = agent.chat("что именно улучшает 250°C", history=history)
    assert not resp.query_result.needs_clarification
    assert any(e["experiment"]["id"] == "EXP-2024-048" for e in resp.query_result.experiments)


def test_table_request_after_compare_does_not_clarify(agent: ResearchAgent):
    history = [
        ChatMessage(role="user", content="Что делали по электролиз для анодный никель?"),
        ChatMessage(
            role="assistant",
            content="По анодному никелю: 99.8% при 250°C. Могу сравнить с Ni-Cu.",
        ),
        ChatMessage(role="user", content="сравнить это с электролизом Ni-Cu"),
        ChatMessage(
            role="assistant",
            content=(
                "Ni-Cu 250°C → 99.2%, 220°C → 98.4%. Анодный Ni 250°C → 99.8%. "
                "Если хотите, могу дальше свести это в таблицу."
            ),
        ),
    ]
    resolved = agent._resolve_query_text("свести это в таблицу", history)
    assert "анодн" in resolved.lower()
    assert "ni-cu" in resolved.lower()
    resp = agent.chat("свести это в таблицу", history=history)
    assert not resp.query_result.needs_clarification
