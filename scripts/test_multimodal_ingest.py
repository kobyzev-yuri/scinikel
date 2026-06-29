#!/usr/bin/env python3
"""Smoke-тест мультимодального ingest: vision status, PDF, поиск по картинкам."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="Test scinikel multimodal ingest")
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="API base URL")
    parser.add_argument("--pdf", type=Path, help="PDF file to ingest")
    parser.add_argument("--query", default="график извлечения никеля", help="CLIP image search query")
    parser.add_argument("--no-vision", action="store_true", help="Skip Gemini/llava on ingest")
    parser.add_argument("--no-clip", action="store_true", help="Skip CLIP image index")
    parser.add_argument("--dry-run", action="store_true", help="Curate only, do not ingest to graph")
    args = parser.parse_args()

    base = args.api.rstrip("/")
    client = httpx.Client(timeout=300.0)

    print("=== Vision / CLIP status ===")
    r = client.get(f"{base}/api/vision/status")
    if r.status_code == 404:
        print(
            "Ошибка: /api/vision/status не найден (404).\n"
            "Сервер на порту 8000 запущен со старой версией кода — перезапустите API:\n"
            "  ./scripts/services.sh restart\n"
            "или: ./scripts/services.sh stop && ./scripts/services.sh start --api-only",
            file=sys.stderr,
        )
        return 2
    r.raise_for_status()
    status = r.json()
    print(json.dumps(status, ensure_ascii=False, indent=2))

    cfg: dict = {}
    try:
        cfg = client.get(f"{base}/api/llm/config").json()
        if cfg.get("answer_mode") == "rule":
            print(
                "\n⚠ Режим «Экономный» (answer_mode=rule): куратор без LLM, только эвристики.\n"
                "  Для статей без EXP-* включите «Локальный AI» или «Полный» в UI → Режим работы,\n"
                "  или: curl -X POST .../api/llm/config -d '{\"work_mode\":\"local\"}'",
                file=sys.stderr,
            )
    except Exception:
        pass

    if not args.pdf:
        print("\n(no --pdf provided, stopping after status check)")
        return 0

    if not args.pdf.exists():
        print(f"PDF not found: {args.pdf}", file=sys.stderr)
        return 1

    print(f"\n=== Ingest PDF: {args.pdf.name} ===")
    if not args.no_vision:
        print("  (Vision: 1–3 мин на PDF с картинками — ждите…)")
    params = {
        "analyze_images": str(not args.no_vision).lower(),
        "index_images": str(not args.no_clip).lower(),
        "ingest": str(not args.dry_run).lower(),
    }
    with args.pdf.open("rb") as fh:
        r = client.post(
            f"{base}/api/ingest/pdf",
            params=params,
            files={"file": (args.pdf.name, fh, "application/pdf")},
        )
    if r.status_code >= 400:
        print(r.text, file=sys.stderr)
        r.raise_for_status()
    data = r.json()
    parsed = data.get("parsed") or {}
    extraction = data.get("extraction") or {}
    exps = extraction.get("experiments") or []
    print(f"  images: {parsed.get('images_count')}  vision: {parsed.get('vision_provider')}  used: {parsed.get('vision_images_used')}")
    print(f"  CLIP indexed: {parsed.get('images_indexed')}")
    print(f"  decision: {extraction.get('decision')}  experiments: {len(exps)}")
    method = extraction.get("extraction_method", "?")
    print(f"  curator: {method}", end="")
    if method == "heuristic" and cfg.get("answer_mode") == "llm":
        print("  ⚠ LLM не ответил (timeout?) — попробуйте provider=proxyapi", file=sys.stderr)
    else:
        print()
    if exps:
        for exp in exps[:3]:
            print(f"    - {exp.get('id')}: {exp.get('material')} / {exp.get('mode')} → {exp.get('property_value')}")
    img_analysis = extraction.get("image_analysis")
    if img_analysis and img_analysis.get("image_analyses"):
        print("\n--- Vision excerpts ---")
        for row in img_analysis["image_analyses"][:2]:
            text = (row.get("analysis") or "")[:400]
            print(f"  [{row.get('image_name')}]: {text}...")

    print(f"\n=== Image search: {args.query!r} ===")
    r = client.get(f"{base}/api/search/images", params={"q": args.query, "limit": 3})
    r.raise_for_status()
    hits = r.json()
    print(f"  backend: {hits.get('backend')}  results: {len(hits.get('results') or [])}")
    for hit in hits.get("results") or []:
        print(f"    {hit.get('id')} score={hit.get('score', 0):.3f} {hit.get('text', '')[:60]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
