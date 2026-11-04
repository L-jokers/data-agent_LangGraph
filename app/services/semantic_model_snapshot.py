from dataclasses import dataclass

from app.conf.meta_config import (
    ColumnConfig,
    DatasetConfig,
    DimensionConfig,
    MetaConfig,
    MetricConfig,
    ModelConfig,
    RelationshipConfig,
    TableConfig,
    TimeDimensionConfig,
)
from app.entities.column_info import ColumnInfo
from app.entities.column_metric import ColumnMetric
from app.entities.dataset_info import DatasetInfo
from app.entities.dimension_info import DimensionInfo
from app.entities.metric_dependency import MetricDependency
from app.entities.metric_info import MetricInfo
from app.entities.relationship_info import RelationshipInfo
from app.entities.table_info import TableInfo
from app.entities.time_dimension_info import TimeDimensionInfo
from app.repositories.mysql.meta.meta_mysql_repository import (
    MetaMySQLRepository,
    SemanticModelVersionError,
)


@dataclass(frozen=True)
class SemanticModelSnapshot:
    version_id: str
    content_hash: str
    status: str
    tables: tuple[TableInfo, ...]
    columns: tuple[ColumnInfo, ...]
    metrics: tuple[MetricInfo, ...]
    column_metrics: tuple[ColumnMetric, ...]
    datasets: tuple[DatasetInfo, ...]
    dimensions: tuple[DimensionInfo, ...]
    metric_dependencies: tuple[MetricDependency, ...]
    relationships: tuple[RelationshipInfo, ...]
    time_dimensions: tuple[TimeDimensionInfo, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "tables", "columns", "metrics", "column_metrics", "datasets",
            "dimensions", "metric_dependencies", "relationships", "time_dimensions",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        self._validate()

    def _validate(self) -> None:
        if not self.version_id:
            raise SemanticModelVersionError("语义快照缺少 version_id")
        tables = {item.id for item in self.tables}
        columns = {item.id for item in self.columns}
        metrics = {item.id for item in self.metrics}
        datasets = {item.id for item in self.datasets}
        dimensions = {item.id for item in self.dimensions}
        time_dimensions = {item.id for item in self.time_dimensions}
        for items in (self.tables, self.columns, self.metrics, self.datasets, self.dimensions, self.time_dimensions):
            if len({item.id for item in items}) != len(items):
                raise SemanticModelVersionError("语义快照存在重复实体 ID")
        for items in (self.tables, self.columns, self.metrics, self.datasets, self.dimensions,
                      self.metric_dependencies, self.relationships, self.time_dimensions):
            if any(item.version_id != self.version_id for item in items):
                raise SemanticModelVersionError("语义快照包含跨版本实体")
        for item in self.columns:
            if item.table_id not in tables:
                raise SemanticModelVersionError(f"字段 {item.id} 引用了不存在的表")
        for item in self.datasets:
            if item.table_name not in tables or item.time_dimension_id not in time_dimensions:
                raise SemanticModelVersionError(f"数据集 {item.id} 的关联不完整")
        for item in self.dimensions:
            if item.table_id not in tables or item.column_id not in columns:
                raise SemanticModelVersionError(f"维度 {item.id} 的关联不完整")
        for item in self.time_dimensions:
            if item.table_name not in tables:
                raise SemanticModelVersionError(f"时间维度 {item.id} 引用了不存在的表")
        for item in self.metrics:
            if item.base_dataset not in datasets or any(column not in columns for column in item.relevant_columns):
                raise SemanticModelVersionError(f"指标 {item.id} 的关联不完整")
        for item in self.column_metrics:
            if item.column_id not in columns or item.metric_id not in metrics:
                raise SemanticModelVersionError("指标字段关联引用不存在的实体")
        for item in self.metric_dependencies:
            if item.metric_id not in metrics or item.depends_on_metric_id not in metrics:
                raise SemanticModelVersionError("指标依赖引用不存在的指标")
        relation_targets = tables | columns
        for item in self.relationships:
            if item.source not in relation_targets or item.target not in relation_targets:
                raise SemanticModelVersionError(f"关系 {item.id} 引用了不存在的表或字段")

    def to_meta_config(self) -> MetaConfig:
        columns_by_table = {table.id: [] for table in self.tables}
        columns_by_id = {}
        for column in self.columns:
            columns_by_table[column.table_id].append(column)
            columns_by_id[column.id] = column
        return MetaConfig(
            model=ModelConfig(id="mysql", version=1, description=self.version_id),
            tables=[
                TableConfig(
                    name=table.name,
                    role=table.role,
                    description=table.description,
                    columns=[
                        ColumnConfig(
                            name=column.name,
                            role=column.role,
                            description=column.description,
                            alias=list(column.alias),
                            type=column.type,
                        )
                        for column in columns_by_table[table.id]
                    ],
                )
                for table in self.tables
            ],
            datasets=[DatasetConfig(item.id, item.table_name, item.grain, item.primary_key, item.time_dimension_id) for item in self.datasets],
            relationships=[RelationshipConfig(item.id, item.source, item.target, item.cardinality, item.enabled) for item in self.relationships],
            dimensions=[
                DimensionConfig(
                    item.id,
                    item.name,
                    item.table_id,
                    columns_by_id[item.column_id].name,
                    list(item.aliases),
                )
                for item in self.dimensions
            ],
            time_dimensions=[TimeDimensionConfig(item.id, item.table_name, item.year_field, item.quarter_field, item.month_field, item.day_field, item.date_key_field, list(item.supported_grains), item.month_filter_requires_year) for item in self.time_dimensions],
            metrics=[MetricConfig(item.id, item.name, item.description, item.metric_type or "simple", item.base_dataset or "", item.expression, item.numerator, item.denominator, list(item.alias), list(item.relevant_columns), item.expression_ast) for item in self.metrics],
        )


class SemanticModelSnapshotLoader:
    def __init__(self, repository: MetaMySQLRepository):
        self.repository = repository

    async def load_for_query(self, version_id: str | None = None) -> SemanticModelSnapshot:
        selected = version_id or await self.repository.get_active_version_id()
        return await self._load(selected, allow_draft=False)

    async def load_for_build(self, version_id: str) -> SemanticModelSnapshot:
        if not version_id:
            raise SemanticModelVersionError("构建快照必须显式指定 version_id")
        return await self._load(version_id, allow_draft=True)

    async def _load(self, version_id: str, allow_draft: bool) -> SemanticModelSnapshot:
        rows = await self.repository.load_version_rows(version_id)
        status = rows["version"].status
        if status == "draft" and not allow_draft:
            raise SemanticModelVersionError("查询入口不得读取 draft 语义版本")
        return SemanticModelSnapshot(
            version_id=version_id,
            content_hash=rows["version"].content_hash,
            status=status,
            tables=rows["tables"],
            columns=rows["columns"],
            metrics=rows["metrics"],
            column_metrics=rows["column_metrics"],
            datasets=rows["datasets"],
            dimensions=rows["dimensions"],
            metric_dependencies=rows["metric_dependencies"],
            relationships=rows["relationships"],
            time_dimensions=rows["time_dimensions"],
        )

