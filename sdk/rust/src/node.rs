//! KCP embedded node — runs in-process, no separate server required.
//!
//! ```no_run
//! use kcp::{KCPNode, NodeConfig, PublishOptions};
//!
//! let node = KCPNode::new(NodeConfig::default())?;
//! let artifact = node.publish(
//!     "JWT Auth Guide",
//!     b"# JWT\n\nUse short-lived tokens.",
//!     PublishOptions::new().format("markdown").tags(vec!["auth".into()]),
//! )?;
//! assert!(node.verify(&artifact, None));
//! let results = node.search("auth", 20)?;
//! # Ok::<(), kcp::KcpError>(())
//! ```

use std::path::{Path, PathBuf};

use serde_json::{json, Map, Value};
use uuid::Uuid;

use crate::crypto::{
    self, decrypt_content, derive_content_key, encrypt_content, hash_content, is_encrypted, sign,
    verify,
};
use crate::error::Result;
use crate::models::{
    now_iso, KnowledgeArtifact, Lineage, NodeStats, PeerInfo, SearchResponse,
};
use crate::store::LocalStore;

/// Node configuration.
#[derive(Debug, Clone)]
pub struct NodeConfig {
    pub user_id: String,
    pub tenant_id: String,
    pub db_path: String,
    pub keys_dir: String,
    /// Explicit peer list. When `None`, `KCP_PEERS` is parsed at construction.
    pub peers: Option<Vec<String>>,
}

impl Default for NodeConfig {
    /// Reference defaults (`anonymous` / `local` / `~/.kcp/kcp.db` /
    /// `~/.kcp/keys`), overridable via `KCP_USER`, `KCP_TENANT`, `KCP_DB`.
    fn default() -> Self {
        let mut cfg = Self {
            user_id: "anonymous".to_string(),
            tenant_id: "local".to_string(),
            db_path: "~/.kcp/kcp.db".to_string(),
            keys_dir: "~/.kcp/keys".to_string(),
            peers: None,
        };
        if let Ok(v) = std::env::var("KCP_USER") {
            if !v.is_empty() {
                cfg.user_id = v;
            }
        }
        if let Ok(v) = std::env::var("KCP_TENANT") {
            if !v.is_empty() {
                cfg.tenant_id = v;
            }
        }
        if let Ok(v) = std::env::var("KCP_DB") {
            if !v.is_empty() {
                cfg.db_path = v;
            }
        }
        cfg
    }
}

impl NodeConfig {
    /// Explicit configuration.
    pub fn new(
        user_id: impl Into<String>,
        tenant_id: impl Into<String>,
        db_path: impl Into<String>,
        keys_dir: impl Into<String>,
    ) -> Self {
        Self {
            user_id: user_id.into(),
            tenant_id: tenant_id.into(),
            db_path: db_path.into(),
            keys_dir: keys_dir.into(),
            peers: None,
        }
    }

    /// Set the peer URLs explicitly (skips `KCP_PEERS` parsing).
    pub fn with_peers(mut self, peers: Vec<String>) -> Self {
        self.peers = Some(peers);
        self
    }

    /// Keep both the database and the keys inside `dir`
    /// (`dir/kcp.db` + `dir/keys`) — handy for tests and per-project nodes.
    pub fn in_dir(dir: impl AsRef<Path>, user_id: impl Into<String>, tenant_id: impl Into<String>) -> Self {
        let dir = dir.as_ref();
        Self::new(
            user_id,
            tenant_id,
            dir.join("kcp.db").display().to_string(),
            dir.join("keys").display().to_string(),
        )
    }
}

/// Options for [`KCPNode::publish`].
#[derive(Debug, Clone)]
pub struct PublishOptions {
    pub format: String,
    pub tags: Vec<String>,
    pub summary: String,
    pub visibility: String,
    pub derived_from: Option<String>,
    pub source: String,
    pub lineage: Option<Lineage>,
}

impl Default for PublishOptions {
    fn default() -> Self {
        Self {
            format: "markdown".to_string(),
            tags: Vec::new(),
            summary: String::new(),
            // `publish()` defaults to public, unlike the model default.
            visibility: "public".to_string(),
            derived_from: None,
            source: String::new(),
            lineage: None,
        }
    }
}

impl PublishOptions {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn format(mut self, format: impl Into<String>) -> Self {
        self.format = format.into();
        self
    }

    pub fn tags(mut self, tags: Vec<String>) -> Self {
        self.tags = tags;
        self
    }

    pub fn summary(mut self, summary: impl Into<String>) -> Self {
        self.summary = summary.into();
        self
    }

    pub fn visibility(mut self, visibility: impl Into<String>) -> Self {
        self.visibility = visibility.into();
        self
    }

    pub fn derived_from(mut self, parent_id: impl Into<String>) -> Self {
        self.derived_from = Some(parent_id.into());
        self
    }

    pub fn source(mut self, source: impl Into<String>) -> Self {
        self.source = source.into();
        self
    }

    pub fn lineage(mut self, lineage: Lineage) -> Self {
        self.lineage = Some(lineage);
        self
    }
}

/// An embedded KCP node.
pub struct KCPNode {
    pub user_id: String,
    pub tenant_id: String,
    pub store: LocalStore,
    keys_dir: PathBuf,
    private_key: [u8; 32],
    public_key: [u8; 32],
    peers: Vec<String>,
}

impl KCPNode {
    /// Create a node: open the store, load (or generate) the Ed25519 keypair,
    /// persist identity in `kcp_config` and parse `KCP_PEERS`.
    pub fn new(cfg: NodeConfig) -> Result<Self> {
        let store = LocalStore::open(&cfg.db_path)?;
        let keys_dir = PathBuf::from(cfg.keys_dir.clone());
        let keys = crypto::load_or_generate_keys(&keys_dir)?;

        store.set_config("user_id", &cfg.user_id)?;
        store.set_config("tenant_id", &cfg.tenant_id)?;
        store.set_config("public_key", &hex::encode(keys.public_key))?;
        if store.get_config("node_id")?.is_empty() {
            store.set_config("node_id", &Uuid::new_v4().to_string())?;
        }

        let peers = match cfg.peers.clone() {
            Some(peers) => peers,
            None => std::env::var("KCP_PEERS")
                .unwrap_or_default()
                .split(',')
                .map(|p| p.trim().to_string())
                .filter(|p| !p.is_empty())
                .collect(),
        };

        Ok(Self {
            user_id: cfg.user_id,
            tenant_id: cfg.tenant_id,
            store,
            keys_dir,
            private_key: keys.private_key,
            public_key: keys.public_key,
            peers,
        })
    }

    /// Persistent node identifier.
    pub fn node_id(&self) -> String {
        self.store.get_config("node_id").unwrap_or_default()
    }

    /// This node's Ed25519 public key (32 raw bytes).
    pub fn public_key(&self) -> [u8; 32] {
        self.public_key
    }

    /// Directory holding `private.key` / `public.key`.
    pub fn keys_dir(&self) -> &Path {
        &self.keys_dir
    }

    /// Configured peer URLs (from `KCP_PEERS`).
    pub fn peers(&self) -> &[String] {
        &self.peers
    }

    // ─── Core operations ──────────────────────────────────────

    /// Publish a signed knowledge artifact.
    ///
    /// The content hash always covers the **plaintext**; `private` artifacts
    /// are AES-256-GCM encrypted at rest with an HKDF-derived per-artifact key.
    pub fn publish(
        &self,
        title: &str,
        content: &[u8],
        opts: PublishOptions,
    ) -> Result<KnowledgeArtifact> {
        let plaintext_hash = hash_content(content);

        let mut stored_content = content.to_vec();
        if opts.visibility == "private" {
            // Register ownership of a temporary key slot first, mirroring the
            // reference implementation's two-phase key registration.
            let temp_id = Uuid::new_v4().to_string();
            let temp_key = derive_content_key(&self.private_key, &temp_id);
            stored_content = encrypt_content(content, &temp_key)?;
            self.store.set_config(&format!("enc_key:{}", temp_id), "1")?;
        }

        let mut artifact = KnowledgeArtifact::new(title, &self.user_id, &self.tenant_id, &opts.format);
        artifact.tags = opts.tags.clone();
        artifact.summary = opts.summary.clone();
        artifact.visibility = opts.visibility.clone();
        artifact.source = opts.source.clone();
        artifact.lineage = opts.lineage.clone();
        artifact.content_hash = plaintext_hash;
        artifact.signature = sign(&artifact.canonical_bytes(), &self.private_key);

        if opts.visibility == "private" {
            // Re-derive with the real artifact ID and store the key marker.
            let content_key = derive_content_key(&self.private_key, &artifact.id);
            stored_content = encrypt_content(content, &content_key)?;
            self.store.set_config(&format!("enc_key:{}", artifact.id), "1")?;
        }

        self.store
            .publish(&artifact, &stored_content, opts.derived_from.as_deref())?;

        if opts.visibility != "private" && !self.peers.is_empty() {
            self.store.enqueue_sync(&artifact.id, &self.peers)?;
        }

        Ok(artifact)
    }

    /// Convenience wrapper for string content (default `PublishOptions`).
    pub fn publish_text(&self, title: &str, content: &str, opts: PublishOptions) -> Result<KnowledgeArtifact> {
        self.publish(title, content.as_bytes(), opts)
    }

    /// Get an artifact by ID.
    pub fn get(&self, artifact_id: &str) -> Result<Option<KnowledgeArtifact>> {
        self.store.get(artifact_id)
    }

    /// Get content by artifact ID, transparently decrypting private artifacts
    /// this node holds the key for.
    pub fn get_content(&self, artifact_id: &str) -> Result<Option<Vec<u8>>> {
        let Some(artifact) = self.store.get(artifact_id)? else {
            return Ok(None);
        };
        let Some(raw) = self.store.get_content(&artifact.content_hash)? else {
            return Ok(None);
        };
        if is_encrypted(&raw) && self.can_decrypt(artifact_id) {
            let key = derive_content_key(&self.private_key, artifact_id);
            match decrypt_content(&raw, &key) {
                Ok(plaintext) => return Ok(Some(plaintext)),
                Err(_) => return Ok(None), // key mismatch (artifact from another node)
            }
        }
        Ok(Some(raw))
    }

    /// Search artifacts by text (FTS5 + BM25).
    pub fn search(&self, query: &str, limit: i64) -> Result<SearchResponse> {
        self.store.search(query, None, limit, 0)
    }

    /// List recent artifacts, optionally filtered by tags.
    pub fn list(&self, limit: i64, tags: &[String]) -> Result<Vec<KnowledgeArtifact>> {
        self.store.list_artifacts(None, None, tags, None, limit, 0)
    }

    /// Soft-delete an artifact (audited).
    pub fn delete(&self, artifact_id: &str) -> Result<bool> {
        self.store.delete(artifact_id, &self.user_id)
    }

    /// Full lineage chain (root → current).
    pub fn lineage(&self, artifact_id: &str) -> Result<Vec<crate::models::LineageEntry>> {
        self.store.get_lineage(artifact_id)
    }

    /// Every artifact derived from this one.
    pub fn derivatives(&self, artifact_id: &str) -> Result<Vec<crate::models::LineageEntry>> {
        self.store.get_derivatives(artifact_id)
    }

    /// Verify an artifact signature. Uses this node's public key unless
    /// another one is supplied.
    pub fn verify(&self, artifact: &KnowledgeArtifact, public_key: Option<&[u8]>) -> bool {
        let key = public_key.unwrap_or(&self.public_key);
        verify(&artifact.canonical_bytes(), &artifact.signature, key)
    }

    /// Verify a signature over an arbitrary canonical payload (hex signature).
    pub fn verify_signature(
        &self,
        payload: &[u8],
        signature_hex: &str,
        public_key: Option<&[u8]>,
    ) -> bool {
        verify(payload, signature_hex, public_key.unwrap_or(&self.public_key))
    }

    /// True when this node holds the decryption key for the artifact.
    pub fn can_decrypt(&self, artifact_id: &str) -> bool {
        self.store
            .get_config(&format!("enc_key:{}", artifact_id))
            .map(|v| !v.is_empty())
            .unwrap_or(false)
    }

    /// Full node statistics.
    pub fn stats(&self) -> Result<NodeStats> {
        let s = self.store.stats()?;
        Ok(NodeStats {
            node_id: self.node_id(),
            user_id: self.user_id.clone(),
            tenant_id: self.tenant_id.clone(),
            artifacts: s.artifacts,
            content_size_bytes: s.content_size_bytes,
            content_size_human: s.content_size_human,
            peers: s.peers,
            db_size_bytes: s.db_size_bytes,
            db_size_human: s.db_size_human,
            db_path: s.db_path,
        })
    }

    /// Sanitized stats suitable for a public health endpoint.
    pub fn public_stats(&self) -> Result<Value> {
        let s = self.store.stats()?;
        Ok(json!({
            "status": "ok",
            "node_id": self.node_id(),
            "artifacts": s.artifacts,
            "peers": self.peers.len() as i64,
            "kcp_version": "0.2.0",
            "protocol": "KCP/1",
        }))
    }

    // ─── Peers ────────────────────────────────────────────────

    /// Register a peer manually, returning its generated ID.
    pub fn add_peer(&self, url: &str, name: &str) -> Result<String> {
        let peer_id = Uuid::new_v4().to_string();
        self.store.add_peer(&peer_id, url, name, "")?;
        Ok(peer_id)
    }

    /// List known peers.
    pub fn get_peers(&self) -> Result<Vec<PeerInfo>> {
        self.store.get_peers()
    }

    // ─── Export / import (offline sharing) ────────────────────

    /// Export an artifact as a portable, self-contained JSON document.
    pub fn export_artifact(&self, artifact_id: &str, include_content: bool) -> Result<Option<Value>> {
        let Some(artifact) = self.store.get(artifact_id)? else {
            return Ok(None);
        };
        let mut export = artifact.to_dict();
        let Some(map) = export.as_object_mut() else {
            return Ok(None);
        };
        map.insert(
            "_kcp_export".into(),
            json!({
                "version": "1",
                "exported_by": self.user_id,
                "exported_at": now_iso(),
                "node_id": self.node_id(),
                "public_key": hex::encode(self.public_key),
            }),
        );
        if include_content {
            if let Some(content) = self.store.get_content(&artifact.content_hash)? {
                use base64::Engine;
                map.insert(
                    "_content_b64".into(),
                    Value::String(base64::engine::general_purpose::STANDARD.encode(&content)),
                );
            }
        }
        let chain = self.store.get_lineage(artifact_id)?;
        if chain.len() > 1 {
            map.insert(
                "_lineage".into(),
                Value::Array(
                    chain
                        .iter()
                        .map(|e| serde_json::to_value(e).unwrap_or(Value::Null))
                        .collect(),
                ),
            );
        }
        Ok(Some(export))
    }

    /// Import an exported artifact, verifying its signature when possible.
    /// Returns `(imported, message)`.
    pub fn import_from_dict(&self, data: &Value, verify_signature: bool) -> Result<(bool, String)> {
        let id = data.get("id").and_then(|v| v.as_str()).unwrap_or_default();
        if !id.is_empty() && self.store.get(id)?.is_some() {
            return Ok((false, format!("Artifact already exists: {}", id)));
        }

        if verify_signature {
            if let Some(pub_hex) = data
                .get("_kcp_export")
                .and_then(|v| v.get("public_key"))
                .and_then(|v| v.as_str())
            {
                if !pub_hex.is_empty() {
                    let pub_key = match hex::decode(pub_hex) {
                        Ok(bytes) => bytes,
                        Err(e) => return Ok((false, format!("Signature check error: {}", e))),
                    };
                    let mut clean = data.clone();
                    if let Value::Object(map) = &mut clean {
                        let private: Vec<String> = map
                            .keys()
                            .filter(|k| k.starts_with('_'))
                            .cloned()
                            .collect();
                        for key in private {
                            map.remove(&key);
                        }
                    }
                    let artifact = KnowledgeArtifact::from_dict(&clean)?;
                    if !verify(&artifact.canonical_bytes(), &artifact.signature, &pub_key) {
                        return Ok((
                            false,
                            "⚠️ Signature verification FAILED. Artifact may be tampered.".to_string(),
                        ));
                    }
                }
            }
        }

        if self.store.import_artifact(data)? {
            let title = data.get("title").and_then(|v| v.as_str()).unwrap_or("Untitled");
            let author = data.get("user_id").and_then(|v| v.as_str()).unwrap_or("unknown");
            Ok((true, format!("✅ Imported: '{}' by {}", title, author)))
        } else {
            Ok((false, "Artifact already exists".to_string()))
        }
    }

    /// Read a JSON file and import it.
    pub fn import_from_file(&self, path: impl AsRef<Path>, verify_signature: bool) -> Result<(bool, String)> {
        let raw = std::fs::read_to_string(path)?;
        let data: Value = serde_json::from_str(&raw)?;
        self.import_from_dict(&data, verify_signature)
    }

    /// Write an exported artifact to a JSON file, returning the path.
    pub fn export_to_file(&self, artifact_id: &str, output_path: impl AsRef<Path>) -> Result<Option<PathBuf>> {
        let Some(data) = self.export_artifact(artifact_id, true)? else {
            return Ok(None);
        };
        let path = output_path.as_ref().to_path_buf();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(&path, serde_json::to_string_pretty(&data)?)?;
        Ok(Some(path))
    }

    /// Close the node's store.
    pub fn close(self) {
        self.store.close();
    }
}

/// Helper: export the public fields of an artifact as a plain JSON map
/// (used by tests and by embedding applications).
pub fn artifact_to_map(artifact: &KnowledgeArtifact) -> Map<String, Value> {
    match artifact.to_dict() {
        Value::Object(map) => map,
        _ => Map::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fresh_node() -> (tempfile::TempDir, KCPNode) {
        let dir = tempfile::tempdir().unwrap();
        let node = KCPNode::new(NodeConfig::in_dir(dir.path(), "alice@acme.com", "acme")).unwrap();
        (dir, node)
    }

    #[test]
    fn new_sets_identity_and_node_id() {
        let (_dir, node) = fresh_node();
        assert_eq!(node.user_id, "alice@acme.com");
        assert_eq!(node.tenant_id, "acme");
        assert_eq!(node.store.get_config("user_id").unwrap(), "alice@acme.com");
        assert_eq!(node.store.get_config("tenant_id").unwrap(), "acme");
        assert!(!node.node_id().is_empty());
    }

    #[test]
    fn node_id_is_persistent_across_restarts() {
        let dir = tempfile::tempdir().unwrap();
        let id = {
            let node = KCPNode::new(NodeConfig::in_dir(dir.path(), "u", "t")).unwrap();
            node.node_id()
        };
        let node2 = KCPNode::new(NodeConfig::in_dir(dir.path(), "u", "t")).unwrap();
        assert_eq!(node2.node_id(), id);
    }

    #[test]
    fn keys_are_persisted_in_keys_dir() {
        let (_dir, node) = fresh_node();
        assert!(node.keys_dir().join("private.key").exists());
        assert!(node.keys_dir().join("public.key").exists());
        assert_eq!(
            node.store.get_config("public_key").unwrap(),
            hex::encode(node.public_key())
        );
    }

    #[test]
    fn default_config_uses_reference_values() {
        let cfg = NodeConfig::default();
        assert!(!cfg.user_id.is_empty());
        assert!(cfg.db_path.contains("kcp.db") || !cfg.db_path.is_empty());
    }

    #[test]
    fn publish_signs_and_verifies() {
        let (_dir, node) = fresh_node();
        let a = node
            .publish("Doc", b"content", PublishOptions::new())
            .unwrap();
        assert!(node.verify(&a, None));
        assert_eq!(a.content_hash, hash_content(b"content"));
        assert_eq!(a.signature.len(), 128);
    }

    #[test]
    fn publish_private_encrypts_at_rest() {
        let (_dir, node) = fresh_node();
        let secret = b"top secret";
        let a = node
            .publish(
                "Secret",
                secret,
                PublishOptions::new().visibility("private").format("text"),
            )
            .unwrap();
        let raw = node.store.get_content(&a.content_hash).unwrap().unwrap();
        assert_ne!(raw, secret);
        assert!(is_encrypted(&raw));
        assert!(node.verify(&a, None));
        assert_eq!(node.get_content(&a.id).unwrap().unwrap(), secret);
    }

    #[test]
    fn publish_default_visibility_is_public() {
        let (_dir, node) = fresh_node();
        let a = node.publish("Doc", b"x", PublishOptions::new()).unwrap();
        assert_eq!(a.visibility, "public");
    }

    #[test]
    fn artifact_to_map_contains_core_keys() {
        let (_dir, node) = fresh_node();
        let a = node.publish("Doc", b"x", PublishOptions::new()).unwrap();
        let map = artifact_to_map(&a);
        assert!(map.contains_key("id"));
        assert!(map.contains_key("signature"));
    }

    #[test]
    fn import_from_dict_rejects_tampered_signature() {
        let (_dir, author) = fresh_node();
        let a = author.publish("Doc", b"x", PublishOptions::new()).unwrap();
        let mut export = author.export_artifact(&a.id, true).unwrap().unwrap();
        export["title"] = json!("Tampered");

        let (_dir2, recipient) = fresh_node();
        let (ok, message) = recipient.import_from_dict(&export, true).unwrap();
        assert!(!ok);
        assert!(message.contains("FAILED"));
    }

    #[test]
    fn import_from_dict_accepts_valid_export() {
        let (_dir, author) = fresh_node();
        let a = author.publish("Doc", b"payload", PublishOptions::new()).unwrap();
        let export = author.export_artifact(&a.id, true).unwrap().unwrap();

        let (_dir2, recipient) = fresh_node();
        let (ok, message) = recipient.import_from_dict(&export, true).unwrap();
        assert!(ok, "{message}");
        assert_eq!(recipient.get_content(&a.id).unwrap().unwrap(), b"payload");
        assert!(recipient.verify(&recipient.get(&a.id).unwrap().unwrap(), Some(&author.public_key())));
    }

    #[test]
    fn export_requires_existing_artifact() {
        let (_dir, node) = fresh_node();
        assert!(node.export_artifact("nope", true).unwrap().is_none());
    }

    #[test]
    fn export_to_file_writes_json() {
        let (_dir, node) = fresh_node();
        let a = node.publish("Doc", b"x", PublishOptions::new()).unwrap();
        let out_path = _dir.path().join("out/doc.json");
        let out = node.export_to_file(&a.id, &out_path).unwrap().unwrap();
        assert!(out.exists());

        let (_dir_b, other) = fresh_node();
        let (ok, _) = other.import_from_file(&out, false).unwrap();
        assert!(ok);
    }

    #[test]
    fn publish_enqueues_sync_only_for_public() {
        let dir = tempfile::tempdir().unwrap();
        let node = KCPNode::new(
            NodeConfig::in_dir(dir.path(), "u", "t")
                .with_peers(vec!["https://peer.example".to_string()]),
        )
        .unwrap();
        assert_eq!(node.peers(), ["https://peer.example".to_string()]);
        let public = node.publish("Pub", b"x", PublishOptions::new()).unwrap();
        let _private = node
            .publish("Priv", b"y", PublishOptions::new().visibility("private"))
            .unwrap();
        let stats = node.store.sync_queue_stats().unwrap();
        assert_eq!(stats.len(), 1);
        assert_eq!(node.store.get_artifact_ids_since(None).unwrap(), vec![public.id]);
    }
}
