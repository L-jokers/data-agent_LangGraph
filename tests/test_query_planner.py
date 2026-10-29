import copy
import unittest
from pathlib import Path

import yaml

from app.conf.meta_config import MetaConfig, load_meta_config
from app.intent.models import QueryIntent, QueryIntentStatus, TimeIntent
from app.planner.models import QueryPlanError
from app.planner.planner import build_query_plan


CONFIG_PATH = Path(__file__).parents[1] / "conf" / "meta_config.yaml"


def ready_intent(**kwargs):
    payload = {
        "status": "ready",
        "metrics": ["paid_amount"],
        "dimensions": [],
        "filters": [],
        "group_by": [],
        "order_by": [],
        "limit": None,
    }
    payload.update(kwargs)
    return QueryIntent.from_payload(payload)


class QueryPlannerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_meta_config(CONFIG_PATH)

    def test_resolves_stable_ids_and_selects_configured_join(self):
        plan = build_query_plan(
            self.config,
            ready_intent(
                metrics=["订单实付金额", "订单数"],
                dimensions=["大区"],
                group_by=["大区"],
                order_by=[{"field": "订单实付金额", "direction": "desc"}],
            ),
        )

        self.assertEqual([metric.id for metric in plan.metrics], ["paid_amount", "order_count"])
        self.assertEqual([dimension.id for dimension in plan.dimensions], ["region_name"])
        self.assertEqual([join.relationship_id for join in plan.joins], ["order_region"])
        self.assertEqual(plan.order_by[0].field_id, "paid_amount")

    def test_month_plan_requires_year_and_generates_year_month_conditions(self):
        plan = build_query_plan(
            self.config,
            ready_intent(metrics=["paid_amount"], dimensions=["region_name"]),
            {"start": "2025-01-01", "end": "2025-01-31", "grain": "month"},
        )

        self.assertEqual(
            [(condition.field, condition.operator, condition.value) for condition in plan.time.conditions],
            [("dim_date.year", "eq", 2025), ("dim_date.month", "eq", 1)],
        )
        self.assertIn("order_date", [join.relationship_id for join in plan.joins])

    def test_order_count_and_average_quantity_use_confirmed_aggregations(self):
        plan = build_query_plan(
            self.config,
            ready_intent(metrics=["order_count", "AOV"]),
        )

        self.assertEqual(plan.aggregations["order_count"], "COUNT(DISTINCT fact_order.order_id)")
        self.assertEqual(
            plan.aggregations["average_quantity_per_order"],
            "SUM(fact_order.order_quantity) / NULLIF(COUNT(DISTINCT fact_order.order_id), 0)",
        )

    def test_physical_field_cannot_be_invented_by_intent(self):
        with self.assertRaisesRegex(QueryPlanError, "未知维度"):
            build_query_plan(
                self.config,
                ready_intent(dimensions=["fact_order.region_id"]),
            )

    def test_unknown_metric_is_blocked(self):
        with self.assertRaisesRegex(QueryPlanError, "未知指标"):
            build_query_plan(self.config, ready_intent(metrics=["unknown_metric"]))

    def test_filter_must_use_semantic_dimension(self):
        with self.assertRaisesRegex(QueryPlanError, "未知过滤维度"):
            build_query_plan(
                self.config,
                ready_intent(filters=[{"field": "region_id", "operator": "eq", "value": 1}]),
            )

    def test_sort_field_must_be_in_current_plan(self):
        with self.assertRaisesRegex(QueryPlanError, "排序字段未出现在当前查询计划"):
            build_query_plan(
                self.config,
                ready_intent(order_by=[{"field": "order_count", "direction": "desc"}]),
            )

    def test_limit_is_bounded(self):
        with self.assertRaisesRegex(QueryPlanError, "limit必须"):
            build_query_plan(self.config, ready_intent(limit=1001))

    def test_non_ready_intent_cannot_be_planned(self):
        intent = ready_intent()
        intent.status = QueryIntentStatus.NEEDS_CLARIFICATION
        with self.assertRaisesRegex(QueryPlanError, "非ready"):
            build_query_plan(self.config, intent)

    def test_ambiguous_alias_is_blocked(self):
        mapping = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        mapping = copy.deepcopy(mapping)
        mapping["dimensions"].append({
            "id": "another_region",
            "name": "另一个地区",
            "table": "dim_region",
            "column": "province",
            "aliases": ["大区"],
        })
        config = MetaConfig.from_mapping(mapping)
        with self.assertRaisesRegex(QueryPlanError, "维度存在歧义"):
            build_query_plan(config, ready_intent(dimensions=["大区"]))


if __name__ == "__main__":
    unittest.main()
