# KCP Roadmap

**Version:** 0.3  
**Updated:** March 2026  
**Author:** Thiago Silva

---

## Vision

KCP becomes the standard protocol for AI-generated knowledge — from personal use to enterprise-wide deployment.

---

## Current State (v0.2 — March 2026) ✅

### Completed

- [x] Protocol specification (SPEC.md)
- [x] Architecture design (3 operating modes: local, hub, federation)
- [x] Python SDK — reference implementation (Python 3.13, **61 tests ✅**)
  - [x] Embedded node (in-process, no server needed)
  - [x] Local storage (SQLite + FTS5)
  - [x] Ed25519 signing and verification
  - [x] SHA-256 content hashing
  - [x] Full-text search
  - [x] Lineage tracking (derivedFrom chains)
  - [x] Export/Import (offline sharing with signature verification)
  - [x] CLI (init, publish, search, list, lineage, serve, sync, stats)
  - [x] Web UI (embedded single-page HTML)
  - [x] HTTP API (FastAPI) for P2P sharing
  - [x] Hub backend client (for corporate deployments)
- [x] TypeScript SDK — Node.js 25, ESM + CJS + DTS (**37 tests ✅**)
  - [x] KCPNode (publish, get, search, verify, lineage, stats)
  - [x] Ed25519 + SHA-256 via @noble/* (zero native deps)
  - [x] JSON file storage backend
- [x] Go SDK (store, node, crypto, CLI — implemented ✅)
- [x] RFC (kcp-001-core.md + RFC-001-CORE.md)
- [x] Whitepaper
- [x] Executive presentation
- [x] AI_AGENT_GUIDE.md (LLM integration guide)
- [x] llms.txt (LLM indexing manifest)
- [x] docs/testing.md (full test documentation)
- [x] Root Makefile (unified test/build/setup orchestration)
- [x] Isolated SDK environments (.python-version, .nvmrc, .go-version)

---

## Phase 1: Shared Storage Transports (v0.3) 🔜

**Goal:** Enable real-time sharing between users without a dedicated server.

### Google Drive / Dropbox / OneDrive Transport

Use cloud storage the organization already has as a sync layer:

```
~/.kcp/
├── kcp.db           (local index — always local)
└── shared/          (synced folder — Google Drive, Dropbox, etc.)
    ├── artifacts/
    │   ├── abc-123.json   (signed metadata)
    │   └── def-456.json
    └── content/
        ├── abc-123.bin    (raw content)
        └── def-456.bin
```

**How it works:**
1. User publishes artifact → SDK writes to `shared/` folder
2. Cloud storage syncs to all team members automatically
3. Other users' SDK watches `shared/` folder for new artifacts
4. Auto-imports new artifacts, verifies signatures, indexes locally

**Config (one line):**
```bash
export KCP_SHARED="/Users/alice/Google Drive/My Drive/kcp-shared"
```

**Tasks:**
- [ ] `SharedFolderBackend` — watches a folder for new artifacts
- [ ] File-based artifact format (JSON metadata + binary content)
- [ ] fswatch / watchdog for real-time detection
- [ ] Auto-import with signature verification
- [ ] Conflict resolution (same ID from different authors)
- [ ] Test with Google Drive, Dropbox, and OneDrive

### S3 / GCS / MinIO Transport

Same concept, but using object storage:

```bash
export KCP_S3_BUCKET=s3://acme-corp-kcp
export AWS_PROFILE=default
```

**Tasks:**
- [ ] `S3Backend` — read/write artifacts to S3
- [ ] Polling or S3 event notifications for real-time sync
- [ ] IAM-based access control
- [ ] Test with AWS S3 and MinIO (local)

---

## Phase 2: Corporate Hub (v0.4)

**Goal:** Centralized deployment for organizations.

```
EC2 (t3.small, $15/mo)
├── FastAPI (REST API)
├── PostgreSQL (metadata + FTS)
├── S3 (content storage)
├── Nginx + Let's Encrypt (HTTPS)
└── OAuth2 / API Key auth
```

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

## Phase 3: Federation (v0.5)

**Goal:** Hub-to-hub communication for cross-organization sharing.

**Tasks:**
- [ ] Hub-to-hub sync protocol
- [ ] mTLS authentication between hubs
- [ ] ACL filtering (control what gets exported/imported)
- [ ] Cross-org lineage tracking
- [ ] Federation registry (discover other hubs)

---

## Phase 4: Advanced Features (v0.6)

- [ ] Semantic search (vector embeddings + cosine similarity)
- [ ] Auto-tagging (LLM-based classification)
- [ ] Knowledge graph visualization
- [ ] Artifact versioning (update in place with history)
- [ ] Notifications (new artifacts matching interests)
- [ ] API rate limiting and quotas

---

## Phase 5: Ecosystem (v1.0)

- [ ] PyPI package (`pip install kcp`)
- [ ] npm package (`npm install @kcp/client`)
- [ ] Go module (`go get github.com/tgosoul2019/kcp`)
- [ ] VS Code extension
- [ ] GitHub Action (publish artifacts from CI/CD)
- [ ] Helm chart for Kubernetes deployment
- [ ] OpenAPI spec for hub API
- [ ] Conformance test suite

---

## Priority Matrix

| Feature | Impact | Effort | Priority |
|---------|--------|--------|----------|
| Google Drive transport | 🔥 High (solves sharing today) | Low (1-2 days) | **P0** |
| S3 transport | High | Medium | P1 |
| Corporate Hub | High | Medium (2-3 days) | P1 |
| Docker Compose | High | Low | P1 |
| OAuth2 / SSO | Medium | Medium | P2 |
| Federation | Medium | High | P3 |
| Semantic search | Low | High | P3 |
| PyPI / npm packages | Medium | Low | P2 |

---

**This roadmap is updated as priorities evolve.**
