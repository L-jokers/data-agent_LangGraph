import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.repositories.mysql.application_session_repository import (
    InMemoryApplicationSessionRepository,
)
from app.services.query_service import QueryService


def events(lines):
    return [json.loads(line[6:]) for line in lines if line.startswith("data: ")]


class FakeGraph:
    def __init__(self, batches, delay=0):
        self.batches = batches
        self.delay = delay
        self.calls = 0

    async def astream(self, **kwargs):
        index = self.calls
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        for event in self.batches[min(index, len(self.batches) - 1)]:
            yield event


class FakeLoader:
    def __init__(self, version="v1"):
        self.version = version
        self.calls = []

    async def load_for_query(self, version_id=None):
        self.calls.append(version_id)
        return SimpleNamespace(version_id=self.version)


def make_service(repository, loader):
    service = QueryService(None, None, None, None, None, None, repository)
    service.snapshot_loader = loader
    return service


class T8SessionTests(unittest.TestCase):
    def test_first_query_emits_session_and_persists_clarification(self):
        repository = InMemoryApplicationSessionRepository()
        loader = FakeLoader()
        graph = FakeGraph([[
            {"type": "clarification", "message": "请补充年份", "missing": ["year"]},
            {"type": "done", "status": "needs_clarification"},
        ]])
        with patch("app.services.query_service.graph", graph):
            result = events(asyncio.run(self._collect(make_service(repository, loader), "查询销售额")))
        session = next(item for item in result if item["type"] == "session")
        clarification = next(item for item in result if item["type"] == "clarification")
        self.assertEqual(session["semantic_model_version"], "v1")
        self.assertEqual(clarification["session_id"], session["session_id"])
        self.assertTrue(clarification["clarification_id"])
        self.assertEqual(repository.records[session["session_id"]].status, "needs_clarification")

    def test_clarification_recovery_reuses_bound_version_and_full_graph(self):
        repository = InMemoryApplicationSessionRepository()
        loader = FakeLoader()
        graph = FakeGraph([
            [{"type": "clarification", "message": "请补充年份", "missing": ["year"]},
             {"type": "done", "status": "needs_clarification"}],
            [{"type": "sql", "sql": "SELECT 1"}, {"type": "result", "rows": [], "meta": {}},
             {"type": "done", "status": "success"}],
        ])
        service = make_service(repository, loader)
        with patch("app.services.query_service.graph", graph):
            first = events(asyncio.run(self._collect(service, "查询销售额")))
            session_id = next(item for item in first if item["type"] == "session")["session_id"]
            clarification_id = next(item for item in first if item["type"] == "clarification")["clarification_id"]
            second = events(asyncio.run(self._collect(service, "2026年", session_id, clarification_id)))
        self.assertIn("sql", [item["type"] for item in second])
        self.assertEqual(loader.calls, [None, "v1"])
        self.assertEqual(repository.records[session_id].status, "completed")

    def test_mismatch_expired_and_terminal_do_not_run_graph(self):
        repository = InMemoryApplicationSessionRepository()
        loader = FakeLoader()
        graph = FakeGraph([[
            {"type": "clarification", "message": "请补充年份", "missing": ["year"]},
            {"type": "done", "status": "needs_clarification"},
        ]])
        service = make_service(repository, loader)
        with patch("app.services.query_service.graph", graph):
            first = events(asyncio.run(self._collect(service, "查询销售额")))
            session_id = next(item for item in first if item["type"] == "session")["session_id"]
            mismatch = events(asyncio.run(self._collect(service, "回答", session_id, "wrong")))
            terminal = events(asyncio.run(self._collect(service, "再次追问", session_id)))
        self.assertEqual(mismatch[0]["code"], "CLARIFICATION_ID_MISMATCH")
        self.assertEqual(terminal[0]["code"], "CLARIFICATION_ID_MISMATCH")
        self.assertEqual(graph.calls, 1)

    def test_expired_session_is_rejected_without_graph_execution(self):
        repository = InMemoryApplicationSessionRepository()
        loader = FakeLoader()
        graph = FakeGraph([[{"type": "done", "status": "success"}]])
        service = make_service(repository, loader)
        with patch("app.services.query_service.graph", graph):
            first = events(asyncio.run(self._collect(service, "查询销售额")))
        session_id = next(item for item in first if item["type"] == "session")["session_id"]
        record = repository.records[session_id]
        repository.records[session_id] = type(record)(**{
            **record.__dict__, "expires_at": repository._now(),
        })
        result = events(asyncio.run(self._collect(service, "回答", session_id, "x")))
        self.assertEqual(result[0]["code"], "SESSION_EXPIRED")
        self.assertEqual(graph.calls, 1)

    def test_request_deadline_returns_unknown_terminal_without_reexecution(self):
        repository = InMemoryApplicationSessionRepository()
        service = make_service(repository, FakeLoader())
        service.request_timeout_seconds = 0.01
        graph = FakeGraph([[{"type": "done", "status": "success"}]], delay=0.1)
        with patch("app.services.query_service.graph", graph):
            result = events(asyncio.run(self._collect(service, "查询销售额")))
        self.assertIn("REQUEST_TIMEOUT", [item.get("code") for item in result])
        self.assertEqual(result[-1]["status"], "execution_unknown")
        self.assertEqual(graph.calls, 1)

    def test_concurrent_clarification_only_one_request_claims_and_runs(self):
        repository = InMemoryApplicationSessionRepository()
        loader = FakeLoader()
        graph = FakeGraph([
            [{"type": "clarification", "message": "请补充年份", "missing": ["year"]},
             {"type": "done", "status": "needs_clarification"}],
            [{"type": "done", "status": "success"}],
        ], delay=0.01)
        service = make_service(repository, loader)
        with patch("app.services.query_service.graph", graph):
            first = events(asyncio.run(self._collect(service, "查询销售额")))
            session_id = next(item for item in first if item["type"] == "session")["session_id"]
            clarification_id = next(item for item in first if item["type"] == "clarification")["clarification_id"]
            results = asyncio.run(self._concurrent(service, session_id, clarification_id))
        flattened = [events(result) for result in results]
        self.assertEqual(graph.calls, 2)
        self.assertTrue(any(item.get("code") == "EXECUTION_STATUS_UNKNOWN" for stream in flattened for item in stream))

    async def _collect(self, service, query, session_id=None, clarification_id=None):
        return [item async for item in service.query(query, session_id, clarification_id)]

    async def _concurrent(self, service, session_id, clarification_id):
        return await asyncio.gather(
            self._collect(service, "2026年", session_id, clarification_id),
            self._collect(service, "2025年", session_id, clarification_id),
        )


if __name__ == "__main__":
    unittest.main()
