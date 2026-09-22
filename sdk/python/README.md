# KCP Python SDK

Reference implementation of the Knowledge Context Protocol.

## Install

```bash
pip install kcp-protocol                    # Core (local storage + crypto)
pip install kcp-protocol[server]            # + HTTP server for P2P sharing
pip install kcp-protocol[all]               # Everything
```

## Quick Start

### Embedded Node (no server needed)

```python
from kcp import KCPNode

# Initialize (auto-generates keys, creates SQLite DB)
node = KCPNode(user_id="alice@acme.com", tenant_id="acme-corp")

# Publish a knowledge artifact
artifact = node.publish(
    title="JWT Authentication Best Practices",
    content="## JWT Auth\n\nAlways validate the `exp` claim...",
    format="markdown",
    tags=["security", "jwt", "authentication"],
    summary="Guide for secure JWT implementation",
)
print(f"Published: {artifact.id}")

# Search
results = node.search("authentication")
for r in results.results:
    print(f"  {r.title} ({r.format})")

# Lineage tracking (knowledge derivation)
derived = node.publish(
    title="OAuth2 + JWT Integration",
    content="Building on JWT best practices...",
    format="markdown",
    tags=["security", "oauth2"],
    derived_from=artifact.id,  # Links to parent
)

# View lineage chain
chain = node.lineage(derived.id)
for step in chain:
    print(f"  → {step['title']} by {step['author']}")
```

### HTTP Server (for P2P sharing)

```python
node = KCPNode(user_id="alice@acme.com")
node.serve(port=8800)
# Web UI at http://localhost:8800/ui
# API at http://localhost:8800/kcp/v1/
```

### CLI

```bash
# Initialize
kcp init

# Publish a file
kcp publish --title "My Analysis" --tags "data,ml" report.md

# Search
kcp search "machine learning"

# List artifacts
kcp list

# Show lineage
kcp lineage <artifact-id>

# Start server for P2P
kcp serve --port 8800

# Add a peer and sync
kcp peer add https://colleague.trycloudflare.com
kcp sync https://colleague.trycloudflare.com

# Stats
kcp stats
```

### Semantic & Hybrid Search (opt-in)

By default the SDK is **FTS5/BM25 only** (zero dependencies). Semantic search is
opt-in through `search_backend` + `embedding_model`:

```python
from kcp import KCPNode

# Local vector index + real embeddings from a local Ollama daemon
node = KCPNode(
    user_id="alice@acme.com",
    search_backend="sqlite-vss",              # local vector index (default: "fts5")
    embedding_model="ollama:nomic-embed-text", # or "openai:text-embedding-3-small"
)

node.publish(title="Throttling strategies", content="Token bucket …", tags=["api"])

node.search("rate limiting")                        # keyword (default, unchanged)
node.search("rate limiting", mode="semantic")       # cosine similarity  → finds "Throttling"
node.search("rate limiting", mode="hybrid", alpha=0.5)  # BM25 + cosine (alpha = BM25 weight)
```

Embedding providers:

| `embedding_model` | Network | Semantics | Notes |
|-------------------|---------|-----------|-------|
| `"hash"` (default) | ✗ | ✗ | Deterministic hashing-trick bag-of-words. **Plumbing only** — validates the vector path, index and fusion; it will *not* match synonyms. |
| `"ollama:nomic-embed-text"` | localhost | ✓ | Any model pulled into a local [Ollama](https://ollama.com) daemon. |
| `"openai:text-embedding-3-small"` | HTTPS | ✓ | Needs `OPENAI_API_KEY` in the environment. |
| `callable(text) -> list[float]` | – | ✓ | Inject your own embedder (domain model, test double, …). |

**What is "real semantics" and what is not:** only `ollama`, `openai` and an
injected callable actually model meaning — `rate limiting` can then match
`throttling strategies`. The default `hash` provider is deterministic offline
*plumbing*: it matches lexical overlap through the vector path (useful to test
the pipeline and to run air-gapped), and calling it "semantic search" would be
misleading. `node.semantic_status()` reports `embedding.semantic` so callers can
tell the two apart.

Storage: vectors live in the same SQLite file, in
`kcp_embeddings(artifact_id, model, dim, vector BLOB /* float32 LE */)`, compared
with exact cosine similarity computed in pure Python (no numpy).

`search_backend="sqlite-vss"` (aliases: `sqlite_vss`, `sqlite`, `local`,
`vector`, `auto`) uses the optional native `sqlite-vss` extension when it can be
loaded and passes a round-trip probe; otherwise it **falls back explicitly** to
the pure-Python exact scan and records why in
`node.semantic_status()["index"]["fallback_reason"]` (also logged). It never
degrades silently. Install the extra with `pip install "kcp-protocol[semantic]"`.
Server-side backends proposed in [issue #1](https://github.com/kcp-protocol/kcp/issues/1)
(`qdrant`, `pgvector`, `chroma`) are **not** implemented — they raise
`NotImplementedError` rather than pretending to work.

CLI equivalents:

```bash
kcp search "rate limiting" --mode hybrid --alpha 0.5
KCP_SEARCH_BACKEND=sqlite-vss KCP_EMBEDDING_MODEL=ollama:nomic-embed-text kcp reindex
```

### Corporate Hub

```python
from kcp import KCPNode

# Just set the hub URL — everything routes there transparently
import os
os.environ["KCP_HUB"] = "https://kcp.acme-corp.internal"

node = KCPNode(user_id="alice@acme.com", tenant_id="acme-corp")
node.publish(...)  # Goes to hub, not local storage
```

## Architecture

```
┌────────────────┬───────────────────┬──────────────────────┐
│  🏠 LOCAL       │  🏢 HUB (corp)     │  🌐 FEDERATION       │
│  SQLite local  │  Central server   │  Hub-to-hub sync     │
│  Zero config   │  1 env var        │  Cross-org sharing   │
│  P2P direct    │  SSO/ACL/Audit    │  mTLS + ACL control  │
└────────────────┴───────────────────┴──────────────────────┘
```

## Modules

| Module | Description |
|--------|-------------|
| `kcp.node` | Embedded KCP node (main entry point) |
| `kcp.store` | SQLite storage backend |
| `kcp.embeddings` | Embedding providers (offline `hash`, Ollama, OpenAI, custom callable) |
| `kcp.vector_index` | Local vector index + pure-Python cosine search |
| `kcp.hub` | HTTP client for corporate hubs |
| `kcp.crypto` | Ed25519 signing + SHA-256 hashing |
| `kcp.models` | Data models (KnowledgeArtifact, Lineage, ACL) |
| `kcp.client` | Low-level HTTP client |
| `kcp.cli` | Command-line interface |

## License

MIT — see [LICENSE](../../LICENSE)
