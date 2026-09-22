"""
Tests for KCP embedding providers (embeddings.py).

Covers the offline deterministic provider (plumbing), the pluggable callable
injection point (used for real-semantics tests), the HTTP providers (with the
network layer stubbed — the suite never reaches the internet) and provider
resolution/validation errors.
"""

import math

import pytest
from kcp.embeddings import (
    BaseEmbeddingProvider,
    CallableEmbeddingProvider,
    EmbeddingError,
    HashEmbeddingProvider,
    OllamaEmbeddingProvider,
    OpenAIEmbeddingProvider,
    cosine_similarity,
    l2_normalize,
    resolve_embedding_provider,
    tokenize,
)


class TestVectorHelpers:
    def test_tokenize_lowercases_and_splits(self):
        assert tokenize("Rate-Limiting: 2 Tokens!") == ["rate", "limiting", "2", "tokens"]

    def test_tokenize_empty(self):
        assert tokenize("") == []

    def test_l2_normalize_produces_unit_norm(self):
        vector = l2_normalize([3.0, 4.0])
        assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0)

    def test_l2_normalize_zero_vector_is_preserved(self):
        assert l2_normalize([0.0, 0.0]) == [0.0, 0.0]

    def test_cosine_identical_is_one(self):
        assert math.isclose(cosine_similarity([1.0, 2.0], [1.0, 2.0]), 1.0)

    def test_cosine_orthogonal_is_zero(self):
        assert math.isclose(cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.0)

    def test_cosine_opposite_is_minus_one(self):
        assert math.isclose(cosine_similarity([1.0, 0.0], [-1.0, 0.0]), -1.0)

    def test_cosine_zero_vector_is_zero(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0

    def test_cosine_dimension_mismatch_raises(self):
        with pytest.raises(ValueError):
            cosine_similarity([1.0], [1.0, 2.0])


class TestHashEmbeddingProvider:
    def test_default_dim(self):
        assert HashEmbeddingProvider().dim == 256

    def test_custom_dim_and_model_name(self):
        provider = HashEmbeddingProvider(dim=64)
        assert provider.dim == 64
        assert provider.model == "hash-64"

    def test_dim_too_small_rejected(self):
        with pytest.raises(ValueError):
            HashEmbeddingProvider(dim=4)

    def test_deterministic_across_instances(self):
        a = HashEmbeddingProvider(dim=64).embed("rate limiting strategies")
        b = HashEmbeddingProvider(dim=64).embed("rate limiting strategies")
        assert a == b

    def test_vector_is_l2_normalized(self):
        vector = HashEmbeddingProvider(dim=128).embed("some words here")
        assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0, rel_tol=1e-6)

    def test_different_texts_differ(self):
        provider = HashEmbeddingProvider(dim=128)
        assert provider.embed("alpha beta") != provider.embed("gamma delta")

    def test_lexical_overlap_is_high_similarity(self):
        provider = HashEmbeddingProvider(dim=256)
        a = provider.embed("jwt authentication best practices")
        b = provider.embed("jwt authentication guide")
        c = provider.embed("kubernetes storage volumes")
        assert cosine_similarity(a, b) > cosine_similarity(a, c)

    def test_empty_text_is_zero_vector_with_right_dim(self):
        vector = HashEmbeddingProvider(dim=32).embed("")
        assert len(vector) == 32
        assert set(vector) == {0.0}

    def test_is_offline_and_not_semantic(self):
        provider = HashEmbeddingProvider()
        assert provider.is_offline is True
        assert provider.is_semantic is False

    def test_status_reports_provider(self):
        status = HashEmbeddingProvider(dim=32).status()
        assert status["provider"] == "hash"
        assert status["model"] == "hash-32"
        assert status["dim"] == 32


class TestCallableEmbeddingProvider:
    def test_wraps_callable(self):
        provider = CallableEmbeddingProvider(lambda _text: [1.0, 0.0])
        assert provider.embed("anything") == [1.0, 0.0]
        assert provider.dim == 2
        assert provider.is_semantic is True

    def test_non_callable_rejected(self):
        with pytest.raises(TypeError):
            CallableEmbeddingProvider("not-a-callable")

    def test_embedder_exception_is_wrapped(self):
        def boom(_text):
            raise RuntimeError("model exploded")

        with pytest.raises(EmbeddingError, match="model exploded"):
            CallableEmbeddingProvider(boom).embed("x")

    def test_non_numeric_output_rejected(self):
        with pytest.raises(EmbeddingError):
            CallableEmbeddingProvider(lambda _text: ["a", "b"]).embed("x")

    def test_empty_output_rejected(self):
        with pytest.raises(EmbeddingError):
            CallableEmbeddingProvider(lambda _text: []).embed("x")

    def test_non_finite_output_rejected(self):
        with pytest.raises(EmbeddingError, match="non-finite"):
            CallableEmbeddingProvider(lambda _text: [float("nan")]).embed("x")

    def test_inconsistent_dimension_rejected(self):
        provider = CallableEmbeddingProvider(lambda text: [1.0] * (len(text) or 1))
        provider.embed("ab")
        with pytest.raises(EmbeddingError, match="dimension mismatch"):
            provider.embed("abc")

    def test_embed_many(self):
        provider = CallableEmbeddingProvider(lambda text: [float(len(text))])
        assert provider.embed_many(["a", "bb"]) == [[1.0], [2.0]]


class TestOpenAIEmbeddingProvider:
    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(EmbeddingError, match="OPENAI_API_KEY"):
            OpenAIEmbeddingProvider()

    def test_embed_parses_response(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        captured = {}

        def fake_post(url, payload, **kwargs):
            captured["url"] = url
            captured["payload"] = payload
            captured["headers"] = kwargs.get("headers", {})
            return {"data": [{"embedding": [0.1, 0.2, 0.3]}]}

        monkeypatch.setattr("kcp.embeddings._http_post_json", fake_post)
        provider = OpenAIEmbeddingProvider()
        vector = provider.embed("hello")
        assert vector == [0.1, 0.2, 0.3]
        assert provider.dim == 3
        assert captured["url"].endswith("/embeddings")
        assert captured["payload"]["input"] == "hello"
        assert captured["headers"]["Authorization"] == "Bearer test-key"

    def test_malformed_response_raises(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setattr("kcp.embeddings._http_post_json", lambda *a, **k: {"error": "nope"})
        with pytest.raises(EmbeddingError, match="no 'data' array"):
            OpenAIEmbeddingProvider().embed("hello")

    def test_status_never_leaks_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "super-secret-key")
        status = OpenAIEmbeddingProvider().status()
        assert "super-secret-key" not in str(status)
        assert status["semantic"] is True
        assert status["offline"] is False


class TestOllamaEmbeddingProvider:
    def test_embed_parses_api_embeddings(self, monkeypatch):
        monkeypatch.setattr(
            "kcp.embeddings._http_post_json",
            lambda *a, **k: {"embedding": [1.0, 2.0]},
        )
        provider = OllamaEmbeddingProvider(model="nomic-embed-text")
        assert provider.embed("hi") == [1.0, 2.0]
        assert provider.dim == 2

    def test_embed_parses_newer_api_embed_shape(self, monkeypatch):
        monkeypatch.setattr(
            "kcp.embeddings._http_post_json",
            lambda *a, **k: {"embeddings": [[0.5, 0.5]]},
        )
        assert OllamaEmbeddingProvider().embed("hi") == [0.5, 0.5]

    def test_missing_vector_field_raises(self, monkeypatch):
        monkeypatch.setattr("kcp.embeddings._http_post_json", lambda *a, **k: {"model": "x"})
        with pytest.raises(EmbeddingError, match="no 'embedding' field"):
            OllamaEmbeddingProvider().embed("hi")

    def test_error_payload_raises(self, monkeypatch):
        monkeypatch.setattr("kcp.embeddings._http_post_json", lambda *a, **k: {"error": "model not found"})
        with pytest.raises(EmbeddingError, match="model not found"):
            OllamaEmbeddingProvider().embed("hi")

    def test_unreachable_daemon_raises_embedding_error(self):
        # Nothing listens on port 1 — connection is refused immediately.
        provider = OllamaEmbeddingProvider(base_url="http://127.0.0.1:1", timeout=1.0)
        with pytest.raises(EmbeddingError, match="unreachable"):
            provider.embed("hi")

    def test_host_without_scheme_gets_http_prefix(self):
        provider = OllamaEmbeddingProvider(base_url="127.0.0.1:11434")
        assert provider.base_url == "http://127.0.0.1:11434"

    def test_is_semantic_and_not_offline(self):
        provider = OllamaEmbeddingProvider()
        assert provider.is_semantic is True
        assert provider.is_offline is False


class TestResolveEmbeddingProvider:
    def test_none_and_defaults_resolve_to_hash(self):
        assert isinstance(resolve_embedding_provider(None), HashEmbeddingProvider)
        assert isinstance(resolve_embedding_provider("hash"), HashEmbeddingProvider)
        assert isinstance(resolve_embedding_provider(""), HashEmbeddingProvider)

    def test_hash_with_dim(self):
        provider = resolve_embedding_provider("hash:64")
        assert isinstance(provider, HashEmbeddingProvider)
        assert provider.dim == 64

    def test_hash_with_bad_dim_raises(self):
        with pytest.raises(ValueError, match="dim must be an integer"):
            resolve_embedding_provider("hash:abc")

    def test_ollama_specs(self):
        assert resolve_embedding_provider("ollama").model == "nomic-embed-text"
        assert resolve_embedding_provider("ollama:all-minilm").model == "all-minilm"

    def test_openai_specs(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        assert resolve_embedding_provider("openai").model == "text-embedding-3-small"
        assert resolve_embedding_provider("openai:text-embedding-3-large").model == "text-embedding-3-large"
        assert resolve_embedding_provider("text-embedding-3-small").model == "text-embedding-3-small"

    def test_callable_spec(self):
        provider = resolve_embedding_provider(lambda _t: [1.0])
        assert isinstance(provider, CallableEmbeddingProvider)

    def test_existing_provider_passthrough(self):
        original = HashEmbeddingProvider(dim=16)
        assert resolve_embedding_provider(original) is original

    def test_duck_typed_provider_passthrough(self):
        class Custom(BaseEmbeddingProvider):
            name = "duck"
            model = "duck-1"
            dim = 2

            def embed(self, text):
                return [1.0, 0.0]

        provider = resolve_embedding_provider(Custom())
        assert provider.embed("x") == [1.0, 0.0]

    def test_unknown_spec_raises_value_error(self):
        with pytest.raises(ValueError, match="unknown embedding_model"):
            resolve_embedding_provider("banana")

    def test_non_string_spec_raises_value_error(self):
        with pytest.raises(ValueError, match="unsupported embedding_model spec"):
            resolve_embedding_provider(42)
