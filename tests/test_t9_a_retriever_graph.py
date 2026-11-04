import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agent.graph import graph
from app.repositories.mysql.application_session_repository import InMemoryApplicationSessionRepository
from app.services.query_service import QueryService
from app.services.semantic_candidate_retriever import CandidateResolution, SemanticCandidate


class FakeRetriever:
    def __init__(self, resolution):
        self.resolution = resolution
        self.calls = []

    async def hybrid_search(self, query, semantic_types, **kwargs):
        self.calls.append((query, tuple(semantic_types), kwargs))
        return {item: self.resolution for item in semantic_types}


class MappingRetriever(FakeRetriever):
    def __init__(self, resolutions):
        self.resolutions = resolutions
        self.calls = []

    async def hybrid_search(self, query, semantic_types, **kwargs):
        self.calls.append((query, tuple(semantic_types), kwargs))
        return {item: self.resolutions[item] for item in semantic_types}


class T9ARetrieverGraphTests(unittest.TestCase):
    def candidate(self):
        return SemanticCandidate("metric", "paid_amount", "v1", "销售额", "销售额", 1.0, "mysql")

    def context(self, retriever, executed, snapshot_version="v1"):
        return {
            "semantic_model_snapshot": SimpleNamespace(version_id=snapshot_version),
            "semantic_candidate_retriever": retriever,
            "trusted_query_chain": None,
            "dw_mysql_repository": SimpleNamespace(execute_sql=AsyncMock(return_value=SimpleNamespace(
                rows=[], truncated=False, max_rows=100, sql="SELECT 1",
            ))),
            "query_limits": SimpleNamespace(max_rows=100, timeout_seconds=30, max_execution_time_ms=30000),
            "reference_time": None,
        }

    def run_graph(self, resolution, intent_payload, state_version="v1", snapshot_version="v1", retriever=None):
        retriever = retriever or FakeRetriever(resolution)
        executed = []
        compiled = SimpleNamespace(sql="SELECT 1", params={}, max_rows=100, timeout_seconds=30)
        plan = SimpleNamespace(semantic_version_id="v1", metrics=(), limit=100)

        async def execute_sql(sql, params, **kwargs):
            executed.append((sql, params))
            return SimpleNamespace(rows=[], truncated=False, max_rows=100)

        context = self.context(retriever, executed, snapshot_version)
        context["dw_mysql_repository"] = SimpleNamespace(execute_sql=execute_sql)
        with patch("app.agent.llm.llm") as mocked_llm, \
             patch("app.agent.nodes.plan_query.build_query_plan", return_value=plan), \
             patch("app.agent.nodes.generate_sql.compile_query", return_value=compiled), \
             patch("app.agent.nodes.validate_sql.validate_compiled_query", return_value=None):
            mocked_llm.ainvoke = AsyncMock(return_value=SimpleNamespace(content=intent_payload))
            result = asyncio.run(graph.ainvoke(
                {"query": "查询销售额", "semantic_version_id": state_version},
                context=context,
            ))
        return result, retriever, executed

    def test_exact_resolution_enters_real_graph_and_calls_execute(self):
        result, retriever, executed = self.run_graph(
            CandidateResolution("exact", (self.candidate(),)),
            '{"status":"ready","metrics":["销售额"]}',
        )
        self.assertEqual(retriever.calls[0][0], "销售额")
        self.assertEqual(retriever.calls[0][2]["version_id"], "v1")
        self.assertEqual(result["query_intent"].metrics, ["paid_amount"])
        self.assertEqual(len(executed), 1)

    def test_clarification_resolution_stops_before_execute(self):
        result, retriever, executed = self.run_graph(
            CandidateResolution("clarification", (self.candidate(),), "分差不足"),
            '{"status":"ready","metrics":["销售额"]}',
        )
        self.assertEqual(retriever.calls[0][2]["session_version_id"], "v1")
        self.assertEqual(result["query_intent"].status, "needs_clarification")
        self.assertEqual(executed, [])

    def test_unresolved_resolution_is_unsupported_and_stops(self):
        result, _, executed = self.run_graph(CandidateResolution("unresolved", ()), '{"status":"ready","metrics":["未知指标"]}')
        self.assertEqual(result["query_intent"].status, "unsupported")
        self.assertEqual(executed, [])

    def test_formal_graph_keeps_types_and_filter_value_dimension_scope(self):
        dimension = SemanticCandidate("dimension", "region", "v1", "地区", "地区", 1.0, "mysql", "region")
        value = SemanticCandidate("filter_value", "value:region:华东", "v1", "地区", "华东", 1.0, "mysql", "region")
        retriever = MappingRetriever({
            "dimension": CandidateResolution("exact", (dimension,)),
            "filter_value": CandidateResolution("exact", (value,)),
        })
        result, used_retriever, executed = self.run_graph(
            CandidateResolution("unresolved", ()),
            '{"status":"ready","filters":[{"field":"地区","operator":"eq","value":"华东"}]}',
            retriever=retriever,
        )
        self.assertEqual(result["query_intent"].filters[0]["field"], "region")
        self.assertEqual(len(executed), 1)
        self.assertIs(used_retriever, retriever)
        self.assertEqual([call[1] for call in retriever.calls], [("dimension",), ("filter_value",)])
        self.assertEqual(retriever.calls[-1][2]["dimension_id"], "region")

    def test_snapshot_version_mismatch_fails_closed_before_retrieval(self):
        retriever = FakeRetriever(CandidateResolution("exact", (self.candidate(),)))
        result, used_retriever, executed = self.run_graph(
            CandidateResolution("exact", (self.candidate(),)),
            '{"status":"ready","metrics":["销售额"]}',
            state_version="v1",
            snapshot_version="v2",
        )
        self.assertEqual(result["query_intent"].status, "unsupported")
        self.assertEqual(len(executed), 0)
        self.assertEqual(used_retriever.calls, [])

    def test_query_service_injects_retriever_into_formal_context(self):
        captured = []
        retriever = FakeRetriever(CandidateResolution("exact", (self.candidate(),)))

        class Loader:
            async def load_for_query(self, version_id=None):
                return SimpleNamespace(version_id="v1")

        class ServiceGraph:
            async def astream(self, **kwargs):
                captured.append(kwargs["context"])
                yield {"type": "done", "status": "unsupported"}

        async def collect(service):
            return [event async for event in service.query("查询销售额")]

        service = QueryService(
            None, None, None, None, None, None,
            session_repository=InMemoryApplicationSessionRepository(),
            semantic_candidate_retriever=retriever,
        )
        service.snapshot_loader = Loader()
        with patch("app.services.query_service.graph", ServiceGraph()):
            asyncio.run(collect(service))
        self.assertIs(captured[0]["semantic_candidate_retriever"], retriever)


if __name__ == "__main__":
    unittest.main()
