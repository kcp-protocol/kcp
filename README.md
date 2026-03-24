<p align="center">
  <img src="docs/assets/kcp-logo-horizontal.svg" alt="KCP — Knowledge Context Protocol" width="280"/>
</p>

# KCP — Knowledge Context Protocol

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

## SDK Status

| SDK | Language | Tests | Status |
|-----|----------|-------|--------|
| Python | Python 3.13 · pytest | ✅ **216 tests** | Production-ready |
| TypeScript | Node.js 25 · Jest | ✅ **37 tests** | Production-ready |
| Go | Go 1.22 · go test | ✅ **64 tests** | Production-ready |
| **MCP Bridge** | Python · pytest-asyncio | ✅ **23 tests** | Production-ready |
| **Total** | | ✅ **227 tests** | All passing |

## Public Peer Network

KCP peers are open nodes anyone can sync with. No account needed.

| Peer | URL | Status | Region |
|------|-----|--------|--------|
| peer01 | `https://peer01.kcp-protocol.org` | ✅ Live | South America |
| peer02 | `https://peer02.kcp-protocol.org` | ✅ Live | South America |
| peer03 | `https://peer03.kcp-protocol.org` | ✅ Live | South America |
| peer04 | `https://peer04.kcp-protocol.org` | ✅ Live | South America |
| peer05 | `https://peer05.kcp-protocol.org` | ✅ Live | South America |
| peer06 | `https://peer06.kcp-protocol.org` | ✅ Live | South America |
| peer07 | `https://peer07.kcp-protocol.org` | ✅ Live | South America |
| peer08 | `https://peer08.kcp-protocol.org` | ✅ Live | South America |

> **~8.000 artifacts** seeded across the network. See live status at [kcp-protocol.org/status.html](https://kcp-protocol.org/status.html)

```bash
# Check peer health
curl https://peer01.kcp-protocol.org/kcp/v1/health

# Add peer and sync
kcp peer add https://peer01.kcp-protocol.org
kcp sync https://peer01.kcp-protocol.org --pull
```

> **Security:** Public peers require the `X-KCP-Client` header on sync operations.
> The KCP SDK sends this automatically. Rate limits: 20 req/s (read), 10 req/s (write), 5 req/s (sync).

## Quick Start

### Install

```bash
# Install from source (PyPI package coming soon)
git clone https://github.com/kcp-protocol/kcp
cd kcp && make setup-python
```

### Try it now (interactive demos)

```bash
git clone https://github.com/kcp-protocol/kcp
cd kcp
make setup-python            # create venv + install deps

# Demo 1 — cross-session: publish in one process, read in another
make demo                    # Session 1: publish 3 artifacts
make demo-read               # Session 2: NEW process reads, searches, verifies signatures

# Demo 2 — MCP tools: all 6 MCP tools working standalone (no editor needed)
make demo-mcp

# Demo 3 — peer sync: two nodes exchange knowledge over HTTP
make peer-demo

# Demo 4 — connect to your editor (Claude Desktop, Cursor, Windsurf)
make setup-mcp-claude        # auto-configures Claude Desktop
make setup-mcp-cursor        # auto-configures Cursor
make setup-mcp-windsurf      # auto-configures Windsurf
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
| [RFC KCP-002](rfcs/kcp-002-mcp-bridge.md) | KCP ↔ MCP Bridge — persistent artifacts as MCP context |
| [MCP Server](mcp-server/README.md) | KCP MCP Server — Claude Desktop / Cursor / Windsurf integration |
| [Whitepaper](docs/whitepaper.md) | Academic paper |
| [Comparison](docs/comparison.md) | vs Semantic Web, MCP, etc. |
| [Use Cases](docs/use-cases.md) | 10 real-world use cases |
| [Roadmap](docs/roadmap.md) | 4-phase development plan |
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
├── demo.py                    # Cross-session demo (make demo + make demo-read)
├── demo_mcp.py                # MCP tools demo — 6 tools standalone (make demo-mcp)
├── Makefile                   # All tasks: test, demo, setup-mcp-*
├── sdk/
│   ├── python/                # Python SDK (reference implementation)
│   ├── go/                    # Go SDK (Go 1.22, 64 tests ✅)
│   └── typescript/            # TypeScript SDK (37 tests ✅)
├── mcp-server/                # MCP Bridge (23 tests ✅)
│   ├── kcp_mcp_server/
│   │   └── server.py          # 6 MCP tools: publish, search, get, lineage, list, stats
│   ├── setup_mcp.py           # Auto-configure Claude Desktop / Cursor / Windsurf
│   └── tests/                 # 23 async tests
├── rfcs/                      # Formal RFCs (KCP-001, KCP-002)
├── docs/                      # Documentation + landing page
│   ├── index.html             # Landing page (kcp-protocol.org)
│   ├── assets/                # Logo SVGs + social card
│   └── *.md                   # Whitepaper, comparison, use-cases, roadmap
└── examples/                  # Example payloads
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). All contributions welcome — code, docs, use cases, translations.

## License

[MIT](LICENSE)

---

**Author:** [Thiago Silva](https://github.com/tgosoul2019)  
**Status:** Beta — protocol stable, ecosystem expanding  
**Feedback:** [Open an issue](https://github.com/kcp-protocol/kcp/issues)
