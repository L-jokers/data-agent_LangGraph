from dataclasses import replace
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.column_info import ColumnInfo
from app.entities.column_metric import ColumnMetric
from app.entities.dataset_info import DatasetInfo
from app.entities.dimension_info import DimensionInfo
from app.entities.metric_dependency import MetricDependency
from app.entities.metric_info import MetricInfo
from app.entities.relationship_info import RelationshipInfo
from app.entities.table_info import TableInfo
from app.entities.time_dimension_info import TimeDimensionInfo
from app.models.column_info_mysql import ColumnInfoMySQL
from app.models.column_metric_mysql import ColumnMetricMySQL
from app.models.dataset_info_mysql import DatasetInfoMySQL
from app.models.dimension_info_mysql import DimensionInfoMySQL
from app.models.metric_dependency_mysql import MetricDependencyMySQL
from app.models.metric_info_mysql import MetricInfoMySQL
from app.models.relationship_info_mysql import RelationshipInfoMySQL
from app.models.semantic_model_current_mysql import SemanticModelCurrentMySQL
from app.models.semantic_model_version_mysql import SemanticModelVersionMySQL
from app.models.table_info_mysql import TableInfoMySQL
from app.models.time_dimension_info_mysql import TimeDimensionInfoMySQL
from app.repositories.mysql.meta.mappers.column_info_mapper import ColumnInfoMapper
from app.repositories.mysql.meta.mappers.column_metric_mapper import ColumnMetricMapper
from app.repositories.mysql.meta.mappers.dataset_info_mapper import DatasetInfoMapper
from app.repositories.mysql.meta.mappers.dimension_info_mapper import DimensionInfoMapper
from app.repositories.mysql.meta.mappers.metric_dependency_mapper import MetricDependencyMapper
from app.repositories.mysql.meta.mappers.metric_info_mapper import MetricInfoMapper
from app.repositories.mysql.meta.mappers.relationship_info_mapper import RelationshipInfoMapper
from app.repositories.mysql.meta.mappers.table_info_mapper import TableInfoMapper
from app.repositories.mysql.meta.mappers.time_dimension_info_mapper import TimeDimensionInfoMapper


class SemanticModelVersionError(RuntimeError):
    pass


class SemanticIndexActivationGate(Protocol):
    async def assert_ready(self, version_id: str, content_hash: str) -> None:
        """Raise when the derived indexes are not verified for this version."""


class MetaMySQLRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _for_version(entity, version_id: str):
        if entity.version_id not in (None, version_id):
            raise SemanticModelVersionError("元数据实体版本与写入版本不一致")
        return replace(entity, version_id=version_id)

    async def create_draft_version(
        self, version_id: str, content_hash: str, description: str | None = None
    ) -> bool:
        existing = await self.session.get(SemanticModelVersionMySQL, version_id)
        if existing is not None:
            if existing.content_hash != content_hash:
                raise SemanticModelVersionError("同一版本标识已存在不同内容，拒绝覆盖")
            return False

        self.session.add(
            SemanticModelVersionMySQL(
                version_id=version_id,
                status="draft",
                content_hash=content_hash,
                description=description,
            )
        )
        await self.session.flush()
        return True

    async def get_active_version_id(self) -> str:
        pointer_result = await self.session.execute(
            select(SemanticModelCurrentMySQL).where(
                SemanticModelCurrentMySQL.singleton_id == 1
            )
        )
        pointer = pointer_result.scalar_one_or_none()
        if pointer is None or pointer.version_id is None:
            raise SemanticModelVersionError("未配置 active 语义模型版本")

        active_result = await self.session.execute(
            select(SemanticModelVersionMySQL.version_id).where(
                SemanticModelVersionMySQL.status == "active"
            )
        )
        active_ids = set(active_result.scalars().all())
        if active_ids != {pointer.version_id}:
            raise SemanticModelVersionError("语义版本指针与 active 状态不一致")
        return pointer.version_id

    async def activate_version(
        self, version_id: str, activation_gate: SemanticIndexActivationGate
    ) -> None:
        if activation_gate is None:
            raise SemanticModelVersionError("未提供语义索引激活门禁，拒绝激活")

        async with self.session.begin():
            pointer_result = await self.session.execute(
                select(SemanticModelCurrentMySQL)
                .where(SemanticModelCurrentMySQL.singleton_id == 1)
                .with_for_update()
            )
            pointer = pointer_result.scalar_one_or_none()
            if pointer is None:
                raise SemanticModelVersionError("语义版本指针行缺失，拒绝激活")

            version_result = await self.session.execute(
                select(SemanticModelVersionMySQL)
                .where(SemanticModelVersionMySQL.version_id == version_id)
                .with_for_update()
            )
            target = version_result.scalar_one_or_none()
            if target is None:
                raise SemanticModelVersionError("目标语义版本不存在")

            active_result = await self.session.execute(
                select(SemanticModelVersionMySQL.version_id).where(
                    SemanticModelVersionMySQL.status == "active"
                )
            )
            active_ids = set(active_result.scalars().all())
            if pointer.version_id is None:
                if active_ids:
                    raise SemanticModelVersionError("存在 active 版本但当前指针为空")
            elif active_ids != {pointer.version_id}:
                raise SemanticModelVersionError("语义版本指针与 active 状态不一致")

            await self._validate_version_completeness(version_id)
            await activation_gate.assert_ready(version_id, target.content_hash)
            if target.status == "active":
                if pointer.version_id != version_id or active_ids != {version_id}:
                    raise SemanticModelVersionError("active 版本与当前指针冲突")
                return
            if target.status not in {"draft", "archived"}:
                raise SemanticModelVersionError("目标语义版本状态不可激活")

            if pointer.version_id is not None:
                old_version = await self.session.get(
                    SemanticModelVersionMySQL, pointer.version_id
                )
                if old_version is None or old_version.status != "active":
                    raise SemanticModelVersionError("当前指针指向无效 active 版本")
                old_version.status = "archived"

            target.status = "active"
            target.activated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            pointer.version_id = version_id
            await self.session.flush()

    async def _validate_version_completeness(self, version_id: str) -> None:
        required_models = (
            (TableInfoMySQL, "表"),
            (ColumnInfoMySQL, "字段"),
            (DatasetInfoMySQL, "数据集"),
            (DimensionInfoMySQL, "维度"),
            (TimeDimensionInfoMySQL, "时间维度"),
            (MetricInfoMySQL, "指标"),
        )
        for model, label in required_models:
            result = await self.session.execute(
                select(func.count()).select_from(model).where(
                    model.version_id == version_id
                )
            )
            if result.scalar_one() == 0:
                raise SemanticModelVersionError(f"目标版本缺少{label}元数据，拒绝激活")

    async def get_version_metadata_counts(self, version_id: str) -> dict[str, int]:
        versioned_models = {
            "table_info": TableInfoMySQL,
            "column_info": ColumnInfoMySQL,
            "metric_info": MetricInfoMySQL,
            "column_metric": ColumnMetricMySQL,
            "dataset": DatasetInfoMySQL,
            "dimension_info": DimensionInfoMySQL,
            "metric_dependency": MetricDependencyMySQL,
            "relationship": RelationshipInfoMySQL,
            "time_dimension": TimeDimensionInfoMySQL,
        }
        counts = {}
        for table_name, model in versioned_models.items():
            result = await self.session.execute(
                select(func.count()).select_from(model).where(
                    model.version_id == version_id
                )
            )
            counts[table_name] = result.scalar_one()
        return counts

    async def load_version_rows(self, version_id: str) -> dict[str, object]:
        version = await self.session.get(SemanticModelVersionMySQL, version_id)
        if version is None:
            raise SemanticModelVersionError(f"不存在语义模型版本: {version_id}")

        async def load(model):
            result = await self.session.execute(
                select(model).where(model.version_id == version_id)
            )
            return list(result.scalars().all())

        return {
            "version": version,
            "tables": [TableInfoMapper.to_entity(item) for item in await load(TableInfoMySQL)],
            "columns": [ColumnInfoMapper.to_entity(item) for item in await load(ColumnInfoMySQL)],
            "metrics": [MetricInfoMapper.to_entity(item) for item in await load(MetricInfoMySQL)],
            "column_metrics": [ColumnMetricMapper.to_entity(item) for item in await load(ColumnMetricMySQL)],
            "datasets": [
                DatasetInfo(
                    id=item.id, table_name=item.table_name, grain=item.grain,
                    primary_key=item.primary_key, time_dimension_id=item.time_dimension_id,
                    version_id=item.version_id,
                )
                for item in await load(DatasetInfoMySQL)
            ],
            "dimensions": [DimensionInfoMapper.to_entity(item) for item in await load(DimensionInfoMySQL)],
            "metric_dependencies": [
                MetricDependency(
                    metric_id=item.metric_id,
                    depends_on_metric_id=item.depends_on_metric_id,
                    dependency_order=item.dependency_order,
                    version_id=item.version_id,
                )
                for item in await load(MetricDependencyMySQL)
            ],
            "relationships": [
                RelationshipInfo(
                    id=item.id,
                    source=item.source,
                    target=item.target,
                    cardinality=item.cardinality,
                    enabled=item.enabled,
                    version_id=item.version_id,
                )
                for item in await load(RelationshipInfoMySQL)
            ],
            "time_dimensions": [
                TimeDimensionInfo(
                    id=item.id,
                    table_name=item.table_name,
                    year_field=item.year_field,
                    quarter_field=item.quarter_field,
                    month_field=item.month_field,
                    day_field=item.day_field,
                    date_key_field=item.date_key_field,
                    supported_grains=item.supported_grains,
                    month_filter_requires_year=item.month_filter_requires_year,
                    version_id=item.version_id,
                )
                for item in await load(TimeDimensionInfoMySQL)
            ],
        }
    async def _resolve_version(self, version_id: str | None) -> str:
        return version_id or await self.get_active_version_id()

    async def save_table_infos(self, table_infos: list[TableInfo], version_id: str):
        models = [
            TableInfoMapper.to_model(self._for_version(item, version_id))
            for item in table_infos
        ]
        self.session.add_all(models)

    async def save_column_infos(self, columns_info: list[ColumnInfo], version_id: str):
        models = [
            ColumnInfoMapper.to_model(self._for_version(item, version_id))
            for item in columns_info
        ]
        self.session.add_all(models)

    async def save_metric_infos(self, metric_infos: list[MetricInfo], version_id: str):
        models = [
            MetricInfoMapper.to_model(self._for_version(item, version_id))
            for item in metric_infos
        ]
        self.session.add_all(models)

    async def save_column_metrics(
        self, column_metrics: list[ColumnMetric], version_id: str
    ):
        models = [
            ColumnMetricMapper.to_model(self._for_version(item, version_id))
            for item in column_metrics
        ]
        self.session.add_all(models)

    async def save_datasets(self, datasets: list[DatasetInfo], version_id: str):
        models = [
            DatasetInfoMapper.to_model(self._for_version(item, version_id))
            for item in datasets
        ]
        self.session.add_all(models)

    async def save_dimensions(self, dimensions: list[DimensionInfo], version_id: str):
        models = [
            DimensionInfoMapper.to_model(self._for_version(item, version_id))
            for item in dimensions
        ]
        self.session.add_all(models)

    async def save_metric_dependencies(
        self, dependencies: list[MetricDependency], version_id: str
    ):
        models = [
            MetricDependencyMapper.to_model(self._for_version(item, version_id))
            for item in dependencies
        ]
        self.session.add_all(models)

    async def save_relationships(
        self, relationships: list[RelationshipInfo], version_id: str
    ):
        models = [
            RelationshipInfoMapper.to_model(self._for_version(item, version_id))
            for item in relationships
        ]
        self.session.add_all(models)

    async def save_time_dimensions(
        self, time_dimensions: list[TimeDimensionInfo], version_id: str
    ):
        models = [
            TimeDimensionInfoMapper.to_model(self._for_version(item, version_id))
            for item in time_dimensions
        ]
        self.session.add_all(models)

    async def get_column_info_by_id(
        self, column_id: str, version_id: str | None = None
    ) -> ColumnInfo | None:
        selected_version = await self._resolve_version(version_id)
        result = await self.session.execute(
            select(ColumnInfoMySQL).where(
                ColumnInfoMySQL.version_id == selected_version,
                ColumnInfoMySQL.id == column_id,
            )
        )
        model = result.scalar_one_or_none()
        return ColumnInfoMapper.to_entity(model) if model else None

    async def get_table_info_by_id(
        self, table_id: str, version_id: str | None = None
    ) -> TableInfo | None:
        selected_version = await self._resolve_version(version_id)
        result = await self.session.execute(
            select(TableInfoMySQL).where(
                TableInfoMySQL.version_id == selected_version,
                TableInfoMySQL.id == table_id,
            )
        )
        model = result.scalar_one_or_none()
        return TableInfoMapper.to_entity(model) if model else None

    async def get_key_columns_by_table_id(
        self, table_id: str, version_id: str | None = None
    ) -> list[ColumnInfo]:
        selected_version = await self._resolve_version(version_id)
        result = await self.session.execute(
            select(ColumnInfoMySQL).where(
                ColumnInfoMySQL.version_id == selected_version,
                ColumnInfoMySQL.table_id == table_id,
                ColumnInfoMySQL.role.in_(("primary_key", "foreign_key")),
            )
        )
        return [ColumnInfoMapper.to_entity(model) for model in result.scalars().all()]
