from datetime import date as DateType
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EntityType(StrEnum):
    MATERIAL = "Material"
    PROPERTY = "Property"
    MODE = "Mode"
    EXPERIMENT = "Experiment"
    DOCUMENT = "Document"
    EQUIPMENT = "Equipment"
    TEAM = "Team"
    CONCLUSION = "Conclusion"
    TOPIC = "Topic"


class RelationType(StrEnum):
    USES_MATERIAL = "USES_MATERIAL"
    AT_MODE = "AT_MODE"
    MEASURES = "MEASURES"
    ON_EQUIPMENT = "ON_EQUIPMENT"
    CONDUCTED_BY = "CONDUCTED_BY"
    CONCLUDES = "CONCLUDES"
    DESCRIBES = "DESCRIBES"
    MENTIONS = "MENTIONS"
    RELATED_TO = "RELATED_TO"
    TAGGED = "TAGGED"


class Entity(BaseModel):
    id: str
    type: EntityType
    name: str
    description: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    source_refs: list[str] = Field(default_factory=list)


class Material(Entity):
    type: EntityType = EntityType.MATERIAL


class Property(Entity):
    type: EntityType = EntityType.PROPERTY


class Mode(Entity):
    type: EntityType = EntityType.MODE


class Experiment(Entity):
    type: EntityType = EntityType.EXPERIMENT


class Document(Entity):
    type: EntityType = EntityType.DOCUMENT


class Equipment(Entity):
    type: EntityType = EntityType.EQUIPMENT


class Team(Entity):
    type: EntityType = EntityType.TEAM


class Conclusion(Entity):
    type: EntityType = EntityType.CONCLUSION


class Topic(Entity):
    type: EntityType = EntityType.TOPIC


class Relation(BaseModel):
    id: str
    type: RelationType
    source_id: str
    target_id: str
    properties: dict[str, Any] = Field(default_factory=dict)


class Measurement(BaseModel):
    """Результат измерения свойства в эксперименте."""

    experiment_id: str
    property_id: str
    value: float | str
    unit: str | None = None
    delta: float | str | None = None
    method: str | None = None


class ExperimentRecord(BaseModel):
    """Плоская запись для импорта из каталога экспериментов."""

    id: str
    title: str
    date: DateType | None = None
    material: str
    mode: str
    property_name: str
    property_value: str
    property_delta: str | None = None
    equipment: str | None = None
    team: str | None = None
    conclusion: str | None = None
    document_ref: str | None = None
    topics: list[str] = Field(default_factory=list)
