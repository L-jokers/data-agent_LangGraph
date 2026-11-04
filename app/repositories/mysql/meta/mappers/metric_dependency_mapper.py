from dataclasses import asdict

from app.entities.metric_dependency import MetricDependency
from app.models.metric_dependency_mysql import MetricDependencyMySQL


class MetricDependencyMapper:
    @staticmethod
    def to_model(entity: MetricDependency) -> MetricDependencyMySQL:
        return MetricDependencyMySQL(**asdict(entity))
