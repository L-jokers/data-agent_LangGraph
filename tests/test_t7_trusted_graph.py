import asyncio
import unittest
from types import SimpleNamespace
from typing import Any, TypedDict
from unittest.mock import patch

from langgraph.constants import END, START
from langgraph.graph import StateGraph

from app.agent.nodes.correct_sql import correct_sql
from app.intent.models import QueryIntent, QueryIntentStatus
from app.services.query_service import QueryService
from app.services.trusted_query_chain import TrustedQueryChain


def ready_intent():
    return QueryIntent.from_payload({
        "status": "ready",
        "metrics": ["paid_amount"],
        "order_by": [{"field": "paid_amount", "direction": "DESC"}],
        "time": {"expression": "", "kind": "relative"},
    })


class CorrectionState(TypedDict, total=False):
    query_intent: Any
    correction_attempts: int
    semantic_version_id: str
    resolved_time: dict[str, Any]
    error: str | None
    query_plan: Any
    compiled_query: Any
    executed: bool

def correction_graph(executed):
    builder = StateGraph(CorrectionState, context_schema=dict)
    builder.add_node("correct_sql", correct_sql)

    async def execute(state, runtime):
        executed.append(state)
        return {"executed": True}

    async def terminal(state, runtime):
        return {"executed": False}

    builder.add_node("execute_sql", execute)
    builder.add_node("terminal", terminal)
    builder.add_edge(START, "correct_sql")
    builder.add_conditional_edges(
        "correct_sql",
        lambda state: "execute_sql" if state.get("error") is None else "terminal",
        {"execute_sql": "execute_sql", "terminal": "terminal"},
    )
    builder.add_edge("execute_sql", END)
    builder.add_edge("terminal", END)
    return builder.compile()


class T7TrustedGraphTests(unittest.TestCase):
    def test_real_graph_path_runs_five_components_and_executes_only_after_security(self):
        calls = []
        snapshot = SimpleNamespace(version_id="v1")
        plan = SimpleNamespace(semantic_version_id="v1", metrics=("paid_amount",), limit=100)
        compiled = SimpleNamespace(sql="SELECT 1")

        def make_plan(snapshot_arg, intent, resolved_time):
            calls.append("plan_generation")
            self.assertIs(snapshot_arg, snapshot)
            return plan

        def validate_plan(plan_arg, *, snapshot, version_id):
            calls.append("plan_validation")
            self.assertIs(snapshot, snapshot)
            self.assertEqual(version_id, "v1")
            return plan_arg

        def compile_query(*args, **kwargs):
            calls.append("sql_compilation")
            return compiled

        def validate_sql(*args, **kwargs):
            calls.append("sql_security_validation")

        executed = []

        async def run():
            with patch("app.services.trusted_query_chain.build_query_plan", side_effect=make_plan), \
                 patch("app.services.trusted_query_chain.validate_query_plan", side_effect=validate_plan), \
                 patch("app.services.trusted_query_chain.compile_query", side_effect=compile_query), \
                 patch("app.services.trusted_query_chain.validate_compiled_query", side_effect=validate_sql):
                graph = correction_graph(executed)
                events = []
                result = await graph.ainvoke(
                    {"query_intent": ready_intent(), "correction_attempts": 0, "semantic_version_id": "v1"},
                    context={
                        "semantic_model_snapshot": snapshot,
                        "trusted_query_chain": TrustedQueryChain(snapshot=snapshot),
                    },
                )
                return result

        result = asyncio.run(run())
        self.assertEqual(calls, ["plan_generation", "plan_validation", "sql_compilation", "sql_security_validation"])
        self.assertTrue(result["executed"])
        self.assertEqual(len(executed), 1)
        self.assertIs(executed[0]["query_plan"], plan)
        self.assertIs(executed[0]["compiled_query"], compiled)

    def test_graph_does_not_execute_when_trusted_chain_is_missing_or_fails(self):
        cases = [
            ({"semantic_model_snapshot": SimpleNamespace(version_id="v1")}, "missing"),
            ({"semantic_model_snapshot": SimpleNamespace(version_id="v2"), "trusted_query_chain": None}, "version"),
        ]
        for context, label in cases:
            executed = []
            graph = correction_graph(executed)
            result = asyncio.run(graph.ainvoke(
                {"query_intent": ready_intent(), "correction_attempts": 0, "semantic_version_id": "v1"},
                context=context,
            ))
            self.assertFalse(result["executed"], label)
            self.assertEqual(executed, [], label)

        async def failing_chain(intent, *, attempt):
            raise RuntimeError("security rejected")

        executed = []
        graph = correction_graph(executed)
        result = asyncio.run(graph.ainvoke(
            {"query_intent": ready_intent(), "correction_attempts": 0, "semantic_version_id": "v1"},
            context={"semantic_model_snapshot": SimpleNamespace(version_id="v1"), "trusted_query_chain": failing_chain},
        ))
        self.assertFalse(result["executed"])
        self.assertEqual(executed, [])

    def test_graph_blocks_plan_compile_security_and_intent_replay_failures(self):
        snapshot = SimpleNamespace(version_id="v1")
        failures = [
            "plan_validation",
            "sql_compilation",
            "sql_security_validation",
        ]
        for failure in failures:
            executed = []
            graph = correction_graph(executed)
            with patch("app.services.trusted_query_chain.build_query_plan", return_value=SimpleNamespace(semantic_version_id="v1", metrics=("m",), limit=1)), \
                 patch("app.services.trusted_query_chain.validate_query_plan", side_effect=RuntimeError(failure) if failure == "plan_validation" else lambda plan, **kwargs: plan), \
                 patch("app.services.trusted_query_chain.compile_query", side_effect=RuntimeError(failure) if failure == "sql_compilation" else lambda *args, **kwargs: SimpleNamespace(sql="SELECT 1")), \
                 patch("app.services.trusted_query_chain.validate_compiled_query", side_effect=RuntimeError(failure) if failure == "sql_security_validation" else None):
                result = asyncio.run(graph.ainvoke(
                    {"query_intent": ready_intent(), "correction_attempts": 0, "semantic_version_id": "v1"},
                    context={"semantic_model_snapshot": snapshot, "trusted_query_chain": TrustedQueryChain(snapshot=snapshot)},
                ))
            self.assertFalse(result["executed"], failure)
            self.assertEqual(executed, [], failure)

        executed = []
        graph = correction_graph(executed)
        with patch("app.services.trusted_query_chain.QueryIntent.from_payload", return_value=QueryIntent(status=QueryIntentStatus.NEEDS_CLARIFICATION)):
            result = asyncio.run(graph.ainvoke(
                {"query_intent": ready_intent(), "correction_attempts": 0, "semantic_version_id": "v1"},
                context={"semantic_model_snapshot": snapshot, "trusted_query_chain": TrustedQueryChain(snapshot=snapshot)},
            ))
        self.assertFalse(result["executed"])
        self.assertEqual(executed, [])

    def test_graph_never_recorrects_after_one_attempt(self):
        executed = []
        graph = correction_graph(executed)
        result = asyncio.run(graph.ainvoke(
            {"query_intent": ready_intent(), "correction_attempts": 1, "semantic_version_id": "v1"},
            context={"semantic_model_snapshot": SimpleNamespace(version_id="v1"), "trusted_query_chain": object()},
        ))
        self.assertFalse(result["executed"])
        self.assertEqual(executed, [])
    def test_query_service_injects_chain_bound_to_loaded_snapshot(self):
        snapshot = SimpleNamespace(version_id="v1")
        captured = {}

        class Loader:
            async def load_for_query(self, version_id):
                self.requested = version_id
                return snapshot

        class FakeGraph:
            async def astream(self, **kwargs):
                captured["context"] = kwargs["context"]
                yield {"type": "done", "status": "success"}

        service = QueryService(None, None, None, None, None, None)
        service.snapshot_loader = Loader()
        with patch("app.services.query_service.graph", FakeGraph()):
            list(asyncio.run(collect(service.query("query"))))
        self.assertIsInstance(captured["context"]["trusted_query_chain"], TrustedQueryChain)
        self.assertIs(captured["context"]["trusted_query_chain"].snapshot, snapshot)
        self.assertEqual(captured["context"]["query_limits"].max_rows, 20)
        self.assertEqual(captured["context"]["query_limits"].timeout_seconds, 60.0)
        self.assertEqual(captured["context"]["query_limits"].max_execution_time_ms, 60000)
        self.assertIs(
            captured["context"]["trusted_query_chain"].query_limits,
            captured["context"]["query_limits"],
        )


async def collect(iterator):
    values = []
    async for value in iterator:
        values.append(value)
    return values


if __name__ == "__main__":
    unittest.main()
