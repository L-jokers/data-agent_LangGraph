from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QueryLimits:
    max_rows: int = 100
    timeout_seconds: float = 10.0
    max_execution_time_ms: int = 5000


@dataclass(frozen=True)
class QueryResult:
    rows: list[dict[str, Any]]
    truncated: bool
    row_count: int
    max_rows: int
