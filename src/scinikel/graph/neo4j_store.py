"""Neo4j backend — подключите при получении production-инфраструктуры."""

from typing import Any

from scinikel.config import settings
from scinikel.graph.base import GraphStore
from scinikel.models.entities import Entity, EntityType, Relation, RelationType


class Neo4jGraphStore(GraphStore):
    """
    Заглушка с интерфейсом GraphStore.
    Реализуйте Cypher-запросы по мере развёртывания Neo4j (docker-compose.yml).
    """

    def __init__(self) -> None:
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:
            raise ImportError("Install neo4j: pip install scinikel[neo4j]") from exc

        self._driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )

    def add_entity(self, entity: Entity) -> None:
        raise NotImplementedError("Neo4j backend: implement MERGE on entity.id")

    def add_relation(self, relation: Relation) -> None:
        raise NotImplementedError("Neo4j backend: implement relationship creation")

    def get_entity(self, entity_id: str) -> Entity | None:
        raise NotImplementedError

    def find_entities(
        self,
        *,
        entity_type: EntityType | None = None,
        name_contains: str | None = None,
        limit: int = 50,
    ) -> list[Entity]:
        raise NotImplementedError

    def neighbors(
        self,
        entity_id: str,
        *,
        relation_type: RelationType | None = None,
        direction: str = "both",
    ) -> list[tuple[Relation, Entity]]:
        raise NotImplementedError

    def traverse(
        self,
        start_id: str,
        path: list[RelationType],
        max_depth: int = 3,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    def export_json(self) -> dict[str, Any]:
        raise NotImplementedError

    def import_json(self, data: dict[str, Any]) -> None:
        raise NotImplementedError

    def stats(self) -> dict[str, int]:
        raise NotImplementedError

    def close(self) -> None:
        self._driver.close()
