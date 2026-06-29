"""Rule-based formatting of answers from graph query results."""

from __future__ import annotations

from typing import Any

from scinikel.query.engine import QueryResult
from scinikel.search.text_cleanup import unique_media_summaries


def _experiment_row(item: dict[str, Any]) -> list[str]:
    exp = item["experiment"]
    mats = ", ".join(m["name"] for m in item.get("materials", [])) or "—"
    modes = ", ".join(m["name"] for m in item.get("modes", [])) or "—"
    measurements = item.get("measurements", [])
    meas_text = "; ".join(
        f"{m.get('value', '?')}" + (f" ({m.get('delta')})" if m.get("delta") else "")
        for m in measurements
    ) or "—"
    concl_parts = [
        c.get("description") or c.get("name", "") for c in item.get("conclusions", [])
    ]
    concl = "; ".join(p for p in concl_parts if p) or "—"
    return [exp.get("id", ""), mats, modes, meas_text, concl]


def build_experiments_table(experiments: list[dict[str, Any]]) -> str:
    if not experiments:
        return "Нет экспериментов для таблицы."

    header = ["Эксперимент", "Материал", "Режим", "Результат", "Комментарий"]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for item in experiments:
        row = _experiment_row(item)
        lines.append("| " + " | ".join(cell.replace("|", "/") for cell in row) + " |")
    return "\n".join(lines)



def format_document_media_answer(result: QueryResult) -> str:
    """Ответ по графикам/таблицам одного PDF — рисунки CLIP + текстовый обзор."""
    doc_id = result.scoped_doc_id or "документ"
    if not result.sources and not result.images:
        return result.answer

    lines = [
        f"**Графики и таблицы в отчёте** `{doc_id}`",
        "",
    ]

    if result.images:
        lines.append("**Аннотации куратора к рисункам:**")
        for idx, image in enumerate(result.images[:5], start=1):
            page = image.get("page")
            page_txt = f", стр. {page}" if page else ""
            label = (image.get("figure_type") or image.get("media_label") or image.get("title") or "рисунок")
            label = label.replace("|", "/")
            lines.append(f"{idx}. **{label}**{page_txt}")
            ann = (image.get("librarian_annotation") or image.get("snippet") or "").strip()
            if ann:
                lines.append(f"   {ann}")
            for kp in image.get("key_points") or []:
                lines.append(f"   • {kp}")
        lines.append("")
        lines.append("_Рисунки — под ответом и во вкладке «Главная» → Источники._")
        lines.append("")
    else:
        lines.append(
            "_Рисунки не в CLIP-индексе. Нужны Qdrant + OpenCLIP (режим «full») "
            "и Vision при индексации PDF — как в 3dtoday add_article_from_parse._"
        )
        lines.append("")

    rows = unique_media_summaries(result.sources, limit=5)
    if rows:
        lines.append("**По тексту статьи (упоминания таблиц и выводов):**")
        lines.append("")
        for idx, row in enumerate(rows, start=1):
            page = row.get("page")
            page_txt = f", стр. {page}" if page else ""
            chunk = row.get("chunk_id") or ""
            chunk_txt = f" · `{chunk}`" if chunk else ""
            lines.append(f"{idx}. **{row['topic']}**{page_txt}{chunk_txt}")
            lines.append(f"   {row['summary']}")
            lines.append("")

    lines.append(
        "_Текстовые фрагменты PDF — в карточках «Источники»; chunk_id — для проверки в отчёте._"
    )

    return "\n".join(lines).rstrip()


def format_structured_answer(result: QueryResult, *, wants_table: bool = False) -> str:
    """Ответ только из графа — без LLM, работает офлайн."""
    if wants_table and result.experiments:
        parts = [build_experiments_table(result.experiments)]
    else:
        parts = [result.answer]

    if not wants_table and len(result.experiments) >= 2:
        parts.append("\n_Могу свести сравнение в таблицу — напишите «свести в таблицу»._")

    if result.gaps:
        gap_lines = [f"• {g['material']} × {g['mode']}" for g in result.gaps[:10]]
        parts.append("\n**Пробелы в данных:**\n" + "\n".join(gap_lines))

    if result.sources:
        doc_titles = ", ".join(s.get("title") or s["id"] for s in result.sources[:5])
        parts.append(f"\n**Источники:** {doc_titles}")

    return "\n".join(parts)


def ensure_table_in_answer(text: str, result: QueryResult, *, wants_table: bool) -> str:
    """Если просили таблицу, а LLM вернул prose — подставляем rule-based таблицу."""
    if not wants_table or not result.experiments:
        return text
    if "|" in text and "---" in text:
        return text
    table = build_experiments_table(result.experiments)
    intro = text.strip()
    if intro and len(intro) < 400:
        return f"{intro}\n\n{table}"
    return table
