import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import networkx as nx

from scinikel.graph.base import GraphStore
from scinikel.models.entities import Entity, EntityType, Relation, RelationType


class NetworkXGraphStore(GraphStore):
    """In-memory graph — быстрый старт для хакатона, легко заменить на Neo4j."""

    def __init__(self) -> None:
        self._g = nx.MultiDiGraph()
        self._entities: dict[str, Entity] = {}

    def add_entity(self, entity: Entity) -> None:
        self._entities[entity.id] = entity
        self._g.add_node(entity.id, type=entity.type.value, name=entity.name)

    def add_relation(self, relation: Relation) -> None:
        if relation.source_id not in self._entities or relation.target_id not in self._entities:
            raise ValueError(f"Unknown entity in relation {relation.id}")
        self._g.add_edge(
            relation.source_id,
            relation.target_id,
            key=relation.id,
            type=relation.type.value,
            **relation.properties,
        )

    def get_entity(self, entity_id: str) -> Entity | None:
        return self._entities.get(entity_id)

    def find_entities(
        self,
        *,
        entity_type: EntityType | None = None,
        name_contains: str | None = None,
        limit: int = 50,
    ) -> list[Entity]:
        results: list[Entity] = []
        needle = name_contains.lower() if name_contains else None
        for entity in self._entities.values():
            if entity_type and entity.type != entity_type:
                continue
            if needle and needle not in entity.name.lower():
                desc = (entity.description or "").lower()
                if needle not in desc:
                    continue
            results.append(entity)
            if len(results) >= limit:
                break
        return results

    def neighbors(
        self,
        entity_id: str,
        *,
        relation_type: RelationType | None = None,
        direction: str = "both",
    ) -> list[tuple[Relation, Entity]]:
        if entity_id not in self._entities:
            return []

        pairs: list[tuple[Relation, Entity]] = []

        if direction in ("out", "both"):
            for _, target, key, data in self._g.out_edges(entity_id, keys=True, data=True):
                rel_type = RelationType(data["type"])
                if relation_type and rel_type != relation_type:
                    continue
                target_entity = self._entities.get(target)
                if target_entity:
                    props = {k: v for k, v in data.items() if k != "type"}
                    pairs.append(
                        (
                            Relation(
                                id=key,
                                type=rel_type,
                                source_id=entity_id,
                                target_id=target,
                                properties=props,
                            ),
                            target_entity,
                        )
                    )

        if direction in ("in", "both"):
            for source, _, key, data in self._g.in_edges(entity_id, keys=True, data=True):
                rel_type = RelationType(data["type"])
                if relation_type and rel_type != relation_type:
                    continue
                source_entity = self._entities.get(source)
                if source_entity:
                    props = {k: v for k, v in data.items() if k != "type"}
                    pairs.append(
                        (
                            Relation(
                                id=key,
                                type=rel_type,
                                source_id=source,
                                target_id=entity_id,
                                properties=props,
                            ),
                            source_entity,
                        )
                    )

        return pairs

    def traverse(
        self,
        start_id: str,
        path: list[RelationType],
        max_depth: int = 3,
    ) -> list[dict[str, Any]]:
        if start_id not in self._entities:
            return []

        results: list[dict[str, Any]] = []
        start = self._entities[start_id]

        def walk(current_id: str, depth: int, chain: list[tuple[str, str, Relation]]) -> None:
            if depth >= min(len(path), max_depth):
                results.append(
                    {
                        "chain": [
                            {
                                "relation": r.type.value,
                                "entity": self._entities[eid].model_dump(),
                                **({"properties": r.properties} if r.properties else {}),
                            }
                            for eid, _, r in chain
                        ],
                        "start": start.model_dump(),
                    }
                )
                return

            expected = path[depth]
            for rel, neighbor in self.neighbors(current_id, relation_type=expected, direction="out"):
                walk(neighbor.id, depth + 1, chain + [(neighbor.id, neighbor.name, rel)])

        walk(start_id, 0, [])
        return results

    def query_experiments_by_context(
        self,
        *,
        material: str | None = None,
        mode: str | None = None,
        property_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Ключевой паттерн хакатона: материал × режим → эффект на свойство."""
        experiments = self.find_entities(entity_type=EntityType.EXPERIMENT, limit=500)
        matched: list[dict[str, Any]] = []

        for exp in experiments:
            ctx = self._experiment_context(exp.id)
            if material and not _fuzzy_match(material, ctx.get("materials", [])):
                continue
            if mode and not _fuzzy_match(mode, ctx.get("modes", [])):
                continue
            if property_name and not _fuzzy_match(property_name, ctx.get("properties", [])):
                continue
            matched.append({"experiment": exp.model_dump(), **ctx})

        return matched

    def query_who_did_what(self, topic: str | None = None) -> list[dict[str, Any]]:
        """Кто занимался темой и на какой установке."""
        experiments = self.find_entities(entity_type=EntityType.EXPERIMENT, limit=500)
        matched: list[dict[str, Any]] = []

        for exp in experiments:
            ctx = self._experiment_context(exp.id)
            if not ctx.get("teams") and not ctx.get("equipment"):
                continue
            if topic and not _topic_matches(topic, exp, ctx):
                continue
            matched.append({"experiment": exp.model_dump(), **ctx})

        return matched

    def _experiment_context(self, experiment_id: str) -> dict[str, Any]:
        ctx: dict[str, Any] = {
            "materials": [],
            "modes": [],
            "properties": [],
            "measurements": [],
            "equipment": [],
            "teams": [],
            "conclusions": [],
            "documents": [],
            "topics": [],
        }
        for rel, entity in self.neighbors(experiment_id):
            bucket = _relation_bucket(rel.type)
            if bucket:
                entry: Any = entity.model_dump()
                if rel.type == RelationType.MEASURES:
                    entry = {**entry, "measurement": rel.properties}
                    ctx["measurements"].append(rel.properties)
                ctx[bucket].append(entry)
        return ctx

    def find_gaps(
        self,
        materials: list[str] | None = None,
        modes: list[str] | None = None,
    ) -> list[dict[str, str]]:
        """Пробелы: комбинации material×mode без экспериментов."""
        mat_entities = self.find_entities(entity_type=EntityType.MATERIAL, limit=200)
        mode_entities = self.find_entities(entity_type=EntityType.MODE, limit=200)

        if materials:
            mat_entities = [e for e in mat_entities if _fuzzy_match_any(materials, [e.name])]
        if modes:
            mode_entities = [e for e in mode_entities if _fuzzy_match_any(modes, [e.name])]

        covered: set[tuple[str, str]] = set()
        for exp in self.find_entities(entity_type=EntityType.EXPERIMENT, limit=500):
            ctx = self._experiment_context(exp.id)
            for m in ctx["materials"]:
                for mo in ctx["modes"]:
                    covered.add((m["name"], mo["name"]))

        gaps = []
        for m in mat_entities:
            for mo in mode_entities:
                if (m.name, mo.name) not in covered:
                    gaps.append({"material": m.name, "mode": mo.name, "status": "not_studied"})
        return gaps

    def subgraph(self, center_id: str, depth: int = 2) -> dict[str, Any]:
        nodes: dict[str, dict] = {}
        edges: list[dict] = []
        visited: set[str] = set()

        def expand(eid: str, d: int) -> None:
            if d > depth or eid in visited:
                return
            visited.add(eid)
            entity = self._entities.get(eid)
            if entity:
                nodes[eid] = {
                    "id": eid,
                    "label": entity.name,
                    "type": entity.type.value,
                }
            for rel, neighbor in self.neighbors(eid):
                edges.append(
                    {
                        "id": rel.id,
                        "source": rel.source_id,
                        "target": rel.target_id,
                        "label": rel.type.value,
                    }
                )
                expand(neighbor.id, d + 1)

        expand(center_id, 0)
        return {"nodes": list(nodes.values()), "edges": edges}

    def export_json(self) -> dict[str, Any]:
        return {
            "entities": [e.model_dump() for e in self._entities.values()],
            "relations": self._export_relations(),
        }

    def _export_relations(self) -> list[dict[str, Any]]:
        relations: list[dict[str, Any]] = []
        for source, target, key, data in self._g.edges(keys=True, data=True):
            props = {k: v for k, v in data.items() if k != "type"}
            relations.append(
                {
                    "id": key,
                    "type": data["type"],
                    "source_id": source,
                    "target_id": target,
                    "properties": props,
                }
            )
        return relations

    def import_json(self, data: dict[str, Any]) -> None:
        self._g.clear()
        self._entities.clear()
        for raw in data.get("entities", []):
            self.add_entity(Entity.model_validate(raw))
        for raw in data.get("relations", []):
            self.add_relation(Relation.model_validate(raw))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.export_json(), ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, path: Path) -> None:
        if path.exists():
            self.import_json(json.loads(path.read_text(encoding="utf-8")))

    def stats(self) -> dict[str, int]:
        by_type: dict[str, int] = {}
        for entity in self._entities.values():
            by_type[entity.type.value] = by_type.get(entity.type.value, 0) + 1
        return {
            "entities": len(self._entities),
            "relations": self._g.number_of_edges(),
            **{f"entity_{k}": v for k, v in by_type.items()},
        }


def _relation_bucket(rel_type: RelationType) -> str | None:
    return {
        RelationType.USES_MATERIAL: "materials",
        RelationType.AT_MODE: "modes",
        RelationType.MEASURES: "properties",
        RelationType.ON_EQUIPMENT: "equipment",
        RelationType.CONDUCTED_BY: "teams",
        RelationType.CONCLUDES: "conclusions",
        RelationType.DESCRIBES: "documents",
        RelationType.TAGGED: "topics",
    }.get(rel_type)


def _tokenize(text: str) -> set[str]:
    return {t for t in re.findall(r"[\w]+", text.lower()) if len(t) > 1 or t.isdigit()}


def _fuzzy_match(needle: str, haystack: list[dict[str, Any]]) -> bool:
    n = needle.lower()
    n_tokens = _tokenize(n)
    for item in haystack:
        name = item.get("name", "").lower()
        if n in name or name in n:
            return True
        overlap = n_tokens & _tokenize(name)
        if len(overlap) >= 2:
            return True
        if overlap and any(len(t) > 3 for t in overlap):
            return True
        # химические символы и короткие ключевые токены
        if overlap & {"ni", "cu", "ph"}:
            return True
        # общий корень для склонений: флотация / флотации
        for nt in n_tokens:
            for name_token in _tokenize(name):
                if len(nt) >= 5 and len(name_token) >= 5 and nt[:5] == name_token[:5]:
                    return True
    return False


def _fuzzy_match_any(needles: list[str], names: list[str]) -> bool:
    return any(_fuzzy_match(needle, [{"name": name} for name in names]) for needle in needles)


def _topic_matches(topic: str, exp: Entity, ctx: dict[str, Any]) -> bool:
    haystack = " ".join(
        [
            exp.name,
            exp.description or "",
            *[m.get("name", "") for m in ctx.get("materials", [])],
            *[m.get("name", "") for m in ctx.get("modes", [])],
            *[t.get("name", "") for t in ctx.get("topics", [])],
        ]
    )
    return _fuzzy_match(topic, [{"name": haystack}])


def new_relation(
    rel_type: RelationType,
    source_id: str,
    target_id: str,
    **properties: Any,
) -> Relation:
    return Relation(
        id=str(uuid4()),
        type=rel_type,
        source_id=source_id,
        target_id=target_id,
        properties=properties,
    )
