---
title: KCP Architecture
description: KCP operating modes (Local / Hub / Federation), storage backends, P2P sync, crypto model, and layered architecture.
tags: [kcp, architecture, p2p, sqlite, ed25519, federation, multi-tenant, layer8, knowledge-governance]
version: "0.2"
updated: "2026-03-20"
---

# KCP Architecture

**Version:** 0.2  
**Date:** March 2026  
**Author:** Thiago Silva

---

## Overview

KCP is a protocol, not a product. This document describes the three operating modes, storage backends, P2P sync, and security model.

---

## 1. Three Operating Modes

KCP adapts to the user's context — from a single person to a global enterprise.

```
┌──────────────────────────────────────────────────────────────────────┐
│                     KCP — Operating Modes                            │
├────────────────┬────────────────────┬────────────────────────────────┤
│  🏠 LOCAL       │  🏢 HUB (corporate)  │  🌐 FEDERATION (cross-org)    │
│                │                    │                                │
│  SQLite in     │  Central registry  │  Hubs connect to each other   │
│  ~/.kcp/kcp.db │  (cloud/on-prem)   │  (like email servers)         │
│                │                    │                                │
│  P2P direct    │  Agents point to   │  Org A ↔ Org B share          │
│  between users │  company hub       │  knowledge with ACL control   │
│                │                    │                                │
│  Zero config   │  1 config:         │  Hub-to-hub sync with mTLS    │
│                │  KCP_HUB=url       │                                │
│                │                    │                                │
│  User stores   │  User stores       │  Each org controls what       │
│  locally       │  nothing (or cache)│  it exports/imports           │
└────────────────┴────────────────────┴────────────────────────────────┘
```

### Mode Detection (automatic)

```python
if config.has("kcp_hub"):
    backend = HubBackend(url=config.kcp_hub)     # Corporate: everything on hub
elif config.has("kcp_peers"):
    backend = P2PBackend(peers=config.kcp_peers)  # Community: peer-to-peer
else:
    backend = LocalStore(path="~/.kcp/kcp.db")    # Standalone: local SQLite
```

The user interface is **identical** in all three modes. The backend is transparent.

---

## 2. Access Layers

KCP provides three layers of access for different user profiles:

```
┌─────────────────────────────────────────────────────┐
│          Layer 1: Natural Language                   │
│   "publish this", "search for X", "share with Y"   │
│         (AI assistant skill/plugin)                  │
├─────────────────────────────────────────────────────┤
│          Layer 2: Web UI (browser)                  │
│   Open link → see artifacts, lineage, search        │
│   (for visual exploration, no install needed)        │
├─────────────────────────────────────────────────────┤
│          Layer 3: CLI / SDK (developers)            │
│   kcp publish, kcp search, kcp sync, Python API     │
│   (for integration in code and pipelines)            │
└─────────────────────────────────────────────────────┘
```

---

## 3. Layered Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      APPLICATION LAYER                          │
│  AI Assistants, CLI, Web UI, IDE extensions                     │
│  (Producers & Consumers of knowledge artifacts)                 │
└───────────────────────────┬─────────────────────────────────────┘
                            │ KCP API (REST + in-process)
┌───────────────────────────▼─────────────────────────────────────┐
│                       KCP NODE (embedded)                       │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐              │
│  │   Publish    │ │  Discovery  │ │  Governance  │              │
│  │   Engine     │ │   Engine    │ │   Engine     │              │
│  │             │ │             │ │              │              │
│  │ • Validate  │ │ • FTS Index │ │ • ACL Check  │              │
│  │ • Sign      │ │ • Tag Index │ │ • Tenant     │              │
│  │ • Hash      │ │ • Semantic  │ │ • Visibility │              │
│  │ • Store     │ │ • Search    │ │ • Audit Log  │              │
│  └─────────────┘ └─────────────┘ └─────────────┘              │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐              │
│  │   Lineage   │ │   Crypto    │ │    Sync     │              │
│  │   Engine    │ │   Engine    │ │   Engine     │              │
│  │             │ │             │ │              │              │
│  │ • DAG Track │ │ • Ed25519   │ │ • Push/Pull  │              │
│  │ • Ancestry  │ │ • SHA-256   │ │ • Peer Mgmt  │              │
│  │ • Derivation│ │ • Key Mgmt  │ │ • Diff Sync  │              │
│  └─────────────┘ └─────────────┘ └─────────────┘              │
└───────────────────────────┬─────────────────────────────────────┘
                            │ Storage Abstraction
┌───────────────────────────▼─────────────────────────────────────┐
│                      STORAGE BACKENDS                           │
│                                                                 │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐           │
│  │   SQLite     │ │  Hub (HTTP)  │ │  KCP Native  │           │
│  │  (default)   │ │  (corporate) │ │  (future)    │           │
│  │              │ │              │ │              │           │
│  │ • Zero config│ │ • Postgres   │ │ • Append-log │           │
│  │ • FTS5 index │ │ • S3 content │ │ • Merkle DAG │           │
│  │ • Portable   │ │ • SSO/OIDC   │ │ • Single-file│           │
│  │ • sql.js OK  │ │ • Audit trail│ │ • Verifiable │           │
│  └──────────────┘ └──────────────┘ └──────────────┘           │
│                                                                 │
└───────────────────────────┬─────────────────────────────────────┘
                            │ P2P / Federation
┌───────────────────────────▼─────────────────────────────────────┐
│                    NETWORK LAYER                                │
│                                                                 │
│  ┌────────┐     ┌────────┐     ┌────────┐     ┌────────┐     │
│  │ Node A │◄───►│ Node B │◄───►│ Hub C  │◄───►│ Hub D  │     │
│  │(laptop)│     │(laptop)│     │(corp)  │     │(corp)  │     │
│  └────────┘     └────────┘     └────────┘     └────────┘     │
│                                                                 │
│  P2P: Direct HTTP sync (with optional tunnel for NAT)          │
│  Federation: Hub-to-hub sync with mTLS + ACL filtering         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Data Flow

### 4.1 Publishing (embedded node, no server)

```
User/Agent                    KCP Node (in-process)
    │                              │
    │  node.publish(title, content)│
    │─────────────────────────────►│
    │                              │
    │                       ┌──────┴──────┐
    │                       │ 1. Hash     │
    │                       │    content  │
    │                       ├─────────────┤
    │                       │ 2. Create   │
    │                       │    artifact │
    │                       ├─────────────┤
    │                       │ 3. Sign     │
    │                       │    Ed25519  │
    │                       ├─────────────┤
    │                       │ 4. Store    │
    │                       │    SQLite   │
    │                       ├─────────────┤
    │                       │ 5. Index    │
    │                       │    FTS5     │
    │                       ├─────────────┤
    │                       │ 6. Audit    │
    │                       │    log      │
    │                       └──────┬──────┘
    │                              │
    │  ← KnowledgeArtifact         │
    │◄─────────────────────────────│
```

### 4.2 P2P Sync

```
Node A                                         Node B
  │                                               │
  │  GET /kcp/v1/sync/list?since=2026-03-01       │
  │──────────────────────────────────────────────►│
  │                                               │
  │  ← {ids: ["abc", "def", ...]}                  │
  │◄──────────────────────────────────────────────│
  │                                               │
  │  (filter out IDs we already have)             │
  │                                               │
  │  GET /kcp/v1/sync/artifact/abc                │
  │──────────────────────────────────────────────►│
  │                                               │
  │  ← {artifact + content_b64}                    │
  │◄──────────────────────────────────────────────│
  │                                               │
  │  (verify signature → store locally)           │
```

---

## 5. Corporate Hub Architecture

For organizations that want centralized knowledge governance:

```
┌────────────────────────────────────────────────────────┐
│                    KCP Hub (deployed)                    │
│          Docker / Kubernetes / Cloud VM                  │
│                                                         │
│   ┌──────────┐  ┌──────────────┐  ┌────────────────┐  │
│   │ REST API │  │  PostgreSQL  │  │ Object Storage │  │
│   │ (FastAPI) │  │  (metadata   │  │ (S3/GCS/MinIO) │  │
│   │          │  │   + FTS)     │  │ (large content)│  │
│   └─────┬────┘  └──────────────┘  └────────────────┘  │
│         │                                               │
│   ┌─────┴───────────────────────────────────┐          │
│   │  SSO/OIDC · ACL · Audit · Rate Limit    │          │
│   └─────────────────────────────────────────┘          │
└────────────────────────────────────────────────────────┘
         ▲              ▲              ▲
         │              │              │
    ┌────┴──┐     ┌────┴──┐     ┌────┴──┐
    │ Alice │     │  Bob  │     │ Carol │
    │(assist)│    │(assist)│    │ (CLI) │
    └───────┘     └───────┘     └───────┘

  Users don't store anything locally.
  Hub handles storage, search, lineage, ACL.
```

### Hub Storage Tiers

| Org Size | Backend | Est. Cost |
|----------|---------|-----------|
| Startup / small team | SQLite + persistent volume | ~$0 |
| Medium company | PostgreSQL + S3 | ~$50/mo |
| Enterprise | PostgreSQL + S3 + Redis + Elasticsearch | ~$200-500/mo |
| Air-gapped / on-prem | PostgreSQL + MinIO | Own infra |

---

## 6. Security

### Signing & Verification

Every artifact is signed with Ed25519 at creation time:

```
Artifact JSON (canonical, sorted keys)
    │
    ▼
Ed25519.sign(private_key) → 64-byte signature (hex)
    │
    ▼
Stored in artifact.signature field
    │
    ▼
Anyone with public_key can verify authenticity
```

### Key Hierarchy

```
Node keypair (Ed25519, auto-generated)
├── ~/.kcp/keys/private.key  (600 permissions, never leaves machine)
└── ~/.kcp/keys/public.key   (shared with peers for verification)
```

### Content Integrity

```
Content bytes → SHA-256 → content_hash (stored in artifact metadata)
```

Anyone can verify that content hasn't been tampered with by rehashing.

### Tenant Isolation (Hub mode)

In Hub deployments, tenants are isolated by:
- Separate encryption keys per tenant
- ACL enforcement on every query
- Audit logging of all access

---

## 7. Decision Log

| Decision | Rationale | Date |
|----------|-----------|------|
| SQLite for local storage | Zero config, portable, sql.js for browser | 2026-03 |
| Ed25519 over RSA | Faster, smaller keys (32 bytes), modern | 2026-03 |
| Embedded node (in-process) | No separate server = zero infra for users | 2026-03 |
| Three modes (local/hub/fed) | Scales from individual to enterprise | 2026-03 |
| HTTP sync over custom protocol | Simpler, works through firewalls/tunnels | 2026-03 |
| Append-only artifacts | No conflicts, full audit trail, immutable | 2026-03 |
| MIT License | Maximum adoption, zero friction | 2026-03 |

---

## 8. Performance Targets

| Metric | Target |
|--------|--------|
| Publish latency (local) | < 10ms |
| Search latency (local FTS) | < 50ms |
| Search latency (hub) | < 200ms |
| Sync (P2P, per artifact) | < 100ms |
| Max artifact size | 100MB |
| Max artifacts per node | 10M+ |
| SQLite DB overhead | < 5% vs raw content |

---

**This is a living document. Updated as the protocol evolves.**


# Arquitetura KCP - Camada 8 (Cognitive Layer)

## 1. Definição
A Camada 8 atua acima da Camada de Aplicação (L7), abstraindo a persistência e garantindo que o conhecimento gerado por IA seja imutável e rastreável.

## 2. Pilares de Rede
* **Persistência Híbrida:** Integração entre Edge P2P (baixa latência/soberania) e Super Peers Cloud (S3/API para longa duração).
* **DNA de Dados:** Cada pacote possui um `Parent_ID` (Linhagem) e uma assinatura `Ed25519`.
* **Cofre Frio (Cold Backup):** Suporte nativo para exportação determinística em arquivos de texto para auditoria governamental e "Replay de Contexto".

## 3. Segurança Pós-Quântica
O protocolo prevê agilidade criptográfica para transição de Ed25519 para algoritmos baseados em redes (Lattice-based) como o Crystals-Dilithium.


🚀 Evolução da Camada 8 (KCP v1.1 - Post-Quantum & Hybrid P2P)
1. Persistência de Rede Híbrida (P2P + Cloud)
O KCP opera num modelo de Malha Híbrida. O conhecimento não reside apenas num servidor central (Hub) ou apenas localmente.

Edge P2P Mesh: Blocos de conhecimento são fragmentados e distribuídos entre nós vizinhos para garantir soberania e resistência à censura.

Super Peers (Cloud): Servidores de alta disponibilidade (S3/Azure/GCP) funcionam como "âncoras de persistência", mas o controle da chave de descodificação permanece no nó originador (Zero-Knowledge).

2. Agnosticismo de Armazenamento (Storage-Agile)
Embora a PoC utilize SQLite e Postgres, o KCP foi desenhado para ser Database-Agnostic. A Camada 8 comunica com os backends através de um Adaptador de Persistência Único:

Suporte Futuro: Extensível para NoSQL (MongoDB), Vetoriais (Pinecone/Milvus), Graph Databases (Neo4j) ou Blockchain (IPFS/Filecoin).

Cold Export: Capacidade de "congelar" qualquer estado de banco de dados num arquivo de texto plano assinado (.kcp) para portabilidade total.

3. Segurança Pós-Quântica (PQC)
Para proteger o DNA do dado contra a futura computação quântica:

Agilidade Criptográfica: O protocolo suporta a transição transparente de Ed25519 para algoritmos baseados em redes (Lattice-based) como o Crystals-Dilithium.

Hashing Robusto: Utilização de SHA-512 no Bloco Gênese para mitigar os efeitos do Algoritmo de Grover.

4. Interface de Conectividade (MCP & gRPC)
A comunicação com IAs (LLMs) é feita nativamente via MCP (Model Context Protocol), permitindo que agentes autónomos leiam e escrevam na Camada 8 sem necessidade de APIs proprietárias.