# KCP Roadmap

**Version:** 0.5  
**Updated:** March 2026  
**Author:** Thiago Silva

---

## Vision

KCP becomes the standard protocol for AI-generated knowledge — from personal use to enterprise-wide deployment.

---

## Phase 1: SDK & Core Protocol ✅ COMPLETE (March 2026)

**Goal:** Build the reference implementation and prove the protocol works.

### Completed (227 tests passing across all SDKs)

- [x] Protocol specification (SPEC.md v0.2)
- [x] Architecture design (3 operating modes: local, hub, federation)
- [x] Python SDK — reference implementation (Python 3.13, **216 tests ✅**)
  - [x] Embedded node (in-process, no server needed)
  - [x] Local storage (SQLite + FTS5 + porter stemmer + BM25)
  - [x] Ed25519 signing and verification
  - [x] SHA-256 content hashing
  - [x] AES-256-GCM encryption at rest
  - [x] Full-text search
  - [x] Lineage tracking (derivedFrom chains)
  - [x] Export/Import (offline sharing with signature verification)
  - [x] CLI (init, publish, search, list, lineage, serve, sync, stats)
  - [x] Web dashboard UI (embedded SPA — artifacts, search, publish, peers, sync, replication)
  - [x] HTTP API (FastAPI) for P2P sharing
  - [x] ACL enforcement (public / org / team / private)
  - [x] Hub backend client (for corporate deployments)
  - [x] Sync queue (SQLite-backed, exponential backoff, circuit breaker)
  - [x] Sync worker (background daemon)
  - [x] Hybrid filesystem storage (content_store.py)
  - [x] Peer discovery API (gossip + bootstrap via peers.json)
  - [x] Multi-peer replication factor (kcp_replication table, ACK-based tracking)
- [x] TypeScript SDK — Node.js 25, ESM + CJS + DTS (**37 tests ✅**)
  - [x] KCPNode (publish, get, search, verify, lineage, stats)
  - [x] Ed25519 + SHA-256 via @noble/* (zero native deps)
  - [x] JSON file storage backend
- [x] Go SDK — Go 1.22, SQLite, Ed25519 (**64 tests ✅**)
  - [x] KCPNode (publish, get, search, list, lineage, delete, stats)
  - [x] Ed25519 signing & verification (pkg/crypto)
  - [x] Data models (pkg/models)
  - [x] SQLite storage backend (pkg/store)
  - [x] CLI entrypoint (cmd/kcp)
- [x] MCP Bridge — VS Code / Claude / Cursor integration (**23 tests ✅**)
  - [x] RFC KCP-002 (MCP Bridge Protocol)
  - [x] kcp:// URI scheme
  - [x] MCP session lineage (mcp_session_id, mcp_tool_call)
- [x] **Total: 227 tests passing** across all SDKs + MCP bridge
- [x] RFC KCP-001 (Core Protocol) + RFC KCP-002 (MCP Bridge) + RFC KCP-003 (Sync)
- [x] RFC KCP-004 (Network Deployment Models)
- [x] Whitepaper, executive presentation, use cases
- [x] Landing page (kcp-protocol.org)

---

## Phase 2: Production Infrastructure ✅ COMPLETE (March 2026)

**Goal:** Deploy multiple live nodes, establish peer network, production hardening.

### Completed

- [x] Production server deployment (Linux, multi-instance)
- [x] **8 live peers** — peer01-08 (nginx routing per hostname)
- [x] SSL/TLS — Let's Encrypt certs for all peers
- [x] nginx per-hostname routing with rate limiting (read / sync / write zones)
- [x] Kernel blackhole auto-ban daemon (IP abuse → automatic network-level block)
- [x] X-KCP-Client header enforcement on public endpoints
- [x] Peer discovery API (GET /kcp/v1/peers, gossip, bootstrap via peers.json)
- [x] docs/peers.json — public peer registry served by GitHub Pages
- [x] Multi-peer replication factor (kcp_replication table + /replication route)
- [x] Web dashboard UI (SPA — artifacts, search, publish, peers, sync, replication tabs)
- [x] Traffic reporter daemon (peer health + metrics → HTML report)
- [x] Process manager services for all peers
- [x] Admin portal with Basic Auth (portal.kcp-protocol.org:8099)

---

## Phase 3: Community Network ✅ COMPLETE (March 2026)

**Goal:** Enable the community to run its own peers with one-click deploy guides.

### Network Models

KCP defines four deployment modes (RFC KCP-004):

| Mode | Who operates | Who pays | Public network? |
|------|-------------|----------|-----------------|
| **Local** | Individual developer | Nobody (local disk) | No |
| **Private Hub** | Organization (IT/DevOps) | The organization | No |
| **Community Peer** | Volunteer operator | The operator | Yes |
| **Federated Mesh** | Multiple orgs / peers | Each participant | Optional |

### Completed

- [x] One-click deploy guide — Docker Compose ([deploy-docker.md](deploy-docker.md))
- [x] DigitalOcean step-by-step guide ([deploy-digitalocean.md](deploy-digitalocean.md))
- [x] Operator documentation (hardware requirements, config reference)
- [x] `peers.json` submission process (GitHub PR + automated health check CI)
- [x] Automatic peer health monitoring (GitHub Actions — PR check + daily cron)
- [x] Artifact seeding — ~8.000 artifacts across 8 peers (public + org + private mix)
- [x] Docker image + docker-compose.yml for community operators
- [x] Static status page (cron VPS → GitHub Pages)

### What the KCP project does NOT do

- Pay for community-operated nodes — operators fund their own infrastructure
- Build a hosting platform — the protocol is MIT-licensed, others can build that

---

## Phase 4: Ecosystem & Adoption 🔜 TARGET: May 2026

**Goal:** Make KCP easy to adopt — PyPI/npm packages, GitHub Action, OpenAPI spec, live network status.

### Tasks

- [ ] **PyPI package** (`pip install kcp`) — automated publish on release
- [ ] **npm package** (`npm install @kcp/client`) — automated publish on release
- [ ] **OpenAPI spec** (docs/openapi.yaml) — full HTTP API documentation
- [ ] **GitHub Action** — publish artifacts from CI/CD workflows
- [ ] **Live network status API** — real-time peer health via CORS-enabled endpoint
- [ ] **VS Code extension** — KCP explorer sidebar
- [ ] **Helm chart** — Kubernetes deployment

### Deferred to v1.0 (Long-term Vision)

- **IPFS backend** — content-addressed storage (CID-based)
- **Federation** — hub-to-hub sync with mTLS
- **Semantic search** — vector embeddings + cosine similarity
- **Corporate Hub** — SSO, multi-tenant, audit log, PostgreSQL
- **Auto-tagging** — LLM-based classification
- **Knowledge graph visualization**
- **Artifact versioning** — update in place with history

---

## Priority Matrix

| Feature | Impact | Effort | Priority | Target |
|---------|--------|--------|----------|--------|
| PyPI / npm packages | High | Low | **P0** | Phase 4 |
| OpenAPI spec | High | Low | **P0** | Phase 4 |
| GitHub Action | High | Medium | **P1** | Phase 4 |
| Live network status | Medium | Low | **P1** | Phase 4 |
| VS Code extension | Medium | Medium | **P2** | Phase 4 |
| Corporate Hub | High | High | **P2** | v1.0 |
| Semantic search | Low | High | **P3** | v1.0 |
| IPFS backend | Medium | High | **P3** | v1.0 |
| Federation | Medium | High | **P3** | v1.0 |

---

**This roadmap is updated as priorities evolve.**
