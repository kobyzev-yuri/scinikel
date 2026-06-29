#!/usr/bin/env python3
"""Проверка релевантности поиска по чанкам (BM25 / Qdrant+e5).

По умолчанию — демо-seed (9 коротких документов).
Для PDF: передайте --pdf (ingest через API) или сначала загрузите на вкладке «База знаний».

  python scripts/test_chunk_search.py --pdf data/samples/giab-ni-cu-flotation-water.pdf
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

# Демо-seed (data/seed/documents.json)
SEED_QUERIES = [
    ("250°C электролиз Ni-Cu", "DOC-2024-089", "EXP-2024-031"),
    ("флотация pH 10.5 извлечение никеля", "DOC-2024-112", "EXP-2024-017"),
    ("EXP-2024-031", "DOC-2024-089", "EXP-2024-031"),
]

# GIAB PDF после ingest (doc_id = doc-{имя файла})
GIAB_DOC_ID = "doc-giab-ni-cu-flotation-water"
PDF_QUERIES = [
    ("ионы жесткости воды флотация никеля", GIAB_DOC_ID, "жесткост"),
    ("извлечение меди никеля медно-никелевые руды", GIAB_DOC_ID, "никел"),
    ("кальция пульпа 27,52 мг", GIAB_DOC_ID, "27,52"),
]


def _norm(s: str) -> str:
    return s.lower().replace("ё", "е")


def _doc_matches(actual: str | None, expected: str | None) -> bool:
    if not expected:
        return True
    return _norm(actual or "") == _norm(expected)


def _token_in_hits(
    results: list[dict],
    expect_doc: str | None,
    expect_token: str | None,
    *,
    top_k: int = 5,
) -> bool:
    if not expect_token:
        return True
    token = _norm(expect_token)
    for row in results[:top_k]:
        if expect_doc and not _doc_matches(row.get("doc_id"), expect_doc):
            continue
        if token in _norm(row.get("text") or ""):
            return True
    return not expect_doc and any(token in _norm(r.get("text") or "") for r in results[:top_k])


def ingest_pdf(
    client: httpx.Client,
    base: str,
    pdf_path: Path,
    *,
    analyze_images: bool = False,
    index_images: bool = False,
) -> dict:
    print(f"\n=== Ingest PDF: {pdf_path.name} ===")
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)
    qs = httpx.QueryParams(
        analyze_images=str(analyze_images).lower(),
        index_images=str(index_images).lower(),
    )
    with pdf_path.open("rb") as fh:
        r = client.post(
            f"{base}/api/ingest/pdf?{qs}",
            files={"file": (pdf_path.name, fh, "application/pdf")},
            timeout=600.0,
        )
    if r.status_code >= 400:
        raise RuntimeError(r.text[:500])
    data = r.json()
    parsed = data.get("parsed") or {}
    print(
        f"  pages={parsed.get('pages_parsed')} vision={parsed.get('vision_images_used')} "
        f"clip={parsed.get('images_indexed')} exps={len((data.get('extraction') or {}).get('experiments') or [])}"
    )
    return data


def run_queries(
    client: httpx.Client,
    base: str,
    queries: list[tuple[str, str | None, str | None]],
    *,
    label: str,
) -> tuple[int, int]:
    ok = 0
    print(f"\n--- {label} ---")
    for query, expect_doc, expect_token in queries:
        print(f"\n=== Query: {query!r} ===")
        r = client.get(f"{base}/api/search/chunks", params={"q": query, "limit": 5})
        r.raise_for_status()
        results = r.json().get("results") or []
        if not results:
            print("  ✗ нет результатов")
            continue
        for i, row in enumerate(results, 1):
            print(
                f"  {i}. score={row.get('score'):.3f} doc={row.get('doc_id')} "
                f"chunk={row.get('chunk_id')} page={row.get('page')}"
            )
            snippet = (row.get("text") or "")[:160].replace("\n", " ")
            print(f"     {snippet}…")
        top = results[0]
        doc_ok = _doc_matches(top.get("doc_id"), expect_doc)
        token_ok = _token_in_hits(results, expect_doc, expect_token)
        if doc_ok and token_ok:
            print("  ✓ релевантность OK")
            ok += 1
        else:
            hints = []
            if not doc_ok:
                hints.append(f"doc={expect_doc}, получили {top.get('doc_id')}")
            if not token_ok:
                hints.append(f"фрагмент с «{expect_token}» среди top-{5}")
            print(f"  ✗ {'; '.join(hints)}")
    return ok, len(queries)


def main() -> int:
    parser = argparse.ArgumentParser(description="Test chunk search relevance")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--query", help="Один запрос вместо набора")
    parser.add_argument(
        "--pdf",
        type=Path,
        help="Ingest PDF перед поиском (напр. data/samples/giab-ni-cu-flotation-water.pdf)",
    )
    parser.add_argument(
        "--pdf-only",
        action="store_true",
        help="Только PDF-запросы (после --pdf или если PDF уже в индексе)",
    )
    parser.add_argument(
        "--with-vision",
        action="store_true",
        help="При --pdf включить Gemini Vision (дольше, больше чанков Vision)",
    )
    parser.add_argument(
        "--set-hybrid",
        action="store_true",
        help="Переключить API на search_mode=hybrid перед тестом",
    )
    args = parser.parse_args()
    base = args.api.rstrip("/")
    client = httpx.Client(timeout=120.0)

    try:
        status = client.get(f"{base}/api/search/status").json()
    except httpx.ConnectError:
        print("API недоступен — ./scripts/services.sh start", file=sys.stderr)
        return 2

    if args.set_hybrid:
        client.post(
            f"{base}/api/llm/config",
            json={"work_mode": "full", "search_mode": "hybrid"},
        )
        status = client.get(f"{base}/api/search/status").json()

    print("=== Search status ===")
    print(json.dumps(status, ensure_ascii=False, indent=2))

    chunk_count = status.get("chunk_count", 0)
    if chunk_count <= 9 and not args.pdf and not args.pdf_only:
        print(
            "\nℹ chunk_count≈9 — в индексе только демо-seed. PDF не загружен.\n"
            "  Загрузите: python scripts/test_chunk_search.py "
            "--pdf data/samples/giab-ni-cu-flotation-water.pdf\n"
            "  или вкладка «База знаний» → PDF. После restart API в режиме keyword — ingest снова.\n"
            "  Режим full + Qdrant: чанки PDF сохраняются в Qdrant между перезапусками.",
            file=sys.stderr,
        )

    if args.pdf:
        ingest_pdf(
            client,
            base,
            args.pdf,
            analyze_images=args.with_vision,
            index_images=args.with_vision,
        )
        status = client.get(f"{base}/api/search/status").json()
        print("\n=== Search status после ingest ===")
        print(json.dumps(status, ensure_ascii=False, indent=2))
        if status.get("chunk_count", 0) <= 9:
            print("⚠ chunk_count не вырос — ingest не проиндексировал текст", file=sys.stderr)

    total_ok = 0
    total_n = 0

    if args.query:
        ok, n = run_queries(client, base, [(args.query, None, None)], label="custom")
        total_ok += ok
        total_n += n
    else:
        if not args.pdf_only:
            ok, n = run_queries(client, base, SEED_QUERIES, label="демо-seed")
            total_ok += ok
            total_n += n
        if args.pdf or args.pdf_only or chunk_count > 12:
            ok, n = run_queries(client, base, PDF_QUERIES, label=f"PDF ({GIAB_DOC_ID})")
            total_ok += ok
            total_n += n
        elif args.pdf_only:
            print("\n✗ --pdf-only: сначала --pdf или загрузите GIAB в UI", file=sys.stderr)
            return 1

    print(f"\nИтого: {total_ok}/{total_n} запросов прошли проверку")
    return 0 if total_ok == total_n else 1


if __name__ == "__main__":
    raise SystemExit(main())
