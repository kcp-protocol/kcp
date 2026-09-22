//! Public-API integration tests for the embedded `KCPNode`.

use kcp::{
    derive_content_key, encrypt_content, hash_content, is_encrypted, KCPNode, Lineage, NodeConfig,
    PublishOptions,
};
use serde_json::json;

fn node_in(dir: &std::path::Path, user: &str, tenant: &str) -> KCPNode {
    KCPNode::new(NodeConfig::in_dir(dir, user, tenant)).expect("node boots")
}

fn node() -> (tempfile::TempDir, KCPNode) {
    let dir = tempfile::tempdir().unwrap();
    let node = node_in(dir.path(), "alice@acme.com", "acme-corp");
    (dir, node)
}

// ─── Construction / identity ─────────────────────────────────

#[test]
fn node_exposes_identity() {
    let (_dir, node) = node();
    assert_eq!(node.user_id, "alice@acme.com");
    assert_eq!(node.tenant_id, "acme-corp");
    assert_eq!(node.node_id().len(), 36);
}

#[test]
fn node_id_survives_reopen() {
    let dir = tempfile::tempdir().unwrap();
    let id = node_in(dir.path(), "u", "t").node_id();
    assert_eq!(node_in(dir.path(), "u", "t").node_id(), id);
}

#[test]
fn node_public_stats_shape() {
    let (_dir, node) = node();
    let stats = node.public_stats().unwrap();
    assert_eq!(stats["status"], json!("ok"));
    assert_eq!(stats["protocol"], json!("KCP/1"));
    assert_eq!(stats["kcp_version"], json!("0.2.0"));
    assert!(stats["node_id"].as_str().is_some());
    assert_eq!(stats["artifacts"], json!(0));
}

#[test]
fn node_stats_include_identity_and_sizes() {
    let (_dir, node) = node();
    let artifact = node.publish("Doc", b"hello", PublishOptions::new()).unwrap();
    let stats = node.stats().unwrap();
    assert_eq!(stats.node_id, node.node_id());
    assert_eq!(stats.user_id, "alice@acme.com");
    assert_eq!(stats.tenant_id, "acme-corp");
    assert_eq!(stats.artifacts, 1);
    assert_eq!(stats.content_size_bytes, 5);
    assert_eq!(stats.peers, 0);
    assert!(!stats.db_path.is_empty());
    assert!(!stats.db_size_human.is_empty());
    assert!(node.get(&artifact.id).unwrap().is_some());
}

#[test]
fn node_uses_configured_keys_dir() {
    let (dir, node) = node();
    assert!(dir.path().join("keys/private.key").exists());
    assert!(dir.path().join("keys/public.key").exists());
    assert_eq!(node.keys_dir(), dir.path().join("keys"));
}

// ─── Publish ─────────────────────────────────────────────────

#[test]
fn publish_returns_signed_artifact() {
    let (_dir, node) = node();
    let a = node
        .publish(
            "Auth Guide",
            b"content",
            PublishOptions::new().format("markdown").tags(vec!["auth".into()]),
        )
        .unwrap();
    assert_eq!(a.title, "Auth Guide");
    assert_eq!(a.format, "markdown");
    assert_eq!(a.tags, vec!["auth".to_string()]);
    assert_eq!(a.visibility, "public");
    assert_eq!(a.version, "1");
    assert_eq!(a.content_hash, hash_content(b"content"));
    assert_eq!(a.signature.len(), 128);
    assert_eq!(a.user_id, "alice@acme.com");
    assert_eq!(a.tenant_id, "acme-corp");
    assert!(node.verify(&a, None));
}

#[test]
fn publish_text_accepts_str_content() {
    let (_dir, node) = node();
    let a = node
        .publish_text("Notes", "Conteúdo ção", PublishOptions::new().format("text"))
        .unwrap();
    assert_eq!(a.content_hash, hash_content("Conteúdo ção".as_bytes()));
    assert_eq!(
        node.get_content(&a.id).unwrap().unwrap(),
        "Conteúdo ção".as_bytes()
    );
}

#[test]
fn publish_empty_content_is_allowed() {
    let (_dir, node) = node();
    let a = node.publish("Empty", b"", PublishOptions::new()).unwrap();
    assert_eq!(a.content_hash, hash_content(b""));
    assert!(node.verify(&a, None));
}

#[test]
fn publish_applies_summary_source_and_lineage() {
    let (_dir, node) = node();
    let a = node
        .publish(
            "Report",
            b"x",
            PublishOptions::new()
                .summary("quarterly numbers")
                .source("agent:analyst")
                .lineage(Lineage::new("revenue 2026").with_agent("analyst")),
        )
        .unwrap();
    assert_eq!(a.summary, "quarterly numbers");
    assert_eq!(a.source, "agent:analyst");
    assert_eq!(a.lineage.as_ref().unwrap().query, "revenue 2026");
    assert_eq!(a.lineage.as_ref().unwrap().agent, "analyst");
}

#[test]
fn publish_sets_visibility() {
    let (_dir, node) = node();
    let a = node
        .publish("Org doc", b"x", PublishOptions::new().visibility("org"))
        .unwrap();
    assert_eq!(a.visibility, "org");
}

#[test]
fn publish_different_content_yields_different_ids_and_hashes() {
    let (_dir, node) = node();
    let a = node.publish("A", b"one", PublishOptions::new()).unwrap();
    let b = node.publish("B", b"two", PublishOptions::new()).unwrap();
    assert_ne!(a.content_hash, b.content_hash);
    assert_ne!(a.id, b.id);
}

#[test]
fn private_publish_is_encrypted_at_rest_and_readable_by_owner() {
    let (_dir, node) = node();
    let secret = b"top secret information";
    let a = node
        .publish("Secret", secret, PublishOptions::new().visibility("private"))
        .unwrap();

    let raw = node.store.get_content(&a.content_hash).unwrap().unwrap();
    assert!(is_encrypted(&raw), "private content must be encrypted at rest");
    assert_ne!(raw, secret);
    assert!(node.can_decrypt(&a.id));
    assert_eq!(node.get_content(&a.id).unwrap().unwrap(), secret);
    assert!(node.verify(&a, None), "signature must cover the plaintext hash");
    assert_eq!(a.content_hash, hash_content(secret));
}

#[test]
fn public_content_is_stored_as_plaintext() {
    let (_dir, node) = node();
    let a = node
        .publish("Public", b"visible to all", PublishOptions::new())
        .unwrap();
    let raw = node.store.get_content(&a.content_hash).unwrap().unwrap();
    assert_eq!(raw, b"visible to all");
    assert!(!is_encrypted(&raw));
}

#[test]
fn encryption_key_depends_on_artifact_id() {
    let seed = [7u8; 32];
    let k1 = derive_content_key(&seed, "id-1");
    let k2 = derive_content_key(&seed, "id-2");
    assert_ne!(k1, k2);
    let blob = encrypt_content(b"secret", &k1).unwrap();
    assert_eq!(&blob[..7], b"KCPENC1");
    assert_eq!(blob.len(), 7 + 12 + 6 + 16);
}

#[test]
fn another_node_cannot_decrypt_private_content() {
    let (_dir_a, alice) = node();
    let (_dir_b, bob) = node();

    let secret = b"Alice's private note";
    let a = alice
        .publish("Private", secret, PublishOptions::new().visibility("private"))
        .unwrap();

    let payload = alice.store.get_artifact_with_content(&a.id).unwrap().unwrap();
    assert!(bob.store.import_artifact(&payload).unwrap());

    let raw = bob.store.get_content(&a.content_hash).unwrap().unwrap();
    assert!(is_encrypted(&raw), "blob stays encrypted on the receiving node");
    assert!(!bob.can_decrypt(&a.id));
    let got = bob.get_content(&a.id).unwrap().unwrap();
    assert_ne!(got, secret);
    // ...but Bob can still verify Alice's signature with her public key.
    assert!(bob.verify(&bob.get(&a.id).unwrap().unwrap(), Some(&alice.public_key())));
}

// ─── Get / search / list ─────────────────────────────────────

#[test]
fn get_unknown_artifact_returns_none() {
    let (_dir, node) = node();
    assert!(node.get("nope").unwrap().is_none());
    assert!(node.get_content("nope").unwrap().is_none());
}

#[test]
fn get_roundtrips_metadata() {
    let (_dir, node) = node();
    let a = node
        .publish("Doc", b"body", PublishOptions::new().summary("sum"))
        .unwrap();
    let got = node.get(&a.id).unwrap().unwrap();
    assert_eq!(got, a);
    assert_eq!(node.get_content(&a.id).unwrap().unwrap(), b"body");
}

#[test]
fn search_finds_published_artifact() {
    let (_dir, node) = node();
    let a = node
        .publish(
            "Kubernetes Networking",
            b"cni, cilium and bgp peering",
            PublishOptions::new(),
        )
        .unwrap();
    let resp = node.search("kubernetes", 20).unwrap();
    assert_eq!(resp.results.len(), 1);
    assert_eq!(resp.results[0].id, a.id);
    assert_eq!(resp.total, 1);
}

#[test]
fn search_empty_query_lists_everything() {
    let (_dir, node) = node();
    node.publish("A", b"aaa", PublishOptions::new()).unwrap();
    node.publish("B", b"bbb", PublishOptions::new()).unwrap();
    assert_eq!(node.search("", 20).unwrap().results.len(), 2);
}

#[test]
fn search_respects_limit_and_misses() {
    let (_dir, node) = node();
    for i in 0..4 {
        node.publish(&format!("doc {i}"), b"body", PublishOptions::new())
            .unwrap();
    }
    assert_eq!(node.search("doc", 2).unwrap().results.len(), 2);
    assert!(node.search("nothing-like-this", 20).unwrap().results.is_empty());
}

#[test]
fn search_does_not_index_encrypted_content() {
    let (_dir, node) = node();
    node.publish(
        "Secret Report",
        b"keyword-only-in-body",
        PublishOptions::new().visibility("private"),
    )
    .unwrap();
    assert_eq!(node.search("Secret", 20).unwrap().results.len(), 1);
    assert!(node.search("keyword-only-in-body", 20).unwrap().results.is_empty());
}

#[test]
fn list_returns_recent_artifacts() {
    let (_dir, node) = node();
    node.publish("One", b"1", PublishOptions::new()).unwrap();
    node.publish("Two", b"2", PublishOptions::new()).unwrap();
    assert_eq!(node.list(10, &[]).unwrap().len(), 2);
    assert_eq!(node.list(1, &[]).unwrap().len(), 1);
}

#[test]
fn list_filters_by_tags() {
    let (_dir, node) = node();
    node.publish("Tagged", b"1", PublishOptions::new().tags(vec!["finance".into()]))
        .unwrap();
    node.publish("Untagged", b"2", PublishOptions::new()).unwrap();
    let found = node.list(10, &["finance".to_string()]).unwrap();
    assert_eq!(found.len(), 1);
    assert_eq!(found[0].title, "Tagged");
}

// ─── Lineage ─────────────────────────────────────────────────

#[test]
fn lineage_of_root_has_one_entry() {
    let (_dir, node) = node();
    let root = node.publish("Root", b"r", PublishOptions::new()).unwrap();
    let chain = node.lineage(&root.id).unwrap();
    assert_eq!(chain.len(), 1);
    assert_eq!(chain[0].id, root.id);
    assert_eq!(chain[0].title, "Root");
}

#[test]
fn lineage_chain_is_root_first() {
    let (_dir, node) = node();
    let root = node.publish("Root", b"r", PublishOptions::new()).unwrap();
    let mid = node
        .publish("Mid", b"m", PublishOptions::new().derived_from(&root.id))
        .unwrap();
    let leaf = node
        .publish("Leaf", b"l", PublishOptions::new().derived_from(&mid.id))
        .unwrap();

    let chain = node.lineage(&leaf.id).unwrap();
    assert_eq!(
        chain.iter().map(|e| e.title.clone()).collect::<Vec<_>>(),
        vec!["Root", "Mid", "Leaf"]
    );
    assert_eq!(chain[0].author, "alice@acme.com");
}

#[test]
fn derivatives_lists_direct_children() {
    let (_dir, node) = node();
    let root = node.publish("Root", b"r", PublishOptions::new()).unwrap();
    node.publish("Child", b"c", PublishOptions::new().derived_from(&root.id))
        .unwrap();
    let kids = node.derivatives(&root.id).unwrap();
    assert_eq!(kids.len(), 1);
    assert_eq!(kids[0].title, "Child");
    assert!(node.derivatives("nope").unwrap().is_empty());
}

// ─── Delete ──────────────────────────────────────────────────

#[test]
fn delete_soft_deletes_and_hides_from_search() {
    let (_dir, node) = node();
    let a = node.publish("Ephemeral", b"temp", PublishOptions::new()).unwrap();
    assert!(node.delete(&a.id).unwrap());
    assert!(node.get(&a.id).unwrap().is_none());
    assert!(node.search("Ephemeral", 20).unwrap().results.is_empty());
    assert!(!node.delete(&a.id).unwrap());
    assert!(!node.delete("never-existed").unwrap());
}

// ─── Verify ──────────────────────────────────────────────────

#[test]
fn verify_rejects_tampered_artifact() {
    let (_dir, node) = node();
    let mut a = node.publish("Doc", b"content", PublishOptions::new()).unwrap();
    a.title = "Tampered".into();
    assert!(!node.verify(&a, None));
}

#[test]
fn verify_rejects_other_node_key_without_public_key() {
    let (_dir_a, alice) = node();
    let (_dir_b, bob) = node();
    let a = alice.publish("Doc", b"x", PublishOptions::new()).unwrap();
    assert!(!bob.verify(&a, None));
    assert!(bob.verify(&a, Some(&alice.public_key())));
}

#[test]
fn verify_signature_over_canonical_payload() {
    let (_dir, node) = node();
    let a = node.publish("Doc", b"x", PublishOptions::new()).unwrap();
    assert!(node.verify_signature(&a.canonical_bytes(), &a.signature, None));
    assert!(!node.verify_signature(b"other payload", &a.signature, None));
    assert!(!node.verify_signature(&a.canonical_bytes(), "not-a-signature", None));
}

// ─── Peers ───────────────────────────────────────────────────

#[test]
fn add_and_list_peers() {
    let (_dir, node) = node();
    let id = node.add_peer("https://peer.example", "peer one").unwrap();
    assert_eq!(id.len(), 36);
    let peers = node.get_peers().unwrap();
    assert_eq!(peers.len(), 1);
    assert_eq!(peers[0].url, "https://peer.example");
    assert_eq!(peers[0].name, "peer one");
}

#[test]
fn publish_enqueues_sync_for_public_only() {
    let dir = tempfile::tempdir().unwrap();
    let node = KCPNode::new(
        NodeConfig::in_dir(dir.path(), "u", "t")
            .with_peers(vec!["https://peer.example".to_string()]),
    )
    .unwrap();
    let public = node.publish("Pub", b"x", PublishOptions::new()).unwrap();
    node.publish("Priv", b"y", PublishOptions::new().visibility("private"))
        .unwrap();

    let queue = node.store.sync_queue_stats().unwrap();
    assert_eq!(queue.len(), 1, "only the public artifact is queued");
    assert_eq!(queue[0].2, 1);
    assert_eq!(node.store.get_artifact_ids_since(None).unwrap(), vec![public.id]);
}

// ─── Export / import (offline sharing) ───────────────────────

#[test]
fn export_and_import_roundtrip_between_nodes() {
    let (_dir_a, alice) = node();
    let (_dir_b, bob) = node();

    let a = alice
        .publish("Shared", b"payload bytes", PublishOptions::new())
        .unwrap();
    let export = alice.export_artifact(&a.id, true).unwrap().unwrap();
    assert_eq!(export["_kcp_export"]["version"], json!("1"));
    assert_eq!(
        export["_kcp_export"]["public_key"].as_str().unwrap(),
        hex::encode(alice.public_key())
    );

    let (ok, message) = bob.import_from_dict(&export, true).unwrap();
    assert!(ok, "{message}");
    assert!(message.contains("Imported"));
    assert_eq!(bob.get_content(&a.id).unwrap().unwrap(), b"payload bytes");
    assert!(bob.verify(&bob.get(&a.id).unwrap().unwrap(), Some(&alice.public_key())));

    let (again, message) = bob.import_from_dict(&export, true).unwrap();
    assert!(!again);
    assert!(message.contains("already exists"));
}

#[test]
fn import_rejects_tampered_export() {
    let (_dir_a, alice) = node();
    let (_dir_b, bob) = node();

    let a = alice.publish("Doc", b"x", PublishOptions::new()).unwrap();
    let mut export = alice.export_artifact(&a.id, true).unwrap().unwrap();
    export["title"] = json!("Tampered title");

    let (ok, message) = bob.import_from_dict(&export, true).unwrap();
    assert!(!ok);
    assert!(message.contains("FAILED"));
    assert!(bob.get(&a.id).unwrap().is_none());
}

#[test]
fn import_without_verification_accepts_anything() {
    let (_dir_a, alice) = node();
    let (_dir_b, bob) = node();
    let a = alice.publish("Doc", b"x", PublishOptions::new()).unwrap();
    let mut export = alice.export_artifact(&a.id, true).unwrap().unwrap();
    export["title"] = json!("Tampered title");
    let (ok, _) = bob.import_from_dict(&export, false).unwrap();
    assert!(ok);
}

#[test]
fn export_to_file_and_import_from_file() {
    let (dir_a, alice) = node();
    let (_dir_b, bob) = node();
    let a = alice
        .publish("Doc", b"file payload", PublishOptions::new())
        .unwrap();
    let path = alice
        .export_to_file(&a.id, dir_a.path().join("exports/doc.json"))
        .unwrap()
        .unwrap();
    assert!(path.exists());

    let (ok, _) = bob.import_from_file(&path, true).unwrap();
    assert!(ok);
    assert_eq!(bob.get_content(&a.id).unwrap().unwrap(), b"file payload");
}

#[test]
fn export_includes_lineage_when_deeper_than_one() {
    let (_dir, node) = node();
    let root = node.publish("Root", b"r", PublishOptions::new()).unwrap();
    let leaf = node
        .publish("Leaf", b"l", PublishOptions::new().derived_from(&root.id))
        .unwrap();

    let root_export = node.export_artifact(&root.id, true).unwrap().unwrap();
    assert!(root_export.get("_lineage").is_none());

    let leaf_export = node.export_artifact(&leaf.id, true).unwrap().unwrap();
    let lineage = leaf_export["_lineage"].as_array().unwrap();
    assert_eq!(lineage.len(), 2);
    assert_eq!(lineage[0]["title"], json!("Root"));
}

#[test]
fn export_without_content_omits_payload() {
    let (_dir, node) = node();
    let a = node.publish("Doc", b"secret-ish", PublishOptions::new()).unwrap();
    let export = node.export_artifact(&a.id, false).unwrap().unwrap();
    assert!(export.get("_content_b64").is_none());
    assert_eq!(export["title"], json!("Doc"));
}

#[test]
fn export_of_unknown_artifact_is_none() {
    let (_dir, node) = node();
    assert!(node.export_artifact("nope", true).unwrap().is_none());
    assert!(node
        .export_to_file("nope", std::env::temp_dir().join("never.json"))
        .unwrap()
        .is_none());
}
