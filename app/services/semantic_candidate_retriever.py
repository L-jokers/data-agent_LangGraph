from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence

from app.core.log import logger
from app.services.semantic_model_snapshot import SemanticModelSnapshot, SemanticModelSnapshotLoader


class CandidateSearchError(RuntimeError):
    pass


@dataclass(frozen=True)
class CandidateSearchConfig:
    es_index_name: str
    qdrant_collection_name: str
    lexical_limit: int = 10
    vector_limit: int = 10
    lexical_threshold: float = 1.0
    vector_threshold: float = 0.6
    auto_score_threshold: float = 1.5
    auto_margin_threshold: float = 0.25
    enable_fuzzy_mapping: bool = True


@dataclass(frozen=True)
class SemanticCandidate:
    semantic_type: str
    stable_id: str
    version_id: str
    display_name: str
    text: str
    score: float
    source: str
    dimension_id: str | None = None
    payload: Mapping[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True)
class CandidateResolution:
    status: str
    candidates: tuple[SemanticCandidate, ...]
    reason: str | None = None


class LexicalSearchClient(Protocol):
    async def lexical_search(self, index_name: str, query: str, version_id: str,
                             semantic_types: Sequence[str], limit: int = 10,
                             dimension_id: str | None = None) -> list[dict[str, Any]]: ...


class VectorSearchClient(Protocol):
    async def vector_search(self, collection_name: str, embedding: list[float], version_id: str,
                            semantic_types: Sequence[str], limit: int = 10,
                            score_threshold: float = 0.0,
                            dimension_id: str | None = None) -> list[dict[str, Any]]: ...


class QueryEmbedding(Protocol):
    async def aembed_query(self, text: str) -> list[float]: ...


class SemanticCandidateRetriever:
    """Read-only candidate retrieval over one validated semantic snapshot."""

    def __init__(self, snapshot_loader: SemanticModelSnapshotLoader,
                 es: LexicalSearchClient, qdrant: VectorSearchClient,
                 embeddings: QueryEmbedding | None, config: CandidateSearchConfig):
        self.snapshot_loader = snapshot_loader
        self.es = es
        self.qdrant = qdrant
        self.embeddings = embeddings
        self.config = config

    async def lexical_search(self, query: str, version_id: str,
                             semantic_types: Sequence[str], dimension_id: str | None = None) -> list[SemanticCandidate]:
        snapshot = await self.snapshot_loader.load_for_query(version_id)
        return await self._lexical_search_snapshot(snapshot, query, semantic_types, dimension_id)

    async def _lexical_search_snapshot(self, snapshot: SemanticModelSnapshot, query: str,
                                       semantic_types: Sequence[str], dimension_id: str | None = None) -> list[SemanticCandidate]:
        rows = await self.es.lexical_search(
            self.config.es_index_name, query, snapshot.version_id, semantic_types,
            self.config.lexical_limit, dimension_id,
        )
        return self._validated_candidates(snapshot, rows, "es", semantic_types, dimension_id)

    async def vector_search(self, query: str, version_id: str,
                            semantic_types: Sequence[str], dimension_id: str | None = None) -> list[SemanticCandidate]:
        if self.embeddings is None:
            return []
        snapshot = await self.snapshot_loader.load_for_query(version_id)
        return await self._vector_search_snapshot(snapshot, query, semantic_types, dimension_id)

    async def _vector_search_snapshot(self, snapshot: SemanticModelSnapshot, query: str,
                                      semantic_types: Sequence[str], dimension_id: str | None = None) -> list[SemanticCandidate]:
        embedding = await self.embeddings.aembed_query(query)
        rows = await self.qdrant.vector_search(
            self.config.qdrant_collection_name, embedding, snapshot.version_id, semantic_types,
            self.config.vector_limit, self.config.vector_threshold, dimension_id,
        )
        return self._validated_candidates(snapshot, rows, "qdrant", semantic_types, dimension_id)

    async def hybrid_search(self, query: str, semantic_types: Sequence[str],
                            version_id: str | None = None, session_version_id: str | None = None,
                            dimension_id: str | None = None, allow_fuzzy: bool | None = None) -> dict[str, CandidateResolution]:
        selected_version = session_version_id or version_id
        if not selected_version:
            selected_version = await self.snapshot_loader.repository.get_active_version_id()
        snapshot = await self.snapshot_loader.load_for_query(selected_version)
        # 先走精确匹配_exact_matches
        exact = self._exact_matches(snapshot, query, semantic_types, dimension_id)
        try:
            # 再走语法召回（取值匹配）
            lexical = await self._lexical_search_snapshot(snapshot, query, semantic_types, dimension_id)
        except Exception:
            lexical = []

        # 允许模糊查询（向量查询）的条件fuzzy_enabled
        # 符合向量查询条件才能走向量查询_vector_search_snapshot
        fuzzy_enabled = self.config.enable_fuzzy_mapping if allow_fuzzy is None else allow_fuzzy
        vector: list[SemanticCandidate] = []
        # 符合向量查询条件：开启语义查询开关fuzzy_enabled，同时精确匹配没有成功not any(item.status == "exact")
        if fuzzy_enabled and not any(item.status == "exact" for item in exact.values()):
            try:
                vector = await self._vector_search_snapshot(snapshot, query, semantic_types, dimension_id)
            except Exception:
                vector = []
        merged = self._merge(exact, lexical + vector)
        return {
            semantic_type: self._classify(semantic_type, merged.get(semantic_type, []), snapshot,
                                          query, fuzzy_enabled)
            for semantic_type in semantic_types
        }

    def _exact_matches(self, snapshot: SemanticModelSnapshot, query: str,
                       semantic_types: Sequence[str], dimension_id: str | None) -> dict[str, CandidateResolution]:
        normalized = query.strip().casefold()
        rows: dict[str, list[SemanticCandidate]] = {semantic_type: [] for semantic_type in semantic_types}
        for semantic_type in semantic_types:
            for candidate in self._snapshot_candidates(snapshot, semantic_type, dimension_id):
                if candidate.text.casefold() == normalized:
                    rows[semantic_type].append(candidate)
        return {semantic_type: self._classify_exact(rows[semantic_type]) for semantic_type in semantic_types}

    @staticmethod
    def _classify_exact(candidates: list[SemanticCandidate]) -> CandidateResolution:
        unique = {item.stable_id: item for item in candidates}
        if len(unique) == 1:
            return CandidateResolution("exact", tuple(unique.values()))
        if len(unique) > 1:
            return CandidateResolution("clarification", tuple(unique.values()), "精确名称或别名对应多个实体")
        return CandidateResolution("unresolved", ())

    def _classify(self, semantic_type: str, candidates: list[SemanticCandidate],
                  snapshot: SemanticModelSnapshot, query: str, fuzzy_enabled: bool) -> CandidateResolution:
        exact = self._classify_exact([item for item in candidates if item.score >= 1.0 and item.text.casefold() == query.strip().casefold()])
        if exact.status != "unresolved":
            return exact
        if semantic_type == "filter_value":
            candidates = [item for item in candidates if self._value_allowed(snapshot, item)]
        if semantic_type == "metric":
            candidates = [item for item in candidates if self._metric_valid(snapshot, item)]
        candidates = sorted({item.stable_id: item for item in candidates}.values(), key=lambda item: item.score, reverse=True)
        if not candidates:
            return CandidateResolution("unresolved", ())
        if not fuzzy_enabled:
            return CandidateResolution("clarification", tuple(candidates[:2]), "冷启动仅允许唯一精确映射")
        if len(candidates) == 1:
            return CandidateResolution("clarification", tuple(candidates), "非精确候选缺少 Top2，不能自动映射")
        logger.info(
            f"第一候选名称：{candidates[0].display_name}，第一候选分数：{candidates[0].score:.4f}；"
            f"第二候选名称：{candidates[1].display_name}，第二候选分数：{candidates[1].score:.4f}"
        )
        if candidates[0].score < self.config.auto_score_threshold or candidates[0].score - candidates[1].score < self.config.auto_margin_threshold:
            return CandidateResolution("clarification", tuple(candidates[:2]), "候选分数或分差不足")
        return CandidateResolution("auto", (candidates[0],))

    @staticmethod
    def _merge(exact: dict[str, CandidateResolution], candidates: Sequence[SemanticCandidate]) -> dict[str, list[SemanticCandidate]]:
        merged = {key: list(value.candidates) for key, value in exact.items()}
        for item in candidates:
            merged.setdefault(item.semantic_type, []).append(item)
        for key, values in merged.items():
            unique: dict[str, SemanticCandidate] = {}
            for value in values:
                previous = unique.get(value.stable_id)
                if previous is None or value.score > previous.score:
                    unique[value.stable_id] = value
            merged[key] = list(unique.values())
        return merged

    @staticmethod
    def _snapshot_candidates(snapshot: SemanticModelSnapshot, semantic_type: str,
                             dimension_id: str | None) -> list[SemanticCandidate]:
        rows: list[SemanticCandidate] = []
        if semantic_type == "metric":
            rows = [SemanticCandidate("metric", item.id, snapshot.version_id, item.name, item.name, 1.0, "mysql", payload={"metric_id": item.id}) for item in snapshot.metrics]
            rows += [SemanticCandidate("metric", item.id, snapshot.version_id, item.name, alias, 1.0, "mysql", payload={"metric_id": item.id}) for item in snapshot.metrics for alias in item.alias]
        elif semantic_type == "dimension":
            rows = [SemanticCandidate("dimension", item.id, snapshot.version_id, item.name, item.name, 1.0, "mysql", item.id, {"dimension_id": item.id}) for item in snapshot.dimensions if dimension_id is None or item.id == dimension_id]
            rows += [SemanticCandidate("dimension", item.id, snapshot.version_id, item.name, alias, 1.0, "mysql", item.id, {"dimension_id": item.id}) for item in snapshot.dimensions if dimension_id is None or item.id == dimension_id for alias in item.aliases]
        elif semantic_type in {"column", "filter_value"}:
            dimensions = {item.column_id: item for item in snapshot.dimensions if dimension_id is None or item.id == dimension_id}
            for column in snapshot.columns:
                dimension = dimensions.get(column.id)
                if dimension is None:
                    continue
                values = column.examples if semantic_type == "filter_value" else [column.name, *column.alias, column.description]
                for value in values:
                    rows.append(SemanticCandidate(semantic_type, f"{semantic_type}:{dimension.id}:{value}" if semantic_type == "filter_value" else column.id, snapshot.version_id, column.name, str(value), 1.0, "mysql", dimension.id, {"dimension_id": dimension.id, "column_id": column.id}))
        return rows

    def _validated_candidates(self, snapshot: SemanticModelSnapshot, rows: Sequence[dict[str, Any]], source: str,
                              semantic_types: Sequence[str], dimension_id: str | None) -> list[SemanticCandidate]:
        allowed = {item.stable_id: item for semantic_type in semantic_types for item in self._snapshot_candidates(snapshot, semantic_type, dimension_id)}
        result: list[SemanticCandidate] = []
        for row in rows:
            row_version = row.get("version_id")
            semantic_type = row.get("semantic_type")
            stable_id = row.get("id") or row.get("stable_id") or row.get(f"{semantic_type}_id")
            if row_version != snapshot.version_id or semantic_type not in semantic_types:
                continue
            reference = next((item for item in allowed.values() if item.payload.get(f"{semantic_type}_id") == row.get(f"{semantic_type}_id") or item.stable_id == stable_id or (semantic_type == "filter_value" and item.dimension_id == row.get("dimension_id") and item.text == row.get("text"))), None)
            if reference is None:
                continue
            result.append(SemanticCandidate(semantic_type, reference.stable_id, snapshot.version_id, row.get("display_name", reference.display_name), row.get("text", reference.text), float(row.get("score", 0.0)), source, row.get("dimension_id", reference.dimension_id), row))
        return result

    @staticmethod
    def _metric_valid(snapshot: SemanticModelSnapshot, candidate: SemanticCandidate) -> bool:
        metric = next((item for item in snapshot.metrics if item.id == candidate.stable_id), None)
        datasets = {item.id for item in snapshot.datasets}
        columns = {item.id for item in snapshot.columns}
        return metric is not None and metric.base_dataset in datasets and all(column in columns for column in metric.relevant_columns)

    @staticmethod
    def _value_allowed(snapshot: SemanticModelSnapshot, candidate: SemanticCandidate) -> bool:
        column_id = candidate.payload.get("column_id")
        value = candidate.text
        return any(item.id == column_id and value in {str(example) for example in item.examples} for item in snapshot.columns)
