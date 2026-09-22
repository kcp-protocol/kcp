//! # KCP — Knowledge Context Protocol (Rust SDK)
//!
//! Rust implementation of the KCP SDK, byte-compatible with the reference
//! Python implementation (`sdk/python/kcp`) and with the Go SDK
//! (`sdk/go`): same canonical payload, same Ed25519 signatures, same SHA-256
//! content hashes, same AES-256-GCM content encryption and the same SQLite +
//! FTS5 storage schema.
//!
//! ## Quick start (embedded — no server required)
//!
//! ```no_run
//! use kcp::{KCPNode, NodeConfig, PublishOptions, Lineage};
//!
//! let node = KCPNode::new(NodeConfig::in_dir("~/.kcp", "alice@acme.com", "acme-corp"))?;
//!
//! // Publish a signed knowledge artifact.
//! let artifact = node.publish(
//!     "JWT Auth Guide",
//!     b"# JWT\n\nShort-lived tokens with rotating refresh keys.",
//!     PublishOptions::new()
//!         .format("markdown")
//!         .tags(vec!["auth".into(), "jwt".into()])
//!         .summary("How the auth service issues tokens"),
//! )?;
//!
//! // Discover it again.
//! let results = node.search("auth", 20)?;
//! assert_eq!(results.results[0].id, artifact.id);
//!
//! // Verify the signature (tamper-evident).
//! assert!(node.verify(&artifact, None));
//!
//! // Track provenance.
//! let derived = node.publish(
//!     "JWT Auth Guide (v2)",
//!     b"# JWT v2",
//!     PublishOptions::new().derived_from(&artifact.id),
//! )?;
//! let chain = node.lineage(&derived.id)?;
//! assert_eq!(chain.len(), 2);
//! # Ok::<(), kcp::KcpError>(())
//! ```
//!
//! ## Compatibility matrix
//!
//! | Concern | Reference (Python) | Rust |
//! |---|---|---|
//! | Signed payload | `json.dumps(to_dict(), sort_keys=True, separators=(",",":"))` | [`models::KnowledgeArtifact::canonical_json`] |
//! | Signature | Ed25519 over the canonical JSON, hex | [`crypto::sign`] |
//! | Content hash | SHA-256 of the plaintext, lowercase hex | [`crypto::hash_content`] |
//! | Private content | HKDF-SHA256 key + AES-256-GCM, `KCPENC1` prefix | [`crypto::derive_content_key`], [`crypto::encrypt_content`] |
//! | Storage | SQLite + FTS5 (`kcp_artifacts`, `kcp_content`, `kcp_audit`, `kcp_config`, `kcp_fts`) | [`store`] |
//!
//! Cross-language vectors produced by the Python SDK live in
//! `tests/fixtures/vectors.json` (regenerate with
//! `tests/fixtures/gen_vectors.py`).

pub mod canon;
pub mod crypto;
pub mod error;
pub mod models;
pub mod node;
pub mod store;

pub use canon::{canonical_bytes, canonical_json};
pub use crypto::{
    decrypt_content, derive_content_key, derive_public_key, encrypt_content, generate_keypair,
    hash_content, is_encrypted, keypair_from_seed, load_keys, load_or_generate_keys, save_keys,
    sign, verify, KeyPair, ENCRYPTION_MAGIC,
};
pub use error::{KcpError, Result};
pub use models::{
    human_size, now_iso, KnowledgeArtifact, Lineage, LineageEntry, NodeStats, PeerInfo, SearchResponse,
    SearchResult, StoreStats, ACL,
};
pub use node::{artifact_to_map, KCPNode, NodeConfig, PublishOptions};
pub use store::{AuditEntry, LocalStore, SyncItem};

/// Crate version (`Cargo.toml`).
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

/// KCP SDK version implemented by this crate.
pub const KCP_VERSION: &str = "0.2.0";

/// KCP wire protocol version.
pub const PROTOCOL_VERSION: &str = "1";
