# KCP Python SDK

Reference implementation of the Knowledge Context Protocol client.

## Status: Alpha (v0.1.0)

Core models, crypto (Ed25519 signing), and client are implemented.
Server-side (KCP Node) is planned for Phase 2.

## Installation

```bash
# Basic (models only, no dependencies)
pip install -e .

# With crypto support (Ed25519 signatures)
pip install -e ".[crypto]"

# With HTTP support (connect to KCP nodes)
pip install -e ".[http]"

# Everything
pip install -e ".[all]"
```

## Quick Start

```python
from kcp import KCPClient, Lineage
from kcp.crypto import generate_keypair

# Generate keypair (one-time)
private_key, public_key = generate_keypair()

# Initialize client
client = KCPClient(
    node_url="http://localhost:8080",
    tenant_id="acme-corp",
    user_id="alice@example.com",
    private_key=private_key,
    team="data-science"
)

# Publish a report
artifact = client.publish(
    title="Q1 Customer Churn Analysis",
    content=open("report.html", "rb").read(),
    format="html",
    tags=["churn", "analytics", "ml"],
    visibility="team",
    summary="Predictive model with 87% accuracy",
    lineage=Lineage(
        query="Predict customer churn using 12 months of history",
        data_sources=["postgres://analytics/customers"],
        agent="jupyter-agent-v1.2.3"
    )
)

print(f"Published: {artifact.id}")
print(f"Hash: {artifact.content_hash}")

# Search for reports
results = client.search(
    query="customer retention",
    tags=["analytics"],
    limit=10
)

for r in results.results:
    print(f"  [{r.relevance:.0%}] {r.title}")
```

## Crypto Operations

```python
from kcp.crypto import generate_keypair, sign_artifact, verify_artifact, hash_content

# Generate Ed25519 keypair
private_key, public_key = generate_keypair()

# Hash content
content_hash = hash_content(b"Hello, KCP!")

# Sign an artifact payload
payload = {"id": "...", "title": "...", "tenant_id": "..."}
signature = sign_artifact(payload, private_key)

# Verify signature
payload["signature"] = signature
is_valid = verify_artifact(payload, public_key)
```

## Project Structure

```
sdk/python/
├── kcp/
│   ├── __init__.py    # Package exports
│   ├── models.py      # KnowledgeArtifact, Lineage, ACL, SearchResult
│   ├── crypto.py      # Ed25519 signing, SHA-256 hashing
│   └── client.py      # KCPClient (HTTP client for KCP nodes)
├── pyproject.toml     # Package config
└── README.md          # This file
```

## Dependencies

| Package | Required For | Install Extra |
|---------|-------------|---------------|
| — | Models, basic usage | (none) |
| `cryptography` | Ed25519 signing | `pip install kcp[crypto]` |
| `httpx` | HTTP client | `pip install kcp[http]` |
