import hashlib
import json
import uuid
from dataclasses import asdict
from pathlib import Path

from langchain_huggingface import HuggingFaceEndpointEmbeddings
from app.conf.meta_config import MetaConfig, load_meta_config
from app.core.log import logger
from app.entities.column_info import ColumnInfo
from app.entities.column_metric import ColumnMetric
from app.entities.dataset_info import DatasetInfo
from app.entities.dimension_info import DimensionInfo
from app.entities.metric_dependency import MetricDependency
from app.entities.metric_info import MetricInfo
from app.entities.relationship_info import RelationshipInfo
from app.entities.table_info import TableInfo
from app.entities.time_dimension_info import TimeDimensionInfo
from app.entities.value_info import ValueInfo
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository


class MetaKnowledgeService:
    def __init__(
        self,
        meta_mysql_repository: MetaMySQLRepository,
        dw_mysql_repository: DWMySQLRepository,
        column_qdrant_repository: ColumnQdrantRepository | None = None,
        embedding_client: HuggingFaceEndpointEmbeddings | None = None,
        value_es_repository: ValueESRepository | None = None,
        metric_qdrant_repository: MetricQdrantRepository | None = None,
    ):
        self.meta_mysql_repository = meta_mysql_repository
        self.dw_mysql_repository = dw_mysql_repository
        self.column_qdrant_repository = column_qdrant_repository
        self.embedding_client = embedding_client
        self.value_es_repository = value_es_repository
        self.metric_qdrant_repository = metric_qdrant_repository

    @staticmethod
    def config_fingerprint(meta_config: MetaConfig) -> str:
        canonical_content = json.dumps(
            asdict(meta_config), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical_content.encode("utf-8")).hexdigest()

    async def _save_tables_to_meta_db(
        self, meta_config: MetaConfig, version_id: str
    ) -> list[ColumnInfo]:
        table_infos: list[TableInfo] = []
        column_infos: list[ColumnInfo] = []

        for table in meta_config.tables:
            # 构造TableInfo实例
            table_info = TableInfo(
                id=table.name,
                name=table.name,
                role=table.role,
                description=table.description,
                version_id=version_id,
            )
            table_infos.append(table_info)

            # 查询该表的所有字段类型
            column_types: dict[str, str] = await self.dw_mysql_repository.get_column_types(table.name)
            for column in table.columns:
                # 查询该字段的部分取值作为示例
                column_values: list = await self.dw_mysql_repository.get_column_values(table.name, column.name, 10)
                # 构造ColumnInfo实例
                column_info = ColumnInfo(
                    id=f"{table.name}.{column.name}",
                    name=column.name,
                    type=column_types[column.name],
                    role=column.role,
                    examples=column_values,
                    description=column.description,
                    alias=column.alias,
                    table_id=table.name,
                    version_id=version_id,
                )
                column_infos.append(column_info)

        # 保存表信息和字段信息到元数据数据库 session.begin()自动管理事务生命周期
        await self.meta_mysql_repository.save_table_infos(table_infos, version_id)
        await self.meta_mysql_repository.session.flush()
        await self.meta_mysql_repository.save_column_infos(column_infos, version_id)
        await self.meta_mysql_repository.session.flush()

        return column_infos

    async def _save_column_info_to_qdrant(self, column_infos: list[ColumnInfo]):
        # 确保column_info的collection存在
        await self.column_qdrant_repository.ensure_collection()
        # 构造待保存的数据（一行数据应该对应多个点）
        points: list[dict] = []
        for column_info in column_infos:
            points.append(
                {
                    "id": uuid.uuid4(),
                    "embedding_text": column_info.name,
                    "payload": column_info,
                }
            )
            points.append(
                {
                    "id": uuid.uuid4(),
                    "embedding_text": column_info.description,
                    "payload": column_info,
                }
            )
            for alia in column_info.alias:
                points.append(
                    {"id": uuid.uuid4(), "embedding_text": alia, "payload": column_info}
                )
        # 向量列表
        # 将embedding_text进行向量化形成vector
        embedding_texts = [point["embedding_text"] for point in points]
        embedding_batch_size = 10
        embeddings = []
        for i in range(0, len(embedding_texts), embedding_batch_size):
            batch_embedding_texts = embedding_texts[i : i + embedding_batch_size]
            batch_embeddings = await self.embedding_client.aembed_documents(
                batch_embedding_texts
            )
            embeddings.extend(batch_embeddings)

        # id列表
        ids = [point["id"] for point in points]

        # payload列表
        payloads = [point["payload"] for point in points]

        # 保存数据到qdrant
        await self.column_qdrant_repository.upsert(ids, embeddings, payloads)

    async def _save_value_info_to_es(
        self, meta_config: MetaConfig, column_infos: list[ColumnInfo]
    ):
        # 取保index存在
        await self.value_es_repository.ensure_index()
        
        # 获取需要同步取值的列
        column2sync: dict[str, bool] = {}
        for table in meta_config.tables:
            for column in table.columns:
                column2sync[f"{table.name}.{column.name}"] = column.sync

        # 构造ValueInfo列表
        value_infos: list[ValueInfo] = []
        for column_info in column_infos:
            sync = column2sync[column_info.id]
            if sync:
                # 查询这个列的所有取值
                table_name = column_info.table_id
                column_name = column_info.name
                values = await self.dw_mysql_repository.get_column_values(
                    table_name, column_name, 100000
                )
                current_value_infos = [
                    ValueInfo(
                        id=f"{column_info.id}.{value}",
                        value=value,
                        column_id=column_info.id,
                    )
                    for value in values
                ]
                value_infos.extend(current_value_infos)
        # 批量保存到Elasticsearch
        await self.value_es_repository.index(value_infos)

    async def _save_metrics_to_meta_db(self, meta_config: MetaConfig, version_id: str):
        metric_infos: list[MetricInfo] = []
        column_metrics: list[ColumnMetric] = []
        metric_dependencies: list[MetricDependency] = []
        for metric in meta_config.metrics:
            # 构造MetricInfo数据
            metric_info = MetricInfo(
                id=metric.id,
                name=metric.name,
                description=metric.description,
                relevant_columns=metric.relevant_columns,
                alias=metric.alias,
                metric_type=metric.type,
                expression=metric.expression,
                numerator=metric.numerator,
                denominator=metric.denominator,
                base_dataset=metric.base_dataset,
                version_id=version_id,
            )
            metric_infos.append(metric_info)

            for relevant_column in metric.relevant_columns:
                # 构造ColumnMetric数据
                column_metric = ColumnMetric(
                    column_id=relevant_column,
                    metric_id=metric.id,
                    version_id=version_id,
                )
                column_metrics.append(column_metric)
            for dependency_order, dependency_id in enumerate(
                (metric.numerator, metric.denominator)
            ):
                if dependency_id is not None:
                    metric_dependencies.append(
                        MetricDependency(
                            metric_id=metric.id,
                            depends_on_metric_id=dependency_id,
                            dependency_order=dependency_order,
                            version_id=version_id,
                        )
                    )
        await self.meta_mysql_repository.save_metric_infos(metric_infos, version_id)
        await self.meta_mysql_repository.session.flush()
        await self.meta_mysql_repository.save_column_metrics(column_metrics, version_id)
        await self.meta_mysql_repository.session.flush()
        await self.meta_mysql_repository.save_metric_dependencies(
            metric_dependencies, version_id
        )
        await self.meta_mysql_repository.session.flush()

        return metric_infos

    async def _save_semantic_objects_to_meta_db(
        self, meta_config: MetaConfig, version_id: str
    ):
        datasets = [
            DatasetInfo(
                id=dataset.id,
                table_name=dataset.table,
                grain=dataset.grain,
                primary_key=dataset.primary_key,
                time_dimension_id=dataset.time_dimension,
                version_id=version_id,
            )
            for dataset in meta_config.datasets
        ]
        relationships = [
            RelationshipInfo(
                id=relationship.id,
                source=relationship.source,
                target=relationship.target,
                cardinality=relationship.cardinality,
                enabled=relationship.enabled,
                version_id=version_id,
            )
            for relationship in meta_config.relationships
        ]
        time_dimensions = [
            TimeDimensionInfo(
                id=time_dimension.id,
                table_name=time_dimension.table,
                year_field=time_dimension.year_field,
                quarter_field=time_dimension.quarter_field,
                month_field=time_dimension.month_field,
                day_field=time_dimension.day_field,
                date_key_field=time_dimension.date_key_field,
                supported_grains=time_dimension.supported_grains,
                month_filter_requires_year=time_dimension.month_filter_requires_year,
                version_id=version_id,
            )
            for time_dimension in meta_config.time_dimensions
        ]
        dimensions = [
            DimensionInfo(
                id=dimension.id,
                name=dimension.name,
                table_id=dimension.table,
                column_id=f"{dimension.table}.{dimension.column}",
                aliases=dimension.aliases,
                version_id=version_id,
            )
            for dimension in meta_config.dimensions
        ]
        await self.meta_mysql_repository.save_dimensions(dimensions, version_id)
        await self.meta_mysql_repository.session.flush()
        await self.meta_mysql_repository.save_time_dimensions(time_dimensions, version_id)
        await self.meta_mysql_repository.session.flush()
        await self.meta_mysql_repository.save_datasets(datasets, version_id)
        await self.meta_mysql_repository.session.flush()
        await self.meta_mysql_repository.save_relationships(relationships, version_id)
        await self.meta_mysql_repository.session.flush()

    async def _save_metric_info_to_qdrant(self, metric_infos: list[MetricInfo]):
        # 确保collection存在
        await self.metric_qdrant_repository.ensure_collection()
        
        # 构造待保存的数据
        points: list[dict] = []
        for metric_info in metric_infos:
            points.append(
                {
                    "id": uuid.uuid4(),
                    "embedding_text": metric_info.name,
                    "payload": metric_info,
                }
            )
            points.append(
                {
                    "id": uuid.uuid4(),
                    "embedding_text": metric_info.description,
                    "payload": metric_info,
                }
            )
            for alia in metric_info.alias:
                points.append(
                    {"id": uuid.uuid4(), "embedding_text": alia, "payload": metric_info}
                )

        ids = [point["id"] for point in points]
        embeddings = []
        embedding_texts = [point["embedding_text"] for point in points]
        embedding_batch_size = 10
        for i in range(0, len(embedding_texts), embedding_batch_size):
            batch_embedding_texts = embedding_texts[i : i + embedding_batch_size]
            batch_embeddings = await self.embedding_client.aembed_documents(
                batch_embedding_texts
            )
            embeddings.extend(batch_embeddings)
        payloads = [point["payload"] for point in points]

        # 保存数据到qdrant
        await self.metric_qdrant_repository.upsert(ids, embeddings, payloads)

    @staticmethod
    def _expected_metadata_counts(meta_config: MetaConfig) -> dict[str, int]:
        return {
            "table_info": len(meta_config.tables),
            "column_info": sum(len(table.columns) for table in meta_config.tables),
            "metric_info": len(meta_config.metrics),
            "column_metric": sum(
                len(metric.relevant_columns) for metric in meta_config.metrics
            ),
            "dataset": len(meta_config.datasets),
            "dimension_info": len(meta_config.dimensions),
            "metric_dependency": sum(
                int(metric.numerator is not None)
                + int(metric.denominator is not None)
                for metric in meta_config.metrics
            ),
            "relationship": len(meta_config.relationships),
            "time_dimension": len(meta_config.time_dimensions),
        }

    async def build(self, config_path: Path, version_id: str):
        meta_config = load_meta_config(config_path)
        await meta_config.validate_against_dw(self.dw_mysql_repository)
        content_hash = self.config_fingerprint(meta_config)
        expected_counts = self._expected_metadata_counts(meta_config)

        async with self.meta_mysql_repository.session.begin():
            created = await self.meta_mysql_repository.create_draft_version(
                version_id,
                content_hash,
                description=meta_config.model.description,
            )
            if not created:
                actual_counts = await self.meta_mysql_repository.get_version_metadata_counts(
                    version_id
                )
                if actual_counts != expected_counts:
                    raise ValueError(
                        "同版本元数据数量与配置不一致，拒绝覆盖或补写"
                    )
                logger.info("语义版本已存在且内容校验一致，未写入")
                return

            if meta_config.tables:
                await self._save_tables_to_meta_db(meta_config, version_id)
            await self._save_semantic_objects_to_meta_db(meta_config, version_id)
            if meta_config.metrics:
                await self._save_metrics_to_meta_db(meta_config, version_id)

        logger.info("语义版本 %s 已初始化为 draft；未激活，未构建检索索引", version_id)
