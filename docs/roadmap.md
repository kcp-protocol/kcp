# KCP Roadmap

**Version:** 0.4  
**Updated:** June 2026  
**Author:** Thiago Silva

---

## Vision

KCP becomes the standard protocol for AI-generated knowledge — from personal use to enterprise-wide deployment.

---

## Current State (v0.4 — June 2026) ✅

### Completed (227 tests passing across all SDKs)

- [x] Protocol specification (SPEC.md)
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
  - [x] **Multi-peer replication factor** (kcp_replication table, ACK-based tracking, `complete` flag)
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
- [x] Whitepaper, executive presentation, use cases
- [x] Landing page (kcp-protocol.org) — ROI section, live peer widget

---

## Phase 2: Production Infrastructure ✅ COMPLETE (June 2026)

**Goal:** Deploy multiple live nodes, establish peer network, production hardening.

### Completed

- [x] Production server deployment (Linux, multi-instance)
- [x] **3 live peers** — peer04, peer05, peer07 (same host, nginx routing per hostname)
- [x] SSL/TLS — Let's Encrypt wildcard cert (peer04/05/07.kcp-protocol.org)
- [x] nginx per-hostname routing with rate limiting (read / sync / write zones)
- [x] Kernel blackhole auto-ban daemon (IP abuse → automatic network-level block)
- [x] X-KCP-Client header enforcement on public endpoints
- [x] Peer discovery API (GET /kcp/v1/peers/discover, gossip, bootstrap via peers.json)
- [x] docs/peers.json — public peer registry served by GitHub Pages
- [x] Multi-peer replication factor (kcp_replication table + /replication route + tests)
- [x] Web dashboard UI (SPA — artifacts, search, publish, peers, sync, replication tabs)
- [x] Traffic reporter daemon (peer health + metrics → HTML report)
- [x] Process manager services for all peers

---

## Phase 3: Community Network & One-Click Deploy (v0.5) ✅ COMPLETE (March 2026)

**Goal:** Enable the community to run its own peers. The KCP project runs reference
nodes during the proof-of-concept phase, but the long-term model is a **voluntary
mesh where each operator funds their own node** — exactly like how the web works.

See [RFC KCP-004 — Network Deployment Models](../rfcs/kcp-004-network-models.md)
for the full network sustainability strategy.

### Network Models

KCP defines four deployment modes (RFC KCP-004):

| Mode | Who operates | Who pays | Public network? |
|------|-------------|----------|-----------------|
| **Local** | Individual developer | Nobody (local disk) | No |
| **Private Hub** | Organization (IT/DevOps) | The organization | No |
| **Community Peer** | Volunteer operator | The operator | Yes |
| **Federated Mesh** | Multiple orgs / peers | Each participant | Optional |

### Phase 3 Tasks — Lower the barrier for community operators

- [x] One-click deploy guide — Docker Compose ([deploy-docker.md](deploy-docker.md))
- [x] DigitalOcean step-by-step guide ([deploy-digitalocean.md](deploy-digitalocean.md))
- [x] Operator documentation (hardware requirements, config reference, ToS)
- [x] `peers.json` submission process (GitHub PR + automated health check CI)
- [x] Automatic peer health monitoring (GitHub Actions — PR check + daily cron)
- [x] RFC KCP-004 published ([rfcs/kcp-004-network-models.md](../rfcs/kcp-004-network-models.md))
- [x] Artifact seeding — ~8.000 artifacts across 8 peers (public + org + private mix)
- [x] Docker image + docker-compose.yml for community operators

### What the KCP project does NOT need to do

- Pay for community-operated nodes — operators fund their own infrastructure
- Run peer01/02/03/06 ourselves — they should be operated by community members
- Build a hosting platform — the protocol is MIT-licensed, others can build that

---

## Phase 4: IPFS & Decentralized Storage (v0.6)

**Goal:** Content-addressed storage via IPFS for permanent, censorship-resistant artifact persistence.

### Tasks

- [ ] IPFS content backend (`IPFSBackend`) — CID-based addressing
- [ ] Pin artifact content to IPFS on publish
- [ ] kcp:// → ipfs:// URI mapping
- [ ] IPFS gateway fallback for public artifacts
- [ ] RFC KCP-005 (IPFS Storage Layer)

---

## Phase 5: Corporate Hub (v0.6) 🔜

**Goal:** Centralized deployment for organizations — single-click enterprise setup.

**Tasks:**
- [ ] Hub server (FastAPI + PostgreSQL)
- [ ] Docker Compose (one-command local setup)
- [ ] Dockerfile for production
- [ ] OAuth2 / Google Workspace SSO integration
- [ ] Multi-tenant isolation
- [ ] ACL (team-level, user-level permissions)
- [ ] Audit log (who did what, when)
- [ ] Admin dashboard (Web UI)
- [ ] Terraform / CloudFormation for AWS deployment
- [ ] Deploy guide (AWS, GCP, self-hosted)

---

## Phase 6: Federation (v0.7)

**Goal:** Hub-to-hub communication for cross-organization sharing.

**Tasks:**
- [ ] Hub-to-hub sync protocol
- [ ] mTLS authentication between hubs
- [ ] ACL filtering (control what gets exported/imported)
- [ ] Cross-org lineage tracking
- [ ] Federation registry (discover other hubs)

---

## Phase 7: Advanced Features (v0.8)

- [ ] Semantic search (vector embeddings + cosine similarity)
- [ ] Auto-tagging (LLM-based classification)
- [ ] Knowledge graph visualization
- [ ] Artifact versioning (update in place with history)
- [ ] Notifications (new artifacts matching interests)
- [ ] RFC KCP-004 (Network Security Layer)

---

## Phase 8: Ecosystem (v1.0)

- [ ] PyPI package (`pip install kcp`)
- [ ] npm package (`npm install @kcp/client`)
- [ ] Go module (`go get github.com/kcp-protocol/kcp`)
- [ ] VS Code extension
- [ ] GitHub Action (publish artifacts from CI/CD)
- [ ] Helm chart for Kubernetes deployment
- [ ] OpenAPI spec for hub API
- [ ] Conformance test suite
- [ ] Additional SDKs: Rust, Java, Kotlin/Mobile

---

## Priority Matrix

| Feature | Impact | Effort | Priority |
|---------|--------|--------|----------|
| Multi-region peers (community) | 🔥 High (resilience + latency) | Medium | **P0** |
| RFC KCP-004 (Network Security) | High | Low | P0 |
| Corporate Hub | High | Medium | P1 |
| IPFS storage backend | Medium | High | P2 |
| OAuth2 / SSO | Medium | Medium | P2 |
| Federation | Medium | High | P3 |
| Semantic search | Low | High | P3 |
| PyPI / npm packages | Medium | Low | P2 |

---

**This roadmap is updated as priorities evolve.**
