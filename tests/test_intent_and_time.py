import unittest
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.intent.llm_output import LLMOutputParseError, response_to_payload
from app.intent.models import QueryIntent, QueryIntentParseError, QueryIntentStatus, TimeIntent
from app.intent.time_coverage import validate_time_extraction
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
        with self.assertRaises(QueryIntentParseError):
            QueryIntent.from_payload({"status": "ready", "time": {"expression": "本周", "grain": "unknown"}})

    def test_empty_time_set_is_rejected_instead_of_silently_ignored(self):
        with self.assertRaisesRegex(TimeParseError, "时间集合不能为空"):
            resolve_time_intent(TimeIntent(expression="日期集合", kind="set"), datetime.now(timezone.utc))

    def test_json_code_fence_is_supported_for_parser_boundary(self):
        payload = response_to_payload('```json\n{"status":"ready","metrics":[]}\n```')
        self.assertEqual(payload["status"], "ready")

    def test_response_adapter_accepts_fenced_json_text_blocks(self):
        response = type("Response", (), {
            "content": [{"type": "text", "text": '```json\n{"status":"ready"}\n```'}],
        })()
        self.assertEqual(response_to_payload(response), {"status": "ready"})

    def test_response_adapter_accepts_structured_output_envelope(self):
        response = {"parsed": {"status": "ready", "time": {"expression": "", "kind": "relative"}}, "parsing_error": None}
        self.assertEqual(response_to_payload(response), response["parsed"])

    def test_response_adapter_accepts_provider_structured_dict(self):
        payload = {"status": "ready", "time": {"expression": "", "kind": "relative"}}
        self.assertIs(response_to_payload(payload), payload)

    def test_schema_constraint_passes_provider_method_and_strict_flag(self):
        from app.agent.llm import create_schema_constrained_model

        model = SimpleNamespace(with_structured_output=unittest.mock.Mock(return_value="bound"))
        result = create_schema_constrained_model(model, {"type": "object"})
        self.assertEqual(result, "bound")
        model.with_structured_output.assert_called_once_with(
            {"type": "object"}, method="json_schema", strict=True, include_raw=False,
        )

    def test_response_adapter_rejects_failed_structured_output_without_echo(self):
        with self.assertRaisesRegex(LLMOutputParseError, "STRUCTURED_OUTPUT_PARSE_FAILED"):
            response_to_payload({"parsed": None, "parsing_error": "sensitive raw model output"})

    def test_time_null_and_missing_field_are_checked_against_original_query(self):
        with self.assertRaises(QueryIntentParseError) as raised:
            QueryIntent.from_payload({"status": "ready", "time": None})
        self.assertEqual(raised.exception.code, "TIME_NULL")
        self.assertEqual(raised.exception.status, QueryIntentStatus.NEEDS_CLARIFICATION)

        omitted = QueryIntent.from_payload({"status": "ready"})
        with self.assertRaises(QueryIntentParseError) as raised:
            validate_time_extraction("统计本周订单数", omitted)
        self.assertEqual(raised.exception.code, "TIME_OMITTED")
        self.assertEqual(raised.exception.status, QueryIntentStatus.NEEDS_CLARIFICATION)
        validate_time_extraction("统计订单数", omitted)

    def test_adapter_schema_and_time_coverage_accept_valid_intent_and_reject_bad_time(self):
        response = SimpleNamespace(content=(
            '{"status":"ready","metrics":["订单数"],"dimensions":[],"filters":[], '
            '"time":{"expression":"本周星期一和星期三","kind":"weekday_set",'
            '"weekdays":[1,3],"week_scope":"current"},"group_by":[],"order_by":[]}'
        ))
        payload = response_to_payload(response)
        intent = QueryIntent.from_payload(payload)
        validate_time_extraction("查询本周星期一和星期三的订单数", intent)
        self.assertEqual(intent.status, QueryIntentStatus.READY)
        self.assertEqual(intent.time.weekdays, [1, 3])

        with self.assertRaises(QueryIntentParseError) as raised:
            QueryIntent.from_payload({"status": "ready", "time": {"kind": "relative"}})
        self.assertEqual(raised.exception.code, "INVALID_TIME_SCHEMA")

    def test_null_time_structured_response_fails_closed_before_retriever_or_sql(self):
        from app.agent.graph import graph

        executed = []
        retriever = SimpleNamespace(hybrid_search=AsyncMock(side_effect=AssertionError("must not retrieve")))
        context = {
            "semantic_model_snapshot": SimpleNamespace(version_id="v1"),
            "semantic_candidate_retriever": retriever,
            "dw_mysql_repository": SimpleNamespace(execute_sql=AsyncMock(side_effect=lambda *a, **k: executed.append(a))),
            "query_limits": SimpleNamespace(max_rows=20, timeout_seconds=60, max_execution_time_ms=60000),
            "reference_time": None,
            "trusted_query_chain": None,
        }
        with patch("app.agent.llm.llm") as mocked_llm:
            mocked_llm.ainvoke = AsyncMock(return_value={
                "status": "ready", "metrics": ["订单数"], "dimensions": [],
                "filters": [], "time": None, "group_by": [], "order_by": [],
                "limit": None, "message": None, "missing": [],
            })
            result = asyncio.run(graph.ainvoke(
                {"query": "统计订单数", "semantic_version_id": "v1"}, context=context,
            ))
        self.assertEqual(result["query_intent"].status, QueryIntentStatus.NEEDS_CLARIFICATION)
        self.assertEqual(executed, [])
        retriever.hybrid_search.assert_not_awaited()

    def test_response_adapter_rejects_invalid_json_without_echoing_content(self):
        with self.assertRaises(LLMOutputParseError) as raised:
            response_to_payload("not json with private user value")
        self.assertEqual(raised.exception.code, "INVALID_JSON")
        self.assertNotIn("private user value", str(raised.exception))

    def test_query_intent_rejects_unknown_fields_and_wrong_types(self):
        with self.assertRaises(QueryIntentParseError):
            QueryIntent.from_payload({"status": "ready", "semantic_id": "forbidden"})
        with self.assertRaises(QueryIntentParseError):
            QueryIntent.from_payload({"status": "ready", "metrics": "not-a-list"})

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

    def test_multiple_dates_are_deduplicated_and_sorted(self):
        resolved = resolve_time_intent(
            TimeIntent(expression="多个日期", kind="set", dates=["2025-03-03", "2025-03-01", "2025-03-03"]),
            datetime(2025, 3, 10, tzinfo=timezone.utc),
        )
        self.assertEqual([item.isoformat() for item in resolved.dates], ["2025-03-01", "2025-03-03"])

    def test_adjacent_ranges_merge_without_changing_date_set(self):
        resolved = resolve_time_intent(
            TimeIntent(expression="多个区间", kind="set", ranges=[
                {"start": "2025-03-01", "end": "2025-03-03"},
                {"start": "2025-03-04", "end": "2025-03-05"},
            ]),
            datetime(2025, 3, 10, tzinfo=timezone.utc),
        )
        self.assertEqual(len(resolved.ranges), 1)
        self.assertEqual(resolved.ranges[0].start.isoformat(), "2025-03-01")
        self.assertEqual(resolved.ranges[0].end.isoformat(), "2025-03-05")

    def test_week_starts_on_sunday(self):
        resolved = resolve_time_intent(TimeIntent(expression="本周"), datetime(2025, 3, 5, tzinfo=timezone.utc))
        self.assertEqual(resolved.start.isoformat(), "2025-03-02")
        self.assertEqual(resolved.end.isoformat(), "2025-03-08")

    def test_weekday_set_requires_explicit_week_scope_and_preserves_discrete_dates(self):
        with self.assertRaisesRegex(QueryIntentParseError, "缺少周范围"):
            QueryIntent.from_payload({
                "status": "ready", "metrics": ["订单数"],
                "time": {"expression": "星期一和星期三", "kind": "weekday_set", "weekdays": [1, 3]},
            })
        resolved = resolve_time_intent(
            TimeIntent(expression="本周星期一和星期三", kind="weekday_set", weekdays=[1, 3], week_scope="current"),
            datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc),
        )
        self.assertEqual([item.isoformat() for item in resolved.dates], ["2026-10-26", "2026-10-28"])

    def test_periodic_weekday_is_not_silently_converted_to_current_week(self):
        with self.assertRaisesRegex(TimeParseError, "周期星期筛选暂不支持"):
            resolve_time_intent(
                TimeIntent(expression="每周一和周三", kind="periodic_weekday", weekdays=[1, 3]),
                datetime(2026, 10, 31, tzinfo=timezone.utc),
            )

    def test_time_coverage_rejects_omitted_and_partial_llm_output(self):
        with self.assertRaisesRegex(QueryIntentParseError, "结构化输出为空"):
            validate_time_extraction(
                "查询本周星期一和星期三的订单数",
                QueryIntent(
                    status=QueryIntentStatus.READY,
                    metrics=["订单数"],
                    time=None,
                ),
            )
        partial = QueryIntent.from_payload({
            "status": "ready", "metrics": ["订单数"],
            "time": {"expression": "本周", "kind": "relative"},
        })
        with self.assertRaisesRegex(QueryIntentParseError, "未覆盖"):
            validate_time_extraction("查询本周星期一和星期三的订单数", partial)

    def test_time_coverage_allows_legal_no_time_query(self):
        intent = QueryIntent.from_payload({
            "status": "ready", "metrics": ["订单数"],
            "time": {"expression": "", "kind": "relative"},
        })
        validate_time_extraction("查询订单数", intent)

    def test_time_limits_are_rejected_without_truncation(self):
        with self.assertRaisesRegex(TimeParseError, "最多支持7个"):
            resolve_time_intent(TimeIntent(expression="日期集合", dates=[f"2025-03-{day:02d}" for day in range(1, 9)]), datetime.now(timezone.utc))
        with self.assertRaisesRegex(TimeParseError, "最多支持5个"):
            resolve_time_intent(TimeIntent(expression="区间集合", ranges=[{"start": f"2025-03-{day:02d}", "end": f"2025-03-{day:02d}"} for day in (1, 3, 5, 7, 9, 11)]), datetime.now(timezone.utc))

    def test_prompt_contains_no_fixed_business_mapping(self):
        prompt = Path("prompts/parse_intent.prompt").read_text(encoding="utf-8")
        self.assertNotIn("paid_amount", prompt)
        self.assertNotIn("region_name", prompt)
        self.assertIn('没有时间条件时省略整个 "time" 字段', prompt)
        self.assertIn('必须包含字符串 "expression"', prompt)
        self.assertIn("weekday_set、periodic_weekday", prompt)


if __name__ == "__main__":
    unittest.main()
