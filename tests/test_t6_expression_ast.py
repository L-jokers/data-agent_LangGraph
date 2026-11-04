import copy
import unittest
from dataclasses import replace
from pathlib import Path

from app.compiler.sql_compiler import SQLCompilerError, compile_query
from app.conf.meta_config import MetaConfig, load_meta_config
from app.intent.models import QueryIntent
from app.planner.planner import build_query_plan


CONFIG_PATH = Path(__file__).parents[1] / "conf" / "meta_config.yaml"


def ready_intent(metrics):
    return QueryIntent.from_payload(
        {
            "status": "ready",
            "metrics": metrics,
            "dimensions": [],
            "group_by": [],
            "filters": [],
            "order_by": [],
            "limit": 10,
        }
    )


class T6ExpressionASTTest(unittest.TestCase):
    def setUp(self):
        self.config = load_meta_config(CONFIG_PATH)

    def test_new_metric_is_metadata_only_and_compiles(self):
        mapping = copy.deepcopy(__import__("yaml").safe_load(CONFIG_PATH.read_text(encoding="utf-8")))
        mapping["metrics"].append(
            {
                "id": "order_amount_max",
                "name": "订单金额最大值",
                "description": "订单金额最大值",
                "type": "simple",
                "base_dataset": "orders",
                "aliases": ["最大订单金额"],
                "relevant_columns": ["fact_order.order_amount"],
                "expression_ast": {
                    "node": "aggregate",
                    "function": "max",
                    "input": {"node": "field", "ref": "fact_order.order_amount"},
                },
            }
        )
        config = MetaConfig.from_mapping(mapping)
        plan = build_query_plan(config, ready_intent(["order_amount_max"]))
        compiled = compile_query(plan)
        self.assertIn("MAX(`fact_order`.`order_amount`)", compiled.sql)

    def test_unknown_ast_node_fails_closed(self):
        plan = build_query_plan(self.config, ready_intent(["paid_amount"]))
        broken = replace(plan, expression_asts={"paid_amount": {"node": "raw_sql", "sql": "DROP TABLE x"}})
        with self.assertRaises(SQLCompilerError):
            compile_query(broken)

    def test_unknown_function_operator_and_field_fail_closed(self):
        plan = build_query_plan(self.config, ready_intent(["paid_amount"]))
        cases = [
            {"node": "function", "function": "concat", "args": [{"node": "literal", "value": 1}]},
            {"node": "binary", "op": "||", "left": {"node": "literal", "value": 1}, "right": {"node": "literal", "value": 1}},
            {"node": "aggregate", "function": "sum", "input": {"node": "field", "ref": "fact_order.secret"}},
        ]
        for ast in cases:
            with self.subTest(ast=ast), self.assertRaises(SQLCompilerError):
                compile_query(replace(plan, expression_asts={"paid_amount": ast}))

    def test_metric_dependency_reference_is_structural_not_id_branch(self):
        plan = build_query_plan(self.config, ready_intent(["average_quantity_per_order"]))
        compiled = compile_query(plan)
        self.assertIn("SUM(`fact_order`.`order_quantity`)", compiled.sql)
        self.assertIn("COUNT(DISTINCT `fact_order`.`order_id`)", compiled.sql)

    def test_window_is_final_output_only_and_frame_is_approved(self):
        plan = build_query_plan(self.config, ready_intent(["paid_amount"]))
        window = {
            "node": "window",
            "function": "sum",
            "input": {"node": "field", "ref": "fact_order.order_amount"},
            "partition_by": [],
            "order_by": [],
            "frame": "rows_unbounded_preceding_to_current",
        }
        compiled = compile_query(replace(plan, expression_asts={"paid_amount": window}))
        self.assertIn("OVER (ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)", compiled.sql)

        nested = {"node": "binary", "op": "+", "left": window, "right": {"node": "literal", "value": 1}}
        with self.assertRaises(SQLCompilerError):
            compile_query(replace(plan, expression_asts={"paid_amount": nested}))

        unapproved = dict(window, frame="rows_between_1_preceding")
        with self.assertRaises(SQLCompilerError):
            compile_query(replace(plan, expression_asts={"paid_amount": unapproved}))

    def test_ast_business_values_are_not_embedded_as_literals(self):
        plan = build_query_plan(self.config, ready_intent(["paid_amount"]))
        ast = {
            "node": "function",
            "function": "nullif",
            "args": [{"node": "field", "ref": "fact_order.order_amount"}, {"node": "literal", "value": 0}],
        }
        compiled = compile_query(replace(plan, expression_asts={"paid_amount": ast}))
        self.assertNotIn("'", compiled.sql)
        self.assertIn("NULLIF(`fact_order`.`order_amount`, 0)", compiled.sql)

    def test_case_and_condition_aggregate_are_supported_from_ast(self):
        plan = build_query_plan(self.config, ready_intent(["paid_amount"]))
        ast = {
            "node": "condition_aggregate",
            "function": "sum",
            "condition": {
                "node": "binary",
                "op": ">",
                "left": {"node": "field", "ref": "fact_order.order_amount"},
                "right": {"node": "literal", "value": 0},
            },
            "input": {
                "node": "case",
                "when": {
                    "node": "binary",
                    "op": ">",
                    "left": {"node": "field", "ref": "fact_order.order_quantity"},
                    "right": {"node": "literal", "value": 0},
                },
                "then": {"node": "field", "ref": "fact_order.order_amount"},
                "else": {"node": "literal", "value": 0},
            },
        }
        compiled = compile_query(replace(plan, expression_asts={"paid_amount": ast}))
        self.assertIn("SUM(CASE WHEN", compiled.sql)

    def test_window_partition_must_use_declared_query_field(self):
        plan = build_query_plan(self.config, ready_intent(["paid_amount"]))
        ast = {
            "node": "window",
            "function": "sum",
            "input": {"node": "field", "ref": "fact_order.order_amount"},
            "partition_by": [{"node": "field", "ref": "dim_region.secret"}],
        }
        with self.assertRaises(SQLCompilerError):
            compile_query(replace(plan, expression_asts={"paid_amount": ast}))


if __name__ == "__main__":
    unittest.main()
