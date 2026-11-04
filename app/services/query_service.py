import json
import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from langchain_huggingface import HuggingFaceEndpointEmbeddings

from app.agent.context import DataAgentContext
from app.agent.graph import graph
from app.agent.state import DataAgentState
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.application_session_repository import (
    InMemoryApplicationSessionRepository,
    SessionRecord,
)
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository
from app.services.semantic_model_snapshot import SemanticModelSnapshotLoader
from app.services.semantic_candidate_retriever import CandidateSearchConfig, SemanticCandidateRetriever
from app.clients.semantic_index_clients import ElasticsearchIndexClient, QdrantIndexClient
from app.conf.app_config import app_config
from app.services.trusted_query_chain import TrustedQueryChain
from app.security.query_limits import QueryLimits


class QueryService:
    def __init__(
        self,
        embedding_client: HuggingFaceEndpointEmbeddings,
        column_qdrant_repository: ColumnQdrantRepository,
        value_es_repository: ValueESRepository,
        metric_qdrant_repository: MetricQdrantRepository,
        meta_mysql_repository: MetaMySQLRepository,
        dw_mysql_repository: DWMySQLRepository,
        session_repository=None,
        semantic_candidate_retriever: SemanticCandidateRetriever | None = None,
    ):
        self.embedding_client = embedding_client
        self.column_qdrant_repository = column_qdrant_repository
        self.value_es_repository = value_es_repository
        self.metric_qdrant_repository = metric_qdrant_repository
        self.meta_mysql_repository = meta_mysql_repository
        self.dw_mysql_repository = dw_mysql_repository
        self.snapshot_loader = SemanticModelSnapshotLoader(meta_mysql_repository)
        self.session_repository = session_repository or InMemoryApplicationSessionRepository()
        self.query_limits = QueryLimits(max_rows=20, timeout_seconds=60.0, max_execution_time_ms=60000)
        self.request_timeout_seconds = 180.0
        if semantic_candidate_retriever is not None:
            self.semantic_candidate_retriever = semantic_candidate_retriever
        elif all(item is not None for item in (
            embedding_client, value_es_repository, metric_qdrant_repository, meta_mysql_repository,
        )):
            self.semantic_candidate_retriever = SemanticCandidateRetriever(
                self.snapshot_loader,
                ElasticsearchIndexClient(value_es_repository.client),
                QdrantIndexClient(metric_qdrant_repository.client),
                embedding_client,
                CandidateSearchConfig(
                    es_index_name=app_config.es.index_name,
                    qdrant_collection_name="data-agent-semantic",
                    # 冷启动阶段之后需要开启模糊查询（向量语义查询）开关：当前默认是关闭
                    # enable_fuzzy_mapping = True,
                ),
            )
        else:
            self.semantic_candidate_retriever = None

    @staticmethod
    def _sse(event: dict[str, Any]) -> str:
        return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

    async def _session_event(self, record: SessionRecord) -> str:
        return self._sse({
            "type": "session",
            "session_id": record.session_id,
            "turn_id": record.turn_id,
            "turn_number": record.turn_number,
            "status": record.status,
            "semantic_model_version": record.semantic_model_version,
            "state_version": record.state_version,
        })

    async def _terminal_session(self, record: SessionRecord) -> AsyncIterator[str]:
        yield await self._session_event(record)
        if record.status in {"completed", "unsupported", "error", "execution_unknown"}:
            yield self._sse({
                "type": "error",
                "code": "SESSION_TERMINAL",
                "message": "当前会话已结束，请发起新查询",
            })
        yield self._sse({"type": "done", "status": record.status})

    async def query(
        self,
        query: str,
        session_id: str | None = None,
        clarification_id: str | None = None,
    ) -> AsyncIterator[str]:
        record = None
        query_text = query
        if session_id:
            record = await self.session_repository.get(session_id)
            if record is None:
                yield self._sse({"type": "error", "code": "SESSION_NOT_FOUND", "message": "会话不存在"})
                yield self._sse({"type": "done", "status": "error"})
                return
            if record.expires_at <= self.session_repository._now():
                yield self._sse({"type": "error", "code": "SESSION_EXPIRED", "message": "会话已过期，请发起新查询"})
                yield self._sse({"type": "done", "status": "expired"})
                return
            if record.status == "needs_clarification":
                if not clarification_id or clarification_id != record.clarification_id:
                    yield self._sse({"type": "error", "code": "CLARIFICATION_ID_MISMATCH", "message": "澄清标识不匹配"})
                    yield self._sse({"type": "done", "status": "error"})
                    return
                claimed = await self.session_repository.claim_clarification(record, clarification_id, query)
                if claimed is None:
                    current = await self.session_repository.get(session_id)
                    if current:
                        async for event in self._terminal_session(current):
                            yield event
                    return
                record = claimed
                query_text = f"{record.original_query}\n用户补充的澄清信息：{query.strip()}"
            elif record.status == "processing":
                yield self._sse({"type": "error", "code": "EXECUTION_STATUS_UNKNOWN", "message": "上一轮执行状态未知，请发起新查询"})
                yield self._sse({"type": "done", "status": "execution_unknown"})
                return
            else:
                async for event in self._terminal_session(record):
                    yield event
                return

        try:
            snapshot = await self.snapshot_loader.load_for_query(
                record.semantic_model_version if record else None
            )
        except Exception:
            if record:
                updated = await self.session_repository.update_outcome(
                    record.session_id, record.state_version, status="error",
                    terminal_status="error",
                )
                if updated:
                    record = updated
            yield self._sse({"type": "error", "code": "SEMANTIC_SNAPSHOT_UNAVAILABLE", "message": "语义模型不可用"})
            yield self._sse({"type": "done", "status": "error"})
            return
        if record and snapshot.version_id != record.semantic_model_version:
            yield self._sse({"type": "error", "code": "SESSION_VERSION_MISMATCH", "message": "会话语义版本不一致"})
            yield self._sse({"type": "done", "status": "error"})
            return
        if record is None:
            record = await self.session_repository.create(query, snapshot.version_id)
        yield await self._session_event(record)

        context = DataAgentContext(
            meta_mysql_repository=self.meta_mysql_repository,
            dw_mysql_repository=self.dw_mysql_repository,
            semantic_model_snapshot=snapshot,
            semantic_candidate_retriever=self.semantic_candidate_retriever,
            query_limits=self.query_limits,
            trusted_query_chain=TrustedQueryChain(snapshot=snapshot, query_limits=self.query_limits),
        )
        state = DataAgentState(query=query_text, semantic_version_id=snapshot.version_id)
        done_sent = False
        clarification_saved = False
        try:
            async with asyncio.timeout(self.request_timeout_seconds):
                async for chunk in graph.astream(input=state, context=context, stream_mode="custom"):
                    if not isinstance(chunk, dict) or "type" not in chunk:
                        continue
                    if chunk["type"] == "sql":
                        chunk = {"type": "sql", "sql": chunk.get("sql", "")}
                    if chunk["type"] == "clarification":
                        clarification_id = chunk.get("clarification_id") or str(uuid4())
                        updated = await self.session_repository.update_outcome(
                            record.session_id, record.state_version,
                            status="needs_clarification", clarification_id=clarification_id,
                            pending_fields=chunk.get("missing", []),
                            terminal_status="needs_clarification",
                        )
                        if updated is None:
                            current = await self.session_repository.get(record.session_id)
                            if current:
                                async for event in self._terminal_session(current):
                                    yield event
                            return
                        record = updated
                        clarification_saved = True
                        chunk = {**chunk, "clarification_id": clarification_id, "session_id": record.session_id}
                    if chunk["type"] == "done":
                        status = chunk.get("status", "error")
                        if not clarification_saved:
                            stored_status = "completed" if status == "success" else status
                            updated = await self.session_repository.update_outcome(
                                record.session_id, record.state_version,
                                status=stored_status, terminal_status=status,
                                execution_marker="result_delivered" if status == "success" else None,
                            )
                            if updated:
                                record = updated
                        yield await self._session_event(record)
                        done_sent = True
                    yield self._sse(chunk)
        except TimeoutError:
            if not done_sent:
                updated = await self.session_repository.update_outcome(
                    record.session_id, record.state_version,
                    status="execution_unknown", terminal_status="execution_unknown",
                    execution_marker="unknown",
                )
                if updated:
                    record = updated
                yield await self._session_event(record)
                yield self._sse({"type": "error", "code": "REQUEST_TIMEOUT", "message": "请求超时，请发起新查询"})
                yield self._sse({"type": "done", "status": "execution_unknown"})
        except Exception:
            if not done_sent:
                updated = await self.session_repository.update_outcome(
                    record.session_id, record.state_version,
                    status="execution_unknown", terminal_status="execution_unknown",
                    execution_marker="unknown",
                )
                if updated:
                    record = updated
                yield await self._session_event(record)
                yield self._sse({
                    "type": "error", "code": "EXECUTION_STATUS_UNKNOWN",
                    "message": "查询执行状态未知，请发起新查询",
                })
                yield self._sse({"type": "done", "status": "execution_unknown"})
