from dataclasses import asdict

from app.entities.metric_info import MetricInfo
from app.models.metric_info_mysql import MetricInfoMySQL


class MetricInfoMapper:
    @staticmethod
    def to_entity(model: MetricInfoMySQL) -> MetricInfo:
        return MetricInfo(
            id=model.id,
            name=model.name,
            description=model.description,
            relevant_columns=model.relevant_columns,
            alias=model.alias,
            metric_type=model.metric_type,
            expression=model.expression,
            numerator=model.numerator,
            denominator=model.denominator,
            base_dataset=model.base_dataset,
            status=model.status or "active",
            version_id=model.version_id,
            grain=model.grain,
            period=model.period,
            business_scope=model.business_scope,
            aggregation=model.aggregation,
            stage=model.stage,
            allowed_dimensions=model.allowed_dimensions,
            expression_ast=model.expression_ast,
        )

    @staticmethod
    def to_model(entity: MetricInfo):
        return MetricInfoMySQL(**asdict(entity))
