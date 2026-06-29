"""Демо-PDF для авто-индексации при старте и lazy-load по doc_id."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

SAMPLE_DOC_PDFS: dict[str, Path] = {
    "doc-giab-ni-cu-flotation-water": REPO_ROOT / "data" / "samples" / "giab-ni-cu-flotation-water.pdf",
}

SAMPLE_DOC_META: dict[str, dict[str, str]] = {
    "doc-giab-ni-cu-flotation-water": {
        "title": "giab-ni-cu-flotation-water",
        "doc_type": "report",
    },
}
