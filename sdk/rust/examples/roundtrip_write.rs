//! Write a KCP database with the Rust SDK.
//!
//! Used by `tests/fixtures/verify_rust_db.py` to prove that the reference
//! Python SDK can read (and verify) a database produced by this crate.
//!
//! ```bash
//! cargo run --example roundtrip_write -- /tmp/kcp-db
//! ```

use kcp::{KCPNode, Lineage, NodeConfig, PublishOptions};
use serde_json::json;
use std::path::PathBuf;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let dir: PathBuf = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "/tmp/kcp-rust-db".to_string())
        .into();
    std::fs::create_dir_all(&dir)?;

    let node = KCPNode::new(NodeConfig::in_dir(&dir, "alice@acme.com", "acme-corp"))?;

    let root = node.publish(
        "Rust written artifact",
        b"# Rust to Python\n\nWritten by the Rust SDK, read by the Python reference.",
        PublishOptions::new()
            .format("markdown")
            .tags(vec!["rust".into(), "interop".into()])
            .summary("schema + signature cross-language check")
            .source("agent:rust-sdk")
            .lineage(Lineage::new("cross-language verification").with_agent("rust-sdk")),
    )?;

    let derived = node.publish(
        "Rust derived artifact",
        b"# Derived\n\nSecond generation artifact.",
        PublishOptions::new()
            .format("text")
            .derived_from(&root.id)
            .summary("child of the first artifact"),
    )?;

    let secret = node.publish(
        "Rust private artifact",
        b"encrypted payload written by rust",
        PublishOptions::new().format("text").visibility("private"),
    )?;

    let report = json!({
        "db_path": node.store.db_path().display().to_string(),
        "keys_dir": node.keys_dir().display().to_string(),
        "node_id": node.node_id(),
        "public_key_hex": hex::encode(node.public_key()),
        "artifacts": [
            {"id": root.id, "title": root.title, "content_hash": root.content_hash,
             "signature": root.signature, "visibility": root.visibility},
            {"id": derived.id, "title": derived.title, "content_hash": derived.content_hash,
             "signature": derived.signature, "visibility": derived.visibility,
             "derived_from": root.id},
            {"id": secret.id, "title": secret.title, "content_hash": secret.content_hash,
             "signature": secret.signature, "visibility": secret.visibility},
        ],
    });
    println!("{}", serde_json::to_string_pretty(&report)?);

    let out = std::env::var("KCP_EXAMPLE_REPORT").unwrap_or_else(|_| {
        dir.join("rust_report.json").display().to_string()
    });
    std::fs::write(out, serde_json::to_string_pretty(&report)?)?;
    Ok(())
}
