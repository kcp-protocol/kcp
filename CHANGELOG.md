# Changelog

All notable changes to KCP are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
for the SDKs and the node HTTP API. The protocol itself is versioned separately
through RFCs in `rfcs/`.

## [Unreleased] — 0.2.0

### Added

- **Python SDK: opt-in vector/semantic search** — embedding providers (`hash`
  hashing-trick default, Ollama, OpenAI-compatible, callable), vector index with
  an exact pure-Python fallback and optional `sqlite-vss`, hybrid keyword+vector
  ranking, and lifecycle filters on the semantic path ([#6]).
- **Lineage conflict resolution** — Merkle DAG proofs plus a G-Set CRDT merge for
  concurrent lineage edits; published as RFC **KCP-005** ([#7], [#13]).
- **Rust SDK** — Ed25519/SHA-256 parity with the Python SDK and a SQLite
  backend, so services can embed a KCP node without Python ([#8]).
- **Artifact TTL/expiry and versioning** — artifacts can expire, be superseded,
  and be queried per version/canonical id ([#9]).
- **Web UI for a local node** — served at `/ui` by `KCPNode.serve()`: search
  (keyword/semantic/hybrid), artifact detail with hash and signature, lineage,
  replication state and network stats ([#5]).
- Changelog, `CODE_OF_CONDUCT.md`, `SECURITY.md`, issue and PR templates.

### Changed

- `docs/peers.json` registry: `node_id` values refreshed after the 2026-09-21
  peer reset; the daily peer health check keeps it honest ([#12]).

### Fixed

- **CI quality gates** — Ruff went from 376 findings to zero and the SDK is
  formatted consistently, so `Code Quality` is green and blocking again ([#15]);
  the 26 SonarCloud new-code findings (float equality, local HTTP endpoint,
  cognitive complexity, duplicated SQL literals, test refactors) are resolved and
  the SonarCloud Quality Gate on `main` is **OK** again ([#18]).

[#5]: https://github.com/kcp-protocol/kcp/issues/5
[#6]: https://github.com/kcp-protocol/kcp/pull/6
[#7]: https://github.com/kcp-protocol/kcp/pull/7
[#8]: https://github.com/kcp-protocol/kcp/pull/8
[#9]: https://github.com/kcp-protocol/kcp/pull/9
[#12]: https://github.com/kcp-protocol/kcp/pull/12
[#13]: https://github.com/kcp-protocol/kcp/pull/13
[#15]: https://github.com/kcp-protocol/kcp/pull/15
[#16]: https://github.com/kcp-protocol/kcp/issues/16
[#18]: https://github.com/kcp-protocol/kcp/pull/18

## [0.1.0] — published on PyPI

Initial public SDK release (`kcp-protocol` on PyPI): artifacts with Ed25519
signatures, content-addressed store, keyword search, peer registry and
gossip-based sync, plus the protocol spec and the MCP server.
