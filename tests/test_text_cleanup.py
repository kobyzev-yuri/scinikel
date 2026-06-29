"""Tests for PDF snippet cleanup and media summaries."""

from scinikel.search.text_cleanup import (
    clean_pdf_snippet,
    describe_media_fragment,
    flotation_image_rank_bonus,
    summarize_vision_image,
    unique_media_summaries,
)


def test_clean_pdf_snippet_fixes_hyphenation():
    raw = "резуль - татов было установлено распределение ма териала"
    cleaned = clean_pdf_snippet(raw)
    assert "результат" in cleaned
    assert "материала" in cleaned
    assert " - " not in cleaned


def test_describe_calcium_fragment():
    topic, summary = describe_media_fragment(
        {
            "snippet": "[стр. 10] к онцентра - ции ионов кальция в пу льпе 27,52 мг/дм3",
            "chunk_id": "doc-giab#c30",
            "page_hint": 10,
        }
    )
    assert topic == "Оптимум кальция"
    assert "27,52" in summary


def test_summarize_vision_image_strips_intro():
    raw = (
        "Проанализируем представленное изображение:\n"
        "1. Тип изображения\n\n"
        "Гистограмма (stacked bar chart), распределение классов флотируемости при разных "
        "концентрациях ионов кальция в пульпе."
    )
    label, summary = summarize_vision_image(raw)
    assert label == "Гистограмма классов флотируемости"
    assert "Проанализируем" not in summary
    assert "кальци" in summary.lower()


def test_flotation_image_rank_penalizes_microphoto():
    assert flotation_image_rank_bonus("Микрофото минералов", "графики таблицы жёсткость") < 0
    assert flotation_image_rank_bonus("Гистограмма кальция флотация", "графики") > 0


def test_summarize_vision_strips_markdown_headers():
    raw = (
        "### 1. Тип изображения\n"
        "Гистограмма (stacked bar chart), распределение классов флотируемости при кальции."
    )
    label, summary = summarize_vision_image(raw)
    assert "###" not in summary
    assert "Тип изображения" not in summary
    assert "кальци" in summary.lower()


def test_unique_media_summaries_dedupes_topics():
    sources = [
        {"snippet": "табл. 4 флотируемость кальция", "chunk_id": "#c27"},
        {"snippet": "табл. 4 ещё раз", "chunk_id": "#c28"},
        {"snippet": "27,52 мг/дм3 кальция", "chunk_id": "#c30", "page_hint": 10},
    ]
    rows = unique_media_summaries(sources)
    assert len(rows) == 2
    assert rows[0]["topic"] == "Таблица 4"
    assert rows[1]["topic"] == "Оптимум кальция"
