from abc import ABC, abstractmethod
from typing import Any

from scinikel.models.entities import Entity, EntityType, Relation, RelationType


class GraphStore(ABC):
    @abstractmethod
    def add_entity(self, entity: Entity) -> None: ...

    @abstractmethod
    def add_relation(self, relation: Relation) -> None: ...

    @abstractmethod
    def get_entity(self, entity_id: str) -> Entity | None: ...

    @abstractmethod
    def find_entities(
        self,
        *,
        entity_type: EntityType | None = None,
        name_contains: str | None = None,
        limit: int = 50,
    ) -> list[Entity]: ...

    @abstractmethod
    def neighbors(
        self,
        entity_id: str,
        *,
        relation_type: RelationType | None = None,
        direction: str = "both",
    ) -> list[tuple[Relation, Entity]]: ...

    @abstractmethod
    def traverse(
        self,
        start_id: str,
        path: list[RelationType],
        max_depth: int = 3,
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    def export_json(self) -> dict[str, Any]: ...

    @abstractmethod
    def import_json(self, data: dict[str, Any]) -> None: ...

    @abstractmethod
    def stats(self) -> dict[str, int]: ...
