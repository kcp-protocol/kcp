"""
Tests for the local vector index and the store-level semantic/hybrid search.

The index lives in the same SQLite file as the artifacts; similarity is exact
cosine similarity computed in pure Python (no numpy), with an explicit,
documented fallback when the optional ``sqlite-vss`` native extension is absent.
"""

import importlib.util
import sqlite3

import pytest
from kcp.store import LocalStore
from kcp.vector_index import (
    BRUTEFORCE_BACKEND,
    VectorIndex,
    VectorIndexError,
    decode_vector,
    encode_vector,
)

#: The pure-Python fallback assertions only hold when the optional native
#: extension is absent (which is the case in CI and for a plain `pip install`).
VSS_INSTALLED = importlib.util.find_spec("sqlite_vss") is not None
needs_no_vss = pytest.mark.skipif(VSS_INSTALLED, reason="sqlite-vss extension is installed")


def make_store(tmp_path, vector_backend="sqlite-vss") -> LocalStore:
    return LocalStore(str(tmp_path / "kcp_vec.db"), vector_backend=vector_backend)


@pytest.fixture
def store(tmp_path):
    return make_store(tmp_path)


def seed_artifacts(store: LocalStore, rows) -> dict:
    """Publish minimal artifacts directly through the store (no crypto involved)."""
    from kcp.models import KnowledgeArtifact

    ids = {}
    for key, title, tenant in rows:
        artifact = KnowledgeArtifact(
            title=title,
            user_id="u@test",
            tenant_id=tenant,
            format="text",
            content_hash=f"hash-{key}",
        )
        store.publish(artifact, content=b"")
        ids[key] = artifact.id
    return ids


class TestVectorEncoding:
    def test_round_trip(self):
        vector = [0.5, -1.25, 0.0, 3.0]
        assert decode_vector(encode_vector(vector)) == pytest.approx(vector)

    def test_blob_is_float32(self):
        assert len(encode_vector([1.0, 2.0, 3.0])) == 12

    def test_corrupt_blob_rejected(self):
        with pytest.raises(VectorIndexError, match="corrupt vector blob"):
            decode_vector(b"\x00\x01\x02")


class TestVectorIndexBasics:
    def test_add_get_count_and_models(self, store):
        index = store.vector_index
        a = seed_artifacts(store, [("a", "A", "t")])["a"]
        index.add(a, [1.0, 0.0, 0.0], model="test-model")
        assert index.count() == 1
        assert index.count("test-model") == 1
        assert index.get(a, "test-model") == pytest.approx([1.0, 0.0, 0.0])
        assert index.models() == ["test-model"]
        assert index.model_dim("test-model") == 3
        assert index.indexed_ids("test-model") == {a}

    def test_get_unknown_returns_none(self, store):
        assert store.vector_index.get("nope", "hash") is None

    def test_add_is_idempotent_per_model(self, store):
        index = store.vector_index
        a = seed_artifacts(store, [("a", "A", "t")])["a"]
        index.add(a, [1.0, 0.0], model="m")
        index.add(a, [0.0, 1.0], model="m")
        assert index.count("m") == 1
        assert index.get(a, "m") == pytest.approx([0.0, 1.0])

    def test_multiple_models_coexist(self, store):
        index = store.vector_index
        a = seed_artifacts(store, [("a", "A", "t")])["a"]
        index.add(a, [1.0, 0.0], model="model-a")
        index.add(a, [1.0, 0.0, 0.0], model="model-b")
        assert sorted(index.models()) == ["model-a", "model-b"]

    def test_empty_vector_rejected(self, store):
        with pytest.raises(VectorIndexError, match="empty vector"):
            store.vector_index.add("id", [], model="m")

    def test_dimension_conflict_within_model_rejected(self, store):
        index = store.vector_index
        index.add("id-1", [1.0, 0.0], model="m")
        with pytest.raises(VectorIndexError, match="dimension mismatch"):
            index.add("id-2", [1.0, 0.0, 0.0], model="m")

    def test_drop_by_model_and_all(self, store):
        index = store.vector_index
        index.add("id-1", [1.0, 0.0], model="m1")
        index.add("id-1", [1.0, 0.0], model="m2")
        assert index.drop("id-1", "m1") == 1
        assert index.models() == ["m2"]
        assert index.drop("id-1") == 1
        assert index.count() == 0

    def test_clear(self, store):
        index = store.vector_index
        index.add("id-1", [1.0, 0.0], model="m1")
        index.add("id-2", [1.0, 0.0], model="m1")
        assert index.clear("m1") == 2
        assert index.count() == 0


class TestVectorIndexSearch:
    def _seed(self, store):
        ids = seed_artifacts(store, [("a", "A", "t"), ("b", "B", "t"), ("c", "C", "t")])
        store.vector_index.add(ids["a"], [1.0, 0.0, 0.0], model="m")
        store.vector_index.add(ids["b"], [0.25, 0.97, 0.0], model="m")
        store.vector_index.add(ids["c"], [0.9, 0.1, 0.0], model="m")
        return ids

    def test_orders_by_cosine_similarity(self, store):
        ids = self._seed(store)
        hits = store.vector_index.search([1.0, 0.0, 0.0], model="m")
        assert [artifact_id for artifact_id, _ in hits] == [ids["a"], ids["c"], ids["b"]]
        assert hits[0][1] == pytest.approx(1.0)

    def test_limit_is_respected(self, store):
        self._seed(store)
        assert len(store.vector_index.search([1.0, 0.0, 0.0], model="m", limit=2)) == 2

    def test_limit_none_returns_everything(self, store):
        self._seed(store)
        assert len(store.vector_index.search([1.0, 0.0, 0.0], model="m", limit=None)) == 3

    def test_unknown_model_returns_empty(self, store):
        self._seed(store)
        assert store.vector_index.search([1.0, 0.0, 0.0], model="other") == []

    def test_query_dimension_mismatch_raises(self, store):
        self._seed(store)
        with pytest.raises(VectorIndexError, match="query vector has"):
            store.vector_index.search([1.0, 0.0], model="m")

    def test_empty_query_rejected(self, store):
        self._seed(store)
        with pytest.raises(VectorIndexError, match="empty query vector"):
            store.vector_index.search([], model="m")

    def test_persists_across_reopen(self, tmp_path):
        store = make_store(tmp_path)
        ids = self._seed(store)
        store.close()
        reopened = make_store(tmp_path)
        assert reopened.vector_index.count("m") == 3
        hits = reopened.vector_index.search([0.0, 1.0, 0.0], model="m")
        assert hits[0][0] == ids["b"]


class TestVectorIndexBackends:
    @needs_no_vss
    def test_sqlite_vss_alias_falls_back_explicitly(self, store):
        """Without the native extension the fallback must be visible, never silent."""
        status = store.vector_index.status()
        assert status["requested_backend"] == "sqlite-vss"
        assert status["effective_backend"] == BRUTEFORCE_BACKEND
        assert status["fallback"] is True
        assert "sqlite-vss" in status["fallback_reason"]
        assert status["ann_extension"] is False

    @needs_no_vss
    @pytest.mark.parametrize("alias", ["sqlite_vss", "local", "vector", "auto", "sqlite"])
    def test_local_aliases_accepted(self, tmp_path, alias):
        store = make_store(tmp_path, vector_backend=alias)
        assert store.vector_index.effective_backend == BRUTEFORCE_BACKEND
        assert store.vector_index.status()["requested_backend"] == alias

    def test_explicit_bruteforce_reports_reason(self, tmp_path):
        store = make_store(tmp_path, vector_backend="sqlite-bruteforce")
        assert "explicitly" in store.vector_index.fallback_reason

    def test_server_backend_not_implemented(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "x.db"))
        with pytest.raises(VectorIndexError, match="not implemented"):
            VectorIndex(conn, backend="qdrant")

    def test_unknown_backend_rejected(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "y.db"))
        with pytest.raises(VectorIndexError, match="unknown vector backend"):
            VectorIndex(conn, backend="not-a-backend")

    def test_status_lists_models_and_counts(self, store):
        ids = seed_artifacts(store, [("a", "A", "t")])
        store.vector_index.add(ids["a"], [1.0, 0.0], model="m1")
        store.vector_index.add(ids["a"], [1.0, 0.0, 0.0], model="m2")
        status = store.vector_index.status()
        assert status["vectors"] == 2
        assert status["models"]["m1"] == {"count": 1, "dim": 2}
        assert status["table"] == "kcp_embeddings"

    def test_schema_is_plain_sqlite(self, store):
        """The index must be inspectable with plain SQLite (portability guarantee)."""
        ids = seed_artifacts(store, [("a", "A", "t")])
        store.index_embedding(ids["a"], [1.0, 0.0], model="m")
        row = store._conn.execute("SELECT artifact_id, model, dim, vector FROM kcp_embeddings").fetchone()
        assert row["artifact_id"] == ids["a"]
        assert row["model"] == "m"
        assert row["dim"] == 2
        assert len(row["vector"]) == 8  # 2 × float32


class TestStoreSemanticSearch:
    def test_index_and_fetch_embedding(self, store):
        ids = seed_artifacts(store, [("a", "Alpha", "t")])
        store.index_embedding(ids["a"], [1.0, 0.0], model="m")
        assert store.embedded_ids("m") == {ids["a"]}
        assert store.get_embedding(ids["a"], "m") == pytest.approx([1.0, 0.0])
        assert store.drop_embedding(ids["a"]) == 1
        assert store.embedded_ids("m") == set()

    def test_semantic_search_orders_by_similarity(self, store):
        ids = seed_artifacts(store, [("a", "Alpha", "t"), ("b", "Beta", "t")])
        store.index_embedding(ids["a"], [1.0, 0.0], model="m")
        store.index_embedding(ids["b"], [0.3, 0.95], model="m")
        response = store.semantic_search([1.0, 0.0], model="m")
        assert [r.id for r in response.results] == [ids["a"], ids["b"]]
        assert response.total == 2
        assert response.results[0].relevance == pytest.approx(1.0)
        assert response.results[1].relevance == pytest.approx(0.3, abs=0.01)
        assert response.results[0].scores["semantic"] == pytest.approx(1.0)

    def test_orthogonal_vectors_are_not_results(self, store):
        ids = seed_artifacts(store, [("a", "Alpha", "t"), ("b", "Beta", "t")])
        store.index_embedding(ids["a"], [1.0, 0.0], model="m")
        store.index_embedding(ids["b"], [0.0, 1.0], model="m")
        response = store.semantic_search([1.0, 0.0], model="m")
        assert [r.id for r in response.results] == [ids["a"]]
        assert response.total == 1

    def test_min_score_allows_keeping_everything(self, store):
        ids = seed_artifacts(store, [("a", "Alpha", "t"), ("b", "Beta", "t")])
        store.index_embedding(ids["a"], [1.0, 0.0], model="m")
        store.index_embedding(ids["b"], [0.0, 1.0], model="m")
        response = store.semantic_search([1.0, 0.0], model="m", min_score=-1.0)
        assert response.total == 2

    def test_semantic_search_respects_limit_and_offset(self, store):
        ids = seed_artifacts(store, [("a", "Alpha", "t"), ("b", "Beta", "t"), ("c", "Gamma", "t")])
        store.index_embedding(ids["a"], [1.0, 0.0], model="m")
        store.index_embedding(ids["b"], [0.5, 0.5], model="m")
        store.index_embedding(ids["c"], [0.1, 0.99], model="m")
        page = store.semantic_search([1.0, 0.0], model="m", limit=1, offset=1)
        assert [r.id for r in page.results] == [ids["b"]]
        assert page.total == 3

    def test_semantic_search_excludes_deleted(self, store):
        ids = seed_artifacts(store, [("a", "Alpha", "t")])
        store.index_embedding(ids["a"], [1.0, 0.0], model="m")
        store.delete(ids["a"])
        assert store.semantic_search([1.0, 0.0], model="m").results == []

    def test_delete_drops_the_embedding(self, store):
        ids = seed_artifacts(store, [("a", "Alpha", "t")])
        store.index_embedding(ids["a"], [1.0, 0.0], model="m")
        store.delete(ids["a"])
        assert store.embedding_stats()["vectors"] == 0

    def test_semantic_search_tenant_filter(self, store):
        ids = seed_artifacts(store, [("a", "Alpha", "tenant-1"), ("b", "Beta", "tenant-2")])
        store.index_embedding(ids["a"], [1.0, 0.0], model="m")
        store.index_embedding(ids["b"], [1.0, 0.0], model="m")
        response = store.semantic_search([1.0, 0.0], model="m", tenant_id="tenant-1")
        assert [r.id for r in response.results] == [ids["a"]]
        assert response.total == 1

    def test_stats_exposes_embedding_count(self, store):
        ids = seed_artifacts(store, [("a", "Alpha", "t")])
        store.index_embedding(ids["a"], [1.0, 0.0], model="m")
        assert store.stats()["embeddings"] == 1


class TestStoreHybridSearch:
    def _pool(self, store):
        return seed_artifacts(
            store,
            [
                ("kw", "Postgres replication guide", "t"),
                ("sem", "Database failover notes", "t"),
                ("other", "Gardening tips", "t"),
            ],
        )

    def test_hybrid_returns_union_of_both_rankings(self, store):
        ids = self._pool(store)
        # only "sem" is embedded → semantic ranking is just that artifact
        store.index_embedding(ids["sem"], [1.0, 0.0], model="m")
        response = store.hybrid_search("replication", [1.0, 0.0], model="m", alpha=0.5)
        found = {r.id for r in response.results}
        assert ids["kw"] in found  # matched by BM25
        assert ids["sem"] in found  # matched by cosine
        assert ids["other"] not in found

    def test_alpha_one_is_keyword_only(self, store):
        ids = self._pool(store)
        store.index_embedding(ids["sem"], [1.0, 0.0], model="m")
        response = store.hybrid_search("replication", [1.0, 0.0], model="m", alpha=1.0)
        assert [r.id for r in response.results] == [ids["kw"]]
        assert response.results[0].scores["semantic"] == 0.0

    def test_alpha_zero_is_semantic_only(self, store):
        ids = self._pool(store)
        store.index_embedding(ids["sem"], [1.0, 0.0], model="m")
        response = store.hybrid_search("replication", [1.0, 0.0], model="m", alpha=0.0)
        assert [r.id for r in response.results] == [ids["sem"]]

    def test_scores_expose_both_components(self, store):
        ids = self._pool(store)
        store.index_embedding(ids["kw"], [1.0, 0.0], model="m")
        response = store.hybrid_search("replication", [1.0, 0.0], model="m", alpha=0.5)
        top = response.results[0]
        assert top.id == ids["kw"]
        assert set(top.scores) == {"keyword", "semantic", "fused"}
        assert top.scores["keyword"] == pytest.approx(1.0)
        assert top.scores["semantic"] == pytest.approx(1.0)
        assert top.relevance == pytest.approx(top.scores["fused"])

    def test_alpha_validation(self, store):
        with pytest.raises(ValueError, match="alpha"):
            store.hybrid_search("q", [1.0], model="m", alpha=1.5)

    def test_hybrid_without_embeddings_is_keyword_only(self, store):
        ids = self._pool(store)
        response = store.hybrid_search("replication", [1.0, 0.0], model="m", alpha=0.5)
        assert [r.id for r in response.results] == [ids["kw"]]

    def test_hybrid_pagination(self, store):
        self._pool(store)
        response = store.hybrid_search("replication", [1.0, 0.0], model="m", limit=1, offset=0)
        assert len(response.results) == 1
