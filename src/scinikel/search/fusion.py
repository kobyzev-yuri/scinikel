"""Fusion ранжирования: RRF для BM25 + dense (этап 3 roadmap)."""

from __future__ import annotations

from typing import Any

DEFAULT_RRF_K = 60


def _result_key(item: dict[str, Any]) -> str:
    meta = item.get("metadata") or {}
    return str(
        meta.get("chunk_id")
        or meta.get("id")
        or item.get("id")
        or item.get("text", "")[:80]
    )


def reciprocal_rank_fusion(
    result_lists: list[list[dict[str, Any]]],
    *,
    k: int = DEFAULT_RRF_K,
    top_k: int | None = None,
) -> list[dict[str, Any]]:
    """
    Reciprocal Rank Fusion: score(d) = Σ 1/(k + rank_i(d)).
    Паттерн industry-standard для гибридного поиска (≠ metadata hybrid в 3dtoday).
    """
    if not result_lists:
        return []
    if len(result_lists) == 1:
        rows = list(result_lists[0])
        return rows[:top_k] if top_k else rows

    scores: dict[str, float] = {}
    items: dict[str, dict[str, Any]] = {}
    sources: dict[str, list[str]] = {}

    for list_idx, results in enumerate(result_lists):
        source = results[0].get("backend", f"list{list_idx}") if results else f"list{list_idx}"
        for rank, item in enumerate(results, start=1):
            key = _result_key(item)
            if not key:
                continue
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            if key not in items:
                items[key] = dict(item)
                sources[key] = []
            src = item.get("backend") or source
            if src and src not in sources[key]:
                sources[key].append(src)

    fused: list[dict[str, Any]] = []
    for key, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        row = dict(items[key])
        row["score"] = score
        row["backend"] = "rrf"
        meta = dict(row.get("metadata") or {})
        meta["fusion_sources"] = sources.get(key, [])
        row["metadata"] = meta
        fused.append(row)

    if top_k is not None:
        fused = fused[:top_k]
    return fused
