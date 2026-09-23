"""
KCP Embedding Providers

Pluggable embedding generation for semantic search (see issue #1).

Two very different things live behind the same interface — read this before
trusting a result:

* **Real semantics** — providers ``ollama`` and ``openai`` call a real embedding
  model. Vectors carry meaning: "rate limiting" can match "throttling
  strategies". These providers need a network service (local Ollama daemon or
  the OpenAI API) and are therefore **optional**.
* **Deterministic plumbing** — the default provider ``hash`` is an offline
  hashing-trick bag-of-words vectorizer. It is fully deterministic, has zero
  dependencies and zero network access, and is what the test-suite uses to
  exercise the search *plumbing* end-to-end. It has **no semantic knowledge**:
  it only matches lexical overlap (like FTS5, but through the vector path).
  Never claim "semantic search" for a node that uses it.

A caller can also inject any ``callable(text) -> list[float]`` (e.g. a
dictionary/synonym embedder) through ``CallableEmbeddingProvider`` — that is how
tests demonstrate *real* semantic behaviour without a network service.

Design rules:

* No mandatory third-party dependency. HTTP providers use ``urllib`` only, so
  the core SDK bootstrap stays zero-dep.
* Failures are never silent: providers raise :class:`EmbeddingError` with the
  endpoint/HTTP status, never falling back to a different provider behind the
  caller's back.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any

logger = logging.getLogger("kcp.embeddings")

__all__ = [
    "DEFAULT_TIMEOUT",
    "BaseEmbeddingProvider",
    "CallableEmbeddingProvider",
    "EmbeddingError",
    "HashEmbeddingProvider",
    "OllamaEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "SemanticSearchUnavailableError",
    "cosine_similarity",
    "l2_normalize",
    "resolve_embedding_provider",
    "tokenize",
]

#: Default HTTP timeout (seconds) for remote embedding providers.
DEFAULT_TIMEOUT = 10.0

_WORD_RE = re.compile(r"[a-z0-9_]+")


class EmbeddingError(RuntimeError):
    """Raised when an embedding provider cannot produce a vector.

    Covers missing credentials, unreachable endpoints, HTTP errors, malformed
    responses and dimension mismatches. Always carries an actionable message.
    """


class SemanticSearchUnavailableError(RuntimeError):
    """Raised when ``mode='semantic'|'hybrid'`` is used without a vector backend.

    The default ``KCPNode`` uses FTS5 only (zero dependencies). Semantic search
    is opt-in — construct the node with ``search_backend="sqlite-vss"`` (or pass
    an ``embedding_model``/``embedder``) to enable it.
    """


# ─── Vector helpers (pure Python, no numpy) ────────────────────


def tokenize(text: str) -> list[str]:
    """Lowercase word tokenizer shared by the offline provider."""
    if not text:
        return []
    return _WORD_RE.findall(text.lower())


def _is_zero_norm(value: float) -> bool:
    """True when a norm (or a sum of squares) is zero.

    Norms are never negative, so ``math.isclose(value, 0.0)`` with the default
    relative tolerance is exact here — it only avoids comparing floats with
    ``==``.
    """
    return math.isclose(value, 0.0)


def l2_normalize(vector: Sequence[float]) -> list[float]:
    """Return ``vector`` scaled to unit L2 norm (zero vectors are returned as-is)."""
    values = [float(v) for v in vector]
    norm = math.sqrt(sum(v * v for v in values))
    if _is_zero_norm(norm):
        return values
    return [v / norm for v in values]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity between two equal-length vectors (pure Python)."""
    if len(a) != len(b):
        raise ValueError(f"dimension mismatch: {len(a)} != {len(b)}")
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    if _is_zero_norm(na) or _is_zero_norm(nb):
        return 0.0
    return dot / math.sqrt(na * nb)


def _validate_vector(raw: Any, provider: str, *, expected_dim: int | None = None) -> list[float]:
    """Coerce a provider response into a finite ``list[float]`` or raise."""
    if raw is None:
        raise EmbeddingError(f"{provider}: empty embedding returned")
    try:
        values = [float(v) for v in raw]
    except (TypeError, ValueError) as exc:
        raise EmbeddingError(f"{provider}: embedding is not a sequence of numbers ({exc})") from exc
    if not values:
        raise EmbeddingError(f"{provider}: empty embedding returned")
    for v in values:
        if math.isnan(v) or math.isinf(v):
            raise EmbeddingError(f"{provider}: embedding contains non-finite values")
    if expected_dim is not None and len(values) != expected_dim:
        raise EmbeddingError(
            f"{provider}: dimension mismatch — got {len(values)}, expected {expected_dim}. "
            "Query and stored vectors must come from the same embedding model."
        )
    return values


def _http_post_json(
    url: str,
    payload: dict,
    *,
    headers: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    provider: str = "provider",
) -> dict:
    """POST JSON and decode a JSON response, raising :class:`EmbeddingError` on failure."""
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310  # nosec B310 — url comes from a provider config (http/https only), never from artifact content
        url,
        data=body,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310  # nosec B310
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "ignore")[:200]
        except Exception:  # pragma: no cover — best-effort error body
            detail = ""
        raise EmbeddingError(f"{provider}: {url} returned HTTP {exc.code}{f' — {detail}' if detail else ''}") from exc
    except Exception as exc:  # urllib.error.URLError, TimeoutError, socket errors…
        raise EmbeddingError(f"{provider}: {url} unreachable — {exc}") from exc

    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise EmbeddingError(f"{provider}: {url} returned invalid JSON — {exc}") from exc
    if not isinstance(data, dict):
        raise EmbeddingError(f"{provider}: {url} returned unexpected payload type {type(data).__name__}")
    return data


# ─── Providers ─────────────────────────────────────────────────


class BaseEmbeddingProvider:
    """Common interface for embedding providers.

    Subclasses implement :meth:`embed`; ``embed_many`` and :meth:`status` are
    provided here. ``dim`` may be unknown (``None``) until the first vector is
    produced, which is the case for HTTP providers.
    """

    name = "base"
    model = "unknown"
    dim: int | None = None

    def embed(self, text: str) -> list[float]:  # pragma: no cover — abstract
        raise NotImplementedError

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed several texts. Overridden by remote providers that batch."""
        return [self.embed(t) for t in texts]

    def status(self) -> dict:
        """Sanitized description — never contains credentials."""
        return {
            "provider": self.name,
            "model": self.model,
            "dim": self.dim,
            "semantic": self.is_semantic,
            "offline": self.is_offline,
        }

    @property
    def is_semantic(self) -> bool:
        """True only for providers backed by a real embedding model."""
        return False

    @property
    def is_offline(self) -> bool:
        """True when the provider performs no network access."""
        return True


class HashEmbeddingProvider(BaseEmbeddingProvider):
    """Deterministic, offline, zero-dependency *plumbing* embedder (default).

    Hashing trick over lowercased word tokens: each token is hashed (SHA-256,
    salted) into a fixed number of buckets with a deterministic sign, counts are
    accumulated and the vector is L2-normalized.

    Properties: fully offline, reproducible across processes and languages, and
    useful to exercise the vector index, fusion and storage paths.

    **Limitations:** no semantics whatsoever. Synonyms, morphology and
    paraphrases are invisible to it — ``rate limiting`` will *not* match
    ``throttling``. Use ``ollama``/``openai`` (or an injected callable) for real
    semantic search.
    """

    name = "hash"

    def __init__(self, dim: int = 256, model: str | None = None):
        if dim < 8:
            raise ValueError("dim must be >= 8")
        self.dim = int(dim)
        self.model = model or f"hash-{self.dim}"
        self._salt = b"kcp-hash-embedding-v1"

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in tokenize(text):
            digest = hashlib.sha256(self._salt + token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign * (1.0 + math.log1p(digest[5] / 255.0))
        return l2_normalize(vector)


class OllamaEmbeddingProvider(BaseEmbeddingProvider):
    """Embeddings from a local `Ollama <https://ollama.com>`_ daemon (optional).

    Requires the daemon to be running (default ``http://localhost:11434``) and
    the model to be pulled (e.g. ``ollama pull nomic-embed-text``). Speaks HTTP
    over ``urllib``; no third-party client is required.
    """

    name = "ollama"
    is_offline = False

    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        dim: int | None = None,
    ):
        raw_url = base_url or os.environ.get("OLLAMA_HOST") or "http://localhost:11434"
        if not raw_url.startswith(("http://", "https://")):
            # Ollama runs as a loopback daemon by design; callers behind a TLS
            # proxy pass a base_url that already starts with https://.
            raw_url = f"http://{raw_url}"  # NOSONAR — local loopback endpoint, not user input
        self.base_url = raw_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.dim = dim

    @property
    def is_semantic(self) -> bool:
        return True

    def embed(self, text: str) -> list[float]:
        data = _http_post_json(
            f"{self.base_url}/api/embeddings",
            {"model": self.model, "prompt": text},
            timeout=self.timeout,
            provider=f"ollama({self.model})",
        )
        if "embedding" not in data and "error" in data:
            raise EmbeddingError(f"ollama({self.model}): {data['error']}")
        vector = data.get("embedding")
        if not vector:
            # Newer /api/embed shape: {"embeddings": [[...]]}
            embeddings = data.get("embeddings")
            if isinstance(embeddings, list) and embeddings:
                vector = embeddings[0]
        if not vector:
            raise EmbeddingError(
                f"ollama({self.model}): response has no 'embedding' field — "
                f"is the model pulled? (ollama pull {self.model})"
            )
        values = _validate_vector(vector, f"ollama({self.model})", expected_dim=self.dim)
        self.dim = len(values)
        return values


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """Embeddings from the OpenAI API (optional).

    Requires ``OPENAI_API_KEY`` in the environment (or the ``api_key`` argument).
    The key is never logged and never included in :meth:`status`.
    """

    name = "openai"
    is_offline = False

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        dim: int | None = None,
    ):
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise EmbeddingError(
                "openai: OPENAI_API_KEY is not set. Export it, pass api_key=…, "
                "or use the offline default embedder ('hash')."
            )
        self._api_key = key
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.model = model
        self.timeout = timeout
        self.dim = dim

    @property
    def is_semantic(self) -> bool:
        return True

    def embed(self, text: str) -> list[float]:
        data = _http_post_json(
            f"{self.base_url}/embeddings",
            {"model": self.model, "input": text},
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=self.timeout,
            provider=f"openai({self.model})",
        )
        items = data.get("data")
        if not isinstance(items, list) or not items:
            raise EmbeddingError(f"openai({self.model}): response has no 'data' array")
        values = _validate_vector(items[0].get("embedding"), f"openai({self.model})", expected_dim=self.dim)
        self.dim = len(values)
        return values


class CallableEmbeddingProvider(BaseEmbeddingProvider):
    """Wrap a user-supplied ``callable(text) -> list[float]`` as a provider.

    This is the injection point for domain-specific embedders (e.g. a
    dictionary/synonym embedder) and for tests that need *real* semantic
    behaviour without a network service. The callable's output is validated:
    non-numeric, empty, non-finite or dimension-inconsistent vectors raise
    :class:`EmbeddingError`.
    """

    name = "custom"

    def __init__(self, fn: Callable[[str], Sequence[float]], model: str = "custom", dim: int | None = None):
        if not callable(fn):
            raise TypeError("fn must be callable: (text: str) -> Sequence[float]")
        self._fn = fn
        self.model = model
        self.dim = dim

    @property
    def is_semantic(self) -> bool:
        """The wrapped callable is assumed to model real similarity."""
        return True

    def embed(self, text: str) -> list[float]:
        try:
            raw = self._fn(text)
        except Exception as exc:
            if isinstance(exc, EmbeddingError):
                raise  # the embedder already speaks KCP's error type — propagate as-is
            raise EmbeddingError(f"custom embedder failed: {exc}") from exc
        values = _validate_vector(raw, f"custom({self.model})", expected_dim=self.dim)
        self.dim = len(values)
        return values


# ─── Resolution ────────────────────────────────────────────────

#: Prefixes resolved to the OpenAI provider (model names imply the provider).
_OPENAI_MODEL_PREFIXES = ("text-embedding-", "openai:")


def _hash_provider_from_spec(raw: str) -> HashEmbeddingProvider:
    """Build the hashing-trick provider from a ``hash:DIM`` spec.

    Any ``ValueError`` from the dim parsing *or* from the provider constructor
    (``dim < 8``) is reported as an invalid spec.
    """
    try:
        return HashEmbeddingProvider(dim=int(raw.split(":", 1)[1]))
    except ValueError as exc:
        raise ValueError(f"invalid hash embedding model {raw!r}: dim must be an integer") from exc


def resolve_embedding_provider(spec: Any = None, *, dim: int | None = None) -> BaseEmbeddingProvider:
    """Build an embedding provider from a spec.

    Accepted specs:

    * ``None`` / ``"hash"`` → :class:`HashEmbeddingProvider` (offline default)
    * ``"hash:512"`` → hashing-trick embedder with 512 buckets
    * ``"ollama[:MODEL]"`` → local Ollama daemon (e.g. ``ollama:nomic-embed-text``)
    * ``"openai[:MODEL]"`` / ``"text-embedding-3-small"`` → OpenAI API
    * a callable → :class:`CallableEmbeddingProvider`
    * any object exposing ``embed()`` → returned unchanged

    Raises :class:`EmbeddingError` for missing credentials and ``ValueError`` for
    unknown specs.
    """
    if spec is None:
        return HashEmbeddingProvider(dim=dim or 256)
    if isinstance(spec, BaseEmbeddingProvider):
        return spec
    if callable(spec) and not isinstance(spec, str):
        return CallableEmbeddingProvider(spec, dim=dim)
    if hasattr(spec, "embed") and callable(spec.embed):
        return spec  # duck-typed provider (already built by the caller)
    if not isinstance(spec, str):
        raise ValueError(
            f"unsupported embedding_model spec {spec!r}: expected a string, a callable or a provider object"
        )

    raw = spec.strip()
    lowered = raw.lower()

    if lowered in ("", "none", "hash", "default"):
        return HashEmbeddingProvider(dim=dim or 256)
    if lowered.startswith("hash:"):
        return _hash_provider_from_spec(raw)
    if lowered.startswith("ollama"):
        model = _split_model(raw, default="nomic-embed-text")
        return OllamaEmbeddingProvider(model=model, dim=dim)
    if lowered.startswith("openai") or lowered.startswith(_OPENAI_MODEL_PREFIXES):
        model = _split_model(raw, default="text-embedding-3-small")
        return OpenAIEmbeddingProvider(model=model, dim=dim)

    raise ValueError(
        f"unknown embedding_model {spec!r}. Supported: 'hash[:DIM]', 'ollama[:MODEL]', "
        "'openai[:MODEL]', a callable(text)->list[float], or a provider object with .embed()."
    )


def _split_model(raw: str, *, default: str) -> str:
    """Extract ``model`` from ``provider:model`` (``"openai"`` → default)."""
    if ":" in raw:
        _, _, model = raw.partition(":")
        model = model.strip()
        return model or default
    return default
