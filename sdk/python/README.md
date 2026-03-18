# KCP Python SDK

Reference implementation of the Knowledge Context Protocol.

## Install

```bash
pip install kcp                    # Core (local storage + crypto)
pip install kcp[server]            # + HTTP server for P2P sharing
pip install kcp[all]               # Everything
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
| `kcp.hub` | HTTP client for corporate hubs |
| `kcp.crypto` | Ed25519 signing + SHA-256 hashing |
| `kcp.models` | Data models (KnowledgeArtifact, Lineage, ACL) |
| `kcp.client` | Low-level HTTP client |
| `kcp.cli` | Command-line interface |

## License

MIT — see [LICENSE](../../LICENSE)
