import json
import unittest
from types import SimpleNamespace

from app.intent.llm_output import response_to_payload
from app.intent.models import QueryIntent, QueryIntentParseError
from app.intent.time_coverage import validate_time_extraction


class T9CIntentOutputBoundaryTest(unittest.TestCase):
    def test_json_response_passes_adapter_schema_and_time_validation(self):
        cases = [
            (
                "relative_week",
                "\u67e5\u8be2\u672c\u5468\u8ba2\u5355\u6570",
                {
                    "status": "ready",
                    "metrics": ["orders"],
                    "time": {
                        "expression": "\u672c\u5468",
                        "kind": "relative",
                    },
                },
                "object",
            ),
            (
                "weekday_set",
                "\u67e5\u8be2\u672c\u5468\u661f\u671f\u4e00\u548c\u661f\u671f\u4e09\u7684\u8ba2\u5355\u6570",
                {
                    "status": "ready",
                    "metrics": ["orders"],
                    "time": {
                        "expression": "\u672c\u5468\u661f\u671f\u4e00\u548c\u661f\u671f\u4e09",
                        "kind": "weekday_set",
                        "weekdays": [1, 3],
                        "week_scope": "current",
                    },
                },
                "object",
            ),
            (
                "no_time",
                "\u67e5\u8be2\u8ba2\u5355\u6570",
                {"status": "ready", "metrics": ["orders"]},
                "missing",
            ),
            (
                "recent_days",
                "\u67e5\u8be2\u6700\u8fd17\u5929\u7684\u8ba2\u5355\u6570",
                {
                    "status": "ready",
                    "metrics": ["orders"],
                    "time": {
                        "expression": "\u6700\u8fd17\u5929",
                        "kind": "relative",
                    },
                },
                "object",
            ),
        ]

        for case_name, query, expected_payload, expected_time_shape in cases:
            with self.subTest(case=case_name):
                response = SimpleNamespace(
                    content=json.dumps(expected_payload, ensure_ascii=False)
                )
                payload = response_to_payload(response)
                self.assertEqual(set(payload), set(expected_payload))
                if "time" not in payload:
                    time_shape = "missing"
                elif payload["time"] is None:
                    time_shape = "null"
                elif isinstance(payload["time"], dict):
                    time_shape = "object"
                else:
                    time_shape = "other"
                self.assertEqual(time_shape, expected_time_shape)

                intent = QueryIntent.from_payload(payload)
                validate_time_extraction(query, intent)

    def test_invalid_time_shapes_fail_schema_validation(self):
        invalid_payloads = [
            ({"status": "ready", "time": None}, "TIME_NULL"),
            ({"status": "ready", "time": "relative"}, "INVALID_TIME_SCHEMA"),
            ({"status": "ready", "time": {"kind": "relative"}}, "INVALID_TIME_SCHEMA"),
        ]

        for payload, expected_code in invalid_payloads:
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(QueryIntentParseError) as raised:
                    QueryIntent.from_payload(payload)
                self.assertEqual(raised.exception.code, expected_code)

    def test_omitted_time_fails_time_completeness_validation(self):
        payload = response_to_payload(
            SimpleNamespace(content='{"status":"ready","metrics":["orders"]}')
        )
        intent = QueryIntent.from_payload(payload)

        with self.assertRaises(QueryIntentParseError) as raised:
            validate_time_extraction(
                "\u67e5\u8be2\u672c\u5468\u8ba2\u5355\u6570",
                intent,
            )

        self.assertEqual(raised.exception.code, "TIME_OMITTED")


if __name__ == "__main__":
    unittest.main()
