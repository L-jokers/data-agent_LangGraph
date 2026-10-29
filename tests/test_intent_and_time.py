import unittest
from datetime import datetime, timezone

from app.intent.llm_output import response_to_payload
from app.intent.models import QueryIntent, QueryIntentParseError, QueryIntentStatus, TimeIntent
from app.time.parser import TimeParseError, resolve_time_intent


class IntentAndTimeTest(unittest.TestCase):
    def test_structured_intent_payload_is_parsed(self):
        intent = QueryIntent.from_payload({
            "status": "ready",
            "metrics": ["订单实付金额"],
            "dimensions": ["大区"],
            "filters": [],
            "time": {"expression": "上个月", "kind": "relative"},
            "group_by": ["大区"],
            "order_by": [{"field": "订单实付金额", "direction": "desc"}],
            "limit": 100,
            "message": None,
            "missing": [],
        })

        self.assertEqual(intent.status, QueryIntentStatus.READY)
        self.assertEqual(intent.time.expression, "上个月")
        self.assertEqual(intent.limit, 100)

    def test_invalid_structured_output_is_rejected(self):
        with self.assertRaises(QueryIntentParseError):
            QueryIntent.from_payload({"status": "ready", "metrics": "订单数"})

    def test_json_code_fence_is_supported_for_parser_boundary(self):
        payload = response_to_payload('```json\n{"status":"ready","metrics":[]}\n```')
        self.assertEqual(payload["status"], "ready")

    def test_reference_time_uses_utc_plus_eight(self):
        reference_time = datetime(2025, 2, 28, 16, 30, tzinfo=timezone.utc)
        resolved = resolve_time_intent(TimeIntent(expression="今天"), reference_time)
        self.assertEqual(resolved.start.isoformat(), "2025-03-01")
        self.assertEqual(resolved.end.isoformat(), "2025-03-01")

    def test_recent_days_include_today_as_closed_natural_day_range(self):
        reference_time = datetime(2025, 3, 10, 1, 0, tzinfo=timezone.utc)
        resolved = resolve_time_intent(TimeIntent(expression="最近3天"), reference_time)
        self.assertEqual(resolved.start.isoformat(), "2025-03-08")
        self.assertEqual(resolved.end.isoformat(), "2025-03-10")

    def test_previous_month_crosses_year_boundary(self):
        reference_time = datetime(2025, 1, 15, 12, 0, tzinfo=timezone.utc)
        resolved = resolve_time_intent(TimeIntent(expression="上个月"), reference_time)
        self.assertEqual(resolved.start.isoformat(), "2024-12-01")
        self.assertEqual(resolved.end.isoformat(), "2024-12-31")

    def test_month_without_year_requires_clarification(self):
        with self.assertRaisesRegex(TimeParseError, "缺少年份"):
            resolve_time_intent(
                TimeIntent(expression="1月"),
                datetime(2025, 3, 1, tzinfo=timezone.utc),
            )

    def test_unsupported_time_expression_is_rejected(self):
        with self.assertRaisesRegex(TimeParseError, "不支持"):
            resolve_time_intent(
                TimeIntent(expression="去年同期"),
                datetime(2025, 3, 1, tzinfo=timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
