import asyncio
import unittest
from types import SimpleNamespace

from app.agent.nodes.execute_sql import execute_sql


class FakeRepository:
    def __init__(self, rows):
        self.rows = rows

    async def execute_sql(self, *args, **kwargs):
        return SimpleNamespace(rows=self.rows, truncated=False, max_rows=100)


class FakeRuntime:
    def __init__(self, rows):
        self.context = {"dw_mysql_repository": FakeRepository(rows)}
        self.events = []
        self.stream_writer = self.events.append


class Stage6ResultSemanticsTests(unittest.TestCase):
    def compiled(self, sql):
        return SimpleNamespace(sql=sql, params={}, max_rows=100, timeout_seconds=1)

    def run_execution(self, sql, rows):
        runtime = FakeRuntime(rows)
        asyncio.run(execute_sql({"compiled_query": self.compiled(sql)}, runtime))
        return runtime.events

    def test_zero_aggregate_value_is_a_nonempty_result_row(self):
        events = self.run_execution(
            "SELECT COUNT(*) AS row_count FROM fact_order",
            [{"row_count": 0}],
        )
        result = events[0]
        self.assertEqual(result["rows"], [{"row_count": 0}])
        self.assertFalse(result["meta"]["empty"])
        self.assertEqual(events[-1], {"type": "done", "status": "success"})

    def test_null_aggregate_value_is_a_nonempty_result_row(self):
        events = self.run_execution(
            "SELECT SUM(fact_order.amount) AS total FROM fact_order",
            [{"total": None}],
        )
        result = events[0]
        self.assertEqual(result["rows"], [{"total": None}])
        self.assertFalse(result["meta"]["empty"])

    def test_no_returned_rows_are_reported_as_empty_success(self):
        events = self.run_execution("SELECT total FROM report", [])
        result = events[0]
        self.assertEqual(result["rows"], [])
        self.assertTrue(result["meta"]["empty"])
        self.assertEqual(events[-1], {"type": "done", "status": "success"})


if __name__ == "__main__":
    unittest.main()
