import asyncio
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from app.entities.table_info import TableInfo
from app.models import (
    Base,
    ColumnInfoMySQL,
    ColumnMetricMySQL,
    DatasetInfoMySQL,
    DimensionInfoMySQL,
    MetricDependencyMySQL,
    MetricInfoMySQL,
    RelationshipInfoMySQL,
    SemanticModelCurrentMySQL,
    SemanticModelVersionMySQL,
    TableInfoMySQL,
    TimeDimensionInfoMySQL,
)
from app.repositories.mysql.meta.meta_mysql_repository import (
    MetaMySQLRepository,
    SemanticModelVersionError,
)


class FakeScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return self.value

    def scalar_one(self):
        return self.value


class FakeSession:
    def __init__(self, results):
        self.results = iter(results)

    async def execute(self, statement):
        return next(self.results)


class DraftVersionSession:
    def __init__(self, existing=None):
        self.existing = existing
        self.added = []
        self.flush_count = 0

    async def get(self, model, version_id):
        return self.existing

    def add(self, model):
        self.added.append(model)

    async def flush(self):
        self.flush_count += 1


class ActivationGate:
    def __init__(self):
        self.calls = []

    async def assert_ready(self, version_id, content_hash):
        self.calls.append((version_id, content_hash))


class TransactionContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False


class ActivationSession:
    def __init__(self, results, old_version):
        self.results = iter(results)
        self.old_version = old_version
        self.flush_count = 0
        self.statements = []

    def begin(self):
        return TransactionContext()

    async def execute(self, statement):
        self.statements.append(statement)
        return next(self.results)

    async def get(self, model, version_id):
        return self.old_version

    async def flush(self):
        self.flush_count += 1


class SemanticVersioningTests(unittest.TestCase):
    def test_metadata_tables_have_composite_version_keys(self):
        versioned_models = (
            TableInfoMySQL,
            ColumnInfoMySQL,
            MetricInfoMySQL,
            ColumnMetricMySQL,
            TimeDimensionInfoMySQL,
            RelationshipInfoMySQL,
            DatasetInfoMySQL,
            DimensionInfoMySQL,
            MetricDependencyMySQL,
        )
        for model in versioned_models:
            with self.subTest(model=model.__name__):
                self.assertIn("version_id", model.__table__.primary_key.columns)
                self.assertIn("version_id", model.__table__.columns)

    def test_version_schema_has_database_active_uniqueness_and_singleton_guard(self):
        unique_columns = {
            tuple(column.name for column in constraint.columns)
            for constraint in SemanticModelVersionMySQL.__table__.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
        self.assertIn(("active_version_guard",), unique_columns)
        self.assertIn(
            "singleton_id",
            SemanticModelCurrentMySQL.__table__.primary_key.columns,
        )
        self.assertTrue(
            any(
                "singleton_id = 1" in str(constraint.sqltext)
                for constraint in SemanticModelCurrentMySQL.__table__.constraints
                if hasattr(constraint, "sqltext")
            )
        )

    def test_all_versioned_tables_compile_for_mysql(self):
        for table in Base.metadata.sorted_tables:
            with self.subTest(table=table.name):
                str(CreateTable(table).compile(dialect=mysql.dialect()))

    def test_missing_current_version_fails_closed(self):
        repository = MetaMySQLRepository(
            FakeSession([FakeScalarResult(SimpleNamespace(version_id=None))])
        )
        with self.assertRaisesRegex(SemanticModelVersionError, "未配置 active"):
            asyncio.run(repository.get_active_version_id())

    def test_missing_pointer_fails_closed(self):
        repository = MetaMySQLRepository(FakeSession([FakeScalarResult(None)]))
        with self.assertRaisesRegex(SemanticModelVersionError, "未配置 active"):
            asyncio.run(repository.get_active_version_id())

    def test_pointer_and_active_status_mismatch_fails_closed(self):
        repository = MetaMySQLRepository(
            FakeSession(
                [
                    FakeScalarResult(SimpleNamespace(version_id="v2")),
                    FakeScalarResult(["v1"]),
                ]
            )
        )
        with self.assertRaisesRegex(SemanticModelVersionError, "不一致"):
            asyncio.run(repository.get_active_version_id())

    def test_active_selection_fails_closed_for_zero_or_multiple_active_versions(self):
        mismatched_active_sets = ([], ["v2", "v3"])
        for active_ids in mismatched_active_sets:
            with self.subTest(active_ids=active_ids):
                repository = MetaMySQLRepository(
                    FakeSession(
                        [
                            FakeScalarResult(SimpleNamespace(version_id="v2")),
                            FakeScalarResult(active_ids),
                        ]
                    )
                )
                with self.assertRaisesRegex(
                    SemanticModelVersionError, "不一致"
                ):
                    asyncio.run(repository.get_active_version_id())

    def test_repository_rejects_cross_version_entity_write(self):
        with self.assertRaisesRegex(SemanticModelVersionError, "版本与写入版本不一致"):
            MetaMySQLRepository._for_version(
                TableInfo("fact", "fact", "fact", "", version_id="v1"), "v2"
            )

    def test_new_database_schema_is_versioned_and_non_destructive(self):
        schema = Path("docker/mysql/meta.sql").read_text(encoding="utf-8")
        normalized = schema.upper()
        self.assertNotIn("DROP TABLE", normalized)
        self.assertNotIn("TRUNCATE", normalized)
        self.assertNotIn("DELETE FROM", normalized)
        for table_name in (
            "table_info",
            "column_info",
            "metric_info",
            "column_metric",
            "time_dimension",
            "relationship",
            "dataset",
            "dimension_info",
            "metric_dependency",
        ):
            with self.subTest(table=table_name):
                self.assertIn(f"CREATE TABLE {table_name}".upper(), normalized)
        self.assertIn("CREATE TABLE semantic_model_version".upper(), normalized)
        self.assertIn("CREATE TABLE semantic_model_current".upper(), normalized)
        self.assertIn("INSERT INTO semantic_model_current (singleton_id, version_id) VALUES (1, NULL)", schema)

    def test_new_database_schema_contains_all_model_columns(self):
        statements = Path("docker/mysql/meta.sql").read_text(
            encoding="utf-8"
        ).split(";")
        create_statements = {
            match.group(1): statement
            for statement in statements
            if (match := re.search(r"CREATE TABLE\s+(\w+)", statement, re.IGNORECASE))
        }
        for table in Base.metadata.sorted_tables:
            with self.subTest(table=table.name):
                self.assertIn(table.name, create_statements)
                for column in table.columns:
                    self.assertRegex(
                        create_statements[table.name],
                        rf"(?<!\w){re.escape(column.name)}(?!\w)",
                    )

    def test_builder_does_not_execute_schema_ddl(self):
        builder = Path("app/scripts/build_meta_knowledge.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("initialize_meta_schema", builder)
        self.assertNotIn("versioned_meta.sql", builder)

    def test_create_draft_version_persists_new_version(self):
        session = DraftVersionSession()
        repository = MetaMySQLRepository(session)

        created = asyncio.run(
            repository.create_draft_version("v1", "hash", "first version")
        )

        self.assertTrue(created)
        self.assertEqual(len(session.added), 1)
        self.assertEqual(session.added[0].version_id, "v1")
        self.assertEqual(session.added[0].content_hash, "hash")
        self.assertEqual(session.added[0].status, "draft")
        self.assertEqual(session.flush_count, 1)

    def test_create_draft_version_is_idempotent_for_same_hash(self):
        session = DraftVersionSession(
            SimpleNamespace(content_hash="hash", version_id="v1")
        )
        repository = MetaMySQLRepository(session)

        created = asyncio.run(repository.create_draft_version("v1", "hash"))

        self.assertFalse(created)
        self.assertEqual(session.added, [])
        self.assertEqual(session.flush_count, 0)

    def test_create_draft_version_rejects_hash_conflict(self):
        session = DraftVersionSession(
            SimpleNamespace(content_hash="original", version_id="v1")
        )
        repository = MetaMySQLRepository(session)

        with self.assertRaisesRegex(SemanticModelVersionError, "拒绝覆盖"):
            asyncio.run(repository.create_draft_version("v1", "different"))

    def test_activation_updates_version_state_and_pointer_in_one_transaction(self):
        pointer = SimpleNamespace(singleton_id=1, version_id="v1")
        target = SimpleNamespace(
            version_id="v2",
            status="draft",
            activated_at=None,
            content_hash="hash-v2",
        )
        previous = SimpleNamespace(version_id="v1", status="active")
        session = ActivationSession(
            [
                FakeScalarResult(pointer),
                FakeScalarResult(target),
                FakeScalarResult(["v1"]),
                *[FakeScalarResult(1) for _ in range(6)],
            ],
            previous,
        )

        gate = ActivationGate()
        asyncio.run(MetaMySQLRepository(session).activate_version("v2", gate))

        self.assertEqual(pointer.version_id, "v2")
        self.assertEqual(target.status, "active")
        self.assertIsNotNone(target.activated_at)
        self.assertEqual(previous.status, "archived")
        self.assertEqual(gate.calls, [("v2", "hash-v2")])
        self.assertEqual(session.flush_count, 1)
        self.assertIn(
            "FOR UPDATE",
            str(session.statements[0].compile(dialect=mysql.dialect())).upper(),
        )
        self.assertIn(
            "FOR UPDATE",
            str(session.statements[1].compile(dialect=mysql.dialect())).upper(),
        )

    def test_activation_requires_an_index_activation_gate(self):
        pointer = SimpleNamespace(singleton_id=1, version_id=None)
        target = SimpleNamespace(
            version_id="v1", status="draft", activated_at=None, content_hash="hash"
        )
        session = ActivationSession(
            [
                FakeScalarResult(pointer),
                FakeScalarResult(target),
                FakeScalarResult([]),
                *[FakeScalarResult(1) for _ in range(6)],
            ],
            None,
        )

        with self.assertRaisesRegex(SemanticModelVersionError, "激活门禁"):
            asyncio.run(MetaMySQLRepository(session).activate_version("v1", None))

    def test_versioned_repository_read_filters_by_requested_version(self):
        class RecordingSession:
            statement = None

            async def execute(self, statement):
                self.statement = statement
                return FakeScalarResult(None)

        session = RecordingSession()
        repository = MetaMySQLRepository(session)

        result = asyncio.run(repository.get_column_info_by_id("c1", "v2"))
        sql = str(session.statement.compile(dialect=mysql.dialect()))

        self.assertIsNone(result)
        self.assertIn("column_info.version_id", sql)
        self.assertIn("column_info.id", sql)


if __name__ == "__main__":
    unittest.main()
