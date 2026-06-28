"""Загрузка данных из JSON/XLSX в граф знаний."""

import json
from pathlib import Path

from scinikel.graph.networkx_store import NetworkXGraphStore
from scinikel.ingest.graph_materializer import add_experiment_record
from scinikel.models.entities import Document, ExperimentRecord


def load_experiments(store: NetworkXGraphStore, path: Path) -> int:
    records = [ExperimentRecord.model_validate(r) for r in json.loads(path.read_text(encoding="utf-8"))]
    entity_cache: dict[str, str] = {}
    for rec in records:
        add_experiment_record(store, rec, entity_cache)
    return len(records)


def load_experiments_xlsx(store: NetworkXGraphStore, path: Path) -> int:
    from scinikel.ingest.xlsx_parser import parse_xlsx

    records = parse_xlsx(path)
    entity_cache: dict[str, str] = {}
    for rec in records:
        add_experiment_record(store, rec, entity_cache)
    return len(records)


def load_documents(store: NetworkXGraphStore, path: Path) -> int:
    docs = json.loads(path.read_text(encoding="utf-8"))
    count = 0
    for raw in docs:
        doc = Document(
            id=raw["id"],
            name=raw["title"],
            description=raw.get("abstract"),
            attributes={
                "doc_type": raw.get("doc_type"),
                "year": raw.get("year"),
                "authors": raw.get("authors", []),
            },
            source_refs=[raw["id"]],
        )
        store.add_entity(doc)
        count += 1
    return count


def ingest_seed_data(store: NetworkXGraphStore, seed_dir: Path) -> dict[str, int]:
    stats = {"experiments": 0, "documents": 0}
    exp_path = seed_dir / "experiments.json"
    xlsx_path = seed_dir / "experiments.xlsx"
    doc_path = seed_dir / "documents.json"

    if exp_path.exists():
        stats["experiments"] = load_experiments(store, exp_path)
    elif xlsx_path.exists():
        stats["experiments"] = load_experiments_xlsx(store, xlsx_path)

    if doc_path.exists():
        stats["documents"] = load_documents(store, doc_path)
    return stats
