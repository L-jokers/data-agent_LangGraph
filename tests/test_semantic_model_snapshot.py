import asyncio
import unittest
from types import SimpleNamespace

from app.entities.column_info import ColumnInfo
from app.entities.column_metric import ColumnMetric
from app.entities.dataset_info import DatasetInfo
from app.entities.dimension_info import DimensionInfo
from app.entities.metric_dependency import MetricDependency
from app.entities.metric_info import MetricInfo
from app.entities.relationship_info import RelationshipInfo
from app.entities.table_info import TableInfo
from app.entities.time_dimension_info import TimeDimensionInfo
from app.repositories.mysql.meta.meta_mysql_repository import SemanticModelVersionError
from app.services.semantic_model_snapshot import SemanticModelSnapshotLoader


def rows(version_id="v1", status="active"):
    return {
        "version": SimpleNamespace(version_id=version_id, status=status, content_hash="hash-" + version_id),
        "tables": [
            TableInfo("fact_order", "fact_order", "fact", "orders", version_id),
            TableInfo("dim_region", "dim_region", "dimension", "regions", version_id),
        ],
        "columns": [
            ColumnInfo("fact_order.amount", "amount", "decimal", "measure", [1], "amount", [], "fact_order", version_id),
            ColumnInfo("dim_region.name", "name", "varchar", "dimension", ["华东"], "name", [], "dim_region", version_id),
        ],
        "metrics": [MetricInfo("sales", "sales", "sales", ["fact_order.amount"], ["销售额"], "sum", "SUM(fact_order.amount)", None, None, "orders", version_id=version_id)],
        "column_metrics": [ColumnMetric("fact_order.amount", "sales", version_id)],
        "datasets": [DatasetInfo("orders", "fact_order", "order", "id", "order_date", version_id)],
        "dimensions": [DimensionInfo("region", "region", "dim_region", "dim_region.name", [], version_id)],
        "metric_dependencies": [MetricDependency("sales", "sales", 0, version_id)],
        "relationships": [RelationshipInfo("order_region", "fact_order", "dim_region", "many_to_one", True, version_id)],
        "time_dimensions": [TimeDimensionInfo("order_date", "fact_order", "year", "quarter", "month", "day", "date", ["month"], True, version_id)],
    }


class FakeRepository:
    def __init__(self, versions):
        self.versions = versions
        self.active_calls = 0
        self.loaded = []

    async def get_active_version_id(self):
        self.active_calls += 1
        return "active"

    async def load_version_rows(self, version_id):
        self.loaded.append(version_id)
        return self.versions[version_id]


class SemanticModelSnapshotTests(unittest.TestCase):
    def test_loads_one_complete_version_and_keeps_it_immutable(self):
        repository = FakeRepository({"v1": rows()})
        snapshot = asyncio.run(SemanticModelSnapshotLoader(repository).load_for_query("v1"))
        self.assertEqual(snapshot.version_id, "v1")
        self.assertEqual(len(snapshot.tables), 2)
        meta_config = snapshot.to_meta_config()
        self.assertEqual(meta_config.datasets[0].id, "orders")
        self.assertEqual(meta_config.dimensions[0].column, "name")
        with self.assertRaises(AttributeError):
            snapshot.tables.append(snapshot.tables[0])
        self.assertEqual(repository.loaded, ["v1"])

    def test_rejects_cross_version_or_missing_association(self):
        invalid = rows()
        invalid["columns"] = [ColumnInfo("missing.amount", "amount", "decimal", "measure", [], "", [], "missing", "v1")]
        repository = FakeRepository({"v1": invalid})
        with self.assertRaisesRegex(SemanticModelVersionError, "不存在的表"):
            asyncio.run(SemanticModelSnapshotLoader(repository).load_for_query("v1"))

    def test_relationships_accept_declared_column_references(self):
        model_rows = rows()
        model_rows["relationships"] = [RelationshipInfo("order_customer", "fact_order.amount", "dim_region.name", "many_to_one", True, "v1")]
        repository = FakeRepository({"v1": model_rows})
        snapshot = asyncio.run(SemanticModelSnapshotLoader(repository).load_for_query("v1"))
        self.assertEqual(snapshot.relationships[0].source, "fact_order.amount")
    def test_draft_is_build_only(self):
        repository = FakeRepository({"draft": rows("draft", "draft")})
        loader = SemanticModelSnapshotLoader(repository)
        with self.assertRaisesRegex(SemanticModelVersionError, "不得读取 draft"):
            asyncio.run(loader.load_for_query("draft"))
        snapshot = asyncio.run(loader.load_for_build("draft"))
        self.assertEqual(snapshot.status, "draft")

    def test_query_selects_active_once_and_recovery_keeps_bound_version(self):
        repository = FakeRepository({"active": rows("active"), "archived": rows("archived", "archived")})
        loader = SemanticModelSnapshotLoader(repository)
        asyncio.run(loader.load_for_query())
        asyncio.run(loader.load_for_query("archived"))
        self.assertEqual(repository.active_calls, 1)
        self.assertEqual(repository.loaded, ["active", "archived"])


if __name__ == "__main__":
    unittest.main()

