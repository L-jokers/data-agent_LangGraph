from dataclasses import dataclass


@dataclass
class MetricDependency:
    metric_id: str
    depends_on_metric_id: str
    dependency_order: int = 0
    version_id: str | None = None
