# RFC-001: KCP Core Protocol Specification

**Status:** Draft — Active  
**Date:** 2026-03-20  
**Author:** Thiago Silva (tgosoul@gmail.com)  
**See also:** [rfcs/kcp-001-core.md](rfcs/kcp-001-core.md) — full IETF-style RFC

---

## Summary

KCP (Knowledge Context Protocol) is a Layer 8 protocol — above HTTP/OSI Layer 7 — that gives every AI-generated output a **persistent, signed, and traceable identity**.

## Core Operations

| Operation | SDK Method | Description |
|-----------|-----------|-------------|
| `PUBLISH` | `node.publish(...)` | Sign + store a knowledge artifact |
| `GET` | `node.get(id)` | Retrieve artifact by ID |
| `SEARCH` | `node.search(query)` | Full-text search across artifacts |
| `VERIFY` | `node.verify(id)` | Verify Ed25519 signature + content hash |
| `LINEAGE` | `node.lineage(id)` | Walk the parent→child DAG |
| `STATS` | `node.stats()` | Node statistics |

## Cryptographic Primitives

- **Signing:** Ed25519 (RFC 8032)
- **Content hash:** SHA-256 (artifact tamper detection)
- **Genesis fingerprint:** SHA-512 (protocol anchor — `GENESIS.json`)

## Connectivity

- **Local mode:** embedded in-process node, SQLite storage (`~/.kcp/kcp.db`)
- **Hub mode:** central corporate server, `KCP_HUB=<url>` env var
- **Federation:** hub-to-hub mTLS sync with ACL
- **MCP-compatible:** KCP artifacts are exposable as MCP resources

## Implementation Status

| SDK | Language | Tests | Status |
|-----|----------|-------|--------|
| Python | 3.13 | 61 ✅ | `sdk/python/` |
| TypeScript | Node.js 25 | 37 ✅ | `sdk/typescript/` |
| Go | 1.22 | 🔄 | `sdk/go/` |