from dataclasses import dataclass


@dataclass
class TableInfo:
    id: str
    name: str
    role: str
    description: str
    version_id: str | None = None
