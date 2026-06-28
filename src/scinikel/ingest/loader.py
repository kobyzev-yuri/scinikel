"""Загрузка данных из JSON/CSV в граф знаний."""

import json
import re
from pathlib import Path
from uuid import uuid4

from scinikel.graph.networkx_store import NetworkXGraphStore, new_relation
from scinikel.models.entities import (
    Conclusion,
    Document,
    EntityType,
    Equipment,
    Experiment,
    ExperimentRecord,
    Material,
    Mode,
    Property,
    RelationType,
    Team,
    Topic,
)


def slugify(text: str) -> str:
    base = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_]+", "-", base.strip())[:64]


def _ensure_entity(store: NetworkXGraphStore, cache: dict, key: str, factory):
    if key not in cache:
        entity = factory()
        store.add_entity(entity)
        cache[key] = entity.id
    return cache[key]


def load_experiments(store: NetworkXGraphStore, path: Path) -> int:
    records = [ExperimentRecord.model_validate(r) for r in json.loads(path.read_text(encoding="utf-8"))]
    entity_cache: dict[str, str] = {}
    count = 0

    for rec in records:
        mat_id = _ensure_entity(
            store,
            entity_cache,
            f"mat:{rec.material}",
            lambda m=rec.material: Material(id=f"mat-{slugify(m)}", name=m),
        )
        mode_id = _ensure_entity(
            store,
            entity_cache,
            f"mode:{rec.mode}",
            lambda m=rec.mode: Mode(id=f"mode-{slugify(m)}", name=m),
        )
        prop_id = _ensure_entity(
            store,
            entity_cache,
            f"prop:{rec.property_name}",
            lambda p=rec.property_name: Property(id=f"prop-{slugify(p)}", name=p),
        )

        exp = Experiment(
            id=rec.id,
            name=rec.title,
            description=rec.conclusion,
            attributes={"date": str(rec.date) if rec.date else None},
            source_refs=[rec.document_ref] if rec.document_ref else [],
        )
        store.add_entity(exp)

        store.add_relation(new_relation(RelationType.USES_MATERIAL, exp.id, mat_id))
        store.add_relation(new_relation(RelationType.AT_MODE, exp.id, mode_id))
        store.add_relation(
            new_relation(
                RelationType.MEASURES,
                exp.id,
                prop_id,
                value=rec.property_value,
                delta=rec.property_delta,
            )
        )

        if rec.equipment:
            eq_id = _ensure_entity(
                store,
                entity_cache,
                f"eq:{rec.equipment}",
                lambda e=rec.equipment: Equipment(id=f"eq-{slugify(e)}", name=e),
            )
            store.add_relation(new_relation(RelationType.ON_EQUIPMENT, exp.id, eq_id))

        if rec.team:
            team_id = _ensure_entity(
                store,
                entity_cache,
                f"team:{rec.team}",
                lambda t=rec.team: Team(id=f"team-{slugify(t)}", name=t),
            )
            store.add_relation(new_relation(RelationType.CONDUCTED_BY, exp.id, team_id))

        if rec.conclusion:
            concl_id = f"concl-{rec.id}"
            store.add_entity(
                Conclusion(id=concl_id, name=f"Вывод {rec.id}", description=rec.conclusion)
            )
            store.add_relation(new_relation(RelationType.CONCLUDES, exp.id, concl_id))

        if rec.document_ref:
            doc_key = f"doc:{rec.document_ref}"
            if doc_key not in entity_cache:
                store.add_entity(
                    Document(
                        id=rec.document_ref,
                        name=rec.document_ref,
                        description="Ссылка из каталога экспериментов",
                    )
                )
                entity_cache[doc_key] = rec.document_ref
            store.add_relation(new_relation(RelationType.DESCRIBES, rec.document_ref, exp.id))

        for topic_name in rec.topics:
            topic_id = _ensure_entity(
                store,
                entity_cache,
                f"topic:{topic_name}",
                lambda tn=topic_name: Topic(id=f"topic-{slugify(tn)}", name=tn),
            )
            store.add_relation(new_relation(RelationType.TAGGED, exp.id, topic_id))

        count += 1

    return count


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
        existing = store.get_entity(doc.id)
        if existing:
            store.add_entity(doc)  # overwrite node data via re-add
        else:
            store.add_entity(doc)
        count += 1
    return count


def ingest_seed_data(store: NetworkXGraphStore, seed_dir: Path) -> dict[str, int]:
    stats = {"experiments": 0, "documents": 0}
    exp_path = seed_dir / "experiments.json"
    doc_path = seed_dir / "documents.json"
    if exp_path.exists():
        stats["experiments"] = load_experiments(store, exp_path)
    if doc_path.exists():
        stats["documents"] = load_documents(store, doc_path)
    return stats
