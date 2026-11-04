import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.agent.nodes.plan_query import plan_query
from app.conf.meta_config import load_meta_config
from app.entities.metric_dependency import MetricDependency
from app.entities.metric_info import MetricInfo
from app.intent.models import QueryIntent, QueryIntentStatus
from app.services.clarification_recovery import (
    ClarificationRecoveryError,
    InMemoryClarificationStore,
    combine_clarification_query,
    resume_clarification,
)
from app.services.metric_dependency_validator import validate_metric_dependencies


CONFIG_PATH = Path(__file__).parents[1] / "conf" / "meta_config.yaml"


def metric(metric_id, metric_type="simple", *, version="v1", deps=None, **kwargs):
    defaults = {
        "grain": "order",
        "period": "day",
        "business_scope": "all",
        "aggregation": "sum",
    } if metric_type in {"derived", "ratio", "calculated", "window"} else {}
    defaults.update(kwargs)
    return MetricInfo(
        id=metric_id,
        name=metric_id,
        description=metric_id,
        relevant_columns=["fact_order.amount"],
        alias=[],
        metric_type=metric_type,
        expression=defaults.pop("expression", "SUM(fact_order.amount)"),
        base_dataset="orders",
        status=defaults.pop("status", "active"),
        version_id=version,
        **defaults,
    )


def snapshot(metrics, dependencies=(), version="v1"):
    return SimpleNamespace(
        version_id=version,
        metrics=tuple(metrics),
        metric_dependencies=tuple(dependencies),
        to_meta_config=lambda: load_meta_config(CONFIG_PATH),
    )


class MetricDependencyValidationTests(unittest.TestCase):
    def test_depth_zero_one_and_two_are_allowed_but_three_is_rejected(self):
        base = metric("base")
        direct = metric("direct", "derived", aggregation="avg")
        depth_two = metric("depth_two", "derived", aggregation="max")
        depth_three = metric("depth_three", "derived", aggregation="count")
        dependencies = [
            MetricDependency("direct", "base", version_id="v1"),
            MetricDependency("depth_two", "direct", version_id="v1"),
            MetricDependency("depth_three", "depth_two", version_id="v1"),
        ]
        validate_metric_dependencies(snapshot([base, direct, depth_two, depth_three], dependencies), ["base", "direct", "depth_two"])
        with self.assertRaisesRegex(ValueError, "依赖深度"):
            validate_metric_dependencies(snapshot([base, direct, depth_two, depth_three], dependencies), ["depth_three"])

    def test_cycle_unknown_cross_version_and_window_input_are_blocked(self):
        a = metric("a", "derived", aggregation="avg")
        b = metric("b", "derived", aggregation="max")
        with self.assertRaisesRegex(ValueError, "循环依赖"):
            validate_metric_dependencies(
                snapshot([a, b], [MetricDependency("a", "b", version_id="v1"), MetricDependency("b", "a", version_id="v1")]),
                ["a"],
            )
        with self.assertRaisesRegex(ValueError, "不存在的指标"):
            validate_metric_dependencies(snapshot([a], [MetricDependency("a", "missing", version_id="v1")]), ["a"])
        with self.assertRaisesRegex(ValueError, "跨越语义版本"):
            validate_metric_dependencies(snapshot([a], [MetricDependency("a", "a", version_id="v2")]), ["a"])
        window = metric("window", "window")
        with self.assertRaisesRegex(ValueError, "窗口指标"):
            validate_metric_dependencies(
                snapshot([a, window], [MetricDependency("a", "window", version_id="v1")]), ["a"]
            )

    def test_derived_missing_definition_returns_structured_clarification(self):
        incomplete = metric(
            "ratio", "ratio", expression=None, aggregation=None,
            grain=None, period=None, business_scope=None,
        )
        with self.assertRaises(ValueError) as context:
            validate_metric_dependencies(snapshot([incomplete]), ["ratio"])
        error = context.exception
        self.assertEqual(error.code, "METRIC_DEFINITION_INCOMPLETE")
        self.assertEqual(error.status, "needs_clarification")
        self.assertIn("统计周期", error.missing)
        self.assertIn("聚合方式", error.missing)

    def test_status_grain_duplicate_aggregation_and_stage_rules_are_enforced(self):
        inactive = metric("inactive", status="deprecated")
        with self.assertRaisesRegex(ValueError, "状态不可查询"):
            validate_metric_dependencies(snapshot([inactive]), ["inactive"])

        parent = metric("parent", "derived", aggregation="sum")
        child = metric("child", "derived", aggregation="sum")
        with self.assertRaisesRegex(ValueError, "重复聚合"):
            validate_metric_dependencies(
                snapshot([parent, child], [MetricDependency("child", "parent", version_id="v1")]), ["child"]
            )

        grain_conflict = metric("grain_conflict", grain="month")
        with self.assertRaisesRegex(ValueError, "粒度"):
            validate_metric_dependencies(snapshot([grain_conflict]), ["grain_conflict"], query_grain="day")

        filter_stage = metric("filter_stage", "derived", stage="filter")
        with self.assertRaisesRegex(ValueError, "过滤阶段"):
            validate_metric_dependencies(snapshot([filter_stage]), ["filter_stage"])

    def test_plan_query_receives_snapshot_and_keeps_version_in_plan(self):
        config_metric = metric("paid_amount")
        fake_snapshot = snapshot([config_metric], version="v1")
        intent = QueryIntent.from_payload({"status": "ready", "metrics": ["paid_amount"]})
        events = []
        runtime = SimpleNamespace(
            context={"semantic_model_snapshot": fake_snapshot},
            stream_writer=events.append,
        )
        result = asyncio.run(plan_query({"query_intent": intent}, runtime))
        self.assertEqual(result["query_plan"].semantic_version_id, "v1")
        self.assertEqual(result["query_plan"].metrics[0].id, "paid_amount")

    def test_plan_query_uses_snapshot_and_returns_clarification_for_missing_definition(self):
        config = load_meta_config(CONFIG_PATH)
        incomplete = metric(
            "paid_amount", "derived", expression=None, aggregation=None,
            grain=None, period=None, business_scope=None,
        )
        fake_snapshot = snapshot([incomplete])
        intent = QueryIntent.from_payload({"status": "ready", "metrics": ["paid_amount"]})
        events = []
        runtime = SimpleNamespace(
            context={"semantic_model_snapshot": fake_snapshot},
            stream_writer=events.append,
        )
        result = asyncio.run(plan_query({"query_intent": intent}, runtime))
        self.assertEqual(result["query_intent"].status, QueryIntentStatus.NEEDS_CLARIFICATION)
        self.assertIn("统计粒度", result["query_intent"].missing)
        self.assertIsNone(result["query_plan"])


class ClarificationRecoveryTests(unittest.TestCase):
    def test_only_pending_clarification_can_resume_with_original_query_and_fixed_version(self):
        store = InMemoryClarificationStore()
        record = store.create("统计销售额", "v1", ["统计周期"])
        pending = store.get_pending(record.session_id, record.clarification_id)
        consumed = store.consume(pending)
        self.assertEqual(consumed.semantic_version_id, "v1")
        self.assertIn("统计销售额", combine_clarification_query(consumed, "按月统计"))
        store.complete(record.session_id, record.clarification_id, "success")
        with self.assertRaisesRegex(ClarificationRecoveryError, "不支持上下文追问"):
            store.get_pending(record.session_id, record.clarification_id)

    def test_empty_answer_and_wrong_clarification_are_blocked(self):
        store = InMemoryClarificationStore()
        record = store.create("统计销售额", "v1", ["来源字段"])
        with self.assertRaisesRegex(ClarificationRecoveryError, "不能为空"):
            combine_clarification_query(record, " ")
        with self.assertRaisesRegex(ClarificationRecoveryError, "不匹配"):
            store.get_pending(record.session_id, "wrong")

    def test_resume_reparses_complete_query_and_keeps_bound_version(self):
        store = InMemoryClarificationStore()
        record = store.create("统计销售额", "v-fixed", ["统计周期"])
        calls = []

        async def runner(query, version_id):
            calls.append((query, version_id))
            return {"status": "planned"}

        result = asyncio.run(resume_clarification(
            store, record.session_id, record.clarification_id, "按月统计", runner
        ))
        self.assertEqual(result["status"], "planned")
        self.assertEqual(calls[0][1], "v-fixed")
        self.assertIn("统计销售额", calls[0][0])
        self.assertIn("按月统计", calls[0][0])


if __name__ == "__main__":
    unittest.main()
