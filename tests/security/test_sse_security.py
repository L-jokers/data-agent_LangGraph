import asyncio
import unittest
from types import SimpleNamespace

from app.agent.nodes.execute_sql import execute_sql


class FakeRepository:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    async def execute_sql(self, *args, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class FakeRuntime:
    def __init__(self, repository):
        self.context = {"dw_mysql_repository": repository}
        self.events = []
        self.stream_writer = self.events.append


class SseSecurityTests(unittest.TestCase):
    def compiled(self):
        return SimpleNamespace(sql="SELECT 1", params={}, max_rows=2, timeout_seconds=1)

    def test_truncation_metadata_is_forwarded(self):
        repository = FakeRepository(SimpleNamespace(
            rows=[{"id": 1}, {"id": 2}],
            truncated=True,
            row_count=2,
            max_rows=2,
        ))
        runtime = FakeRuntime(repository)
        asyncio.run(execute_sql({"compiled_query": self.compiled()}, runtime))
        self.assertEqual([event["type"] for event in runtime.events], ["result", "done"])
        self.assertTrue(runtime.events[0]["meta"]["truncated"])
        self.assertEqual(runtime.events[1]["status"], "success")

    def test_database_error_is_stable_and_sanitized(self):
        repository = FakeRepository(error=RuntimeError("password=secret"))
        runtime = FakeRuntime(repository)
        asyncio.run(execute_sql({"compiled_query": self.compiled()}, runtime))
        self.assertEqual([event["type"] for event in runtime.events], ["error", "done"])
        self.assertEqual(runtime.events[0]["code"], "QUERY_EXECUTION_FAILED")
        self.assertNotIn("secret", str(runtime.events[0]))
        self.assertEqual(runtime.events[1]["status"], "error")


if __name__ == "__main__":
    unittest.main()
