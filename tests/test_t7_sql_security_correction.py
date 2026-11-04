import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.agent.nodes.correct_sql import correct_sql
from app.agent.nodes.validate_sql import validate_sql
from app.compiler.sql_compiler import compile_query
from app.conf.meta_config import load_meta_config
from app.entities.column_info import ColumnInfo
from app.entities.table_info import TableInfo
from app.intent.models import QueryIntent
from app.planner.planner import build_query_plan
from app.security.sqlglot_validator import SQLSecurityError, validate_compiled_query
from app.services.sql_correction import determine_correction, rerun_after_correction


CONFIG_PATH = Path(__file__).parents[1] / "conf" / "meta_config.yaml"


def ready_intent(order_by=None, metrics=None, filters=None):
    return QueryIntent.from_payload(
        {
            "status": "ready",
            "metrics": metrics or ["paid_amount"],
            "dimensions": [],
            "group_by": [],
            "filters": filters or [],
            "order_by": order_by or [],
            "limit": 10,
            "time": {"expression": "", "kind": "relative"},
        }
    )


class T7SecurityAndCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.config = load_meta_config(CONFIG_PATH)
        self.plan = build_query_plan(self.config, ready_intent())
        self.compiled = compile_query(self.plan)

    def test_snapshot_plan_and_compiled_allowlist_are_checked(self):
        tables = [
            TableInfo(table.name, table.name, table.role, table.description, "v1")
            for table in self.config.tables
        ]
        columns = [
            ColumnInfo(
                f"{table.name}.{column.name}", column.name, column.type or "unknown",
                column.role, [], column.description, list(column.alias), table.name, "v1",
            )
            for table in self.config.tables
            for column in table.columns
        ]
        snapshot = SimpleNamespace(tables=tuple(tables), columns=tuple(columns), version_id="v1")
        validate_compiled_query(self.compiled, snapshot=snapshot, plan=self.plan)

        tampered = self.compiled.__class__(
            sql=self.compiled.sql,
            params=self.compiled.params,
            max_rows=self.compiled.max_rows,
            timeout_seconds=self.compiled.timeout_seconds,
            max_execution_time_ms=self.compiled.max_execution_time_ms,
            allowed_tables=frozenset(set(self.compiled.allowed_tables) | {"secret_table"}),
            allowed_columns=self.compiled.allowed_columns,
            allowed_functions=self.compiled.allowed_functions,
            allowed_joins=self.compiled.allowed_joins,
            allowed_join_conditions=self.compiled.allowed_join_conditions,
        )
        with self.assertRaises(SQLSecurityError):
            validate_compiled_query(tampered, snapshot=snapshot, plan=self.plan)

    def test_security_failure_does_not_emit_sql(self):
        events = []
        invalid = self.compiled.__class__(
            sql="SELECT SLEEP(10) FROM `fact_order` LIMIT 10",
            params={},
            max_rows=self.compiled.max_rows,
            timeout_seconds=self.compiled.timeout_seconds,
            max_execution_time_ms=self.compiled.max_execution_time_ms,
            allowed_tables=frozenset({"fact_order"}),
            allowed_columns=frozenset(),
            allowed_functions=frozenset({"SUM"}),
            allowed_joins=frozenset(),
            allowed_join_conditions=frozenset(),
        )
        runtime = SimpleNamespace(stream_writer=events.append, context={})
        result = asyncio.run(validate_sql({"compiled_query": invalid, "query_plan": self.plan}, runtime))
        self.assertEqual(result["error"], "SQL_SECURITY_VALIDATION_FAILED")
        self.assertFalse(any(event.get("type") == "sql" for event in events))

    def test_window_position_is_checked_by_sqlglot_validator(self):
        from dataclasses import replace

        window_plan = replace(
            self.plan,
            expression_asts={
                "paid_amount": {
                    "node": "window",
                    "function": "sum",
                    "input": {"node": "field", "ref": "fact_order.order_amount"},
                }
            },
        )
        validate_compiled_query(compile_query(window_plan), plan=window_plan)

    def test_correction_only_normalizes_explicit_enum_and_never_changes_semantics(self):
        decision = determine_correction(ready_intent(order_by=[{"field": "paid_amount", "direction": "DESC"}]), attempt=0)
        self.assertTrue(decision.applied)
        self.assertEqual(decision.intent.order_by[0]["direction"], "desc")

        no_correction = determine_correction(ready_intent(metrics=["order_count"]), attempt=0)
        self.assertFalse(no_correction.applied)
        blocked = determine_correction(ready_intent(order_by=[{"field": "paid_amount", "direction": "DESC"}]), attempt=1)
        self.assertFalse(blocked.applied)
        self.assertEqual(blocked.reason, "CORRECTION_LIMIT_REACHED")

    def test_correction_reruns_complete_trusted_chain_once(self):
        events = []

        async def validate_intent(intent):
            events.append("intent_validation")
            return intent

        async def build_plan(intent):
            events.append("plan_generation")
            return "plan"

        async def validate_plan(plan):
            events.append("plan_validation")
            return plan

        async def compile_sql(plan):
            events.append("sql_compilation")
            return "compiled"

        async def validate_sql_result(compiled):
            events.append("sql_security_validation")
            return "validated"

        run = asyncio.run(
            rerun_after_correction(
                ready_intent(order_by=[{"field": "paid_amount", "direction": "DESC"}]),
                attempt=0,
                validate_intent=validate_intent,
                build_plan=build_plan,
                validate_plan=validate_plan,
                compile_sql=compile_sql,
                validate_sql=validate_sql_result,
            )
        )
        self.assertEqual(run.events, tuple(events))
        self.assertEqual(run.events, (
            "intent_validation", "plan_generation", "plan_validation",
            "sql_compilation", "sql_security_validation",
        ))
        self.assertEqual(run.compiled, "compiled")

    def test_correction_node_requires_trusted_replay_and_records_single_attempt(self):
        events = []

        async def chain(intent, *, attempt):
            return SimpleNamespace(events=("intent_validation", "plan_generation", "plan_validation", "sql_compilation", "sql_security_validation"), result=True, plan="plan", compiled=SimpleNamespace(sql="SELECT 1"))

        runtime = SimpleNamespace(stream_writer=events.append, context={"trusted_query_chain": chain, "semantic_model_snapshot": SimpleNamespace(version_id="v1")})
        state = {
            "query_intent": ready_intent(order_by=[{"field": "paid_amount", "direction": "DESC"}]),
            "correction_attempts": 0,
            "semantic_version_id": "v1",
        }
        result = asyncio.run(correct_sql(state, runtime))
        self.assertEqual(result["correction_attempts"], 1)
        self.assertEqual(len(result["correction_events"]), 5)


if __name__ == "__main__":
    unittest.main()
