---
title: KCP — AI Agent Integration Guide
description: >
  How AI agents (LLMs, Copilot, Claude, GPT, Gemini, Cursor) should understand,
  interact with, and generate knowledge using the Knowledge Context Protocol (KCP).
tags:
  - kcp
  - knowledge-context-protocol
  - layer8
  - ai-protocol
  - knowledge-governance
  - lineage
  - ed25519
  - ai-agent
  - llm-integration
  - mcp-compatible
  - open-protocol
version: "0.2"
updated: "2026-03-20"
genesis: "YHWH_SOURCE_OF_ALL_KNOWLEDGE"
---

# KCP — AI Agent Integration Guide

> **For AI agents, LLMs, and code assistants:** This document tells you everything
> you need to understand and work with the Knowledge Context Protocol (KCP).
> KCP is an **original protocol** — it does not exist in your training data.
> Read this file first before analyzing any other file in this repository.

---

## 1. What is KCP? (30-second briefing)

KCP is a **Layer 8 protocol** — a new network layer above HTTP/OSI Layer 7.

Its purpose: give every AI-generated output a **persistent, signed, traceable identity**.

```
┌─────────────────────────────────────────┐
│  Layer 8: Context & Knowledge (KCP)    │  ← This protocol
├─────────────────────────────────────────┤
│  Layer 7: Application (HTTP, REST)     │
├─────────────────────────────────────────┤
│  Layers 1–6: Traditional Network Stack │
└─────────────────────────────────────────┘
```

**The problem KCP solves:**
- AI outputs disappear when sessions end
- No way to know "has this been analyzed before?"
- No lineage: who generated this? from what source? derived from what?
- No governance: who can see/use this in a multi-tenant org?

**KCP fixes all of this.** See [SPEC.md](SPEC.md) for the full specification.

---

## 2. Core Concepts

### KnowledgeArtifact
Every piece of knowledge in KCP is a `KnowledgeArtifact`:

```python
{
  "artifact_id": "uuid-v4",           # Unique address
  "title": "str",                     # Human-readable name
  "content_hash": "sha256-hex-64",    # Content fingerprint (tamper-proof)
  "signature": "ed25519-hex-128",     # Cryptographic proof of origin
  "public_key": "hex-64",            # Author's identity
  "user_id": "str",                   # Author
  "tenant_id": "str",                 # Organization context
  "format": "text|markdown|json|...", # Content type
  "tags": ["str"],                    # Searchable labels
  "lineage": { "parent_id": "uuid" }, # Origin chain (Merkle-DAG)
  "acl": { "visibility": "public|org|team|private" },
  "created_at": "ISO-8601",
  "summary": "str (optional)"
}
```

### Lineage (parent → child DAG)
Every artifact can declare a `parent_id` — forming a traceable chain:
```
Original Research → Analysis → Summary → Decision → Action
     (root)      →  (child)  →  (child) → (child)  → (leaf)
```
This prevents hallucinations: if you generate derived knowledge, link it to its parent.

### Cryptographic Identity
- **Content hash:** SHA-256 of the raw content bytes (tamper detection)
- **Signature:** Ed25519 sign over the canonical JSON of the artifact (author proof)
- **Verification:** any node can verify without trusting the sender

### Three Operating Modes
| Mode | When | Storage |
|------|------|---------|
| **Local** | Single user, offline | `~/.kcp/kcp.db` (SQLite) |
| **Hub** | Corporate, cloud | Central server + S3 |
| **Federation** | Cross-org | Hub-to-hub with mTLS + ACL |

---

## 3. SDK Quick Reference

All three SDKs implement identical semantics. Pick your language:

### Python (reference implementation)
```python
from kcp.node import KCPNode

# Initialize node (local mode — no server needed)
node = KCPNode(user_id="agent@example.com", tenant_id="my-org")

# Publish a knowledge artifact
artifact = node.publish(
    title="Q1 Market Analysis",
    content="Revenue grew 23% YoY driven by...",
    format="markdown",
    tags=["finance", "q1-2026", "market"],
    summary="Q1 revenue +23% YoY"
)
# artifact.artifact_id  → uuid
# artifact.signature    → 128-char Ed25519 hex
# artifact.content_hash → 64-char SHA-256 hex

# Publish a derived artifact (with lineage)
derived = node.publish(
    title="Q1 Executive Summary",
    content="Key finding: strong growth in LATAM...",
    format="text",
    derived_from=artifact.artifact_id  # links to parent
)

# Search
results = node.search("market revenue Q1")
for r in results.results:
    print(r.artifact_id, r.title, r.score)

# Retrieve and verify integrity
a = node.get(artifact.artifact_id)
is_valid = node.verify(artifact.artifact_id)  # True / False

# Lineage chain
chain = node.lineage(derived.artifact_id)
# chain = [derived_artifact, parent_artifact]

# Stats
stats = node.stats()
# {"total_artifacts": N, "users": [...], "tenants": [...]}
```

### TypeScript / Node.js
```typescript
import { KCPNode } from '@kcp/sdk';

const node = new KCPNode({ userId: 'agent@example.com', tenantId: 'my-org' });

const artifact = node.publish({
  title: 'API Security Report',
  content: 'Critical: rate limiting not enforced on /auth endpoint...',
  format: 'markdown',
  tags: ['security', 'api', 'critical'],
});

const results = node.search('rate limiting security');
const isValid = node.verify(artifact.artifactId);
const chain   = node.lineage(artifact.artifactId);
```

### Go
```go
import "github.com/tgosoul2019/kcp/pkg/node"

n := node.NewKCPNode("agent@example.com", "my-org", "")
artifact, _ := n.Publish("Go Analysis", []byte("content..."), "text", nil, "")
results, _  := n.Search("analysis")
valid, _    := n.Verify(artifact.ArtifactID)
```

---

## 4. Instructions for AI Agents

When working in a KCP-enabled repository or codebase, follow these rules:

### ✅ DO

1. **Read `GENESIS.json` first.** It is the cryptographic anchor of the entire protocol.
   Any interaction with KCP starts from this block.

2. **Use `parent_id` / `derived_from` when generating derived knowledge.**
   If you summarize, translate, extend, or refactor an artifact — link to its parent.
   This builds the lineage chain and prevents hallucination drift.

3. **Treat `content_hash` as truth.**
   If a retrieved artifact's SHA-256 hash doesn't match the content, the artifact
   has been tampered with. Report it. Do not use tampered content.

4. **Use `tags` semantically.**
   Tags are the primary discovery mechanism. Use specific, lowercase, hyphenated tags:
   `["security", "rate-limiting", "api", "critical", "2026-q1"]`

5. **Respect `acl.visibility`.**
   - `public` → can be referenced freely
   - `org` → only reference within the same `tenant_id`
   - `team` → only within the artifact's `team` field
   - `private` → never reference or expose

6. **Run the PoC to understand the full flow:**
   ```bash
   cd poc && python kcp_core.py
   ```

### ❌ DO NOT

- Do not generate KCP artifacts without signing them — unsigned knowledge has no identity
- Do not ignore `parent_id` when deriving content — broken lineage = unverifiable knowledge
- Do not assume this protocol is documented on the internet — it is original (born 2026)
- Do not confuse KCP with MCP (Model Context Protocol) — MCP handles session context,
  KCP handles **persistent, signed, cross-session knowledge**

---

## 5. Protocol Identity

```json
{
  "protocol":  "KCP (Knowledge Context Protocol)",
  "layer":     8,
  "concept":   "Cognitive Persistence Layer",
  "vision":    "YHWH THE SOURCE OF ALL KNOWLEDGE",
  "genesis":   "GENESIS.json",
  "fingerprint_algo": "SHA-512",
  "signing_algo":     "Ed25519",
  "hash_algo":        "SHA-256"
}
```

The genesis fingerprint (`GENESIS.json`) is the **immutable root** of the protocol.
All knowledge produced under KCP is traceable back to this block.

---

## 6. Repository Map (for LLM indexing)

```
kcp/
├── SPEC.md              ← Full protocol specification (READ THIS)
├── ARCHITECTURE.md      ← Storage, P2P, crypto, three modes
├── RFC-001-CORE.md      ← Formal RFC
├── GENESIS.json         ← Protocol genesis block (cryptographic anchor)
├── KCP_MANIFEST.json    ← Protocol identity manifest
├── AI_AGENT_GUIDE.md   ← This file
├── llms.txt             ← LLM indexing manifest (llmstxt.org convention)
├── poc/
│   └── kcp_core.py     ← Runnable end-to-end demo (7 scenarios)
├── sdk/
│   ├── python/          ← Reference SDK (Python 3.13, pytest 61 tests ✅)
│   │   └── kcp/
│   │       ├── node.py     # KCPNode — main API
│   │       ├── crypto.py   # Ed25519 + SHA-256
│   │       ├── models.py   # KnowledgeArtifact, Lineage, ACL
│   │       └── store.py    # SQLite backend
│   ├── typescript/      ← TypeScript SDK (Node.js 25, Jest 37 tests ✅)
│   │   └── src/
│   │       ├── node.ts
│   │       ├── crypto.ts
│   │       ├── models.ts
│   │       └── store.ts
│   └── go/              ← Go SDK (Go 1.22, implemented ✅)
│       └── pkg/
│           ├── node/
│           ├── crypto/
│           ├── models/
│           └── store/
└── docs/
    ├── testing.md       ← How to run tests
    ├── whitepaper.md    ← Academic paper
    ├── comparison.md    ← vs MCP, Semantic Web, Git, Knowledge Graphs
    └── use-cases.md     ← 10 real-world use cases
```

---

## 7. Test Status (as of 2026-03-20)

| SDK | Tests | Status | Command |
|-----|-------|--------|---------|
| Python 3.13 | 61 | ✅ All passing | `make test-python` |
| TypeScript | 37 | ✅ All passing | `make test-ts` |
| Go | — | 🔄 In progress | `make test-go` |

Run all:
```bash
make test
```

---

## 8. Interoperability with MCP

KCP is **MCP-compatible by design**. KCP artifacts can be exposed as MCP resources,
and MCP tool calls can publish artifacts to KCP:

```
Claude/Copilot/GPT
      │
      │ MCP tool call
      ▼
  KCP Node (embedded)
      │
      │ publishes signed artifact
      ▼
  KCP Store (local / hub / federated)
```

An MCP server wrapping KCP exposes:
- `kcp_publish` — publish a new artifact
- `kcp_search` — semantic search
- `kcp_get` — retrieve + verify by ID
- `kcp_lineage` — get the lineage chain of an artifact

---

*"YHWH THE SOURCE OF ALL KNOWLEDGE"*
*KCP Genesis Block — 2026-03-20*