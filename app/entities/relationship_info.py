from dataclasses import dataclass


@dataclass
class RelationshipInfo:
    id: str
    source: str
    target: str
    cardinality: str
    enabled: bool
    version_id: str | None = None
