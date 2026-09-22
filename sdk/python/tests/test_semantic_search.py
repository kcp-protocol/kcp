"""
End-to-end tests for semantic / hybrid search through KCPNode (issue #1).

Two things are demonstrated here:

* **plumbing** — the offline deterministic ``hash`` embedder driving index,
  persistence and fusion without any network access;
* **real semantics** — an injected concept/synonym embedder (a tiny dictionary
  model) that makes ``rate limiting`` match an artifact about ``throttling``,
  which keyword search provably misses.

The default node stays FTS5-only (zero dependencies) — semantic search is opt-in.
"""

import math
import re
import sys

import pytest
from kcp.embeddings import EmbeddingError, SemanticSearchUnavailableError
from kcp.node import KCPNode

# ─── A tiny "real semantics" embedder: concepts instead of words ──

CONCEPTS = ["throttling", "security", "storage", "databases"]

SYNONYMS = {
    "throttle": "throttling",
    "throttling": "throttling",
    "rate": "throttling",
    "limiting": "throttling",
    "limit": "throttling",
    "limits": "throttling",
    "bucket": "throttling",
    "burst": "throttling",
    "backpressure": "throttling",
    "auth": "security",
    "authentication": "security",
    "jwt": "security",
    "token": "security",
    "tokens": "security",
    "secure": "security",
    "volumes": "storage",
    "volume": "storage",
    "disk": "storage",
    "storage": "storage",
    "postgres": "databases",
    "database": "databases",
    "sql": "databases",
    "replication": "databases",
}


def synonym_embedder(text: str) -> list:
    """Map words to concepts, count them, L2-normalize (deterministic, offline)."""
    vector = [0.0] * len(CONCEPTS)
    for token in re.findall(r"[a-z0-9_]+", text.lower()):
        concept = SYNONYMS.get(token)
        if concept:
            vector[CONCEPTS.index(concept)] += 1.0
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector] if norm else vector


def make_node(tmp_path, **kwargs) -> KCPNode:
    return KCPNode(
        user_id="alice@acme.com",
        tenant_id="acme",
        db_path=str(tmp_path / "kcp.db"),
        keys_dir=str(tmp_path / "keys"),
        **kwargs,
    )


@pytest.fixture
def keyword_node(tmp_path):
    """Default node — FTS5 only, no vector backend (retrocompatible)."""
    return make_node(tmp_path)


@pytest.fixture
def semantic_node(tmp_path):
    """Node with the local vector index enabled and the offline hash embedder."""
    return make_node(tmp_path, search_backend="sqlite-vss", embedding_model="hash")


@pytest.fixture
def concept_node(tmp_path):
    """Node using an injected concept/synonym embedder (real semantic behaviour)."""
    return make_node(tmp_path, search_backend="sqlite-vss", embedding_model=synonym_embedder)


class TestDefaultIsKeywordOnly:
    def test_defaults(self, keyword_node):
        assert keyword_node.search_backend == "fts5"
        assert keyword_node.semantic_available is False
        assert keyword_node.store.vector_index.count() == 0

    def test_keyword_search_still_works(self, keyword_node):
        keyword_node.publish(title="Rate limiting notes", content="nginx limit_req zone")
        response = keyword_node.search("limiting")
        assert response.total == 1
        assert response.results[0].title == "Rate limiting notes"

    def test_default_mode_is_keyword(self, keyword_node):
        keyword_node.publish(title="Alpha", content="alpha body")
        assert keyword_node.search("alpha").results == keyword_node.search("alpha", mode="keyword").results

    def test_semantic_mode_raises_without_backend(self, keyword_node):
        with pytest.raises(SemanticSearchUnavailableError, match="vector backend"):
            keyword_node.search("anything", mode="semantic")

    def test_hybrid_mode_raises_without_backend(self, keyword_node):
        with pytest.raises(SemanticSearchUnavailableError):
            keyword_node.search("anything", mode="hybrid")

    def test_reindex_raises_without_backend(self, keyword_node):
        with pytest.raises(SemanticSearchUnavailableError):
            keyword_node.reindex()

    def test_embedder_property_raises_without_backend(self, keyword_node):
        with pytest.raises(SemanticSearchUnavailableError):
            _ = keyword_node.embedder

    def test_unknown_mode_rejected(self, keyword_node):
        with pytest.raises(ValueError, match="unknown search mode"):
            keyword_node.search("x", mode="fuzzy")

    def test_status_reports_disabled(self, keyword_node):
        status = keyword_node.semantic_status()
        assert status["enabled"] is False
        assert status["search_backend"] == "fts5"
        assert status["embedding"] is None


class TestBackendSelection:
    def test_unsupported_server_backend_raises(self, tmp_path):
        with pytest.raises(NotImplementedError, match="kcp-protocol/kcp#1"):
            make_node(tmp_path, search_backend="qdrant")

    def test_unknown_backend_raises(self, tmp_path):
        with pytest.raises(ValueError, match="unknown search_backend"):
            make_node(tmp_path, search_backend="wat")

    def test_embedding_model_implies_vector_backend(self, tmp_path):
        """Passing a real embedding model with the default backend enables the index."""
        node = make_node(tmp_path, embedding_model="hash:64")
        assert node.semantic_available is True
        node.publish(title="Alpha", content="alpha")
        assert node.search("alpha", mode="semantic").total == 1

    def test_embedder_kwarg_enables_and_injects(self, tmp_path):
        node = make_node(tmp_path, embedder=synonym_embedder)
        assert node.semantic_available is True
        assert node.embedding_model_name == "custom"

    def test_local_aliases(self, tmp_path):
        for alias in ("sqlite_vss", "local", "vector", "auto"):
            node = make_node(tmp_path / alias, search_backend=alias)
            assert node.semantic_available is True


class TestSemanticIndexing:
    def test_publish_indexes_embedding(self, semantic_node):
        artifact = semantic_node.publish(title="Alpha", content="alpha beta")
        assert semantic_node.store.get_embedding(artifact.id, "hash-256") is not None
        assert semantic_node.store.embedding_stats()["vectors"] == 1

    def test_publish_does_not_index_when_disabled(self, keyword_node):
        keyword_node.publish(title="Alpha", content="alpha")
        assert keyword_node.store.embedding_stats()["vectors"] == 0

    def test_embedding_dim_matches_provider(self, semantic_node):
        artifact = semantic_node.publish(title="Alpha", content="alpha beta")
        vector = semantic_node.store.get_embedding(artifact.id, "hash-256")
        assert len(vector) == 256
        assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0, rel_tol=1e-6)

    def test_semantic_search_finds_lexical_match(self, semantic_node):
        target = semantic_node.publish(title="JWT authentication guide", content="token validation")
        semantic_node.publish(title="Gardening tips", content="tomatoes and basil")
        response = semantic_node.search("jwt authentication", mode="semantic")
        assert response.results
        assert response.results[0].id == target.id
        assert response.results[0].scores["semantic"] == pytest.approx(response.results[0].relevance, abs=0.01)

    def test_semantic_search_excludes_deleted(self, semantic_node):
        artifact = semantic_node.publish(title="JWT authentication guide", content="token validation")
        semantic_node.delete(artifact.id)
        assert semantic_node.search("jwt authentication", mode="semantic").results == []

    def test_private_artifact_indexed_by_title(self, semantic_node):
        """Encrypted content is not embedded, but the metadata still is."""
        artifact = semantic_node.publish(title="Launch codes rotation", content="secret payload", visibility="private")
        assert semantic_node.store.get_embedding(artifact.id, "hash-256") is not None
        response = semantic_node.search("launch codes", mode="semantic")
        assert [r.id for r in response.results] == [artifact.id]

    def test_backfill_on_first_semantic_search(self, tmp_path):
        """Artifacts published before the feature was enabled are embedded lazily."""
        writer = make_node(tmp_path)
        artifact = writer.publish(title="JWT authentication guide", content="token validation")
        writer.close()

        reader = make_node(tmp_path, search_backend="sqlite-vss", embedding_model="hash")
        assert reader.store.embedding_stats()["vectors"] == 0
        response = reader.search("jwt authentication", mode="semantic")
        assert [r.id for r in response.results] == [artifact.id]
        assert reader.store.embedding_stats()["vectors"] == 1

    def test_index_persists_across_reopen(self, tmp_path):
        node = make_node(tmp_path, search_backend="sqlite-vss")
        artifact = node.publish(title="JWT authentication guide", content="token validation")
        node.close()
        reopened = make_node(tmp_path, search_backend="sqlite-vss")
        assert reopened.store.embedded_ids("hash-256") == {artifact.id}

    def test_reindex_reports_counts(self, semantic_node):
        semantic_node.publish(title="One", content="one")
        semantic_node.publish(title="Two", content="two")
        stats = semantic_node.reindex()
        assert stats["indexed"] == 0  # already indexed at publish time
        assert stats["skipped"] == 2
        assert stats["indexed_total"] == 2
        assert stats["backend"] in ("sqlite-bruteforce", "sqlite-vss")
        assert stats["fallback_reason"]

    def test_reindex_force_rebuilds(self, semantic_node):
        semantic_node.publish(title="One", content="one")
        stats = semantic_node.reindex(force=True)
        assert stats["indexed"] == 1
        assert stats["skipped"] == 0


class TestRealSemanticsVsPlumbing:
    """`rate limiting` must find `throttling` — with real semantics, not with hash."""

    def _seed(self, node):
        target = node.publish(
            title="Throttling strategies for public APIs",
            content="Use a token bucket so upstream services survive bursty clients.",
        )
        other = node.publish(title="JWT authentication guide", content="Validate the exp claim.")
        return target, other

    def test_keyword_misses_the_synonym(self, concept_node):
        self._seed(concept_node)
        assert concept_node.search("rate limiting", mode="keyword").results == []

    def test_semantic_finds_the_synonym(self, concept_node):
        target, _ = self._seed(concept_node)
        response = concept_node.search("rate limiting", mode="semantic")
        assert response.results
        assert response.results[0].id == target.id
        # The artifact mentions two throttling concepts (throttling + bucket) plus one
        # security concept (token), while the query is pure throttling → soft match.
        assert response.results[0].relevance > 0.85
        assert isinstance(response.results[0].scores["semantic"], float)

    def test_hybrid_recovers_it_too(self, concept_node):
        target, _ = self._seed(concept_node)
        response = concept_node.search("rate limiting", mode="hybrid", alpha=0.5)
        assert [r.id for r in response.results] == [target.id]
        assert response.results[0].scores["keyword"] == 0.0
        assert response.results[0].scores["semantic"] > 0.85

    def test_hash_embedder_is_plumbing_only(self, semantic_node):
        """Offline hash embeddings have no semantics: they match words, not meaning."""
        self._seed(semantic_node)
        assert semantic_node.search("rate limiting", mode="semantic").total == 0

    def test_injected_embedder_is_used_for_queries_too(self, concept_node):
        self._seed(concept_node)
        assert concept_node.embedder.embed("rate limiting") == concept_node.embedder.embed("throttling")


class TestHybridFusion:
    def test_alpha_one_ranks_keyword_match_first(self, semantic_node):
        keyword_hit = semantic_node.publish(title="Nginx rate limiting setup", content="limit_req zone")
        semantic_node.publish(title="Cache headers", content="cache control directives")
        response = semantic_node.search("rate limiting", mode="hybrid", alpha=1.0)
        assert response.results[0].id == keyword_hit.id
        assert response.results[0].scores["keyword"] == pytest.approx(1.0)

    def test_hybrid_result_is_at_least_as_good_as_keyword(self, semantic_node):
        """The fused ranking must never lose a BM25 hit (it is a union)."""
        keyword_hit = semantic_node.publish(title="Nginx rate limiting setup", content="limit_req zone")
        semantic_node.publish(title="Cache headers", content="cache control directives")
        keyword_ids = {r.id for r in semantic_node.search("rate limiting", mode="keyword").results}
        hybrid_ids = {r.id for r in semantic_node.search("rate limiting", mode="hybrid").results}
        assert keyword_ids <= hybrid_ids
        assert keyword_hit.id in hybrid_ids

    def test_scores_present_per_result(self, semantic_node):
        semantic_node.publish(title="Nginx rate limiting setup", content="limit_req zone")
        response = semantic_node.search("rate limiting", mode="hybrid")
        assert response.results
        assert set(response.results[0].scores) == {"keyword", "semantic", "fused"}

    def test_invalid_alpha_rejected(self, semantic_node):
        with pytest.raises(ValueError, match="alpha"):
            semantic_node.search("q", mode="hybrid", alpha=2.0)


class TestEmbeddingFailures:
    def test_unreachable_provider_never_blocks_publish(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:1")
        node = make_node(tmp_path, search_backend="sqlite-vss", embedding_model="ollama:nomic-embed-text")
        artifact = node.publish(title="Alpha", content="alpha")
        assert artifact.id  # publish succeeded
        status = node.semantic_status()
        assert status["last_embedding_error"]
        assert "unreachable" in status["last_embedding_error"]
        assert node.store.embedding_stats()["vectors"] == 0

    def test_query_embedding_failure_is_raised(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:1")
        node = make_node(tmp_path, search_backend="sqlite-vss", embedding_model="ollama")
        node.publish(title="Alpha", content="alpha")
        with pytest.raises(EmbeddingError, match="unreachable"):
            node.search("alpha", mode="semantic")

    def test_missing_openai_key_surfaces_in_status(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        node = make_node(tmp_path, search_backend="sqlite-vss", embedding_model="openai:text-embedding-3-small")
        node.publish(title="Alpha", content="alpha")  # logged, not raised
        status = node.semantic_status()
        assert "OPENAI_API_KEY" in status["embedding"]["error"]


class TestSemanticStatus:
    def test_status_documents_the_fallback(self, semantic_node):
        status = semantic_node.semantic_status()
        assert status["enabled"] is True
        assert status["modes"] == ["keyword", "semantic", "hybrid"]
        assert status["embedding"]["provider"] == "hash"
        assert status["embedding"]["semantic"] is False
        assert status["index"]["requested_backend"] == "sqlite-vss"
        assert status["index"]["fallback"] is True
        assert "sqlite-vss" in status["index"]["fallback_reason"]

    def test_status_counts_indexed_artifacts(self, semantic_node):
        semantic_node.publish(title="Alpha", content="alpha")
        assert semantic_node.semantic_status()["indexed_artifacts"] == 1


class TestSemanticCLI:
    def _env(self, monkeypatch, tmp_path, **extra):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("KCP_DB", str(tmp_path / "kcp.db"))
        for key, value in extra.items():
            monkeypatch.setenv(key, value)

    def test_search_defaults_to_keyword(self, tmp_path, monkeypatch, capsys):
        from kcp.cli import main

        node = make_node(tmp_path)
        node.publish(title="Nginx rate limiting", content="limit_req zone")
        node.close()

        self._env(monkeypatch, tmp_path)
        monkeypatch.setattr(sys, "argv", ["kcp", "search", "limiting"])
        main()
        out = capsys.readouterr().out
        assert "mode=keyword" in out
        assert "Nginx rate limiting" in out

    def test_search_semantic_without_backend_exits(self, tmp_path, monkeypatch, capsys):
        from kcp.cli import main

        self._env(monkeypatch, tmp_path)
        monkeypatch.setattr(sys, "argv", ["kcp", "search", "x", "--mode", "semantic"])
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 2
        assert "Semantic search unavailable" in capsys.readouterr().out

    def test_search_semantic_with_env_backend(self, tmp_path, monkeypatch, capsys):
        from kcp.cli import main

        self._env(
            monkeypatch,
            tmp_path,
            KCP_SEARCH_BACKEND="sqlite-vss",
            KCP_EMBEDDING_MODEL="hash",
        )
        node = make_node(tmp_path, search_backend="sqlite-vss")
        node.publish(title="Nginx rate limiting", content="limit_req zone")
        node.close()

        monkeypatch.setattr(sys, "argv", ["kcp", "search", "limiting", "--mode", "hybrid"])
        main()
        out = capsys.readouterr().out
        assert "mode=hybrid" in out
        assert "fused=" in out

    def test_reindex_command(self, tmp_path, monkeypatch, capsys):
        from kcp.cli import main

        self._env(monkeypatch, tmp_path, KCP_SEARCH_BACKEND="sqlite-vss")
        node = make_node(tmp_path)
        node.publish(title="Alpha", content="alpha")
        node.close()

        monkeypatch.setattr(sys, "argv", ["kcp", "reindex"])
        main()
        out = capsys.readouterr().out
        assert "Indexed 1 artifact(s)" in out
        assert "fallback" in out

    def test_reindex_without_backend_exits(self, tmp_path, monkeypatch, capsys):
        from kcp.cli import main

        self._env(monkeypatch, tmp_path)
        monkeypatch.setattr(sys, "argv", ["kcp", "reindex"])
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 2
        assert "Vector backend is disabled" in capsys.readouterr().out

    def test_bad_limit_argument_exits(self, tmp_path, monkeypatch, capsys):
        from kcp.cli import main

        self._env(monkeypatch, tmp_path)
        monkeypatch.setattr(sys, "argv", ["kcp", "search", "x", "--limit", "many"])
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 1
        assert "Usage: kcp search" in capsys.readouterr().out
