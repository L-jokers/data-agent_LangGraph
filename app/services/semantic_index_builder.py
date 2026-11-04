from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol, Sequence

from app.services.semantic_model_snapshot import SemanticModelSnapshot


class IndexBuildError(RuntimeError):
    pass


@dataclass(frozen=True)
class IndexBuildConfig:
    es_index_name: str
    qdrant_collection_name: str
    embedding_model: str
    embedding_dimension: int
    verification_ttl_seconds: int = 86400
    embedding_batch_size: int = 10

    @property
    def config_hash(self) -> str:
        payload = {
            "es_index_name": self.es_index_name,
            "qdrant_collection_name": self.qdrant_collection_name,
            "embedding_model": self.embedding_model,
            "embedding_dimension": self.embedding_dimension,
            "verification_ttl_seconds": self.verification_ttl_seconds,
            "embedding_batch_size": self.embedding_batch_size,
        }
        return _hash(json.dumps(payload, ensure_ascii=False, sort_keys=True))


@dataclass(frozen=True)
class IndexManifest:
    version_id: str
    content_hash: str
    config_hash: str
    documents: tuple[dict[str, Any], ...]

    @property
    def document_ids(self) -> frozenset[str]:
        return frozenset(item["id"] for item in self.documents)

    @property
    def manifest_hash(self) -> str:
        return _hash(json.dumps(self.documents, ensure_ascii=False, sort_keys=True))


class EmbeddingClient(Protocol):
    async def aembed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...


class ESIndexClient(Protocol):
    async def ensure_index(self, index_name: str) -> None: ...
    async def bulk_index(self, index_name: str, documents: Sequence[dict[str, Any]]) -> None: ...
    async def get_documents(self, index_name: str, document_ids: Sequence[str]) -> list[dict[str, Any]]: ...


class QdrantIndexClient(Protocol):
    async def ensure_collection(self, collection_name: str, vector_size: int) -> None: ...
    async def upsert(self, collection_name: str, points: Sequence[dict[str, Any]]) -> None: ...
    async def get_points(self, collection_name: str, point_ids: Sequence[str]) -> list[dict[str, Any]]: ...


class VerificationStore(Protocol):
    async def record_verified(self, record: dict[str, Any]) -> None: ...


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    return str(value).strip()


def _stable_id(version_id: str, config_hash: str, semantic_type: str, entity_id: str, text: str) -> str:
    return _hash("|".join((version_id, config_hash, semantic_type, entity_id, text)))


def _point_id(document_id: str) -> str:
    raw = document_id[:32]
    return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"


def build_manifest(snapshot: SemanticModelSnapshot, config: IndexBuildConfig) -> IndexManifest:
    tables = {item.id: item for item in snapshot.tables}
    columns = {item.id: item for item in snapshot.columns}
    dimensions = {item.id: item for item in snapshot.dimensions}
    documents: list[dict[str, Any]] = []

    def add(semantic_type: str, entity_id: str, text: Any, display_name: str, **payload: Any) -> None:
        value = _text(text)
        if not value:
            return
        document_id = _stable_id(snapshot.version_id, config.config_hash, semantic_type, entity_id, value)
        documents.append({
            "id": document_id,
            "semantic_type": semantic_type,
            "version_id": snapshot.version_id,
            "text": value,
            "display_name": display_name,
            **payload,
        })

    for metric in snapshot.metrics:
        base = {"metric_id": metric.id}
        add("metric", metric.id, metric.name, metric.name, **base)
        for alias in metric.alias:
            add("metric", metric.id, alias, metric.name, **base)
        add("metric", metric.id, metric.description, metric.name, **base)

    for dimension in snapshot.dimensions:
        base = {
            "dimension_id": dimension.id,
            "table_id": dimension.table_id,
            "column_id": dimension.column_id,
        }
        add("dimension", dimension.id, dimension.name, dimension.name, **base)
        for alias in dimension.aliases:
            add("dimension", dimension.id, alias, dimension.name, **base)

    for column in snapshot.columns:
        table_name = tables[column.table_id].name
        base = {"column_id": column.id, "table_id": column.table_id}
        add("column", column.id, column.name, column.name, table_name=table_name, **base)
        for alias in column.alias:
            add("column", column.id, alias, column.name, table_name=table_name, **base)
        add("column", column.id, column.description, column.name, table_name=table_name, **base)

    dimension_by_column = {item.column_id: item for item in snapshot.dimensions}
    for column_id, dimension in dimension_by_column.items():
        column = columns[column_id]
        for example in column.examples:
            value = _text(example)
            if value:
                add(
                    "filter_value",
                    f"{dimension.id}:{value}",
                    value,
                    value,
                    dimension_id=dimension.id,
                    table_id=dimension.table_id,
                    column_id=dimension.column_id,
                )

    documents = list({item["id"]: item for item in documents}.values())
    documents.sort(key=lambda item: item["id"])
    return IndexManifest(snapshot.version_id, snapshot.content_hash, config.config_hash, tuple(documents))


class SemanticIndexBuilder:
    def __init__(self, es: ESIndexClient, qdrant: QdrantIndexClient, embeddings: EmbeddingClient, verification_store: VerificationStore):
        self.es = es
        self.qdrant = qdrant
        self.embeddings = embeddings
        self.verification_store = verification_store

    async def build(self, snapshot: SemanticModelSnapshot, config: IndexBuildConfig, target: str = "both") -> IndexManifest:
        if config.embedding_batch_size <= 0:
            raise IndexBuildError("embedding_batch_size 必须大于 0")
        if target not in {"es", "qdrant", "both"}:
            raise IndexBuildError("target 必须是 es、qdrant 或 both")
        manifest = build_manifest(snapshot, config)
        if not manifest.documents:
            raise IndexBuildError("语义快照没有可构建的索引实体")
        if target in {"es", "both"}:
            await self.es.ensure_index(config.es_index_name)
            await self.es.bulk_index(config.es_index_name, manifest.documents)
            await self._verify_es(config, manifest)
        if target in {"qdrant", "both"}:
            vectors = await self._embed_in_batches([item["text"] for item in manifest.documents], config.embedding_batch_size)
            if len(vectors) != len(manifest.documents) or any(len(vector) != config.embedding_dimension for vector in vectors):
                raise IndexBuildError("embedding 返回数量或维度不匹配")
            await self.qdrant.ensure_collection(config.qdrant_collection_name, config.embedding_dimension)
            points = [
                {"id": _point_id(item["id"]), "vector": vector, "payload": item}
                for item, vector in zip(manifest.documents, vectors)
            ]
            await self.qdrant.upsert(config.qdrant_collection_name, points)
            await self._verify_qdrant(config, manifest)
        await self.verification_store.record_verified({
            "version_id": manifest.version_id,
            "content_hash": manifest.content_hash,
            "config_hash": manifest.config_hash,
            "target": target,
            "es_index_name": config.es_index_name,
            "qdrant_collection_name": config.qdrant_collection_name,
            "manifest_hash": manifest.manifest_hash,
            "status": "verified",
            "verified_at": datetime.now(timezone.utc).replace(tzinfo=None),
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=config.verification_ttl_seconds)).replace(tzinfo=None),
            "document_count": len(manifest.documents),
        })
        return manifest

    async def _embed_in_batches(self, texts: Sequence[str], batch_size: int) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            try:
                batch_vectors = await self.embeddings.aembed_documents(batch)
            except Exception as exc:
                raise IndexBuildError(f"embedding batch failed: start={start}, size={len(batch)}") from exc
            if len(batch_vectors) != len(batch):
                raise IndexBuildError(f"embedding batch count mismatch: start={start}, expected={len(batch)}, actual={len(batch_vectors)}")
            vectors.extend(batch_vectors)
        return vectors
    async def _verify_es(self, config: IndexBuildConfig, manifest: IndexManifest) -> None:
        found = await self.es.get_documents(config.es_index_name, list(manifest.document_ids))
        self._verify_payloads(manifest, found, "ES")

    async def _verify_qdrant(self, config: IndexBuildConfig, manifest: IndexManifest) -> None:
        ids = [_point_id(item["id"]) for item in manifest.documents]
        found = await self.qdrant.get_points(config.qdrant_collection_name, ids)
        self._verify_payloads(manifest, [item["payload"] for item in found], "Qdrant")

    @staticmethod
    def _verify_payloads(manifest: IndexManifest, found: Sequence[dict[str, Any]], label: str) -> None:
        actual = {item.get("id") for item in found}
        if actual != manifest.document_ids:
            raise IndexBuildError(f"{label} 可检索实体集合不完整或存在跨版本污染")
        for item in found:
            expected = next(expected for expected in manifest.documents if expected["id"] == item["id"])
            for key in ("semantic_type", "version_id", "text", "display_name"):
                if item.get(key) != expected[key]:
                    raise IndexBuildError(f"{label} payload 不匹配: {key}")






