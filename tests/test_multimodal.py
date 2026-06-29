"""Tests for multimodal curator (vision fallback) and image merge."""

import pytest

from scinikel.agent.curator import CuratorAgent
from scinikel.graph.networkx_store import NetworkXGraphStore


TABLE_IMAGE_ALT = "Страница 2, таблица EXP-2024-055 Ni-Cu флотация pH 10.5 извлечение Ni 91.2%"


@pytest.mark.asyncio
async def test_curator_image_fallback_extracts_from_alt():
    curator = CuratorAgent(NetworkXGraphStore())
    images = [{"alt": TABLE_IMAGE_ALT, "page": 2}]
    analysis = curator._analyze_images_fallback(images)
    assert analysis is not None
    assert analysis["provider"] == "fallback"
    assert len(analysis["image_analyses"]) == 1

    merged = curator._merge_image_context("Краткий текст отчёта.", analysis)
    assert "EXP-2024-055" in merged
    assert "Аннотации куратора" in merged

    result = await curator.review_and_extract(
        "Отчёт флотации",
        "Краткий текст без цифр.",
        images=images,
        analyze_images=True,
    )
    assert result.get("image_analysis")
    exps = result.get("experiments") or []
    assert exps
    assert "EXP-2024-055" in exps[0].get("id", "").upper() or "EXP-2024-055" in str(exps[0])


def test_merge_image_context_empty():
    curator = CuratorAgent()
    assert curator._merge_image_context("abc", None) == "abc"
    assert curator._merge_image_context("abc", {}) == "abc"


def test_librarian_annotate_vision():
    raw = (
        "Гистограмма распределения классов флотируемости при концентрации кальция 27,52 мг/дм3 "
        "для меди и никеля."
    )
    ann = CuratorAgent.librarian_annotate_vision(raw, page=8, image_name="рис. 1")
    assert ann["figure_type"]
    assert "27,52" in ann["annotation"] or "флотируем" in ann["annotation"].lower()
    assert "Проанализируем" not in ann["annotation"]
    assert ann["key_points"]


def test_content_for_llm_prioritizes_vision():
    curator = CuratorAgent()
    main = "A" * 5000
    vision = "B" * 5000
    merged = main + "\n\n--- Аннотации куратора к рисункам ---\n" + vision
    out = curator._content_for_llm_extract(merged, max_chars=4000)
    assert "Аннотации куратора" in out
    assert "BBBB" in out
