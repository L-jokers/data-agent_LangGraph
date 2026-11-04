from __future__ import annotations

from typing import Any, Sequence

from qdrant_client import models


class ElasticsearchIndexClient:
    def __init__(self, client: Any):
        self.client = client

    async def ensure_index(self, index_name: str) -> None:
        if not await self.client.indices.exists(index=index_name):
            await self.client.indices.create(index=index_name, mappings={
                "dynamic": False,
                "properties": {
                    "id": {"type": "keyword"},
                    "semantic_type": {"type": "keyword"},
                    "version_id": {"type": "keyword"},
                    "text": {"type": "text", "analyzer": "ik_max_word", "search_analyzer": "ik_max_word"},
                    "display_name": {"type": "text", "analyzer": "ik_max_word"},
                    "metric_id": {"type": "keyword"},
                    "dimension_id": {"type": "keyword"},
                    "table_id": {"type": "keyword"},
                    "column_id": {"type": "keyword"},
                    "table_name": {"type": "keyword"},
                },
            })

    async def bulk_index(self, index_name: str, documents: Sequence[dict[str, Any]]) -> None:
        operations: list[dict[str, Any]] = []
        for document in documents:
            operations.extend(({"index": {"_index": index_name, "_id": document["id"]}}, document))
        response = await self.client.bulk(operations=operations)
        if response.get("errors"):
            failed = [item for item in response.get("items", []) if item.get("index", {}).get("error")]
            raise RuntimeError(f"ES bulk 存在失败项: {len(failed)}")

    async def get_documents(self, index_name: str, document_ids: Sequence[str]) -> list[dict[str, Any]]:
        response = await self.client.mget(index=index_name, ids=list(document_ids))
        return [item["_source"] | {"id": item["_id"]} for item in response.get("docs", []) if item.get("found")]

    async def lexical_search(
        self,
        index_name: str,
        query: str,
        version_id: str,
        semantic_types: Sequence[str],
        limit: int = 10,
        dimension_id: str | None = None,
    ) -> list[dict[str, Any]]:
        filters: list[dict[str, Any]] = [
            {"term": {"version_id": version_id}},
            {"terms": {"semantic_type": list(semantic_types)}},
        ]
        if dimension_id is not None:
            filters.append({"term": {"dimension_id": dimension_id}})
        response = await self.client.search(
            index=index_name,
            query={
                "bool": {
                    "must": [{"multi_match": {"query": query, "fields": ["text", "display_name"]}}],
                    "filter": filters,
                }
            },
            size=limit,
        )
        return [hit.get("_source", {}) | {"id": hit.get("_id"), "score": hit.get("_score", 0.0)} for hit in response["hits"]["hits"]]


class QdrantIndexClient:
    def __init__(self, client: Any):
        self.client = client

    async def ensure_collection(self, collection_name: str, vector_size: int) -> None:
        if not await self.client.collection_exists(collection_name):
            await self.client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
            )

    async def upsert(self, collection_name: str, points: Sequence[dict[str, Any]]) -> None:
        await self.client.upsert(
            collection_name=collection_name,
            points=[models.PointStruct(id=item["id"], vector=item["vector"], payload=item["payload"]) for item in points],
        )

    async def get_points(self, collection_name: str, point_ids: Sequence[str]) -> list[dict[str, Any]]:
        points = await self.client.retrieve(collection_name=collection_name, ids=list(point_ids), with_payload=True, with_vectors=False)
        return [{"id": point.payload["id"], "payload": point.payload} for point in points]

    async def vector_search(
        self,
        collection_name: str,
        embedding: list[float],
        version_id: str,
        semantic_types: Sequence[str],
        limit: int = 10,
        score_threshold: float = 0.0,
        dimension_id: str | None = None,
    ) -> list[dict[str, Any]]:
        must = [
            models.FieldCondition(key="version_id", match=models.MatchValue(value=version_id)),
            models.FieldCondition(key="semantic_type", match=models.MatchAny(any=list(semantic_types))),
        ]
        if dimension_id is not None:
            must.append(models.FieldCondition(key="dimension_id", match=models.MatchValue(value=dimension_id)))
        result = await self.client.query_points(
            collection_name=collection_name,
            query=embedding,
            query_filter=models.Filter(must=must),
            score_threshold=score_threshold,
            limit=limit,
            with_payload=True,
        )
        return [point.payload | {"id": point.payload.get("id", point.id), "score": point.score} for point in result.points]
