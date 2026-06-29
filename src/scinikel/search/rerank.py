"""Cross-Encoder rerank — паттерн из 3dtoday/agents/retrieval_agent.py."""

from __future__ import annotations

import logging
import math
import os
from typing import Any

logger = logging.getLogger(__name__)

_reranker = None
_reranker_failed = False

ORIGINAL_WEIGHT = 0.4
RERANK_WEIGHT = 0.6


def rerank_enabled() -> bool:
    return os.getenv("RERANK_ENABLED", "false").lower() in ("1", "true", "yes")


def _get_reranker():
    global _reranker, _reranker_failed
    if _reranker_failed:
        return None
    if _reranker is not None:
        return _reranker
    try:
        from sentence_transformers import CrossEncoder

        model_name = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-12-v2")
        logger.info("Loading reranker: %s", model_name)
        _reranker = CrossEncoder(model_name)
        return _reranker
    except Exception as exc:
        logger.warning("Reranker unavailable: %s", exc)
        _reranker_failed = True
        return None


def rerank_results(
    query: str,
    results: list[dict[str, Any]],
    *,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Переранжировать кандидатов; при ошибке — исходный top_k."""
    model = _get_reranker()
    if not model or len(results) < 2:
        return results[:top_k]

    try:
        pairs = []
        for row in results:
            meta = row.get("metadata") or {}
            title = meta.get("title") or row.get("title") or ""
            text = row.get("text") or meta.get("text") or ""
            pairs.append([query, f"{title} {text[:500]}".strip()])

        scores = model.predict(pairs)
        for i, row in enumerate(results):
            original = float(row.get("score", 0.0))
            rerank_raw = float(scores[i])
            normalized = 1.0 / (1.0 + math.exp(-rerank_raw))
            row["original_score"] = original
            row["rerank_score"] = normalized
            row["score"] = ORIGINAL_WEIGHT * original + RERANK_WEIGHT * normalized

        ranked = sorted(results, key=lambda x: x.get("score", 0.0), reverse=True)
        return ranked[:top_k]
    except Exception as exc:
        logger.warning("Rerank failed: %s", exc)
        return results[:top_k]
