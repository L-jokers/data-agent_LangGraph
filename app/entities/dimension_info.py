from dataclasses import dataclass, field


@dataclass
class DimensionInfo:
    id: str
    name: str
    table_id: str
    column_id: str
    aliases: list[str] = field(default_factory=list)
    version_id: str | None = None
