# ⚛ KCP — Knowledge Context Protocol

**A new architectural layer for AI-generated knowledge governance.**

KCP proposes "Layer 8" above the OSI Application Layer — a standard for publishing, discovering, verifying, and tracking the lineage of knowledge artifacts produced by AI agents.

> 🌐 [Leia em Português](README.pt-br.md)

---

## The Problem

AI agents generate valuable knowledge every day — analyses, reports, decisions, code reviews. But this knowledge:

- **Dies in chat sessions** — no persistence, no discovery
- **Has no provenance** — who created it? from what data? is it trustworthy?
- **Can't be shared** — locked in proprietary formats and platforms
- **Has no lineage** — when knowledge builds on other knowledge, there's no trail

## The Solution

KCP defines a protocol for **knowledge artifacts** — signed, content-addressed, discoverable units of AI-generated knowledge with full lineage tracking.

```
┌────────────────────────────────────────────────────────┐
│  Layer 8: Knowledge & Context (KCP)                    │
│  Governance · Persistence · Discovery · Lineage        │
├────────────────────────────────────────────────────────┤
│  Layer 7: Application (HTTP, DNS, FTP)                 │
├────────────────────────────────────────────────────────┤
│  Layers 1-6: Transport, Network, etc.                  │
└────────────────────────────────────────────────────────┘
```

## Key Features

1. **Signed artifacts** — Every knowledge artifact is signed with Ed25519 for authenticity
2. **Content-addressed** — SHA-256 hashing ensures integrity
3. **Lineage tracking** — `derivedFrom` chains show how knowledge evolves
4. **Three operating modes** — Local (SQLite), Corporate Hub, Federated (P2P)
5. **Zero infrastructure** — Works locally with no server, no config, no accounts
6. **Transparent to users** — AI assistant skills abstract all complexity

## Quick Start

### Install

```bash
pip install kcp              # Core
pip install kcp[server]      # + HTTP server for P2P
```

### Use as library (no server)

```python
from kcp import KCPNode

node = KCPNode(user_id="alice@example.com")

# Publish knowledge
artifact = node.publish(
    title="Rate Limiting Strategies",
    content="## Token Bucket\n\nThe most common approach...",
    format="markdown",
    tags=["architecture", "rate-limiting"],
)

# Search
results = node.search("rate limiting")

# Track lineage
derived = node.publish(
    title="Rate Limiting in gRPC",
    content="Building on general strategies...",
    derived_from=artifact.id,
)
```

### CLI

```bash
kcp init
kcp publish --title "My Analysis" report.md
kcp search "authentication"
kcp serve --port 8800          # Web UI + P2P
kcp peer add https://peer.trycloudflare.com
kcp sync https://peer.trycloudflare.com
```

### Web UI

Start the server and open `http://localhost:8800/ui`:

```bash
kcp serve
```

## Operating Modes

| Mode | For | Storage | Config |
|------|-----|---------|--------|
| 🏠 **Local** | Individual users | SQLite (`~/.kcp/kcp.db`) | None (zero config) |
| 🏢 **Hub** | Organizations | PostgreSQL + S3 | `KCP_HUB=url` |
| 🌐 **Federation** | Cross-org sharing | Hub-to-hub sync | Hub config |

All modes use the **same API**. The backend is transparent to the user.

## Documentation

| Document | Description |
|----------|-------------|
| [SPEC.md](SPEC.md) | Full protocol specification |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Architecture, storage, P2P, security |
| [AI_AGENT_GUIDE.md](AI_AGENT_GUIDE.md) | Integration guide for AI agents (LLMs, Copilot, Claude) |
| [llms.txt](llms.txt) | LLM indexing manifest ([llmstxt.org](https://llmstxt.org/) convention) |
| [RFC-001-CORE.md](RFC-001-CORE.md) | Formal RFC (root) |
| [RFC KCP-001](rfcs/kcp-001-core.md) | Formal RFC (detailed) |
| [Whitepaper](docs/whitepaper.md) | Academic paper |
| [Comparison](docs/comparison.md) | vs Semantic Web, MCP, etc. |
| [Use Cases](docs/use-cases.md) | 10 real-world use cases |
| [Roadmap](docs/roadmap.md) | 6-phase development plan |
| [Presentation](docs/presentation.html) | Executive presentation (PT-BR) |
| [Python SDK](sdk/python/README.md) | Python SDK documentation |
| [Go SDK](sdk/go/README.md) | Go SDK documentation |
| [TypeScript SDK](sdk/typescript/README.md) | TypeScript SDK documentation |
| [Testing Guide](docs/testing.md) | Running & writing tests for all SDKs |
| [Contributing](CONTRIBUTING.md) | Contribution guidelines |

## Project Structure

```
kcp/
├── SPEC.md                    # Protocol specification
├── ARCHITECTURE.md            # Architecture & design
├── AI_AGENT_GUIDE.md          # Integration guide for AI agents & LLMs
├── llms.txt                   # LLM indexing manifest (llmstxt.org)
├── RFC-001-CORE.md            # Formal RFC (root)
├── GENESIS.json               # Protocol genesis block
├── KCP_MANIFEST.json          # Protocol manifest
├── sdk/
│   ├── python/                # Python SDK (reference implementation)
│   │   ├── kcp/
│   │   │   ├── node.py        # Embedded KCP node
│   │   │   ├── store.py       # SQLite storage backend
│   │   │   ├── hub.py         # Corporate hub client
│   │   │   ├── crypto.py      # Ed25519 + SHA-256
│   │   │   ├── models.py      # Data models
│   │   │   ├── client.py      # HTTP client
│   │   │   ├── cli.py         # CLI interface
│   │   │   └── ui/
│   │   │       └── index.html # Web UI (single-file)
│   │   └── pyproject.toml
│   ├── go/                    # Go SDK (implemented)
│   │   ├── cmd/kcp/main.go    # CLI entrypoint
│   │   ├── pkg/crypto/        # Crypto (Ed25519 + SHA-256)
│   │   ├── pkg/models/        # Data models
│   │   ├── pkg/node/          # Embedded KCP node
│   │   ├── pkg/store/         # SQLite storage backend
│   │   └── go.mod
│   └── typescript/            # TypeScript SDK (implemented)
│       ├── src/
│       │   ├── models.ts      # Data models
│       │   ├── crypto.ts      # Ed25519 + SHA-256
│       │   ├── store.ts       # JSON file storage backend
│       │   ├── node.ts        # KCPNode — main API
│       │   └── index.ts       # Barrel exports
│       ├── tests/
│       │   └── kcp.test.ts    # Jest test suite
│       └── package.json
├── rfcs/                      # Formal RFCs
├── poc/                       # Proof of concept
│   └── kcp_core.py
├── docs/                      # Documentation
│   ├── whitepaper.md
│   ├── comparison.md
│   ├── use-cases.md
│   ├── roadmap.md
│   └── presentation.html      # Executive presentation (PT-BR)
└── examples/                  # Example payloads
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). All contributions welcome — code, docs, use cases, translations.

## License

[MIT](LICENSE)

---

**Author:** [Thiago Silva](https://github.com/tgosoul2019)  
**Status:** Alpha — protocol and SDK under active development  
**Feedback:** [Open an issue](https://github.com/tgosoul2019/kcp/issues)
