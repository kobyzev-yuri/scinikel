"""Выбор релевантного фрагмента из текста документа (в т.ч. блок Vision)."""

from __future__ import annotations

import re
from typing import Any

VISION_MARKER = "--- Описание изображений (Vision) ---"

VISUAL_QUERY_HINTS = (
    "график",
    "рисун",
    "таблиц",
    "схем",
    "микрофото",
    "извлечен",
    "кинетик",
    "фото",
    "диаграм",
)

_STOPWORDS = frozenset(
    {
        "что",
        "как",
        "какой",
        "какая",
        "какие",
        "какое",
        "для",
        "при",
        "это",
        "или",
        "ещё",
        "еще",
        "где",
        "кто",
        "влия",
        "делали",
        "был",
        "были",
        "есть",
        "нет",
        "the",
        "and",
    }
)


def _terms(query: str) -> list[str]:
    return [
        t
        for t in re.findall(r"\w{3,}", query.lower())
        if t not in _STOPWORDS
    ]


def _score_text(text: str, terms: list[str]) -> int:
    low = text.lower()
    return sum(1 for t in terms if t in low)


def _truncate(text: str, max_len: int) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    if len(text) <= max_len:
        return text
    cut = text[: max_len - 1].rsplit(" ", 1)[0]
    return (cut or text[: max_len - 1]).rstrip() + "…"


def extract_snippet(text: str, query: str, *, max_len: int = 320) -> dict[str, Any]:
    """
    Вернуть лучший фрагмент: приоритет Vision-блока для визуальных запросов
    или абзаца с максимальным пересечением с запросом.
    """
    if not text or not text.strip():
        return {"snippet": "", "excerpt_type": "text", "page_hint": None}

    terms = _terms(query)
    visual_query = any(h in query.lower() for h in VISUAL_QUERY_HINTS)
    candidates: list[tuple[str, int, str, int | None]] = []

    if VISION_MARKER in text:
        vision = text.split(VISION_MARKER, 1)[1]
        for chunk in re.split(r"\n(?=\[)", vision):
            chunk = chunk.strip()
            if not chunk:
                continue
            score = _score_text(chunk, terms) + (4 if visual_query else 0)
            page_m = re.search(r"стр\.?\s*(\d+)", chunk)
            page = int(page_m.group(1)) if page_m else None
            candidates.append((chunk, score, "vision", page))

    main = text.split(VISION_MARKER)[0] if VISION_MARKER in text else text
    for para in re.split(r"\n{2,}", main):
        para = para.strip()
        if len(para) < 24:
            continue
        candidates.append((para, _score_text(para, terms), "text", None))

    if not candidates:
        return {
            "snippet": _truncate(text, max_len),
            "excerpt_type": "text",
            "page_hint": None,
        }

    best = max(candidates, key=lambda row: (row[1], len(row[0])))
    if best[1] == 0:
        if visual_query and VISION_MARKER in text:
            vision_chunk = candidates[0][0]
            page_m = re.search(r"стр\.?\s*(\d+)", vision_chunk)
            return {
                "snippet": _truncate(vision_chunk, max_len),
                "excerpt_type": "vision",
                "page_hint": int(page_m.group(1)) if page_m else None,
            }
        return {
            "snippet": _truncate(text, max_len),
            "excerpt_type": "text",
            "page_hint": None,
        }

    return {
        "snippet": _truncate(best[0], max_len),
        "excerpt_type": best[2],
        "page_hint": best[3],
    }


def page_hint_from_text(text: str) -> int | None:
    """Номер страницы из [стр. N] в теле чанка (если metadata.page пуст)."""
    pages = [int(m.group(1)) for m in re.finditer(r"\[стр\.\s*(\d+)\]", text, flags=re.IGNORECASE)]
    if pages:
        return pages[-1]
    page_m = re.search(r"стр\.?\s*(\d+)", text, flags=re.IGNORECASE)
    return int(page_m.group(1)) if page_m else None
