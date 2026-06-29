"""Tests for document snippet extraction."""

from scinikel.search.snippet import VISION_MARKER, extract_snippet


def test_extract_snippet_prefers_vision_for_visual_query():
    text = (
        "Введение в флотацию медно-никелевых руд.\n\n"
        "Общие положения без чисел."
        f"\n\n{VISION_MARKER}\n"
        "[fig1, стр. 6]\nГрафик извлечения никеля: ε₀=0,87, k=0,12 мин⁻¹."
    )
    result = extract_snippet(text, "график извлечения никеля")
    assert result["excerpt_type"] == "vision"
    assert "никеля" in result["snippet"].lower()
    assert result["page_hint"] == 6


def test_extract_snippet_finds_relevant_paragraph():
    text = (
        "Введение без ключевых слов.\n\n"
        "При температуре 250°C извлечение Ni составило 87% на концентрате."
    )
    result = extract_snippet(text, "250°C извлечение Ni")
    assert result["excerpt_type"] == "text"
    assert "250" in result["snippet"]


def test_extract_snippet_empty_text():
    result = extract_snippet("", "query")
    assert result["snippet"] == ""
