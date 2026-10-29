from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class MetaConfigValidationError(ValueError):
    pass


@dataclass
class ModelConfig:
    id: str
    version: int
    description: str = ""


@dataclass
class ColumnConfig:
    name: str
    role: str
    description: str
    alias: list[str] = field(default_factory=list)
    sync: bool = False
    type: str | None = None


@dataclass
class TableConfig:
    name: str
    role: str
    description: str
    columns: list[ColumnConfig] = field(default_factory=list)


@dataclass
class DatasetConfig:
    id: str
    table: str
    grain: str
    primary_key: str
    time_dimension: str


@dataclass
class RelationshipConfig:
    id: str
    source: str
    target: str
    cardinality: str
    enabled: bool = True


@dataclass
class DimensionConfig:
    id: str
    name: str
    table: str
    column: str
    aliases: list[str] = field(default_factory=list)


@dataclass
class TimeDimensionConfig:
    id: str
    table: str
    year_field: str
    quarter_field: str
    month_field: str
    day_field: str
    date_key_field: str
    supported_grains: list[str] = field(default_factory=list)
    month_filter_requires_year: bool = True


@dataclass
class MetricConfig:
    id: str
    name: str
    description: str
    type: str
    base_dataset: str
    expression: str | None = None
    numerator: str | None = None
    denominator: str | None = None
    aliases: list[str] = field(default_factory=list)
    relevant_columns: list[str] = field(default_factory=list)

    @property
    def alias(self) -> list[str]:
        return self.aliases


@dataclass
class MetaConfig:
    model: ModelConfig
    tables: list[TableConfig]
    datasets: list[DatasetConfig]
    relationships: list[RelationshipConfig]
    dimensions: list[DimensionConfig]
    time_dimensions: list[TimeDimensionConfig]
    metrics: list[MetricConfig]

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> "MetaConfig":
        return cls(
            model=ModelConfig(**mapping["model"]),
            tables=[
                TableConfig(
                    **{key: value for key, value in table.items() if key != "columns"},
                    columns=[ColumnConfig(**column) for column in table.get("columns", [])],
                )
                for table in mapping.get("tables", [])
            ],
            datasets=[DatasetConfig(**dataset) for dataset in mapping.get("datasets", [])],
            relationships=[
                RelationshipConfig(id=relationship_id, **relationship)
                for relationship_id, relationship in mapping.get("relationships", {}).items()
            ],
            dimensions=[
                DimensionConfig(**dimension) for dimension in mapping.get("dimensions", [])
            ],
            time_dimensions=[
                TimeDimensionConfig(id=time_id, **time_dimension)
                for time_id, time_dimension in mapping.get("time_dimensions", {}).items()
            ],
            metrics=[MetricConfig(**metric) for metric in mapping.get("metrics", [])],
        )

    def validate(self) -> None:
        errors: list[str] = []
        table_map = {table.name: table for table in self.tables}
        table_columns = {
            table.name: {column.name for column in table.columns}
            for table in self.tables
        }

        def check_unique(values: list[str], label: str) -> None:
            duplicates = sorted({value for value in values if values.count(value) > 1})
            if duplicates:
                errors.append(f"{label}重复: {', '.join(duplicates)}")

        if not self.model.id or self.model.version < 1:
            errors.append("model.id不能为空且model.version必须大于等于1")

        check_unique([table.name for table in self.tables], "表名")
        check_unique([dataset.id for dataset in self.datasets], "数据集ID")
        check_unique([relationship.id for relationship in self.relationships], "关系ID")
        check_unique([dimension.id for dimension in self.dimensions], "维度ID")
        check_unique([time_dimension.id for time_dimension in self.time_dimensions], "时间维度ID")
        check_unique([metric.id for metric in self.metrics], "指标ID")

        for table in self.tables:
            check_unique([column.name for column in table.columns], f"表 {table.name} 字段名")

        dataset_map = {dataset.id: dataset for dataset in self.datasets}
        metric_map = {metric.id: metric for metric in self.metrics}
        for dataset in self.datasets:
            if dataset.table not in table_map:
                errors.append(f"数据集 {dataset.id} 引用不存在的表 {dataset.table}")
            elif dataset.primary_key not in table_columns[dataset.table]:
                errors.append(f"数据集 {dataset.id} 的主键不存在: {dataset.table}.{dataset.primary_key}")
            if dataset.grain != "one_row_per_order":
                errors.append(f"数据集 {dataset.id} 的grain不符合本期约束: {dataset.grain}")
            if dataset.time_dimension not in {item.id for item in self.time_dimensions}:
                errors.append(f"数据集 {dataset.id} 引用不存在的时间维度 {dataset.time_dimension}")

        for relationship in self.relationships:
            source_table, source_column = _split_reference(relationship.source, errors, "关系源")
            target_table, target_column = _split_reference(relationship.target, errors, "关系目标")
            if source_table and source_table not in table_map:
                errors.append(f"关系 {relationship.id} 引用不存在的源表 {source_table}")
            if target_table and target_table not in table_map:
                errors.append(f"关系 {relationship.id} 引用不存在的目标表 {target_table}")
            if source_table in table_columns and source_column not in table_columns[source_table]:
                errors.append(f"关系 {relationship.id} 的源字段不存在: {relationship.source}")
            if target_table in table_columns and target_column not in table_columns[target_table]:
                errors.append(f"关系 {relationship.id} 的目标字段不存在: {relationship.target}")
            if relationship.cardinality != "many_to_one":
                errors.append(f"关系 {relationship.id} 的基数不符合本期约束: {relationship.cardinality}")

        for dimension in self.dimensions:
            if dimension.table not in table_map:
                errors.append(f"维度 {dimension.id} 引用不存在的表 {dimension.table}")
            elif dimension.column not in table_columns[dimension.table]:
                errors.append(f"维度 {dimension.id} 的字段不存在: {dimension.table}.{dimension.column}")

        for time_dimension in self.time_dimensions:
            fields = [
                time_dimension.year_field,
                time_dimension.quarter_field,
                time_dimension.month_field,
                time_dimension.day_field,
                time_dimension.date_key_field,
            ]
            if time_dimension.table not in table_map:
                errors.append(f"时间维度 {time_dimension.id} 引用不存在的表 {time_dimension.table}")
            else:
                for field_name in fields:
                    if field_name not in table_columns[time_dimension.table]:
                        errors.append(
                            f"时间维度 {time_dimension.id} 的字段不存在: "
                            f"{time_dimension.table}.{field_name}"
                        )
            if not set(time_dimension.supported_grains).issubset({"year", "quarter", "month", "day"}):
                errors.append(f"时间维度 {time_dimension.id} 包含不支持的粒度")
            if not time_dimension.month_filter_requires_year:
                errors.append(f"时间维度 {time_dimension.id} 必须启用按月同时约束年份")

        aliases: dict[str, str] = {}
        for metric in self.metrics:
            if metric.base_dataset not in dataset_map:
                errors.append(f"指标 {metric.id} 引用不存在的数据集 {metric.base_dataset}")
            if metric.type == "ratio":
                if not metric.numerator or not metric.denominator:
                    errors.append(f"比例指标 {metric.id} 必须声明numerator和denominator")
                elif metric.numerator not in metric_map or metric.denominator not in metric_map:
                    errors.append(f"比例指标 {metric.id} 的分子或分母不存在")
                elif (
                    metric_map[metric.numerator].base_dataset != metric.base_dataset
                    or metric_map[metric.denominator].base_dataset != metric.base_dataset
                ):
                    errors.append(f"比例指标 {metric.id} 的分子分母必须属于同一数据集")
                if metric.expression:
                    errors.append(f"比例指标 {metric.id} 不应同时声明expression")
            elif not metric.expression:
                errors.append(f"非比例指标 {metric.id} 必须声明expression")
            if metric.id == "order_count" and metric.expression != "COUNT(DISTINCT fact_order.order_id)":
                errors.append("order_count必须使用COUNT(DISTINCT fact_order.order_id)")
            for reference in metric.relevant_columns:
                table_name, column_name = _split_reference(reference, errors, f"指标 {metric.id} 字段")
                if table_name in table_columns and column_name not in table_columns[table_name]:
                    errors.append(f"指标 {metric.id} 的字段不存在: {reference}")
            if metric.expression:
                expression_references = {
                    token for token in metric.expression.replace("(", " ").replace(")", " ").replace(",", " ").split()
                    if "." in token
                }
                for reference in expression_references:
                    table_name, column_name = _split_reference(reference, errors, f"指标 {metric.id} 表达式")
                    if table_name in table_columns and column_name not in table_columns[table_name]:
                        errors.append(f"指标 {metric.id} 表达式引用不存在字段: {reference}")
            for alias in metric.aliases:
                previous = aliases.setdefault(alias, metric.id)
                if previous != metric.id:
                    errors.append(f"指标别名冲突: {alias} 同时属于 {previous} 和 {metric.id}")
            if "GMV" in metric.aliases:
                errors.append("GMV不得作为任何指标的自动别名")

        if errors:
            raise MetaConfigValidationError("语义配置校验失败:\n- " + "\n- ".join(errors))

    async def validate_against_dw(self, dw_repository) -> None:
        self.validate()
        errors: list[str] = []
        for table in self.tables:
            column_types = await dw_repository.get_column_types(table.name)
            for column in table.columns:
                if column.name not in column_types:
                    errors.append(f"数仓表 {table.name} 不存在配置字段 {column.name}")
        if errors:
            raise MetaConfigValidationError("语义配置与数仓schema不一致:\n- " + "\n- ".join(errors))


def _split_reference(reference: str, errors: list[str], label: str) -> tuple[str | None, str | None]:
    parts = reference.split(".")
    if len(parts) != 2 or not all(parts):
        errors.append(f"{label}字段引用格式错误: {reference}")
        return None, None
    return parts[0], parts[1]


def load_meta_config(config_path: Path) -> MetaConfig:
    with config_path.open("r", encoding="utf-8") as config_file:
        context = yaml.safe_load(config_file)
    if not isinstance(context, dict):
        raise MetaConfigValidationError("语义配置根节点必须是对象")
    config = MetaConfig.from_mapping(context)
    config.validate()
    return config
