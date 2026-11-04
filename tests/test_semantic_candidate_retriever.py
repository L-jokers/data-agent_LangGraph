import asyncio
import unittest

from app.services.semantic_candidate_retriever import CandidateSearchConfig, SemanticCandidateRetriever
from app.services.semantic_model_snapshot import SemanticModelSnapshotLoader
from tests.test_semantic_model_snapshot import rows


class FakeES:
    def __init__(self, rows):
        self.rows = rows
        self.write_calls = 0

    async def lexical_search(self, index_name, query, version_id, semantic_types, limit=10, dimension_id=None):
        return [item for item in self.rows if item["version_id"] == version_id and item["semantic_type"] in semantic_types and (dimension_id is None or item.get("dimension_id") == dimension_id)]

    async def ensure_index(self, *args, **kwargs):
        self.write_calls += 1


class UnavailableES(FakeES):
    async def lexical_search(self, *args, **kwargs):
        raise RuntimeError("index unavailable")


class FakeQdrant:
    def __init__(self, rows):
        self.rows = rows
        self.write_calls = 0

    async def vector_search(self, collection_name, embedding, version_id, semantic_types, limit=10, score_threshold=0.0, dimension_id=None):
        return [item for item in self.rows if item["version_id"] == version_id and item["semantic_type"] in semantic_types and item.get("score", 0) >= score_threshold and (dimension_id is None or item.get("dimension_id") == dimension_id)]

    async def ensure_collection(self, *args, **kwargs):
        self.write_calls += 1


class FakeEmbedding:
    async def aembed_query(self, query):
        return [1.0, 0.0]


class Repo:
    def __init__(self):
        self.load_calls = []

    async def load_version_rows(self, version_id):
        self.load_calls.append(version_id)
        return rows(version_id, "active")

    async def get_active_version_id(self):
        return "active"


class SemanticCandidateRetrieverTests(unittest.TestCase):
    def setUp(self):
        self.repository = Repo()
        self.loader = SemanticModelSnapshotLoader(self.repository)
        self.es = FakeES([
            {"id": "metric-doc", "semantic_type": "metric", "version_id": "active", "metric_id": "sales", "text": "\u9500\u552e\u989d", "display_name": "\u9500\u552e\u989d", "score": 2.0},
            {"id": "wrong-version", "semantic_type": "metric", "version_id": "other", "metric_id": "sales", "text": "\u9500\u552e\u989d", "display_name": "\u9500\u552e\u989d", "score": 9.0},
        ])
        self.qdrant = FakeQdrant([
            {"id": "value-doc", "semantic_type": "filter_value", "version_id": "active", "dimension_id": "region", "column_id": "dim_region.name", "text": "\u534e\u4e1c", "display_name": "name", "score": 0.9},
        ])
        self.retriever = SemanticCandidateRetriever(
            self.loader, self.es, self.qdrant, FakeEmbedding(),
            CandidateSearchConfig("semantic-active", "semantic-active", auto_score_threshold=1.5, auto_margin_threshold=0.2),
        )

    def test_exact_match_uses_snapshot_and_no_index_write(self):
        result = asyncio.run(self.retriever.hybrid_search("\u9500\u552e\u989d", ["metric"], version_id="active"))
        self.assertEqual(result["metric"].status, "exact")
        self.assertEqual(result["metric"].candidates[0].stable_id, "sales")
        self.assertEqual(self.es.write_calls, 0)
        self.assertEqual(self.qdrant.write_calls, 0)

    def test_filter_value_requires_dimension_and_declared_value(self):
        result = asyncio.run(self.retriever.hybrid_search("\u534e\u4e1c", ["filter_value"], version_id="active", dimension_id="region", allow_fuzzy=True))
        self.assertEqual(result["filter_value"].status, "exact")
        self.assertEqual(result["filter_value"].candidates[0].dimension_id, "region")

    def test_cold_start_does_not_auto_map_fuzzy_candidate(self):
        result = asyncio.run(self.retriever.hybrid_search("\u9500\u552e", ["metric"], version_id="active"))
        self.assertEqual(result["metric"].status, "clarification")

    def test_single_fuzzy_candidate_requires_top2(self):
        result = asyncio.run(self.retriever.hybrid_search("\u9500\u552e", ["filter_value"], version_id="active", dimension_id="region", allow_fuzzy=True))
        self.assertEqual(result["filter_value"].status, "clarification")

    def test_session_version_is_fixed(self):
        result = asyncio.run(self.retriever.hybrid_search("\u9500\u552e\u989d", ["metric"], version_id="other", session_version_id="active"))
        self.assertEqual(result["metric"].candidates[0].version_id, "active")
        self.assertEqual(self.repository.load_calls, ["active"])

    def test_unavailable_index_degrades_without_initialization(self):
        retriever = SemanticCandidateRetriever(
            self.loader, UnavailableES([]), self.qdrant, FakeEmbedding(),
            self.retriever.config,
        )
        result = asyncio.run(retriever.hybrid_search("not-found", ["metric"], version_id="active"))
        self.assertEqual(result["metric"].status, "unresolved")


if __name__ == "__main__":
    unittest.main()
