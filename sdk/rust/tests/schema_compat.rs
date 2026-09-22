//! Storage-schema compatibility tests.
//!
//! These assert that the Rust SDK writes the same SQLite schema as the Python
//! reference (`sdk/python/kcp/store.py`): same tables, same columns in the same
//! order, same FTS5 table/tokenizer — and that rows written by a "Python-shaped"
//! INSERT are readable through the Rust API.

use kcp::{KnowledgeArtifact, LocalStore, PublishOptions, KCPNode, NodeConfig};
use rusqlite::params;

fn store() -> LocalStore {
    LocalStore::open_in_memory().unwrap()
}

fn table_names(store: &LocalStore) -> Vec<String> {
    let mut stmt = store
        .connection()
        .prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        .unwrap();
    let rows = stmt.query_map([], |r| r.get::<_, String>(0)).unwrap();
    rows.map(|r| r.unwrap()).collect()
}

fn column_names(store: &LocalStore, table: &str) -> Vec<String> {
    let mut stmt = store
        .connection()
        .prepare(&format!("PRAGMA table_info({})", table))
        .unwrap();
    let rows = stmt.query_map([], |r| r.get::<_, String>(1)).unwrap();
    rows.map(|r| r.unwrap()).collect()
}

#[test]
fn creates_every_reference_table() {
    let names = table_names(&store());
    for table in [
        "kcp_artifacts",
        "kcp_audit",
        "kcp_config",
        "kcp_content",
        "kcp_fts",
        "kcp_peers",
        "kcp_replication",
        "kcp_sync_log",
        "kcp_sync_queue",
    ] {
        assert!(names.contains(&table.to_string()), "missing table {table}");
    }
}

#[test]
fn artifacts_columns_match_reference_order() {
    let cols = column_names(&store(), "kcp_artifacts");
    assert_eq!(
        cols,
        vec![
            "id",
            "version",
            "user_id",
            "tenant_id",
            "team",
            "tags",
            "source",
            "created_at",
            "format",
            "visibility",
            "title",
            "summary",
            "lineage",
            "content_hash",
            "content_url",
            "signature",
            "acl",
            "derived_from",
            "deleted_at",
        ]
    );
}

#[test]
fn content_columns_match_reference() {
    assert_eq!(
        column_names(&store(), "kcp_content"),
        vec!["content_hash", "content", "size_bytes"]
    );
    assert_eq!(
        column_names(&store(), "kcp_audit"),
        vec!["id", "timestamp", "user_id", "action", "artifact_id", "details"]
    );
    assert_eq!(column_names(&store(), "kcp_config"), vec!["key", "value"]);
}

#[test]
fn fts_table_has_reference_columns_and_tokenizer() {
    let s = store();
    assert_eq!(
        column_names(&s, "kcp_fts"),
        vec!["id", "title", "summary", "tags", "source", "content_text"]
    );
    let sql: String = s
        .connection()
        .query_row(
            "SELECT sql FROM sqlite_master WHERE name = 'kcp_fts'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert!(sql.contains("fts5"), "{sql}");
    assert!(sql.contains("porter unicode61"), "{sql}");
    assert!(sql.contains("UNINDEXED"), "{sql}");
}

#[test]
fn reference_indexes_exist() {
    let s = store();
    let mut stmt = s
        .connection()
        .prepare("SELECT name FROM sqlite_master WHERE type='index' ORDER BY name")
        .unwrap();
    let indexes: Vec<String> = stmt
        .query_map([], |r| r.get::<_, String>(0))
        .unwrap()
        .map(|r| r.unwrap())
        .collect();
    for expected in [
        "idx_artifacts_tenant",
        "idx_artifacts_user",
        "idx_artifacts_hash",
        "idx_artifacts_created",
        "idx_artifacts_derived",
        "idx_sync_queue_status",
        "idx_sync_queue_artifact",
        "idx_replication_artifact",
    ] {
        assert!(indexes.contains(&expected.to_string()), "missing {expected}");
    }
}

#[test]
fn wal_journal_mode_is_enabled() {
    let dir = tempfile::tempdir().unwrap();
    let s = LocalStore::open(dir.path().join("kcp.db")).unwrap();
    let mode: String = s
        .connection()
        .query_row("PRAGMA journal_mode", [], |r| r.get(0))
        .unwrap();
    assert_eq!(mode.to_lowercase(), "wal");
}

#[test]
fn reads_artifact_rows_written_by_the_python_shaped_insert() {
    let s = store();
    // Exactly what sdk/python/kcp/store.py `LocalStore.publish` executes.
    s.connection()
        .execute(
            "INSERT OR REPLACE INTO kcp_artifacts
             (id, version, user_id, tenant_id, team, tags, source, created_at,
              format, visibility, title, summary, lineage, content_hash,
              content_url, signature, acl, derived_from)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            params![
                "py-artifact",
                "1",
                "alice@acme.com",
                "acme-corp",
                "finance",
                "[\"finance\",\"q1\"]",
                "agent:analyst",
                "2026-01-02T03:04:05.123456+00:00",
                "markdown",
                "public",
                "Python written row",
                "summary from python",
                "{\"query\":\"q\",\"data_sources\":[\"s\"],\"agent\":\"\",\"parent_reports\":[]}",
                "hash123",
                "https://cdn/x.md",
                "sighex",
                "{\"allowed_tenants\":[],\"allowed_users\":[\"u\"],\"allowed_teams\":[]}",
                Option::<String>::None,
            ],
        )
        .unwrap();
    s.connection()
        .execute(
            "INSERT INTO kcp_content (content_hash, content, size_bytes) VALUES (?, ?, ?)",
            params!["hash123", b"python blob".to_vec(), 11_i64],
        )
        .unwrap();

    let artifact = s.get("py-artifact").unwrap().unwrap();
    assert_eq!(artifact.title, "Python written row");
    assert_eq!(artifact.tags, vec!["finance".to_string(), "q1".to_string()]);
    assert_eq!(artifact.team.as_deref(), Some("finance"));
    assert_eq!(artifact.lineage.as_ref().unwrap().query, "q");
    assert_eq!(
        artifact.acl.as_ref().unwrap().allowed_users,
        vec!["u".to_string()]
    );
    assert_eq!(
        artifact.timestamp,
        "2026-01-02T03:04:05.123456+00:00",
        "created_at maps back to timestamp"
    );
    assert_eq!(s.get_content("hash123").unwrap().unwrap(), b"python blob");
}

#[test]
fn soft_deleted_rows_are_invisible() {
    let s = store();
    s.connection()
        .execute(
            "INSERT INTO kcp_artifacts (id, user_id, tenant_id, created_at, format, visibility, title, content_hash, deleted_at)
             VALUES ('gone', 'u', 't', '2026-01-01T00:00:00+00:00', 'text', 'public', 'Gone', 'h', '2026-01-02T00:00:00+00:00')",
            [],
        )
        .unwrap();
    assert!(s.get("gone").unwrap().is_none());
    assert!(s.list_artifacts(None, None, &[], None, 10, 0).unwrap().is_empty());
}

#[test]
fn replication_primary_key_is_artifact_peer_pair() {
    let s = store();
    s.record_replication("a", "https://p").unwrap();
    s.record_replication("a", "https://p").unwrap(); // idempotent (INSERT OR REPLACE)
    let count: i64 = s
        .connection()
        .query_row("SELECT COUNT(*) FROM kcp_replication", [], |r| r.get(0))
        .unwrap();
    assert_eq!(count, 1);
}

#[test]
fn sync_queue_unique_constraint_is_artifact_peer() {
    let s = store();
    let urls = vec!["https://p".to_string()];
    assert_eq!(s.enqueue_sync("a", &urls).unwrap(), 1);
    assert_eq!(s.enqueue_sync("a", &urls).unwrap(), 0);
    assert_eq!(s.enqueue_sync("b", &urls).unwrap(), 1);
}

#[test]
fn node_database_is_portable_across_processes() {
    // A fresh LocalStore over an existing node database sees the same data and
    // the same identity/config rows the Python SDK would rely on.
    let dir = tempfile::tempdir().unwrap();
    let db = dir.path().join("kcp.db");
    let (user, public_key, artifact_id) = {
        let node = KCPNode::new(NodeConfig::in_dir(dir.path(), "alice", "acme")).unwrap();
        let a = node
            .publish("Portable", b"content", PublishOptions::new().format("text"))
            .unwrap();
        (
            node.store.get_config("user_id").unwrap(),
            node.store.get_config("public_key").unwrap(),
            a.id,
        )
    };

    let store = LocalStore::open(&db).unwrap();
    assert_eq!(store.get_config("user_id").unwrap(), user);
    assert_eq!(store.get_config("public_key").unwrap(), public_key);
    assert_eq!(store.get_config("tenant_id").unwrap(), "acme");
    assert!(store.get(&artifact_id).unwrap().is_some());
    assert!(!store.get_config("node_id").unwrap().is_empty());
}

#[test]
fn artifact_metadata_roundtrips_through_the_database() {
    let dir = tempfile::tempdir().unwrap();
    let db = dir.path().join("kcp.db");
    let artifact = {
        let node = KCPNode::new(NodeConfig::in_dir(dir.path(), "u", "t")).unwrap();
        node.publish(
            "Rich",
            b"body",
            PublishOptions::new()
                .format("json")
                .summary("s")
                .source("agent")
                .tags(vec!["a".into(), "b".into()]),
        )
        .unwrap()
    };

    let store = LocalStore::open(&db).unwrap();
    let reloaded = store.get(&artifact.id).unwrap().unwrap();
    assert_eq!(reloaded.title, "Rich");
    assert_eq!(reloaded.format, "json");
    assert_eq!(reloaded.summary, "s");
    assert_eq!(reloaded.source, "agent");
    assert_eq!(reloaded.tags.len(), 2);
    assert_eq!(reloaded.signature, artifact.signature);
    assert_eq!(KnowledgeArtifact::from_dict(&reloaded.to_dict()).unwrap().id, artifact.id);
}
