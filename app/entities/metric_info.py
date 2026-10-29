from dataclasses import dataclass


@dataclass
class MetricInfo:
    id: str
    name: str
    description: str
    relevant_columns: list[str]
    alias: list[str]
    metric_type: str | None = None
    expression: str | None = None
    numerator: str | None = None
    denominator: str | None = None
    base_dataset: str | None = None
    status: str = "active"
