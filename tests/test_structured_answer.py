"""Tests for rule-based answer formatting."""

from scinikel.agent.structured_answer import (
    build_experiments_table,
    ensure_table_in_answer,
    format_structured_answer,
)
from scinikel.query.engine import QueryResult


def _sample_experiment() -> dict:
    return {
        "experiment": {"id": "EXP-2023-044", "name": "Обжиг"},
        "materials": [{"name": "Ni-Cu концентрат"}],
        "modes": [{"name": "обжиг 800°C"}],
        "measurements": [{"value": "2.1%", "delta": "-0.4%"}],
        "conclusions": [{"description": "Снижение зольности"}],
    }


def test_build_experiments_table_markdown():
    table = build_experiments_table([_sample_experiment()])
    assert "|" in table
    assert "EXP-2023-044" in table
    assert "обжиг 800°C" in table


def test_ensure_table_when_llm_returns_prose():
    result = QueryResult(
        answer="Краткий текст без таблицы",
        experiments=[_sample_experiment()],
    )
    out = ensure_table_in_answer("Просто список экспериментов.", result, wants_table=True)
    assert "| EXP-2023-044 |" in out or "| EXP-2023-044|" in out.replace(" ", "")


def test_format_structured_offers_table_on_compare():
    exps = [_sample_experiment(), _sample_experiment()]
    exps[1]["experiment"]["id"] = "EXP-2024-041"
    result = QueryResult(answer="Сравнение двух режимов", experiments=exps)
    text = format_structured_answer(result, wants_table=False)
    assert "таблиц" in text.lower()
