import json
from collections.abc import AsyncIterator
from typing import Any

from langchain_huggingface import HuggingFaceEndpointEmbeddings

from app.agent.context import DataAgentContext
from app.agent.graph import graph
from app.agent.state import DataAgentState
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository


class QueryService:
    def __init__(
        self,
        embedding_client: HuggingFaceEndpointEmbeddings,
        column_qdrant_repository: ColumnQdrantRepository,
        value_es_repository: ValueESRepository,
        metric_qdrant_repository: MetricQdrantRepository,
        meta_mysql_repository: MetaMySQLRepository,
        dw_mysql_repository: DWMySQLRepository,
    ):
        self.embedding_client = embedding_client
        self.column_qdrant_repository = column_qdrant_repository
        self.value_es_repository = value_es_repository
        self.metric_qdrant_repository = metric_qdrant_repository
        self.meta_mysql_repository = meta_mysql_repository
        self.dw_mysql_repository = dw_mysql_repository

    @staticmethod
    def _sse(event: dict[str, Any]) -> str:
        return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

    async def query(self, query: str) -> AsyncIterator[str]:
        context = DataAgentContext(
            embedding_client=self.embedding_client,
            column_qdrant_repository=self.column_qdrant_repository,
            value_es_repository=self.value_es_repository,
            metric_qdrant_repository=self.metric_qdrant_repository,
            meta_mysql_repository=self.meta_mysql_repository,
            dw_mysql_repository=self.dw_mysql_repository,
        )
        state = DataAgentState(query=query)
        done_sent = False
        try:
            async for chunk in graph.astream(
                input=state, context=context, stream_mode="custom"
            ):
                if not isinstance(chunk, dict) or "type" not in chunk:
                    continue
                if chunk["type"] == "sql":
                    chunk = {"type": "sql", "sql": chunk.get("sql", "")}
                yield self._sse(chunk)
                done_sent = done_sent or chunk["type"] == "done"
        except Exception:
            if not done_sent:
                yield self._sse({
                    "type": "error",
                    "code": "QUERY_INTERNAL_ERROR",
                    "message": "查询处理失败",
                })
                yield self._sse({"type": "done", "status": "error"})
