import asyncio
import unittest
from pathlib import Path

from app.compiler.sql_compiler import SQLCompilerError, compile_query
from app.conf.meta_config import load_meta_config
from app.intent.models import QueryIntent
from app.planner.planner import build_query_plan
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.agent.nodes.execute_sql import sanitize_execution_error
from app.security.query_limits import QueryResult
from app.security.sqlglot_validator import SQLSecurityError, validate_compiled_query


CONFIG_PATH = Path(__file__).parents[1] / "conf" / "meta_config.yaml"


class FakeMappings:
    def __init__(self, rows):
        self.rows = rows

    def fetchmany(self, count):
        return self.rows[:count]


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return FakeMappings(self.rows)


class FakeSession:
    def __init__(self, rows=None, error=None, delay=0):
        self.rows = rows or []
        self.error = error
        self.delay = delay
        self.calls = []

    async def execute(self, statement, params):
        self.calls.append((str(statement), params))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return FakeResult(self.rows)


def build_sample_plan(**payload):
    config = load_meta_config(CONFIG_PATH)
    data = {
        "status": "ready",
        "metrics": ["paid_amount"],
        "dimensions": ["region_name"],
        "group_by": ["region_name"],
        "filters": [],
        "order_by": [{"field": "paid_amount", "direction": "desc"}],
        "limit": 10,
    }
    data.update(payload)
    return build_query_plan(config, QueryIntent.from_payload(data))


class SQLPhase4Test(unittest.TestCase):
    def test_mysql_sql_structure_and_limit(self):
        compiled = compile_query(build_sample_plan())
        self.assertIn("FROM `fact_order`", compiled.sql)
        self.assertIn("JOIN `dim_region`", compiled.sql)
        self.assertIn("GROUP BY `dim_region`.`region_name`", compiled.sql)
        self.assertIn("ORDER BY `paid_amount` DESC", compiled.sql)
        self.assertIn("LIMIT 10", compiled.sql)
        self.assertIn("MAX_EXECUTION_TIME(5000)", compiled.sql)

    def test_explicit_limit_is_preserved_when_below_system_max(self):
        plan = build_sample_plan(limit=2)
        compiled = compile_query(plan, max_rows=100)

        self.assertTrue(plan.limit_explicit)
        self.assertIn("LIMIT 2", compiled.sql)

    def test_explicit_limit_equal_to_system_max_is_not_probe_limited(self):
        compiled = compile_query(build_sample_plan(limit=2), max_rows=2)

        self.assertIn("LIMIT 2", compiled.sql)

    def test_implicit_limit_requests_one_probe_row(self):
        plan = build_sample_plan(limit=None)
        compiled = compile_query(plan, max_rows=2)

        self.assertFalse(plan.limit_explicit)
        self.assertIn("LIMIT 3", compiled.sql)

    def test_explicit_limit_over_system_max_requests_one_probe_row(self):
        plan = build_sample_plan(limit=10)
        compiled = compile_query(plan, max_rows=2)

        self.assertTrue(plan.limit_explicit)
        self.assertIn("LIMIT 3", compiled.sql)

    def test_compiled_query_can_report_truncation(self):
        plan = build_sample_plan(limit=10)
        compiled = compile_query(plan, max_rows=2)
        session = FakeSession(rows=[{"id": 1}, {"id": 2}, {"id": 3}])
        validate_compiled_query(compiled)

        result = asyncio.run(
            DWMySQLRepository(session).execute_sql(
                compiled.sql,
                compiled.params,
                max_rows=compiled.max_rows,
            )
        )

        self.assertIn("LIMIT 3", compiled.sql)
        self.assertTrue(result.truncated)
        self.assertEqual(result.rows, [{"id": 1}, {"id": 2}])

    def test_filter_values_are_bound_not_embedded(self):
        compiled = compile_query(build_sample_plan(
            filters=[{"field": "region_name", "operator": "eq", "value": "x' OR 1=1"}],
        ))
        self.assertNotIn("x' OR 1=1", compiled.sql)
        self.assertIn(":p0", compiled.sql)
        self.assertEqual(compiled.params["p0"], "x' OR 1=1")

    def test_ast_accepts_compiled_query(self):
        validate_compiled_query(compile_query(build_sample_plan()))

    def test_ast_rejects_dml_ddl_and_multiple_statements(self):
        compiled = compile_query(build_sample_plan())
        for sql in [
            "INSERT INTO fact_order(order_id) VALUES (1)",
            "UPDATE fact_order SET order_amount = 1",
            "DELETE FROM fact_order",
            "DROP TABLE fact_order",
            "ALTER TABLE fact_order ADD x INT",
            "CREATE TABLE x (id INT)",
            "TRUNCATE TABLE fact_order",
            "SELECT 1; SELECT 2",
        ]:
            with self.subTest(sql=sql):
                with self.assertRaises(SQLSecurityError):
                    validate_compiled_query(compiled.__class__(
                        sql=sql,
                        params={},
                        max_rows=compiled.max_rows,
                        timeout_seconds=compiled.timeout_seconds,
                        max_execution_time_ms=compiled.max_execution_time_ms,
                        allowed_tables=frozenset({"fact_order"}),
                        allowed_columns=frozenset(),
                        allowed_functions=frozenset(),
                        allowed_joins=frozenset(),
                        allowed_join_conditions=frozenset(),
                    ))

    def test_ast_rejects_unauthorized_table_column_and_function(self):
        compiled = compile_query(build_sample_plan())
        for sql in [
            "SELECT * FROM secret_table LIMIT 1",
            "SELECT * FROM fact_order LIMIT 1",
            "SELECT secret_column FROM fact_order LIMIT 1",
            "SELECT SLEEP(10) FROM fact_order LIMIT 1",
        ]:
            with self.subTest(sql=sql):
                with self.assertRaises(SQLSecurityError):
                    validate_compiled_query(compiled.__class__(
                        sql=sql,
                        params={},
                        max_rows=compiled.max_rows,
                        timeout_seconds=compiled.timeout_seconds,
                        max_execution_time_ms=compiled.max_execution_time_ms,
                        allowed_tables=frozenset({"fact_order"}),
                        allowed_columns=frozenset({"fact_order.order_id"}),
                        allowed_functions=frozenset({"SUM"}),
                        allowed_joins=frozenset(),
                        allowed_join_conditions=frozenset(),
                    ))

    def test_ast_rejects_unauthorized_join_condition(self):
        compiled = compile_query(build_sample_plan())
        sql = compiled.sql.replace(
            "`fact_order`.`region_id` = `dim_region`.`region_id`",
            "`fact_order`.`customer_id` = `dim_region`.`region_id`",
        )
        with self.assertRaises(SQLSecurityError):
            validate_compiled_query(compiled.__class__(
                sql=sql,
                params=compiled.params,
                max_rows=compiled.max_rows,
                timeout_seconds=compiled.timeout_seconds,
                max_execution_time_ms=compiled.max_execution_time_ms,
                allowed_tables=compiled.allowed_tables,
                allowed_columns=compiled.allowed_columns,
                allowed_functions=compiled.allowed_functions,
                allowed_joins=compiled.allowed_joins,
                allowed_join_conditions=compiled.allowed_join_conditions,
            ))

    def test_max_rows_truncation_and_metadata(self):
        session = FakeSession(rows=[{"id": 1}, {"id": 2}, {"id": 3}])
        result = asyncio.run(DWMySQLRepository(session).execute_sql("SELECT 1", {}, max_rows=2))
        self.assertIsInstance(result, QueryResult)
        self.assertTrue(result.truncated)
        self.assertEqual(result.rows, [{"id": 1}, {"id": 2}])
        self.assertEqual(result.row_count, 2)

    def test_application_timeout_is_enforced(self):
        session = FakeSession(delay=0.05)
        with self.assertRaises(asyncio.TimeoutError):
            asyncio.run(DWMySQLRepository(session).execute_sql("SELECT 1", {}, timeout_seconds=0.001))

    def test_database_error_is_propagated_for_service_sanitization(self):
        session = FakeSession(error=RuntimeError("secret connection password"))
        with self.assertRaisesRegex(RuntimeError, "secret connection password"):
            asyncio.run(DWMySQLRepository(session).execute_sql("SELECT 1", {}))

    def test_database_error_is_sanitized_for_external_response(self):
        error = sanitize_execution_error(RuntimeError("secret connection password"))
        self.assertEqual(error, {"code": "QUERY_EXECUTION_FAILED", "message": "查询执行失败"})

    def test_invalid_compiler_limit_is_rejected(self):
        with self.assertRaises(SQLCompilerError):
            compile_query(build_sample_plan(), max_rows=0)


if __name__ == "__main__":
    unittest.main()
