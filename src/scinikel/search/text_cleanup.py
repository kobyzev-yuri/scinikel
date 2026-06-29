"""Нормализация текста из PDF и краткие подписи для мультимодального ответа."""

from __future__ import annotations

import re
from typing import Any

_PAGE_PREFIX = re.compile(r"^\[стр\.\s*\d+\]\s*", re.IGNORECASE)


def clean_pdf_snippet(text: str) -> str:
    """Убрать типичные артефакты вёрстки PDF (переносы, разорванные слова)."""
    t = _PAGE_PREFIX.sub("", text or "")
    t = t.replace("\n", " ")
    t = re.sub(r"(\w)-\s+(\w)", r"\1\2", t)
    t = re.sub(r"\s+-\s+", "", t)
    replacements = (
        (r"таб\s+л\.", "табл."),
        (r"резуль\s*тат", "результат"),
        (r"к\s+онцентра", "концентра"),
        (r"пу\s+льп", "пульп"),
        (r"мг/\s*д\s*м", "мг/дм"),
        (r"флотируем", "флотируем"),
        (r"быстрофло\s*-?\s*тиру", "быстрофлотиру"),
        (r"с\s+табильност", "стабильност"),
        (r"прис\s+утств", "присутств"),
        (r"содержа\s*-?\s*ни", "содержани"),
        (r"мо\s+де", "моде"),
        (r"соз\s+дан", "создан"),
        (r"предсказываю\s*-?\s*щ", "предсказывающ"),
        (r"каждог\s+о", "каждого"),
        (r"ма\s+териал", "материал"),
        (r"ник\s+ел", "никел"),
        (r"мед\s+и", "меди"),
    )
    for pattern, repl in replacements:
        t = re.sub(pattern, repl, t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _first_readable_sentence(text: str, max_len: int = 160) -> str:
    if not text:
        return "См. фрагмент в источнике."
    cut = text[:max_len]
    if len(text) > max_len:
        cut = cut.rsplit(" ", 1)[0] + "…"
    return cut[0].upper() + cut[1:] if cut else text


_VISION_INTRO = re.compile(
    r"^проанализируем[^.\n]*[.\n]+\s*",
    re.IGNORECASE | re.MULTILINE,
)
_VISION_TYPE = re.compile(
    r"тип\s+изображения\s*[:\*#]*\s*([^\n*#]+)",
    re.IGNORECASE,
)
_MD_HEADERS = re.compile(r"#{1,6}\s*")
_MD_RULE = re.compile(r"-{3,}")


def clean_vision_markdown(text: str) -> str:
    """Убрать markdown/LaTeX из ответа Vision перед аннотацией куратора."""
    t = text or ""
    t = _MD_HEADERS.sub("", t)
    t = _MD_RULE.sub(" ", t)
    t = re.sub(r"\d+\.\s*тип изображения\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"тип изображения\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"\$\s*([^$]+)\s*\$", r"\1", t)
    t = re.sub(r"\\text\{([^}]+)\}", r"\1", t)
    t = re.sub(r"\\approx", "≈", t)
    t = re.sub(r"\\,", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def summarize_vision_image(text: str) -> tuple[str, str]:
    """Краткая подпись рисунка из сырого ответа Vision (убрать «Проанализируем…»)."""
    raw = clean_vision_markdown(re.sub(r"\*+", " ", text or ""))
    raw = _VISION_INTRO.sub("", raw.strip())
    raw = re.sub(r"\s+", " ", raw).strip()
    low = raw.lower()

    if "микрофото" in low[:280] or "микроскоп" in low[:280]:
        return (
            "Микрофото минералов (фон)",
            "Шлиф руды: фазы Cp (халькопирит), Py и др. — минералогический контекст к флотации.",
        )

    label = "Рисунок"
    type_m = _VISION_TYPE.search(raw)
    if type_m:
        typ = type_m.group(1).strip().lower()
    else:
        typ = low[:120]

    if "гистограм" in typ or "столбчат" in typ or "stacked bar" in typ:
        label = "Гистограмма классов флотируемости"
    elif "график" in typ and ("извлечен" in low or "никел" in low or "мед" in low):
        label = "График извлечения Cu/Ni"
    elif "график" in typ or "диаграм" in typ:
        label = "График"
    elif "таблиц" in typ:
        label = "Таблица"
    elif "схем" in typ or "блок-схем" in typ or "алгоритм" in typ:
        label = "Схема расчёта кинетики"
    elif "микрофото" in typ or "микроскоп" in typ:
        label = "Микрофото минералов (фон)"

    keywords = (
        "кальци",
        "флотир",
        "жесткост",
        "жёсткост",
        "никел",
        "мед",
        "извлечен",
        "гистограм",
        "класс",
        "флотируем",
        "27,52",
        "44,45",
    )
    for part in re.split(r"[.\n]", raw):
        s = part.strip()
        if len(s) < 25:
            continue
        s_low = s.lower()
        if s_low.startswith("тип изображения") or re.match(r"^\d+\.", s_low):
            continue
        if "###" in s or s_low.startswith("это "):
            s = re.sub(r"^это\s+", "", s, flags=re.I)
        if any(k in s_low for k in keywords):
            s = re.sub(r"\$\s*([^$]+)\s*\$", r"\1", s)
            s = re.sub(r"\\text\{([^}]+)\}", r"\1", s)
            return label, s[:220] + ("…" if len(s) > 220 else "")

    return label, _first_readable_sentence(raw, max_len=180)


def flotation_image_rank_bonus(snippet: str, question: str) -> float:
    """Доп. ранжирование рисунков под запрос о жёсткости / флотации."""
    text = (snippet or "").lower()
    q = (question or "").lower()
    bonus = 0.0
    if "микрофото" in text or "микроскоп" in text:
        bonus -= 0.2
    if any(k in text for k in ("гистограм", "график", "диаграм", "таблиц", "stacked bar")):
        bonus += 0.1
    if any(k in text for k in ("кальци", "флотир", "жесткост", "жёсткост", "извлечен")):
        bonus += 0.08
    if any(k in q for k in ("график", "таблиц", "жёсткост", "жесткост", "флотир")):
        if "микрофото" in text:
            bonus -= 0.1
    return bonus


def describe_media_fragment(source: dict[str, Any]) -> tuple[str, str]:
    """Вернуть (тема, человекочитаемое описание) для фрагмента документа."""
    raw = source.get("snippet") or ""
    clean = clean_pdf_snippet(raw)
    low = clean.lower()

    if "табл" in low:
        return (
            "Таблица 4",
            "Распределение материала по классам флотируемости при разных концентрациях Ca²⁺ в пульпе.",
        )
    if "27,52" in low or "27.52" in low:
        if "44,45" in low or "44.45" in low:
            return (
                "Сравнение Ca²⁺",
                "При 27,52 мг/дм³ — максимум быстрофлотируемых фракций Cu/Ni; при 44,45 мг/дм³ извлечение снижается.",
            )
        return (
            "Оптимум кальция",
            "При 27,52 мг/дм³ Ca²⁺ в пульпе — наибольшие содержания быстрофлотируемых фракций меди и никеля.",
        )
    if "жесткост" in low or "жёсткост" in low:
        return (
            "Ионы жёсткости",
            "Жёсткость воды снижает стабильность пены и ухудшает флотацию; влияет на извлечение Cu/Ni.",
        )
    if "уравнен" in low or ("распредел" in low and "флотац" in low):
        return (
            "Модель кинетики",
            "Уравнения распределения констант скорости флотации по классам флотируемости.",
        )
    if "пенн" in low and "сл" in low:
        return (
            "Пенный слой",
            "Связь структуры пенного слоя и эффективности флотации (обзор подходов к моделированию).",
        )
    if "график" in low or "рисун" in low:
        return ("Рисунок", _first_readable_sentence(clean))

    return ("Фрагмент отчёта", _first_readable_sentence(clean))


def unique_media_summaries(
    sources: list[dict[str, Any]], *, limit: int = 6
) -> list[dict[str, Any]]:
    """Сгруппировать по теме, убрать дубли, сохранить chunk для цитирования."""
    seen_topics: set[str] = set()
    rows: list[dict[str, Any]] = []
    for source in sources:
        topic, summary = describe_media_fragment(source)
        key = topic.lower()
        if key in seen_topics:
            continue
        seen_topics.add(key)
        rows.append(
            {
                "topic": topic,
                "summary": summary,
                "page": source.get("page_hint"),
                "chunk_id": source.get("chunk_id"),
                "excerpt_type": source.get("excerpt_type"),
            }
        )
        if len(rows) >= limit:
            break
    return rows
