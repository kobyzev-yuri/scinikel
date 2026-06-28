"""
XLS/XLSX-парсер каталога экспериментов → ExperimentRecord.
"""

from __future__ import annotations

import logging
from datetime import date as DateType
from pathlib import Path

import pandas as pd

from scinikel.models.entities import ExperimentRecord

logger = logging.getLogger(__name__)

# Маппинг колонок (рус/англ) — расширяйте под формат организаторов
COLUMN_ALIASES: dict[str, list[str]] = {
    "id": ["id", "exp_id", "experiment_id", "номер", "код"],
    "title": ["title", "name", "название", "описание", "experiment"],
    "date": ["date", "дата"],
    "material": ["material", "материал", "сплав", "alloy"],
    "mode": ["mode", "режим", "process", "условия"],
    "property_name": ["property", "property_name", "свойство", "показатель", "metric"],
    "property_value": ["value", "property_value", "значение", "result", "результат"],
    "property_delta": ["delta", "property_delta", "изменение", "effect"],
    "equipment": ["equipment", "установка", "оборудование", "device"],
    "team": ["team", "lab", "лаборатория", "команда", "group"],
    "conclusion": ["conclusion", "вывод", "summary", "comment"],
    "document_ref": ["document", "document_ref", "doc_id", "отчёт", "report"],
    "topics": ["topics", "tags", "теги", "тематика"],
}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    renamed: dict[str, str] = {}
    lower_map = {str(c).strip().lower(): c for c in df.columns}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lower_map:
                renamed[lower_map[alias]] = canonical
                break
    return df.rename(columns=renamed)


def _parse_date(value) -> DateType | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, DateType):
        return value
    try:
        parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.date()
    except Exception:
        return None


def _parse_topics(value) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [t.strip() for t in str(value).replace(";", ",").split(",") if t.strip()]


def parse_xlsx(path: str | Path, sheet_name: str | int = 0) -> list[ExperimentRecord]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    df = pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl")
    df = _normalize_columns(df)

    required = {"id", "material", "mode", "property_name", "property_value"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in {path.name}: {sorted(missing)}")

    records: list[ExperimentRecord] = []
    for idx, row in df.iterrows():
        try:
            title = str(row.get("title") or row["id"]).strip()
            records.append(
                ExperimentRecord(
                    id=str(row["id"]).strip(),
                    title=title,
                    date=_parse_date(row.get("date")),
                    material=str(row["material"]).strip(),
                    mode=str(row["mode"]).strip(),
                    property_name=str(row["property_name"]).strip(),
                    property_value=str(row["property_value"]).strip(),
                    property_delta=str(row["property_delta"]).strip()
                    if pd.notna(row.get("property_delta"))
                    else None,
                    equipment=str(row["equipment"]).strip()
                    if pd.notna(row.get("equipment"))
                    else None,
                    team=str(row["team"]).strip() if pd.notna(row.get("team")) else None,
                    conclusion=str(row["conclusion"]).strip()
                    if pd.notna(row.get("conclusion"))
                    else None,
                    document_ref=str(row["document_ref"]).strip()
                    if pd.notna(row.get("document_ref"))
                    else None,
                    topics=_parse_topics(row.get("topics")),
                )
            )
        except Exception as exc:
            logger.warning("Skip row %s: %s", idx, exc)

    logger.info("Parsed %s experiment records from %s", len(records), path.name)
    return records


def xlsx_to_json(path: str | Path, out_path: str | Path | None = None) -> list[dict]:
    records = parse_xlsx(path)
    data = [r.model_dump(mode="json") for r in records]
    if out_path:
        import json

        out = Path(out_path)
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data
