import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.api.schemas.query_schema import QuerySchema
from app.services.query_service import QueryService


class FakeGraph:
    def __init__(self, events=None, error=None):
        self.events = events or []
        self.error = error

    async def astream(self, **kwargs):
        for event in self.events:
            yield event
        if self.error:
            raise self.error


def parse_events(lines):
    return [json.loads(line[6:]) for line in lines if line.startswith("data: ")]


class QueryApiContractTests(unittest.TestCase):
    def service(self):
        return QueryService(None, None, None, None, None, None)

    def collect(self, service):
        return parse_events(asyncio.run(self._collect(service)))

    async def _collect(self, service):
        return [event async for event in service.query("查询 2025 年 1 月各大区的订单实付金额")]

    def test_original_request_format_is_accepted(self):
        request = QuerySchema.model_validate({
            "query": "查询 2025 年 1 月各大区的订单实付金额"
        })
        self.assertEqual(request.query, "查询 2025 年 1 月各大区的订单实付金额")

    def test_success_event_order_and_terminal_status(self):
        graph = FakeGraph([
            {"type": "progress", "step": "验证SQL", "status": "success"},
            {"type": "sql", "sql": "SELECT 1"},
            {"type": "result", "rows": [{"value": 1}], "meta": {"truncated": False}},
            {"type": "done", "status": "success"},
        ])
        with patch("app.services.query_service.graph", graph):
            events = self.collect(self.service())
        self.assertEqual([event["type"] for event in events], [
            "progress", "sql", "result", "done"
        ])
        self.assertEqual(events[-1]["status"], "success")
        self.assertEqual(events[2]["rows"], [{"value": 1}])

    def test_clarification_does_not_emit_sql_or_execute(self):
        graph = FakeGraph([
            {"type": "progress", "step": "解析", "status": "success"},
            {"type": "clarification", "message": "请补充年份"},
            {"type": "done", "status": "needs_clarification"},
        ])
        with patch("app.services.query_service.graph", graph):
            events = self.collect(self.service())
        self.assertNotIn("sql", [event["type"] for event in events])
        self.assertEqual(events[-1]["status"], "needs_clarification")

    def test_unsupported_does_not_emit_sql_or_result(self):
        graph = FakeGraph([
            {"type": "unsupported", "message": "不支持该时间表达式"},
            {"type": "done", "status": "unsupported"},
        ])
        with patch("app.services.query_service.graph", graph):
            events = self.collect(self.service())
        self.assertEqual([event["type"] for event in events], ["unsupported", "done"])
        self.assertNotIn("result", [event["type"] for event in events])

    def test_empty_result_is_success(self):
        graph = FakeGraph([
            {"type": "progress", "step": "验证SQL", "status": "success"},
            {"type": "sql", "sql": "SELECT 1"},
            {"type": "result", "rows": [], "meta": {
                "empty": True,
                "truncated": False,
                "message": "查询成功，但没有匹配数据",
            }},
            {"type": "done", "status": "success"},
        ])
        with patch("app.services.query_service.graph", graph):
            events = self.collect(self.service())
        self.assertEqual(events[2]["rows"], [])
        self.assertTrue(events[2]["meta"]["empty"])
        self.assertEqual(events[-1]["status"], "success")

    def test_exception_is_sanitized_and_has_error_terminal(self):
        graph = FakeGraph(error=RuntimeError("mysql://user:password@host secret-api-key"))
        with patch("app.services.query_service.graph", graph):
            events = self.collect(self.service())
        payload = json.dumps(events, ensure_ascii=False)
        self.assertNotIn("password", payload)
        self.assertNotIn("secret-api-key", payload)
        self.assertEqual([event["type"] for event in events], ["error", "done"])
        self.assertEqual(events[-1]["status"], "error")


if __name__ == "__main__":
    unittest.main()
