import asyncio
import unittest
from datetime import datetime, timedelta

from app.services.semantic_index_builder import IndexBuildConfig, IndexBuildError, SemanticIndexBuilder, build_manifest
from app.services.semantic_index_verification import InMemoryVerificationStore
from tests.test_semantic_model_snapshot import rows


class FakeEmbedding:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    async def aembed_documents(self, texts):
        self.calls.append(list(texts))
        if self.fail:
            raise RuntimeError("embedding failed")
        return [[float(len(texts)), 1.0] for _ in texts]


class FakeES:
    def __init__(self, fail=False):
        self.docs = {}
        self.fail = fail
        self.calls = []

    async def ensure_index(self, name):
        self.name = name

    async def bulk_index(self, name, documents):
        if self.fail:
            raise RuntimeError("bulk item failed")
        self.docs.update({item["id"]: item for item in documents})

    async def get_documents(self, name, ids):
        return [self.docs[item] for item in ids if item in self.docs]


class FakeQdrant:
    def __init__(self, partial=False):
        self.points = {}
        self.partial = partial

    async def ensure_collection(self, name, vector_size):
        self.name = name

    async def upsert(self, name, points):
        self.points.update({item["id"]: item for item in points})

    async def get_points(self, name, ids):
        values = [self.points[item] for item in ids if item in self.points]
        return values[:-1] if self.partial and values else values


class SemanticIndexBuilderTests(unittest.TestCase):
    def setUp(self):
        from app.services.semantic_model_snapshot import SemanticModelSnapshotLoader

        class Repo:
            async def load_version_rows(self, version_id):
                return rows(version_id, "draft")

        self.snapshot = asyncio.run(SemanticModelSnapshotLoader(Repo()).load_for_build("draft"))
        self.config = IndexBuildConfig("semantic-draft", "semantic-draft", "fake", 2, embedding_batch_size=2)

    def test_manifest_is_deterministic_and_value_scope_is_dimension_declared(self):
        first = build_manifest(self.snapshot, self.config)
        second = build_manifest(self.snapshot, self.config)
        self.assertEqual(first.manifest_hash, second.manifest_hash)
        values = [item for item in first.documents if item["semantic_type"] == "filter_value"]
        self.assertTrue(values)
        self.assertTrue(all(item["dimension_id"] == "region" for item in values))
        self.assertEqual(len(first.document_ids), len(first.documents))

    def test_embedding_requests_are_batched(self):
        embeddings = FakeEmbedding()
        asyncio.run(SemanticIndexBuilder(FakeES(), FakeQdrant(), embeddings, InMemoryVerificationStore()).build(self.snapshot, self.config))
        self.assertGreater(len(embeddings.calls), 1)
        self.assertTrue(all(len(batch) <= 2 for batch in embeddings.calls))
    def test_both_targets_verify_and_record_success(self):
        store = InMemoryVerificationStore()
        es, qdrant = FakeES(), FakeQdrant()
        manifest = asyncio.run(SemanticIndexBuilder(es, qdrant, FakeEmbedding(), store).build(self.snapshot, self.config))
        self.assertEqual(len(store.records), 1)
        self.assertEqual(store.records[0]["target"], "both")
        self.assertEqual(store.records[0]["manifest_hash"], manifest.manifest_hash)
        asyncio.run(store.assert_ready("draft", "hash-draft", self.config.config_hash, "semantic-draft", "semantic-draft", manifest.manifest_hash))

    def test_embedding_failure_and_partial_qdrant_never_record_success(self):
        for embeddings, qdrant in ((FakeEmbedding(True), FakeQdrant()), (FakeEmbedding(), FakeQdrant(True))):
            store = InMemoryVerificationStore()
            with self.assertRaises((RuntimeError, IndexBuildError)):
                asyncio.run(SemanticIndexBuilder(FakeES(), qdrant, embeddings, store).build(self.snapshot, self.config))
            self.assertEqual(store.records, [])

    def test_es_bulk_failure_never_records_success(self):
        store = InMemoryVerificationStore()
        with self.assertRaises(RuntimeError):
            asyncio.run(SemanticIndexBuilder(FakeES(True), FakeQdrant(), FakeEmbedding(), store).build(self.snapshot, self.config))
        self.assertEqual(store.records, [])

    def test_failed_build_can_retry_idempotently_with_same_manifest(self):
        class RetryES(FakeES):
            def __init__(self):
                super().__init__(True)
                self.calls = 0

            async def bulk_index(self, name, documents):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("transient bulk failure")
                self.fail = False
                await super().bulk_index(name, documents)

        es, qdrant, store = RetryES(), FakeQdrant(), InMemoryVerificationStore()
        builder = SemanticIndexBuilder(es, qdrant, FakeEmbedding(), store)
        with self.assertRaises(RuntimeError):
            asyncio.run(builder.build(self.snapshot, self.config))
        manifest = asyncio.run(builder.build(self.snapshot, self.config))
        self.assertEqual(len(store.records), 1)
        self.assertEqual(manifest.manifest_hash, build_manifest(self.snapshot, self.config).manifest_hash)
        self.assertEqual(len(es.docs), len(manifest.documents))
    def test_config_change_and_expired_record_are_rejected(self):
        store = InMemoryVerificationStore()
        manifest = asyncio.run(SemanticIndexBuilder(FakeES(), FakeQdrant(), FakeEmbedding(), store).build(self.snapshot, self.config))
        with self.assertRaises(Exception):
            asyncio.run(store.assert_ready("draft", "hash-draft", IndexBuildConfig("other", "semantic-draft", "fake", 2).config_hash, "other", "semantic-draft", manifest.manifest_hash))
        store.records[0]["expires_at"] = datetime.min
        with self.assertRaises(Exception):
            asyncio.run(store.assert_ready("draft", "hash-draft", self.config.config_hash, "semantic-draft", "semantic-draft", manifest.manifest_hash))


if __name__ == "__main__":
    unittest.main()





