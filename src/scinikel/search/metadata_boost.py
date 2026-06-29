"""Бустинг score по metadata — адаптация 3dtoday/rag_service.hybrid_search."""

from __future__ import annotations

from typing import Any

# scinikel: experiment_ids / doc_type вместо printer_models / problem_type
BOOST_PER_MATCH = 0.1
BOOST_EXPERIMENT_MATCH = 0.15
MAX_SCORE = 1.0


def apply_metadata_boost(
    results: list[dict[str, Any]],
    filters: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not filters or not results:
        return results

    boosted: list[dict[str, Any]] = []
    for item in results:
        row = dict(item)
        meta = row.get("metadata") or row
        score = float(row.get("score", 0.0))
        boost = 0.0

        doc_type = filters.get("doc_type")
        if doc_type and meta.get("doc_type") == doc_type:
            boost += BOOST_PER_MATCH

        wanted_experiments = filters.get("experiment_ids") or []
        if wanted_experiments:
            payload_exps = meta.get("experiment_ids") or []
            if isinstance(payload_exps, str):
                payload_exps = [payload_exps]
            if any(eid in payload_exps for eid in wanted_experiments):
                boost += BOOST_EXPERIMENT_MATCH
            elif meta.get("experiment_id") in wanted_experiments:
                boost += BOOST_EXPERIMENT_MATCH

        if boost > 0:
            row["score"] = min(score + boost, MAX_SCORE)
            row["boost_applied"] = boost
        boosted.append(row)

    boosted.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return boosted
