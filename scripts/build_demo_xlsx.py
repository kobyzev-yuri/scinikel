#!/usr/bin/env python3
"""Сборка experiments.xlsx из experiments.json для демо и тестов upload."""

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data" / "seed"
JSON_PATH = SEED / "experiments.json"
XLSX_PATH = SEED / "experiments.xlsx"


def build_xlsx() -> Path:
    records = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    rows = []
    for r in records:
        rows.append(
            {
                "id": r["id"],
                "title": r["title"],
                "date": r.get("date"),
                "material": r["material"],
                "mode": r["mode"],
                "property_name": r["property_name"],
                "property_value": r["property_value"],
                "property_delta": r.get("property_delta"),
                "equipment": r.get("equipment"),
                "team": r.get("team"),
                "conclusion": r.get("conclusion"),
                "document_ref": r.get("document_ref"),
                "topics": ", ".join(r.get("topics", [])),
            }
        )
    df = pd.DataFrame(rows)
    XLSX_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(XLSX_PATH, index=False, sheet_name="experiments")
    return XLSX_PATH


if __name__ == "__main__":
    path = build_xlsx()
    print(f"Written {path} ({len(json.loads(JSON_PATH.read_text()))} rows)")
