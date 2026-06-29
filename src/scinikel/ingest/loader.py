"""Загрузка данных из JSON/XLSX в граф знаний."""

import json
from pathlib import Path

from scinikel.graph.networkx_store import NetworkXGraphStore
from scinikel.ingest.graph_materializer import add_experiment_record, slugify
from scinikel.models.entities import Document, Equipment, Material, Team, Topic


def load_experiments(store: NetworkXGraphStore, path: Path) -> int:
    from scinikel.models.entities import ExperimentRecord

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


def load_references(store: NetworkXGraphStore, ref_dir: Path) -> dict[str, int]:
    """Справочники материалов, оборудования, команд, тематик."""
    stats = {"materials": 0, "equipment": 0, "teams": 0, "topics": 0}

    mat_path = ref_dir / "materials.json"
    if mat_path.exists():
        for raw in json.loads(mat_path.read_text(encoding="utf-8")):
            eid = raw.get("id") or f"mat-{slugify(raw['name'])}"
            store.add_entity(
                Material(
                    id=eid,
                    name=raw["name"],
                    description=raw.get("composition"),
                    attributes={k: v for k, v in raw.items() if k not in ("id", "name", "composition")},
                )
            )
            stats["materials"] += 1

    eq_path = ref_dir / "equipment.json"
    if eq_path.exists():
        for raw in json.loads(eq_path.read_text(encoding="utf-8")):
            eid = raw.get("id") or f"eq-{slugify(raw['name'])}"
            store.add_entity(
                Equipment(
                    id=eid,
                    name=raw["name"],
                    description=raw.get("capabilities"),
                    attributes={k: v for k, v in raw.items() if k not in ("id", "name", "capabilities")},
                )
            )
            stats["equipment"] += 1

    team_path = ref_dir / "teams.json"
    if team_path.exists():
        for raw in json.loads(team_path.read_text(encoding="utf-8")):
            eid = raw.get("id") or f"team-{slugify(raw['name'])}"
            store.add_entity(
                Team(
                    id=eid,
                    name=raw["name"],
                    attributes={k: v for k, v in raw.items() if k not in ("id", "name")},
                )
            )
            stats["teams"] += 1

    topic_path = ref_dir / "topics.json"
    if topic_path.exists():
        for raw in json.loads(topic_path.read_text(encoding="utf-8")):
            name = raw["name"] if isinstance(raw, dict) else raw
            eid = f"topic-{slugify(name)}"
            store.add_entity(Topic(id=eid, name=name))
            stats["topics"] += 1

    return stats


def ingest_seed_data(store: NetworkXGraphStore, seed_dir: Path) -> dict[str, int]:
    stats: dict[str, int] = {"experiments": 0, "documents": 0}
    ref_dir = seed_dir / "references"
    if ref_dir.exists():
        stats.update(load_references(store, ref_dir))

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
