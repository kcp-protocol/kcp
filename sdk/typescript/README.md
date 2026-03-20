# KCP TypeScript SDK

TypeScript/Node.js implementation of the Knowledge Context Protocol.  
**Status: ✅ Implemented** — 37 tests passing | Node.js 25 | ESM + CJS + DTS

## Install

```bash
npm install @kcp/sdk
```

> Not yet published to npm. Build from source below.

## Build from source

```bash
cd sdk/typescript
npm install
npm run build   # → dist/  (ESM + CJS + DTS)
npm test        # → 37 tests passing
```

## Quick Start

```typescript
import { KCPNode } from '@kcp/sdk';

// Initialize node (local mode — no server needed)
const node = new KCPNode({
  userId: 'alice@acme.com',
  tenantId: 'acme-corp',
});

// Publish a knowledge artifact
const artifact = node.publish({
  title: 'JWT Authentication Best Practices',
  content: '## JWT Auth\n\nAlways validate the `exp` claim...',
  format: 'markdown',
  tags: ['security', 'jwt', 'authentication'],
  summary: 'Guide for secure JWT implementation',
});
console.log(artifact.artifactId);   // uuid
console.log(artifact.signature);    // 128-char Ed25519 hex
console.log(artifact.contentHash);  // 64-char SHA-256 hex

// Publish derived artifact (with lineage)
const derived = node.publish({
  title: 'OAuth2 + JWT Integration',
  content: 'Building on JWT best practices...',
  format: 'markdown',
  tags: ['security', 'oauth2'],
  derivedFrom: artifact.artifactId,  // links to parent
});

// Search
const results = node.search('authentication security');
results.results.forEach(r => console.log(r.title, r.score));

// Retrieve + verify integrity
const a = node.get(artifact.artifactId);
const isValid = node.verify(artifact.artifactId);  // true / false

// Lineage chain
const chain = node.lineage(derived.artifactId);
// [derived, parent]

// Stats
const stats = node.stats();
// { totalArtifacts: N, users: [...], tenants: [...] }
```

## API Reference

### `new KCPNode(options)`
| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `userId` | `string` | `'anonymous'` | Author identity |
| `tenantId` | `string` | `'local'` | Organization context |
| `dbPath` | `string` | `~/.kcp/kcp.json` | Storage path |
| `privateKey` | `Uint8Array` | auto-generated | Ed25519 private key (32 bytes) |
| `publicKey` | `Uint8Array` | auto-generated | Ed25519 public key (32 bytes) |

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `publish(opts)` | `KnowledgeArtifact` | Sign + store artifact |
| `get(id)` | `KnowledgeArtifact \| undefined` | Retrieve by ID |
| `getContent(id)` | `Uint8Array \| undefined` | Raw content bytes |
| `search(query, limit?)` | `SearchResponse` | Full-text search |
| `list(limit?)` | `KnowledgeArtifact[]` | List all artifacts |
| `verify(id)` | `boolean` | Verify signature + hash |
| `lineage(id)` | `KnowledgeArtifact[]` | Parent chain (root first) |
| `derivatives(id)` | `KnowledgeArtifact[]` | Direct children |
| `stats()` | `object` | Node statistics |
| `close()` | `void` | Flush and close storage |

## Crypto

- **Signing:** Ed25519 via `@noble/ed25519`
- **Content hash:** SHA-256 via `@noble/hashes`
- **Key generation:** `generateKeypair()` → `{ privateKey, publicKey }` (32-byte `Uint8Array`)

## Tests

```bash
npm test
# PASS  tests/kcp.test.ts
# Tests: 37 passed
```

Covers: models, crypto (sign/verify/hash), KCPNode (publish, get, search, verify, lineage, stats).

See [docs/testing.md](../../docs/testing.md) for the full testing guide.
