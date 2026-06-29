"""Материализация ExperimentRecord и extraction JSON в граф знаний."""

import re
from uuid import uuid4

from scinikel.graph.networkx_store import NetworkXGraphStore, new_relation
from scinikel.models.entities import (
    Conclusion,
    Document,
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


def doc_id_from_title(title: str) -> str:
    """Стабильный id документа для индекса и графа (из имени файла / заголовка)."""
    return f"doc-{slugify(title)}"


def _ensure_entity(store: NetworkXGraphStore, cache: dict[str, str], key: str, factory):
    if key not in cache:
        entity = factory()
        store.add_entity(entity)
        cache[key] = entity.id
    return cache[key]


def add_experiment_record(
    store: NetworkXGraphStore,
    rec: ExperimentRecord,
    entity_cache: dict[str, str] | None = None,
) -> str:
    cache = entity_cache if entity_cache is not None else {}

    mat_id = _ensure_entity(
        store,
        cache,
        f"mat:{rec.material}",
        lambda m=rec.material: Material(id=f"mat-{slugify(m)}", name=m),
    )
    mode_id = _ensure_entity(
        store,
        cache,
        f"mode:{rec.mode}",
        lambda m=rec.mode: Mode(id=f"mode-{slugify(m)}", name=m),
    )
    prop_id = _ensure_entity(
        store,
        cache,
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
            cache,
            f"eq:{rec.equipment}",
            lambda e=rec.equipment: Equipment(id=f"eq-{slugify(e)}", name=e),
        )
        store.add_relation(new_relation(RelationType.ON_EQUIPMENT, exp.id, eq_id))

    if rec.team:
        team_id = _ensure_entity(
            store,
            cache,
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
        if doc_key not in cache:
            store.add_entity(
                Document(
                    id=rec.document_ref,
                    name=rec.document_ref,
                    description="Ссылка из каталога экспериментов",
                )
            )
            cache[doc_key] = rec.document_ref
        store.add_relation(new_relation(RelationType.DESCRIBES, rec.document_ref, exp.id))

    for topic_name in rec.topics:
        topic_id = _ensure_entity(
            store,
            cache,
            f"topic:{topic_name}",
            lambda tn=topic_name: Topic(id=f"topic-{slugify(tn)}", name=tn),
        )
        store.add_relation(new_relation(RelationType.TAGGED, exp.id, topic_id))

    return exp.id


def materialize_extraction(store: NetworkXGraphStore, extraction: dict) -> dict[str, int]:
    """Загрузка результата CuratorAgent в граф."""
    cache: dict[str, str] = {}
    stats = {"documents": 0, "experiments": 0}

    doc_raw = extraction.get("document") or {}
    if doc_raw.get("id") or doc_raw.get("title"):
        doc_id = doc_raw.get("id") or f"doc-{slugify(doc_raw.get('title', 'unknown'))}"
        store.add_entity(
            Document(
                id=doc_id,
                name=doc_raw.get("title", doc_id),
                description=doc_raw.get("abstract"),
                attributes={
                    "doc_type": doc_raw.get("doc_type", "report"),
                    "authors": doc_raw.get("authors", []),
                },
                source_refs=[doc_id],
            )
        )
        cache[f"doc:{doc_id}"] = doc_id
        stats["documents"] += 1

    for exp_raw in extraction.get("experiments", []):
        if not exp_raw.get("material") or not exp_raw.get("mode"):
            continue
        rec = ExperimentRecord(
            id=exp_raw.get("id") or f"EXP-{uuid4().hex[:8]}",
            title=exp_raw.get("title") or exp_raw.get("id") or "Эксперимент",
            material=exp_raw["material"],
            mode=exp_raw["mode"],
            property_name=exp_raw.get("property_name") or "результат",
            property_value=str(exp_raw.get("property_value") or "?"),
            property_delta=exp_raw.get("property_delta"),
            equipment=exp_raw.get("equipment"),
            team=exp_raw.get("team"),
            conclusion=exp_raw.get("conclusion"),
            document_ref=exp_raw.get("document_ref") or doc_raw.get("id"),
            topics=exp_raw.get("topics") or extraction.get("topics") or [],
        )
        add_experiment_record(store, rec, cache)
        stats["experiments"] += 1

    return stats
