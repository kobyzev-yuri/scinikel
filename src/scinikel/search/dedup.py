"""Дедупликация результатов поиска — паттерн из 3dtoday/rag_service.py."""

from __future__ import annotations

from typing import Any


def dedup_search_results(
    results: list[dict[str, Any]],
    *,
    id_keys: tuple[str, ...] = ("id", "chunk_id", "doc_id", "original_id", "article_id"),
    url_key: str = "url",
    collapse_by_doc: bool = True,
) -> list[dict[str, Any]]:
    """Оставить лучший результат на doc_id (для чанков) или по id/url — паттерн 3dtoday."""
    if not collapse_by_doc:
        return _dedup_by_id(results, id_keys=id_keys, url_key=url_key)

    best: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in results:
        meta = item.get("metadata") or {}
        doc_id = str(meta.get("doc_id") or _first_str(item, ("doc_id", "original_id", *id_keys)) or "")
        if not doc_id:
            doc_id = str(item.get("id") or len(order))
        prev = best.get(doc_id)
        if prev is None or float(item.get("score", 0)) > float(prev.get("score", 0)):
            if doc_id not in best:
                order.append(doc_id)
            best[doc_id] = item
    return [best[k] for k in order]


def _dedup_by_id(
    results: list[dict[str, Any]],
    *,
    id_keys: tuple[str, ...],
    url_key: str,
) -> list[dict[str, Any]]:
    """Простая дедупликация по id (legacy)."""
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in results:
        doc_id = _first_str(item, id_keys)
        url = item.get(url_key) or (item.get("metadata") or {}).get(url_key)
        if doc_id and doc_id in seen_ids:
            continue
        if url and url in seen_urls:
            continue
        unique.append(item)
        if doc_id:
            seen_ids.add(doc_id)
        if url:
            seen_urls.add(str(url))
    return unique


def _first_str(item: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        val = item.get(key)
        if not val and item.get("metadata"):
            val = item["metadata"].get(key)
        if val:
            return str(val)
    return None
