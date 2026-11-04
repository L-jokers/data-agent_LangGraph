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
    version_id: str | None = None
    grain: str | None = None
    period: str | None = None
    business_scope: str | None = None
    aggregation: str | None = None
    stage: str | None = None
    allowed_dimensions: list[str] | None = None
    expression_ast: dict | None = None
