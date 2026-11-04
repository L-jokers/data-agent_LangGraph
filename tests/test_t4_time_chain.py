import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agent.nodes.parse_intent import parse_intent
from app.intent.models import QueryIntentStatus


class T4TimeChainTest(unittest.TestCase):
    def run_node(self, query: str, response: str):
        writer = lambda event: None
        runtime = SimpleNamespace(stream_writer=writer)
        with patch("app.agent.llm.llm") as mocked_llm:
            mocked_llm.ainvoke = AsyncMock(return_value=response)
            return asyncio.run(parse_intent({"query": query}, runtime))

    def test_mock_llm_weekday_structure_is_preserved(self):
        result = self.run_node(
            "查询本周星期一和星期三的订单数",
            '{"status":"ready","metrics":["订单数"],"time":{"expression":"本周星期一和星期三","kind":"weekday_set","weekdays":[1,3],"week_scope":"current"}}',
        )
        self.assertEqual(result["query_intent"].status, QueryIntentStatus.READY)
        self.assertEqual(result["query_intent"].time.weekdays, [1, 3])

    def test_mock_llm_omitting_time_cannot_enter_ready(self):
        result = self.run_node(
            "查询本周星期一和星期三的订单数",
            '{"status":"ready","metrics":["订单数"]}',
        )
        self.assertEqual(result["query_intent"].status, QueryIntentStatus.NEEDS_CLARIFICATION)
        self.assertIn("TIME_OMITTED", result["query_intent"].missing)

    def test_invalid_llm_json_fails_closed_without_execution_path(self):
        result = self.run_node("private query text", "not valid JSON")
        self.assertEqual(result["query_intent"].status, QueryIntentStatus.UNSUPPORTED)
        self.assertEqual(result["query_intent"].missing, ["INVALID_JSON"])

    def test_schema_failure_logs_code_but_not_user_or_model_content(self):
        with patch("app.agent.nodes.parse_intent.logger.warning") as warning:
            self.run_node("private user data", "invalid model response with secret")
        warning.assert_called_once()
        template, stage, code, summary = warning.call_args.args
        self.assertIn("stage={}", template)
        self.assertIn("code={}", template)
        self.assertEqual((stage, code, summary), ("response_adaptation", "INVALID_JSON", "response_rejected"))
        log_text = " ".join(str(value) for value in warning.call_args.args)
        self.assertNotIn("private user data", log_text)
        self.assertNotIn("secret", log_text)


if __name__ == "__main__":
    unittest.main()
