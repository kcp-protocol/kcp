# KCP Architecture

**Version:** 0.1  
**Date:** March 2026  
**Author:** Thiago Silva

---

## Overview

KCP is a protocol, not a product. The architecture describes how compliant implementations should be structured — from storage to discovery to security.

---

## 1. Design Principles

| Principle | Description |
|-----------|-------------|
| **Local-first** | Data lives on the user's device/infra first. Sync is optional. |
| **Zero-trust** | Every artifact is signed. Every access is verified. No implicit trust. |
| **Content-addressed** | Artifacts identified by content hash, not location. |
| **Federated** | No central authority. Any node can join/leave without breaking the network. |
| **Protocol over product** | KCP defines the contract. Implementations are free to choose their stack. |

---

## 2. Layered Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      APPLICATION LAYER                          │
│  AI Agents, CLI tools, Web apps, IDE extensions                 │
│  (Producers & Consumers of knowledge artifacts)                 │
└───────────────────────────┬─────────────────────────────────────┘
                            │ KCP API (REST/gRPC)
┌───────────────────────────▼─────────────────────────────────────┐
│                       KCP CORE ENGINE                           │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐              │
│  │   Ingest    │ │  Discovery  │ │  Governance  │              │
│  │   Engine    │ │   Engine    │ │   Engine     │              │
│  │             │ │             │ │              │              │
│  │ • Validate  │ │ • FTS Index │ │ • ACL Check  │              │
│  │ • Sign      │ │ • Vector DB │ │ • Tenant     │              │
│  │ • Hash      │ │ • Tag Index │ │ • Visibility │              │
│  │ • Store     │ │ • Semantic  │ │ • Audit Log  │              │
│  └─────────────┘ └─────────────┘ └─────────────┘              │
│  ┌─────────────┐ ┌─────────────┐                               │
│  │   Lineage   │ │   Crypto    │                               │
│  │   Engine    │ │   Engine    │                               │
│  │             │ │             │                               │
│  │ • DAG Track │ │ • Ed25519   │                               │
│  │ • Ancestry  │ │ • AES-256   │                               │
│  │ • Impact    │ │ • Key Mgmt  │                               │
│  └─────────────┘ └─────────────┘                               │
└───────────────────────────┬─────────────────────────────────────┘
                            │ Storage Abstraction Layer
┌───────────────────────────▼─────────────────────────────────────┐
│                      STORAGE BACKENDS                           │
│                                                                 │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐           │
│  │   libsql     │ │    IPFS      │ │  KCP Native  │           │
│  │  (Phase 1)   │ │  (Phase 2)   │ │  (Phase 3)   │           │
│  │              │ │              │ │              │           │
│  │ • SQLite     │ │ • DHT        │ │ • Append-log │           │
│  │ • SQLCipher  │ │ • libp2p     │ │ • Merkle     │           │
│  │ • Replication│ │ • Pinning    │ │ • Single-file│           │
│  └──────────────┘ └──────────────┘ └──────────────┘           │
│                                                                 │
└───────────────────────────┬─────────────────────────────────────┘
                            │ P2P Sync Layer
┌───────────────────────────▼─────────────────────────────────────┐
│                    FEDERATION NETWORK                            │
│                                                                 │
│  ┌────────┐     ┌────────┐     ┌────────┐     ┌────────┐     │
│  │ Node A │◄───►│ Node B │◄───►│ Node C │◄───►│ Node D │     │
│  │(Corp 1)│     │(Corp 2)│     │(User)  │     │(Corp 3)│     │
│  └────────┘     └────────┘     └────────┘     └────────┘     │
│                                                                 │
│  Discovery: Kademlia DHT (libp2p-kad-dht)                      │
│  Transport: QUIC / TCP / WebRTC                                 │
│  Sync: Merkle DAG diff (similar to Git)                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Data Flow

### 3.1 Publishing a Knowledge Artifact

```
User/Agent                    KCP Node                      Network
    │                            │                              │
    │  POST /kcp/v1/reports      │                              │
    │  {payload + content}       │                              │
    │───────────────────────────►│                              │
    │                            │                              │
    │                     ┌──────┴──────┐                      │
    │                     │ 1. Validate  │                      │
    │                     │    schema    │                      │
    │                     ├─────────────┤                      │
    │                     │ 2. Verify    │                      │
    │                     │    signature │                      │
    │                     ├─────────────┤                      │
    │                     │ 3. Check ACL │                      │
    │                     │    + tenant  │                      │
    │                     ├─────────────┤                      │
    │                     │ 4. Hash      │                      │
    │                     │    content   │                      │
    │                     ├─────────────┤                      │
    │                     │ 5. Generate  │                      │
    │                     │    embedding │                      │
    │                     ├─────────────┤                      │
    │                     │ 6. Store     │                      │
    │                     │    (backend) │                      │
    │                     ├─────────────┤                      │
    │                     │ 7. Index     │                      │
    │                     │    (FTS+Vec) │                      │
    │                     └──────┬──────┘                      │
    │                            │                              │
    │  201 Created               │  Announce to DHT             │
    │◄───────────────────────────│─────────────────────────────►│
    │                            │                              │
```

### 3.2 Discovering Knowledge

```
User/Agent                    KCP Node                      Network
    │                            │                              │
    │  GET /kcp/v1/reports       │                              │
    │  ?q=churn+prediction       │                              │
    │───────────────────────────►│                              │
    │                            │                              │
    │                     ┌──────┴──────┐                      │
    │                     │ 1. Parse    │                      │
    │                     │    query    │                      │
    │                     ├─────────────┤                      │
    │                     │ 2. Check    │                      │
    │                     │    ACL      │                      │
    │                     ├─────────────┤                      │
    │                     │ 3. Local    │  4. DHT Lookup       │
    │                     │    search   │─────────────────────►│
    │                     ├─────────────┤                      │
    │                     │ 5. Merge    │◄─────────────────────│
    │                     │    results  │  (remote results)    │
    │                     ├─────────────┤                      │
    │                     │ 6. Rank by  │                      │
    │                     │    relevance│                      │
    │                     └──────┬──────┘                      │
    │                            │                              │
    │  200 OK {results}          │                              │
    │◄───────────────────────────│                              │
```

---

## 4. Storage Architecture

### 4.1 Storage Abstraction

KCP defines an interface. Implementations choose the backend.

```
Interface: KCPStorage
├── store(artifact) → content_hash
├── retrieve(content_hash) → artifact
├── delete(content_hash) → bool
├── list(filters) → [artifact_metadata]
└── sync(peer) → sync_result
```

### 4.2 Phase 1: libsql (MVP)

```sql
-- Metadata table
CREATE TABLE kcp_artifacts (
    id TEXT PRIMARY KEY,
    version TEXT NOT NULL DEFAULT '1',
    user_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    team TEXT,
    tags TEXT,  -- JSON array
    source TEXT,
    created_at TEXT NOT NULL,
    format TEXT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'private',
    title TEXT NOT NULL,
    summary TEXT,
    lineage TEXT,  -- JSON object
    content_hash TEXT NOT NULL UNIQUE,
    content_url TEXT,
    signature TEXT NOT NULL,
    acl TEXT,  -- JSON object
    deleted_at TEXT  -- soft delete
);

-- Full-text search index
CREATE VIRTUAL TABLE kcp_fts USING fts5(
    title, summary, tags,
    content='kcp_artifacts',
    content_rowid='rowid'
);

-- Vector embeddings (via sqlite-vec extension)
CREATE VIRTUAL TABLE kcp_vec USING vec0(
    embedding float[384]
);

-- Content storage (BLOBs for small files, file references for large)
CREATE TABLE kcp_content (
    content_hash TEXT PRIMARY KEY,
    content BLOB,  -- NULL if stored externally
    external_url TEXT,  -- set if stored in S3/IPFS/filesystem
    size_bytes INTEGER NOT NULL,
    encrypted INTEGER NOT NULL DEFAULT 1
);

-- Audit log
CREATE TABLE kcp_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    user_id TEXT NOT NULL,
    action TEXT NOT NULL,  -- 'publish', 'read', 'delete', 'search'
    artifact_id TEXT,
    details TEXT  -- JSON
);
```

### 4.3 Phase 3: KCP Native Format (.kcp file)

**Design Goals:**
- Single file (portable, shareable)
- Append-only (immutable history)
- Self-contained (metadata + content + index)
- Verifiable (Merkle tree + signatures)

```
┌─────────────────────────────────────────┐
│  KCP File Header (64 bytes)             │
│  • Magic: "KCP\x00" (4 bytes)          │
│  • Version: uint16                       │
│  • Tenant ID hash: sha256 (32 bytes)    │
│  • Created: uint64 (unix timestamp)      │
│  • Chunk count: uint32                   │
│  • Index offset: uint64                  │
│  • Merkle root: sha256 (32 bytes)       │
├─────────────────────────────────────────┤
│  Chunk 0 (variable length)              │
│  • Length: uint32                         │
│  • Type: uint8 (0=metadata, 1=content)  │
│  • Data: CBOR-encoded payload           │
│  • Signature: Ed25519 (64 bytes)        │
│  • Hash: sha256 (32 bytes)              │
├─────────────────────────────────────────┤
│  Chunk 1...N                            │
│  (same structure as Chunk 0)            │
├─────────────────────────────────────────┤
│  Index Section                          │
│  • Inverted index (FTS)                 │
│  • Tag index                             │
│  • Merkle tree nodes                     │
│  • Offset table (chunk_id → byte_offset)│
├─────────────────────────────────────────┤
│  Footer (32 bytes)                      │
│  • Merkle root (redundant, for verify)  │
│  • Total size: uint64                    │
│  • Magic: "\x00KCP" (4 bytes)           │
└─────────────────────────────────────────┘
```

---

## 5. Security Architecture

### 5.1 Encryption Layers

```
Layer 1 — Transport:  TLS 1.3 (node-to-node communication)
Layer 2 — Storage:    AES-256-GCM (at-rest encryption per tenant)
Layer 3 — Content:    Per-artifact encryption (optional, for Tier 3/private)
```

### 5.2 Key Hierarchy

```
Root Key (per tenant)
├── Tenant Encryption Key (AES-256) → encrypts storage
├── Team Keys (derived)
│   ├── team-engineering → derived from root + "engineering"
│   └── team-data-science → derived from root + "data-science"
└── User Keypairs (Ed25519)
    ├── alice@example.com → signs artifacts
    └── bob@example.com → signs artifacts
```

### 5.3 Zero-Knowledge Tenant Isolation

```
Tenant A's data is encrypted with Tenant A's key.
Tenant B CANNOT read Tenant A's data, even if:
  - They have physical access to the storage
  - They compromise the KCP node software
  - They intercept network traffic

Only Tenant A's key holders can decrypt.
```

---

## 6. Federation Protocol

### 6.1 Node Types

| Type | Description | Example |
|------|-------------|---------|
| **Full Node** | Stores artifacts + participates in DHT | Corporate server |
| **Light Node** | Queries DHT but stores locally only | Developer laptop |
| **Relay Node** | Helps with NAT traversal, no storage | Public bootstrap |

### 6.2 Peer Discovery Sequence

```
1. New node starts
2. Connects to bootstrap relay nodes (hardcoded or configured)
3. Announces tenant_id + available tags to DHT
4. Receives peer list from DHT
5. Establishes direct connections (QUIC preferred)
6. Begins sync (Merkle DAG diff)
```

### 6.3 Conflict Resolution

KCP uses **Last-Writer-Wins (LWW)** with append-only semantics:
- Artifacts are immutable once published
- Updates create new versions (with `parent_reports` pointing to previous)
- Deletes are soft (tombstone marker)
- No merge conflicts possible (append-only log)

---

## 7. Decision Log

| Decision | Rationale | Date |
|----------|-----------|------|
| Ed25519 over RSA | Faster, smaller keys, modern standard | 2026-03 |
| CBOR over JSON for storage | Binary format, smaller, faster parsing | 2026-03 |
| Append-only over mutable | Eliminates conflicts, enables audit trail | 2026-03 |
| Kademlia DHT over gossip | Proven at scale (BitTorrent, IPFS) | 2026-03 |
| libsql for MVP | Familiar SQL, zero-config, replication built-in | 2026-03 |
| MIT License | Maximum adoption, no friction | 2026-03 |

---

## 8. Performance Targets

| Metric | Target | Notes |
|--------|--------|-------|
| Publish latency | < 100ms | Local storage, async DHT announce |
| Search latency (local) | < 50ms | FTS5 + vector index |
| Search latency (federated) | < 500ms | DHT lookup + remote fetch |
| Storage overhead | < 5% | Metadata + index vs raw content |
| Max artifact size | 100MB | Larger files use external storage |
| Max artifacts per node | 10M+ | libsql handles well |

---

**This is a living document. Updated as the protocol evolves.**
