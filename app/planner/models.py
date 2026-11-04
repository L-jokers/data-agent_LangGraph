from dataclasses import dataclass, field
from typing import Any


class QueryPlanError(ValueError):
    pass


@dataclass(frozen=True)
class MetricPlan:
    id: str
    name: str
    metric_type: str
    expression: str | None
    numerator: str | None
    denominator: str | None
    aliases: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    grain: str | None = None
    aggregation: str | None = None
    stage: str | None = None
    expression_ast: dict[str, Any] | None = None
    source_columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class DimensionPlan:
    id: str
    name: str
    table: str
    column: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class JoinPlan:
    relationship_id: str
    source: str
    target: str
    cardinality: str


@dataclass(frozen=True)
class FilterPlan:
    field_id: str
    table: str
    column: str
    operator: str
    value: Any


@dataclass(frozen=True)
class TimeConditionPlan:
    field: str
    operator: str
    value: Any


@dataclass(frozen=True)
class TimePlan:
    dimension_id: str
    table: str
    grain: str
    start: str
    end: str
    conditions: tuple[TimeConditionPlan, ...]
    condition_groups: tuple[tuple[TimeConditionPlan, ...], ...] = ()


@dataclass(frozen=True)
class OrderPlan:
    field_id: str
    direction: str


@dataclass(frozen=True)
class QueryPlan:
    dataset_id: str
    fact_table: str
    metrics: tuple[MetricPlan, ...]
    dimensions: tuple[DimensionPlan, ...]
    joins: tuple[JoinPlan, ...]
    filters: tuple[FilterPlan, ...]
    time: TimePlan | None
    order_by: tuple[OrderPlan, ...]
    limit: int
    limit_explicit: bool = False
    aggregations: dict[str, str] = field(default_factory=dict)
    semantic_version_id: str | None = None
    expression_asts: dict[str, dict[str, Any]] = field(default_factory=dict)
    metric_dependencies: dict[str, tuple[str, ...]] = field(default_factory=dict)
    metric_source_columns: dict[str, tuple[str, ...]] = field(default_factory=dict)
