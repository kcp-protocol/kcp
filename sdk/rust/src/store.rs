//! KCP local storage backend — SQLite + FTS5.
//!
//! Uses the **exact schema of the Python reference** (`sdk/python/kcp/store.py`):
//! `kcp_artifacts`, `kcp_content`, `kcp_peers`, `kcp_sync_log`, `kcp_audit`,
//! `kcp_config`, `kcp_sync_queue`, `kcp_replication` and the `kcp_fts` FTS5
//! index (`porter unicode61`).
//!
//! `rusqlite` is built with the `bundled` feature, so FTS5 is always compiled
//! in. The driver still degrades gracefully to `LIKE` search if a database was
//! created without FTS5 support, mirroring the Python behaviour.
//!
//! Content bytes live in the `kcp_content` BLOB column (the schema's original
//! semantics, identical to the Go SDK). The Python SDK's optional
//! filesystem-shard store is not re-implemented; a database written by Rust is
//! still fully readable by Python (its `get_content()` falls back to the SQLite
//! BLOB and migrates it to a shard on first read).

use std::path::{Path, PathBuf};

use rusqlite::{params, params_from_iter, Connection, OptionalExtension, ToSql};
use serde_json::Value;

use crate::crypto::ENCRYPTION_MAGIC;
use crate::error::{KcpError, Result};
use crate::models::{
    human_size, ACL, KnowledgeArtifact, Lineage, LineageEntry, PeerInfo, SearchResponse, SearchResult,
    StoreStats,
};

/// Full schema — byte-compatible with the Python reference.
pub const SCHEMA_SQL: &str = r#"
CREATE TABLE IF NOT EXISTS kcp_artifacts (
    id TEXT PRIMARY KEY,
    version TEXT NOT NULL DEFAULT '1',
    user_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    team TEXT,
    tags TEXT,
    source TEXT,
    created_at TEXT NOT NULL,
    format TEXT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'private',
    title TEXT NOT NULL,
    summary TEXT,
    lineage TEXT,
    content_hash TEXT NOT NULL,
    content_url TEXT,
    signature TEXT,
    acl TEXT,
    derived_from TEXT,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS kcp_content (
    content_hash TEXT PRIMARY KEY,
    content BLOB NOT NULL,
    size_bytes INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS kcp_peers (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    name TEXT,
    public_key TEXT,
    last_seen TEXT,
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kcp_sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    peer_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    artifacts_synced INTEGER NOT NULL DEFAULT 0,
    timestamp TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ok',
    details TEXT
);

CREATE TABLE IF NOT EXISTS kcp_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    user_id TEXT,
    action TEXT NOT NULL,
    artifact_id TEXT,
    details TEXT
);

CREATE TABLE IF NOT EXISTS kcp_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_artifacts_tenant ON kcp_artifacts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_user ON kcp_artifacts(user_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_hash ON kcp_artifacts(content_hash);
CREATE INDEX IF NOT EXISTS idx_artifacts_created ON kcp_artifacts(created_at);
CREATE INDEX IF NOT EXISTS idx_artifacts_derived ON kcp_artifacts(derived_from);

CREATE TABLE IF NOT EXISTS kcp_sync_queue (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_id  TEXT NOT NULL,
    peer_url     TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    attempts     INTEGER NOT NULL DEFAULT 0,
    last_attempt TEXT,
    next_attempt TEXT,
    acked_at     TEXT,
    error        TEXT,
    created_at   TEXT NOT NULL,
    UNIQUE(artifact_id, peer_url)
);

CREATE INDEX IF NOT EXISTS idx_sync_queue_status ON kcp_sync_queue(status, next_attempt);
CREATE INDEX IF NOT EXISTS idx_sync_queue_artifact ON kcp_sync_queue(artifact_id);

CREATE TABLE IF NOT EXISTS kcp_replication (
    artifact_id  TEXT NOT NULL,
    peer_url     TEXT NOT NULL,
    acked_at     TEXT NOT NULL,
    PRIMARY KEY (artifact_id, peer_url)
);

CREATE INDEX IF NOT EXISTS idx_replication_artifact ON kcp_replication(artifact_id);
"#;

/// FTS5 index definition (identical to the reference).
pub const FTS_SQL: &str = r#"
CREATE VIRTUAL TABLE IF NOT EXISTS kcp_fts USING fts5(
    id UNINDEXED,
    title,
    summary,
    tags,
    source,
    content_text,
    tokenize = 'porter unicode61'
);
"#;

const ARTIFACT_COLUMNS: &str = "id, version, user_id, tenant_id, team, tags, source, created_at, \
     format, visibility, title, summary, lineage, content_hash, content_url, signature, acl, derived_from";

/// SQLite-backed local storage for KCP artifacts.
pub struct LocalStore {
    conn: Connection,
    db_path: PathBuf,
    fts5: bool,
}

/// One queued outbound sync entry.
#[derive(Debug, Clone, PartialEq)]
pub struct SyncItem {
    pub id: i64,
    pub artifact_id: String,
    pub peer_url: String,
    pub attempts: i64,
}

/// One audit-log row.
#[derive(Debug, Clone, PartialEq)]
pub struct AuditEntry {
    pub timestamp: String,
    pub user_id: String,
    pub action: String,
    pub artifact_id: String,
    pub details: String,
}

impl LocalStore {
    /// Open (creating if needed) a KCP store at `db_path`.
    pub fn open(db_path: impl AsRef<Path>) -> Result<Self> {
        let db_path = expand_tilde(db_path.as_ref());
        if let Some(parent) = db_path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let conn = Connection::open(&db_path)?;
        // WAL + foreign keys, like the reference implementation.
        let _mode: String = conn.query_row("PRAGMA journal_mode=WAL", [], |row| row.get(0))?;
        conn.pragma_update(None, "foreign_keys", "ON")?;
        let mut store = Self {
            conn,
            db_path,
            fts5: false,
        };
        store.init_schema()?;
        Ok(store)
    }

    /// Open a throwaway in-memory store (tests, ephemeral nodes).
    pub fn open_in_memory() -> Result<Self> {
        let conn = Connection::open_in_memory()?;
        conn.pragma_update(None, "foreign_keys", "ON")?;
        let mut store = Self {
            conn,
            db_path: PathBuf::from(":memory:"),
            fts5: false,
        };
        store.init_schema()?;
        Ok(store)
    }

    fn init_schema(&mut self) -> Result<()> {
        self.conn.execute_batch(SCHEMA_SQL)?;
        match self.conn.execute_batch(FTS_SQL) {
            Ok(()) => self.fts5 = true,
            Err(_) => self.fts5 = false,
        }
        Ok(())
    }

    /// True when the FTS5 index is available.
    pub fn has_fts5(&self) -> bool {
        self.fts5
    }

    /// Path of the underlying database file.
    pub fn db_path(&self) -> &Path {
        &self.db_path
    }

    /// Borrow the underlying SQLite connection (diagnostics / advanced use).
    pub fn connection(&self) -> &Connection {
        &self.conn
    }

    /// Close the store.
    pub fn close(self) {
        let _ = self.conn.close();
    }

    // ─── CRUD ─────────────────────────────────────────────────

    /// Store an artifact together with its (possibly encrypted) content.
    pub fn publish(
        &self,
        artifact: &KnowledgeArtifact,
        content: &[u8],
        derived_from: Option<&str>,
    ) -> Result<()> {
        if !content.is_empty() {
            self.conn.execute(
                "INSERT OR IGNORE INTO kcp_content (content_hash, content, size_bytes) VALUES (?, ?, ?)",
                params![artifact.content_hash, content, content.len() as i64],
            )?;
        }

        let tags_json = serde_json::to_string(&artifact.tags)?;
        let lineage_json = artifact
            .lineage
            .as_ref()
            .map(|l| serde_json::to_string(&l.to_dict()))
            .transpose()?;
        let acl_json = artifact
            .acl
            .as_ref()
            .map(|a| serde_json::to_string(&a.to_dict()))
            .transpose()?;

        self.conn.execute(
            "INSERT OR REPLACE INTO kcp_artifacts
             (id, version, user_id, tenant_id, team, tags, source, created_at,
              format, visibility, title, summary, lineage, content_hash,
              content_url, signature, acl, derived_from)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            params![
                artifact.id,
                artifact.version,
                artifact.user_id,
                artifact.tenant_id,
                artifact.team,
                tags_json,
                artifact.source,
                artifact.timestamp,
                artifact.format,
                artifact.visibility,
                artifact.title,
                artifact.summary,
                lineage_json,
                artifact.content_hash,
                artifact.content_url,
                artifact.signature,
                acl_json,
                derived_from,
            ],
        )?;

        if self.fts5 {
            let content_text = extract_text(content);
            // FTS failures (e.g. older SQLite without FTS5) must not break writes.
            let _ = self.conn.execute(
                "INSERT OR REPLACE INTO kcp_fts (id, title, summary, tags, source, content_text)
                 VALUES (?, ?, ?, ?, ?, ?)",
                params![
                    artifact.id,
                    artifact.title,
                    artifact.summary,
                    artifact.tags.join(" "),
                    artifact.source,
                    content_text,
                ],
            );
        }

        self.audit(&artifact.user_id, "publish", &artifact.id, "")?;
        Ok(())
    }

    /// Fetch artifact metadata by ID.
    pub fn get(&self, artifact_id: &str) -> Result<Option<KnowledgeArtifact>> {
        let sql = format!(
            "SELECT {ARTIFACT_COLUMNS} FROM kcp_artifacts WHERE id = ? AND deleted_at IS NULL"
        );
        let mut stmt = self.conn.prepare(&sql)?;
        let mut rows = stmt.query(params![artifact_id])?;
        match rows.next()? {
            Some(row) => Ok(Some(row_to_artifact(row)?)),
            None => Ok(None),
        }
    }

    /// Fetch raw content bytes by content hash.
    pub fn get_content(&self, content_hash: &str) -> Result<Option<Vec<u8>>> {
        let blob: Option<Vec<u8>> = self
            .conn
            .query_row(
                "SELECT content FROM kcp_content WHERE content_hash = ?",
                params![content_hash],
                |row| row.get(0),
            )
            .optional()?;
        Ok(blob.filter(|b| !b.is_empty()))
    }

    /// Soft-delete an artifact. Returns true when a row was updated.
    pub fn delete(&self, artifact_id: &str, user_id: &str) -> Result<bool> {
        let now = crate::models::now_iso();
        let changed = self.conn.execute(
            "UPDATE kcp_artifacts SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
            params![now, artifact_id],
        )?;
        if changed > 0 {
            self.audit(user_id, "delete", artifact_id, "")?;
            Ok(true)
        } else {
            Ok(false)
        }
    }

    /// List artifacts with optional filters, newest first.
    pub fn list_artifacts(
        &self,
        tenant_id: Option<&str>,
        user_id: Option<&str>,
        tags: &[String],
        format_filter: Option<&str>,
        limit: i64,
        offset: i64,
    ) -> Result<Vec<KnowledgeArtifact>> {
        let mut sql = format!("SELECT {ARTIFACT_COLUMNS} FROM kcp_artifacts WHERE deleted_at IS NULL");
        let mut args: Vec<Box<dyn ToSql>> = Vec::new();
        if let Some(tenant) = tenant_id {
            sql.push_str(" AND tenant_id = ?");
            args.push(Box::new(tenant.to_string()));
        }
        if let Some(user) = user_id {
            sql.push_str(" AND user_id = ?");
            args.push(Box::new(user.to_string()));
        }
        if let Some(fmt) = format_filter {
            sql.push_str(" AND format = ?");
            args.push(Box::new(fmt.to_string()));
        }
        for tag in tags {
            sql.push_str(" AND tags LIKE ?");
            args.push(Box::new(format!("%{}%", tag)));
        }
        sql.push_str(" ORDER BY created_at DESC LIMIT ? OFFSET ?");
        args.push(Box::new(limit));
        args.push(Box::new(offset));

        let mut stmt = self.conn.prepare(&sql)?;
        let mut rows = stmt.query(params_from_iter(args.iter().map(|b| &**b)))?;
        let mut out = Vec::new();
        while let Some(row) = rows.next()? {
            out.push(row_to_artifact(row)?);
        }
        Ok(out)
    }

    /// Full-text search (FTS5 + BM25, `LIKE` fallback).
    ///
    /// An empty query returns every non-deleted artifact (the Go SDK's `LIKE`
    /// path behaves this way; the Python FTS path would return no rows).
    pub fn search(
        &self,
        query: &str,
        tenant_id: Option<&str>,
        limit: i64,
        offset: i64,
    ) -> Result<SearchResponse> {
        let start = std::time::Instant::now();
        let empty_query = query.trim().is_empty();
        let fts_query = if empty_query {
            "\"\"".to_string()
        } else {
            query.trim().to_string()
        };

        let mut results: Vec<SearchResult> = Vec::new();
        let mut used_fts = false;

        if self.fts5 && !empty_query {
            let mut sql = format!(
                "SELECT a.id, a.title, a.summary, a.created_at, a.format, bm25(kcp_fts) AS bm25_score
                 FROM kcp_fts f JOIN kcp_artifacts a ON f.id = a.id
                 WHERE kcp_fts MATCH ? AND a.deleted_at IS NULL"
            );
            let mut args: Vec<Box<dyn ToSql>> = vec![Box::new(fts_query.clone())];
            if let Some(tenant) = tenant_id {
                sql.push_str(" AND a.tenant_id = ?");
                args.push(Box::new(tenant.to_string()));
            }
            sql.push_str(" ORDER BY bm25_score LIMIT ? OFFSET ?");
            args.push(Box::new(limit));
            args.push(Box::new(offset));

            let rows = self
                .conn
                .prepare(&sql)
                .and_then(|mut stmt| {
                    let mut rows = stmt.query(params_from_iter(args.iter().map(|b| &**b)))?;
                    let mut collected = Vec::new();
                    while let Some(row) = rows.next()? {
                        let bm25: Option<f64> = row.get(5)?;
                        collected.push(SearchResult {
                            id: row.get(0)?,
                            title: row.get(1)?,
                            summary: row.get::<_, Option<String>>(2)?.unwrap_or_default(),
                            created_at: row.get(3)?,
                            format: row.get(4)?,
                            relevance: relevance_from_bm25(bm25),
                            preview: String::new(),
                        });
                    }
                    Ok(collected)
                })
                .map(|r| r);

            match rows {
                Ok(collected) => {
                    results = collected;
                    used_fts = true;
                }
                Err(_) => used_fts = false,
            }
        }

        if !used_fts {
            let like = format!("%{}%", query);
            let mut sql = format!(
                "SELECT {ARTIFACT_COLUMNS} FROM kcp_artifacts WHERE deleted_at IS NULL
                 AND (title LIKE ? OR summary LIKE ? OR tags LIKE ? OR source LIKE ?)"
            );
            let mut args: Vec<Box<dyn ToSql>> = vec![
                Box::new(like.clone()),
                Box::new(like.clone()),
                Box::new(like.clone()),
                Box::new(like),
            ];
            if let Some(tenant) = tenant_id {
                sql.push_str(" AND tenant_id = ?");
                args.push(Box::new(tenant.to_string()));
            }
            sql.push_str(" ORDER BY created_at DESC LIMIT ? OFFSET ?");
            args.push(Box::new(limit));
            args.push(Box::new(offset));

            let mut stmt = self.conn.prepare(&sql)?;
            let mut rows = stmt.query(params_from_iter(args.iter().map(|b| &**b)))?;
            while let Some(row) = rows.next()? {
                let artifact = row_to_artifact(row)?;
                results.push(SearchResult {
                    id: artifact.id,
                    title: artifact.title,
                    summary: artifact.summary,
                    created_at: artifact.timestamp,
                    relevance: 1.0,
                    format: artifact.format,
                    preview: String::new(),
                });
            }
        }

        let total = if used_fts {
            let mut sql = String::from(
                "SELECT COUNT(*) FROM kcp_fts f JOIN kcp_artifacts a ON f.id = a.id
                 WHERE kcp_fts MATCH ? AND a.deleted_at IS NULL",
            );
            let mut args: Vec<Box<dyn ToSql>> = vec![Box::new(fts_query)];
            if let Some(tenant) = tenant_id {
                sql.push_str(" AND a.tenant_id = ?");
                args.push(Box::new(tenant.to_string()));
            }
            self.conn
                .query_row(&sql, params_from_iter(args.iter().map(|b| &**b)), |row| {
                    row.get::<_, i64>(0)
                })
                .unwrap_or(results.len() as i64)
        } else {
            results.len() as i64
        };

        Ok(SearchResponse {
            results,
            total: total as usize,
            query_time_ms: start.elapsed().as_millis() as i64,
        })
    }

    // ─── Lineage ──────────────────────────────────────────────

    /// Full lineage chain, root first.
    pub fn get_lineage(&self, artifact_id: &str) -> Result<Vec<LineageEntry>> {
        let mut chain = Vec::new();
        let mut visited: Vec<String> = Vec::new();
        let mut current = Some(artifact_id.to_string());

        while let Some(id) = current.clone() {
            if id.is_empty() || visited.contains(&id) {
                break;
            }
            visited.push(id.clone());
            let row: Option<(String, String, String, String, Option<String>)> = self
                .conn
                .query_row(
                    "SELECT id, title, user_id, created_at, derived_from FROM kcp_artifacts WHERE id = ?",
                    params![id],
                    |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?, row.get(4)?)),
                )
                .optional()?;
            let Some((id, title, author, created_at, derived_from)) = row else {
                break;
            };
            current = derived_from.clone();
            chain.push(LineageEntry {
                id,
                title,
                author,
                created_at,
                derived_from,
            });
        }

        chain.reverse();
        Ok(chain)
    }

    /// Direct derivatives of an artifact (children).
    pub fn get_derivatives(&self, artifact_id: &str) -> Result<Vec<LineageEntry>> {
        let mut stmt = self.conn.prepare(
            "SELECT id, title, user_id, created_at FROM kcp_artifacts
             WHERE derived_from = ? AND deleted_at IS NULL",
        )?;
        let mut rows = stmt.query(params![artifact_id])?;
        let mut out = Vec::new();
        while let Some(row) = rows.next()? {
            out.push(LineageEntry {
                id: row.get(0)?,
                title: row.get(1)?,
                author: row.get(2)?,
                created_at: row.get(3)?,
                derived_from: Some(artifact_id.to_string()),
            });
        }
        Ok(out)
    }

    // ─── Peers ────────────────────────────────────────────────

    /// Register a peer with a pre-assigned ID.
    pub fn add_peer(&self, peer_id: &str, url: &str, name: &str, public_key: &str) -> Result<()> {
        let now = crate::models::now_iso();
        self.conn.execute(
            "INSERT OR REPLACE INTO kcp_peers (id, url, name, public_key, last_seen, added_at)
             VALUES (?, ?, ?, ?, ?, ?)",
            params![peer_id, url, name, public_key, now, now],
        )?;
        Ok(())
    }

    /// Insert or update a peer by URL (gossip discovery).
    pub fn upsert_peer(
        &self,
        url: &str,
        name: &str,
        node_id: &str,
        public_key: &str,
    ) -> Result<()> {
        let now = crate::models::now_iso();
        let existing: Option<String> = self
            .conn
            .query_row("SELECT id FROM kcp_peers WHERE url = ?", params![url], |row| {
                row.get(0)
            })
            .optional()?;
        match existing {
            Some(_) => {
                self.conn.execute(
                    "UPDATE kcp_peers SET
                        name = COALESCE(NULLIF(?, ''), name),
                        id = COALESCE(NULLIF(?, ''), id),
                        last_seen = ?,
                        public_key = COALESCE(NULLIF(?, ''), public_key)
                     WHERE url = ?",
                    params![name, node_id, now, public_key, url],
                )?;
            }
            None => {
                let peer_id = if node_id.is_empty() {
                    uuid::Uuid::new_v4().to_string()
                } else {
                    node_id.to_string()
                };
                self.conn.execute(
                    "INSERT INTO kcp_peers (id, url, name, public_key, last_seen, added_at)
                     VALUES (?, ?, ?, ?, ?, ?)",
                    params![peer_id, url, name, public_key, now, now],
                )?;
            }
        }
        Ok(())
    }

    /// All known peers, most recently seen first.
    pub fn get_peers(&self) -> Result<Vec<PeerInfo>> {
        let mut stmt = self.conn.prepare(
            "SELECT id, url, name, public_key, last_seen, added_at FROM kcp_peers ORDER BY last_seen DESC",
        )?;
        let mut rows = stmt.query([])?;
        let mut out = Vec::new();
        while let Some(row) = rows.next()? {
            out.push(PeerInfo {
                id: row.get(0)?,
                url: row.get(1)?,
                name: row.get::<_, Option<String>>(2)?.unwrap_or_default(),
                public_key: row.get::<_, Option<String>>(3)?.unwrap_or_default(),
                last_seen: row.get::<_, Option<String>>(4)?.unwrap_or_default(),
                added_at: row.get::<_, Option<String>>(5)?.unwrap_or_default(),
            });
        }
        Ok(out)
    }

    /// Touch `last_seen` for a peer ID.
    pub fn update_peer_seen(&self, peer_id: &str) -> Result<()> {
        let now = crate::models::now_iso();
        self.conn.execute(
            "UPDATE kcp_peers SET last_seen = ? WHERE id = ?",
            params![now, peer_id],
        )?;
        Ok(())
    }

    /// Touch `last_seen` for a peer URL.
    pub fn update_peer_seen_by_url(&self, url: &str) -> Result<()> {
        let now = crate::models::now_iso();
        self.conn.execute(
            "UPDATE kcp_peers SET last_seen = ? WHERE url = ?",
            params![now, url],
        )?;
        Ok(())
    }

    // ─── Config ───────────────────────────────────────────────

    /// Read a config value (empty string when missing).
    pub fn get_config(&self, key: &str) -> Result<String> {
        let value: Option<String> = self
            .conn
            .query_row("SELECT value FROM kcp_config WHERE key = ?", params![key], |row| {
                row.get(0)
            })
            .optional()?;
        Ok(value.unwrap_or_default())
    }

    /// Read a config value with a fallback.
    pub fn get_config_or(&self, key: &str, default: &str) -> Result<String> {
        let value = self.get_config(key)?;
        if value.is_empty() {
            Ok(default.to_string())
        } else {
            Ok(value)
        }
    }

    /// Upsert a config value.
    pub fn set_config(&self, key: &str, value: &str) -> Result<()> {
        self.conn.execute(
            "INSERT OR REPLACE INTO kcp_config (key, value) VALUES (?, ?)",
            params![key, value],
        )?;
        Ok(())
    }

    // ─── Audit ────────────────────────────────────────────────

    /// Append an audit row.
    pub fn audit(&self, user_id: &str, action: &str, artifact_id: &str, details: &str) -> Result<()> {
        let now = crate::models::now_iso();
        self.conn.execute(
            "INSERT INTO kcp_audit (timestamp, user_id, action, artifact_id, details) VALUES (?, ?, ?, ?, ?)",
            params![now, user_id, action, artifact_id, details],
        )?;
        Ok(())
    }

    /// Read the audit log (oldest first).
    pub fn audit_log(&self, limit: i64) -> Result<Vec<AuditEntry>> {
        let mut stmt = self.conn.prepare(
            "SELECT timestamp, user_id, action, artifact_id, details FROM kcp_audit ORDER BY id LIMIT ?",
        )?;
        let mut rows = stmt.query(params![limit])?;
        let mut out = Vec::new();
        while let Some(row) = rows.next()? {
            out.push(AuditEntry {
                timestamp: row.get(0)?,
                user_id: row.get::<_, Option<String>>(1)?.unwrap_or_default(),
                action: row.get(2)?,
                artifact_id: row.get::<_, Option<String>>(3)?.unwrap_or_default(),
                details: row.get::<_, Option<String>>(4)?.unwrap_or_default(),
            });
        }
        Ok(out)
    }

    // ─── Stats ────────────────────────────────────────────────

    /// Storage statistics.
    pub fn stats(&self) -> Result<StoreStats> {
        let artifacts: i64 = self.conn.query_row(
            "SELECT COUNT(*) FROM kcp_artifacts WHERE deleted_at IS NULL",
            [],
            |row| row.get(0),
        )?;
        let content_size_bytes: i64 = self.conn.query_row(
            "SELECT COALESCE(SUM(size_bytes), 0) FROM kcp_content",
            [],
            |row| row.get(0),
        )?;
        let peers: i64 = self
            .conn
            .query_row("SELECT COUNT(*) FROM kcp_peers", [], |row| row.get(0))?;
        let db_size_bytes = std::fs::metadata(&self.db_path)
            .map(|m| m.len() as i64)
            .unwrap_or(0);

        Ok(StoreStats {
            artifacts,
            content_size_bytes,
            content_size_human: human_size(content_size_bytes),
            peers,
            db_size_bytes,
            db_size_human: human_size(db_size_bytes),
            db_path: self.db_path.display().to_string(),
        })
    }

    // ─── Sync / export / import ───────────────────────────────

    /// IDs created after `since` — public artifacts only (never sync private).
    pub fn get_artifact_ids_since(&self, since: Option<&str>) -> Result<Vec<String>> {
        let mut out = Vec::new();
        match since {
            Some(ts) => {
                let mut stmt = self.conn.prepare(
                    "SELECT id FROM kcp_artifacts WHERE created_at > ? AND deleted_at IS NULL
                     AND visibility = 'public' ORDER BY created_at",
                )?;
                let mut rows = stmt.query(params![ts])?;
                while let Some(row) = rows.next()? {
                    out.push(row.get(0)?);
                }
            }
            None => {
                let mut stmt = self.conn.prepare(
                    "SELECT id FROM kcp_artifacts WHERE deleted_at IS NULL
                     AND visibility = 'public' ORDER BY created_at",
                )?;
                let mut rows = stmt.query([])?;
                while let Some(row) = rows.next()? {
                    out.push(row.get(0)?);
                }
            }
        }
        Ok(out)
    }

    /// Artifact metadata + base64 content, ready for a sync push.
    pub fn get_artifact_with_content(&self, artifact_id: &str) -> Result<Option<Value>> {
        let Some(artifact) = self.get(artifact_id)? else {
            return Ok(None);
        };
        let mut payload = artifact.to_dict();
        if let Some(derived_from) = self.derived_from(artifact_id)? {
            if let Value::Object(map) = &mut payload {
                map.insert("derived_from".into(), Value::String(derived_from));
            }
        }
        if let Some(content) = self.get_content(&artifact.content_hash)? {
            if let Value::Object(map) = &mut payload {
                map.insert(
                    "_content_b64".into(),
                    Value::String(base64_encode(&content)),
                );
            }
        }
        Ok(Some(payload))
    }

    /// Import an artifact received from a peer. Returns true when new.
    pub fn import_artifact(&self, data: &Value) -> Result<bool> {
        let id = data
            .get("id")
            .and_then(|v| v.as_str())
            .ok_or_else(|| KcpError::MissingField("id".into()))?;
        if self.get(id)?.is_some() {
            return Ok(false);
        }
        let artifact = KnowledgeArtifact::from_dict(data)?;
        let content = match data.get("_content_b64").and_then(|v| v.as_str()) {
            Some(b64) => base64_decode(b64)?,
            None => Vec::new(),
        };
        let derived_from = data
            .get("derived_from")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty());
        self.publish(&artifact, &content, derived_from)?;
        Ok(true)
    }

    /// The `derived_from` column for an artifact (not part of the model payload).
    pub fn derived_from(&self, artifact_id: &str) -> Result<Option<String>> {
        let value: Option<Option<String>> = self
            .conn
            .query_row(
                "SELECT derived_from FROM kcp_artifacts WHERE id = ?",
                params![artifact_id],
                |row| row.get(0),
            )
            .optional()?;
        Ok(value.flatten())
    }

    // ─── Sync queue ───────────────────────────────────────────

    /// Enqueue an artifact for delivery to one or more peers.
    pub fn enqueue_sync(&self, artifact_id: &str, peer_urls: &[String]) -> Result<usize> {
        let now = crate::models::now_iso();
        let mut added = 0usize;
        for url in peer_urls {
            added += self.conn.execute(
                "INSERT OR IGNORE INTO kcp_sync_queue
                 (artifact_id, peer_url, status, created_at, next_attempt) VALUES (?, ?, 'pending', ?, ?)",
                params![artifact_id, url, now, now],
            )?;
        }
        Ok(added)
    }

    /// Claim up to `batch_size` due entries, marking them `in_flight`.
    pub fn dequeue_pending_sync(&self, batch_size: i64) -> Result<Vec<SyncItem>> {
        let now = crate::models::now_iso();
        let mut stmt = self.conn.prepare(
            "SELECT id, artifact_id, peer_url, attempts FROM kcp_sync_queue
             WHERE status = 'pending' AND (next_attempt IS NULL OR next_attempt <= ?)
             ORDER BY created_at LIMIT ?",
        )?;
        let mut rows = stmt.query(params![now, batch_size])?;
        let mut items = Vec::new();
        while let Some(row) = rows.next()? {
            items.push(SyncItem {
                id: row.get(0)?,
                artifact_id: row.get(1)?,
                peer_url: row.get(2)?,
                attempts: row.get(3)?,
            });
        }
        for item in &items {
            self.conn.execute(
                "UPDATE kcp_sync_queue SET status = 'in_flight', last_attempt = ? WHERE id = ?",
                params![now, item.id],
            )?;
        }
        Ok(items)
    }

    /// Mark a queue entry delivered and record the replication ACK.
    pub fn ack_sync(&self, queue_id: i64) -> Result<()> {
        let now = crate::models::now_iso();
        let row: Option<(String, String)> = self
            .conn
            .query_row(
                "SELECT artifact_id, peer_url FROM kcp_sync_queue WHERE id = ?",
                params![queue_id],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .optional()?;
        self.conn.execute(
            "UPDATE kcp_sync_queue SET status = 'done', acked_at = ?, error = NULL WHERE id = ?",
            params![now, queue_id],
        )?;
        if let Some((artifact_id, peer_url)) = row {
            self.record_replication(&artifact_id, &peer_url)?;
        }
        Ok(())
    }

    /// Mark a queue entry failed; retry with exponential backoff.
    pub fn nack_sync(&self, queue_id: i64, error: &str, max_attempts: i64) -> Result<()> {
        let attempts: Option<i64> = self
            .conn
            .query_row(
                "SELECT attempts FROM kcp_sync_queue WHERE id = ?",
                params![queue_id],
                |row| row.get(0),
            )
            .optional()?;
        let Some(attempts) = attempts else {
            return Ok(());
        };
        let attempts = attempts + 1;
        if attempts >= max_attempts {
            self.conn.execute(
                "UPDATE kcp_sync_queue SET status = 'failed', attempts = ?, error = ? WHERE id = ?",
                params![attempts, error, queue_id],
            )?;
        } else {
            // 30s, 2m, 10m, 1h, 6h, 24h
            const DELAYS: [i64; 6] = [30, 120, 600, 3600, 21600, 86400];
            let delay = DELAYS[((attempts - 1).max(0) as usize).min(DELAYS.len() - 1)];
            let next = chrono::Utc::now() + chrono::Duration::seconds(delay);
            let next_attempt = next.to_rfc3339_opts(chrono::SecondsFormat::Micros, false);
            self.conn.execute(
                "UPDATE kcp_sync_queue SET status = 'pending', attempts = ?, error = ?, next_attempt = ?
                 WHERE id = ?",
                params![attempts, error, next_attempt, queue_id],
            )?;
        }
        Ok(())
    }

    /// Queue counts grouped by peer URL and status.
    pub fn sync_queue_stats(&self) -> Result<Vec<(String, String, i64)>> {
        let mut stmt = self.conn.prepare(
            "SELECT peer_url, status, COUNT(*) FROM kcp_sync_queue GROUP BY peer_url, status",
        )?;
        let mut rows = stmt.query([])?;
        let mut out = Vec::new();
        while let Some(row) = rows.next()? {
            out.push((row.get(0)?, row.get(1)?, row.get(2)?));
        }
        Ok(out)
    }

    /// Log a sync event.
    pub fn log_sync(
        &self,
        peer_id: &str,
        direction: &str,
        count: i64,
        status: &str,
        details: &str,
    ) -> Result<()> {
        let now = crate::models::now_iso();
        self.conn.execute(
            "INSERT INTO kcp_sync_log (peer_id, direction, artifacts_synced, timestamp, status, details)
             VALUES (?, ?, ?, ?, ?, ?)",
            params![peer_id, direction, count, now, status, details],
        )?;
        Ok(())
    }

    // ─── Replication ──────────────────────────────────────────

    /// Record that a peer holds this artifact.
    pub fn record_replication(&self, artifact_id: &str, peer_url: &str) -> Result<()> {
        let now = crate::models::now_iso();
        self.conn.execute(
            "INSERT OR REPLACE INTO kcp_replication (artifact_id, peer_url, acked_at) VALUES (?, ?, ?)",
            params![artifact_id, peer_url, now],
        )?;
        Ok(())
    }

    /// Alias kept for parity with the Python API.
    pub fn record_replication_ack(&self, artifact_id: &str, peer_url: &str) -> Result<()> {
        self.record_replication(artifact_id, peer_url)
    }

    /// Replication details for one artifact.
    pub fn get_replication_status(&self, artifact_id: &str) -> Result<Value> {
        let mut stmt = self.conn.prepare(
            "SELECT peer_url, acked_at FROM kcp_replication WHERE artifact_id = ? ORDER BY acked_at",
        )?;
        let mut rows = stmt.query(params![artifact_id])?;
        let mut urls = Vec::new();
        let mut acked = serde_json::Map::new();
        while let Some(row) = rows.next()? {
            let url: String = row.get(0)?;
            let at: String = row.get(1)?;
            urls.push(Value::String(url.clone()));
            acked.insert(url, Value::String(at));
        }
        let mut out = serde_json::Map::new();
        out.insert("artifact_id".into(), Value::String(artifact_id.to_string()));
        out.insert("replicated_to".into(), Value::Array(urls.clone()));
        out.insert("acked_at".into(), Value::Object(acked));
        out.insert("count".into(), Value::Number(urls.len().into()));
        Ok(Value::Object(out))
    }

    /// Replication peer-count per artifact.
    pub fn get_replication_summary(&self) -> Result<Vec<(String, i64)>> {
        let mut stmt = self.conn.prepare(
            "SELECT artifact_id, COUNT(*) FROM kcp_replication GROUP BY artifact_id",
        )?;
        let mut rows = stmt.query([])?;
        let mut out = Vec::new();
        while let Some(row) = rows.next()? {
            out.push((row.get(0)?, row.get(1)?));
        }
        Ok(out)
    }
}

/// Rebuild the FTS index from the artifacts table (used after migrations).
pub fn rebuild_fts(conn: &Connection) -> Result<()> {
    conn.execute_batch("DROP TABLE IF EXISTS kcp_fts;")?;
    conn.execute_batch(FTS_SQL)?;
    let mut stmt = conn.prepare(
        "SELECT a.id, a.title, a.summary, a.tags, a.source, c.content
         FROM kcp_artifacts a LEFT JOIN kcp_content c ON a.content_hash = c.content_hash
         WHERE a.deleted_at IS NULL",
    )?;
    let mut rows = stmt.query([])?;
    let mut pending: Vec<(String, String, String, String, String, String)> = Vec::new();
    while let Some(row) = rows.next()? {
        let blob: Option<Vec<u8>> = row.get(5)?;
        pending.push((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, Option<String>>(2)?.unwrap_or_default(),
            row.get::<_, Option<String>>(3)?.unwrap_or_default(),
            row.get::<_, Option<String>>(4)?.unwrap_or_default(),
            extract_text(blob.as_deref().unwrap_or_default()),
        ));
    }
    drop(rows);
    drop(stmt);
    for (id, title, summary, tags, source, content_text) in pending {
        conn.execute(
            "INSERT OR REPLACE INTO kcp_fts (id, title, summary, tags, source, content_text)
             VALUES (?, ?, ?, ?, ?, ?)",
            params![id, title, summary, tags, source, content_text],
        )?;
    }
    Ok(())
}

// ─── Helpers ─────────────────────────────────────────────────

/// Text extracted for the FTS index. Encrypted blobs carry no searchable text.
fn extract_text(content: &[u8]) -> String {
    if content.is_empty() {
        return String::new();
    }
    if content.len() >= ENCRYPTION_MAGIC.len() && &content[..ENCRYPTION_MAGIC.len()] == ENCRYPTION_MAGIC {
        return String::new();
    }
    match std::str::from_utf8(content) {
        Ok(s) => s.chars().take(50_000).collect(),
        Err(_) => String::from_utf8_lossy(content).chars().take(50_000).collect(),
    }
}

/// BM25 → 0.0..=1.0 relevance, matching the reference formula.
fn relevance_from_bm25(bm25: Option<f64>) -> f64 {
    let bm25 = bm25.unwrap_or(-1.0);
    if bm25 == 0.0 {
        return 1.0;
    }
    let relevance = 1.0 / (1.0 + bm25.abs());
    let clamped = relevance.max(0.0).min(1.0);
    (clamped * 10_000.0).round() / 10_000.0
}

fn row_to_artifact(row: &rusqlite::Row<'_>) -> Result<KnowledgeArtifact> {
    let tags_json: Option<String> = row.get(5)?;
    let lineage_json: Option<String> = row.get(12)?;
    let acl_json: Option<String> = row.get(16)?;

    let tags: Vec<String> = tags_json
        .as_deref()
        .filter(|s| !s.is_empty())
        .and_then(|s| serde_json::from_str(s).ok())
        .unwrap_or_default();
    let lineage: Option<Lineage> = lineage_json
        .as_deref()
        .filter(|s| !s.is_empty())
        .and_then(|s| serde_json::from_str(s).ok());
    let acl: Option<ACL> = acl_json
        .as_deref()
        .filter(|s| !s.is_empty())
        .and_then(|s| serde_json::from_str(s).ok());

    Ok(KnowledgeArtifact {
        id: row.get(0)?,
        version: row.get(1)?,
        user_id: row.get(2)?,
        tenant_id: row.get(3)?,
        team: row.get::<_, Option<String>>(4)?,
        tags,
        source: row.get::<_, Option<String>>(6)?.unwrap_or_default(),
        timestamp: row.get(7)?,
        format: row.get(8)?,
        visibility: row.get(9)?,
        title: row.get(10)?,
        summary: row.get::<_, Option<String>>(11)?.unwrap_or_default(),
        lineage,
        content_hash: row.get(13)?,
        content_url: row.get::<_, Option<String>>(14)?.unwrap_or_default(),
        signature: row.get::<_, Option<String>>(15)?.unwrap_or_default(),
        acl,
        embeddings: Vec::new(),
        derived_from: row.get::<_, Option<String>>(17)?,
    })
}

fn expand_tilde(path: &Path) -> PathBuf {
    let s = path.to_string_lossy().to_string();
    if let Some(rest) = s.strip_prefix("~/") {
        if let Some(home) = std::env::var_os("HOME") {
            return PathBuf::from(home).join(rest);
        }
    }
    path.to_path_buf()
}

fn base64_encode(data: &[u8]) -> String {
    use base64::Engine;
    base64::engine::general_purpose::STANDARD.encode(data)
}

fn base64_decode(data: &str) -> Result<Vec<u8>> {
    use base64::Engine;
    base64::engine::general_purpose::STANDARD
        .decode(data)
        .map_err(|e| KcpError::Other(format!("invalid base64 content: {}", e)))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::crypto;
    use serde_json::json;

    fn store() -> LocalStore {
        LocalStore::open_in_memory().unwrap()
    }

    fn artifact(title: &str, content: &str) -> (KnowledgeArtifact, Vec<u8>) {
        let mut a = KnowledgeArtifact::new(title, "alice@acme.com", "acme", "text");
        a.content_hash = crypto::hash_content(content.as_bytes());
        a.signature = "sig".into();
        (a, content.as_bytes().to_vec())
    }

    #[test]
    fn schema_creates_reference_tables() {
        let s = store();
        let tables: Vec<String> = {
            let mut stmt = s
                .conn
                .prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                .unwrap();
            let rows = stmt.query_map([], |r| r.get::<_, String>(0)).unwrap();
            rows.map(|r| r.unwrap()).collect()
        };
        for expected in [
            "kcp_artifacts",
            "kcp_content",
            "kcp_peers",
            "kcp_sync_log",
            "kcp_audit",
            "kcp_config",
            "kcp_sync_queue",
            "kcp_replication",
        ] {
            assert!(tables.contains(&expected.to_string()), "missing {expected}");
        }
        assert!(s.has_fts5());
    }

    #[test]
    fn schema_has_expected_columns() {
        let s = store();
        let mut stmt = s.conn.prepare("PRAGMA table_info(kcp_artifacts)").unwrap();
        let cols: Vec<String> = stmt
            .query_map([], |r| r.get::<_, String>(1))
            .unwrap()
            .map(|r| r.unwrap())
            .collect();
        for col in [
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
        ] {
            assert!(cols.contains(&col.to_string()), "missing column {col}");
        }
    }

    #[test]
    fn publish_and_get_roundtrip() {
        let s = store();
        let (a, content) = artifact("Hello", "hello kcp");
        s.publish(&a, &content, None).unwrap();
        let got = s.get(&a.id).unwrap().unwrap();
        assert_eq!(got, a);
    }

    #[test]
    fn publish_stores_content() {
        let s = store();
        let (a, content) = artifact("Hello", "hello kcp");
        s.publish(&a, &content, None).unwrap();
        assert_eq!(s.get_content(&a.content_hash).unwrap().unwrap(), content);
    }

    #[test]
    fn get_returns_none_for_unknown_id() {
        assert!(store().get("nope").unwrap().is_none());
    }

    #[test]
    fn get_content_returns_none_for_unknown_hash() {
        assert!(store().get_content("deadbeef").unwrap().is_none());
    }

    #[test]
    fn publish_writes_audit_row() {
        let s = store();
        let (a, content) = artifact("Hello", "x");
        s.publish(&a, &content, None).unwrap();
        let log = s.audit_log(10).unwrap();
        assert_eq!(log.len(), 1);
        assert_eq!(log[0].action, "publish");
        assert_eq!(log[0].artifact_id, a.id);
    }

    #[test]
    fn delete_soft_deletes_and_audits() {
        let s = store();
        let (a, content) = artifact("Hello", "x");
        s.publish(&a, &content, None).unwrap();
        assert!(s.delete(&a.id, "alice@acme.com").unwrap());
        assert!(s.get(&a.id).unwrap().is_none());
        assert!(!s.delete(&a.id, "alice@acme.com").unwrap());
        assert_eq!(s.audit_log(10).unwrap().len(), 2);
    }

    #[test]
    fn delete_unknown_returns_false() {
        assert!(!store().delete("nope", "u").unwrap());
    }

    #[test]
    fn list_orders_newest_first() {
        let s = store();
        for (i, title) in ["one", "two", "three"].iter().enumerate() {
            let mut a = KnowledgeArtifact::new(*title, "u", "t", "text");
            a.timestamp = format!("2026-01-0{}T00:00:00.000000+00:00", i + 1);
            a.content_hash = crypto::hash_content(title.as_bytes());
            s.publish(&a, title.as_bytes(), None).unwrap();
        }
        let listed = s.list_artifacts(None, None, &[], None, 10, 0).unwrap();
        assert_eq!(
            listed.iter().map(|a| a.title.clone()).collect::<Vec<_>>(),
            vec!["three", "two", "one"]
        );
    }

    #[test]
    fn list_respects_limit_and_offset() {
        let s = store();
        for i in 0..5 {
            let title = format!("t{}", i);
            let mut a = KnowledgeArtifact::new(&title, "u", "t", "text");
            a.content_hash = crypto::hash_content(title.as_bytes());
            s.publish(&a, title.as_bytes(), None).unwrap();
        }
        assert_eq!(s.list_artifacts(None, None, &[], None, 2, 0).unwrap().len(), 2);
        assert_eq!(s.list_artifacts(None, None, &[], None, 10, 4).unwrap().len(), 1);
    }

    #[test]
    fn list_filters_by_tenant_and_user_and_format() {
        let s = store();
        let mut a = KnowledgeArtifact::new("A", "alice", "acme", "markdown");
        a.content_hash = crypto::hash_content(b"a");
        let mut b = KnowledgeArtifact::new("B", "bob", "other", "text");
        b.content_hash = crypto::hash_content(b"b");
        s.publish(&a, b"a", None).unwrap();
        s.publish(&b, b"b", None).unwrap();

        assert_eq!(s.list_artifacts(Some("acme"), None, &[], None, 10, 0).unwrap().len(), 1);
        assert_eq!(s.list_artifacts(None, Some("bob"), &[], None, 10, 0).unwrap().len(), 1);
        assert_eq!(s.list_artifacts(None, None, &[], Some("text"), 10, 0).unwrap().len(), 1);
    }

    #[test]
    fn list_filters_by_tag() {
        let s = store();
        let mut a = KnowledgeArtifact::new("Tagged", "u", "t", "text");
        a.tags = vec!["finance".into(), "q1".into()];
        a.content_hash = crypto::hash_content(b"a");
        let mut b = KnowledgeArtifact::new("Untagged", "u", "t", "text");
        b.content_hash = crypto::hash_content(b"b");
        s.publish(&a, b"a", None).unwrap();
        s.publish(&b, b"b", None).unwrap();

        let found = s.list_artifacts(None, None, &["finance".to_string()], None, 10, 0).unwrap();
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].title, "Tagged");
    }

    #[test]
    fn search_finds_by_title() {
        let s = store();
        let (a, content) = artifact("Authentication Guide", "jwt tokens");
        s.publish(&a, &content, None).unwrap();
        let resp = s.search("Authentication", None, 20, 0).unwrap();
        assert_eq!(resp.results.len(), 1);
        assert_eq!(resp.results[0].id, a.id);
        assert_eq!(resp.total, 1);
    }

    #[test]
    fn search_finds_by_content_text() {
        let s = store();
        let (a, content) = artifact("Notes", "kubernetes networking deep dive");
        s.publish(&a, &content, None).unwrap();
        assert_eq!(s.search("kubernetes", None, 20, 0).unwrap().results.len(), 1);
    }

    #[test]
    fn search_finds_by_summary_and_source() {
        let s = store();
        let mut a = KnowledgeArtifact::new("T", "u", "t", "text");
        a.summary = "quarterly revenue analysis".into();
        a.source = "agent:analyst".into();
        a.content_hash = crypto::hash_content(b"c");
        s.publish(&a, b"c", None).unwrap();
        assert_eq!(s.search("revenue", None, 20, 0).unwrap().results.len(), 1);
        assert_eq!(s.search("analyst", None, 20, 0).unwrap().results.len(), 1);
    }

    #[test]
    fn search_returns_empty_for_no_match() {
        let s = store();
        let (a, content) = artifact("Hello", "world");
        s.publish(&a, &content, None).unwrap();
        assert!(s.search("zzzznotfound", None, 20, 0).unwrap().results.is_empty());
    }

    #[test]
    fn search_empty_query_returns_everything() {
        let s = store();
        let (a, content) = artifact("One", "first");
        s.publish(&a, &content, None).unwrap();
        let (b, content2) = artifact("Two", "second");
        s.publish(&b, &content2, None).unwrap();
        assert_eq!(s.search("", None, 20, 0).unwrap().results.len(), 2);
    }

    #[test]
    fn search_respects_limit() {
        let s = store();
        for i in 0..5 {
            let title = format!("doc {i}");
            let mut a = KnowledgeArtifact::new(&title, "u", "t", "text");
            a.content_hash = crypto::hash_content(title.as_bytes());
            s.publish(&a, title.as_bytes(), None).unwrap();
        }
        assert_eq!(s.search("doc", None, 2, 0).unwrap().results.len(), 2);
    }

    #[test]
    fn search_ignores_soft_deleted() {
        let s = store();
        let (a, content) = artifact("Ephemeral", "temp");
        s.publish(&a, &content, None).unwrap();
        s.delete(&a.id, "u").unwrap();
        assert!(s.search("Ephemeral", None, 20, 0).unwrap().results.is_empty());
    }

    #[test]
    fn search_filters_by_tenant() {
        let s = store();
        let mut a = KnowledgeArtifact::new("Shared topic", "u", "tenant-a", "text");
        a.content_hash = crypto::hash_content(b"a");
        s.publish(&a, b"a", None).unwrap();
        let mut b = KnowledgeArtifact::new("Shared topic", "u", "tenant-b", "text");
        b.content_hash = crypto::hash_content(b"b");
        s.publish(&b, b"b", None).unwrap();
        assert_eq!(s.search("Shared", Some("tenant-a"), 20, 0).unwrap().results.len(), 1);
        assert_eq!(s.search("Shared", None, 20, 0).unwrap().results.len(), 2);
    }

    #[test]
    fn search_relevance_is_between_zero_and_one() {
        let s = store();
        let (a, content) = artifact("Vector Search", "vector vector vector");
        s.publish(&a, &content, None).unwrap();
        let resp = s.search("vector", None, 20, 0).unwrap();
        let relevance = resp.results[0].relevance;
        assert!((0.0..=1.0).contains(&relevance), "relevance {relevance}");
    }

    #[test]
    fn search_query_time_is_recorded() {
        let s = store();
        let resp = s.search("anything", None, 20, 0).unwrap();
        assert!(resp.query_time_ms >= 0);
    }

    #[test]
    fn lineage_single_root() {
        let s = store();
        let (a, content) = artifact("Root", "x");
        s.publish(&a, &content, None).unwrap();
        let chain = s.get_lineage(&a.id).unwrap();
        assert_eq!(chain.len(), 1);
        assert_eq!(chain[0].id, a.id);
        assert!(chain[0].derived_from.is_none());
    }

    #[test]
    fn lineage_chain_is_root_first() {
        let s = store();
        let (root, c1) = artifact("Root", "r");
        s.publish(&root, &c1, None).unwrap();
        let (mid, c2) = artifact("Mid", "m");
        s.publish(&mid, &c2, Some(&root.id)).unwrap();
        let (leaf, c3) = artifact("Leaf", "l");
        s.publish(&leaf, &c3, Some(&mid.id)).unwrap();

        let chain = s.get_lineage(&leaf.id).unwrap();
        assert_eq!(
            chain.iter().map(|e| e.title.clone()).collect::<Vec<_>>(),
            vec!["Root", "Mid", "Leaf"]
        );
        assert_eq!(chain[2].derived_from.as_deref(), Some(mid.id.as_str()));
    }

    #[test]
    fn lineage_unknown_id_is_empty() {
        assert!(store().get_lineage("nope").unwrap().is_empty());
    }

    #[test]
    fn lineage_survives_cycles() {
        let s = store();
        let (a, c) = artifact("A", "a");
        s.publish(&a, &c, None).unwrap();
        let (b, c) = artifact("B", "b");
        s.publish(&b, &c, Some(&a.id)).unwrap();
        // Force a cycle: a derived from b
        s.conn
            .execute("UPDATE kcp_artifacts SET derived_from = ? WHERE id = ?", params![b.id, a.id])
            .unwrap();
        let chain = s.get_lineage(&a.id).unwrap();
        assert_eq!(chain.len(), 2);
    }

    #[test]
    fn derivatives_lists_children() {
        let s = store();
        let (root, c1) = artifact("Root", "r");
        s.publish(&root, &c1, None).unwrap();
        for title in ["child1", "child2"] {
            let (child, content) = artifact(title, "c");
            s.publish(&child, &content, Some(&root.id)).unwrap();
        }
        let kids = s.get_derivatives(&root.id).unwrap();
        assert_eq!(kids.len(), 2);
        assert!(kids.iter().all(|k| k.derived_from.as_deref() == Some(root.id.as_str())));
    }

    #[test]
    fn config_set_get_and_default() {
        let s = store();
        assert_eq!(s.get_config("missing").unwrap(), "");
        assert_eq!(s.get_config_or("missing", "fallback").unwrap(), "fallback");
        s.set_config("user_id", "alice").unwrap();
        assert_eq!(s.get_config("user_id").unwrap(), "alice");
        s.set_config("user_id", "bob").unwrap();
        assert_eq!(s.get_config("user_id").unwrap(), "bob");
    }

    #[test]
    fn peer_add_and_list() {
        let s = store();
        s.add_peer("peer-1", "https://p1.kcp.dev", "peer one", "pk1").unwrap();
        let peers = s.get_peers().unwrap();
        assert_eq!(peers.len(), 1);
        assert_eq!(peers[0].url, "https://p1.kcp.dev");
        assert_eq!(peers[0].name, "peer one");
    }

    #[test]
    fn upsert_peer_updates_by_url() {
        let s = store();
        s.upsert_peer("https://p1.kcp.dev", "one", "node-1", "pk").unwrap();
        s.upsert_peer("https://p1.kcp.dev", "one-renamed", "node-1", "pk").unwrap();
        let peers = s.get_peers().unwrap();
        assert_eq!(peers.len(), 1);
        assert_eq!(peers[0].name, "one-renamed");
    }

    #[test]
    fn peer_seen_updates_timestamp() {
        let s = store();
        s.add_peer("peer-1", "https://p1.kcp.dev", "", "").unwrap();
        s.update_peer_seen("peer-1").unwrap();
        s.update_peer_seen_by_url("https://p1.kcp.dev").unwrap();
        assert!(!s.get_peers().unwrap()[0].last_seen.is_empty());
    }

    #[test]
    fn stats_counts_artifacts_and_content() {
        let s = store();
        let (a, content) = artifact("One", "hello kcp");
        s.publish(&a, &content, None).unwrap();
        let stats = s.stats().unwrap();
        assert_eq!(stats.artifacts, 1);
        assert_eq!(stats.content_size_bytes, content.len() as i64);
        assert!(!stats.content_size_human.is_empty());
        assert!(!stats.db_path.is_empty());
    }

    #[test]
    fn import_artifact_is_idempotent() {
        let s = store();
        let (a, content) = artifact("Sync", "payload");
        let payload = json!({
            "id": a.id,
            "version": a.version,
            "user_id": a.user_id,
            "tenant_id": a.tenant_id,
            "timestamp": a.timestamp,
            "format": a.format,
            "visibility": a.visibility,
            "title": a.title,
            "content_hash": a.content_hash,
            "_content_b64": base64_encode(&content),
        });
        assert!(s.import_artifact(&payload).unwrap());
        assert!(!s.import_artifact(&payload).unwrap());
        assert_eq!(s.get_content(&a.content_hash).unwrap().unwrap(), content);
    }

    #[test]
    fn import_requires_id() {
        assert!(store().import_artifact(&json!({"title": "x"})).is_err());
    }

    #[test]
    fn get_artifact_with_content_includes_b64_and_lineage() {
        let s = store();
        let (root, c1) = artifact("Root", "r");
        s.publish(&root, &c1, None).unwrap();
        let (leaf, content) = artifact("Leaf", "leaf");
        s.publish(&leaf, &content, Some(&root.id)).unwrap();

        let payload = s.get_artifact_with_content(&leaf.id).unwrap().unwrap();
        assert_eq!(payload["derived_from"], json!(root.id));
        assert_eq!(payload["_content_b64"], json!(base64_encode(&content)));
        assert!(s.get_artifact_with_content("nope").unwrap().is_none());
    }

    #[test]
    fn ids_since_only_returns_public() {
        let s = store();
        let mut pub_artifact = KnowledgeArtifact::new("Public", "u", "t", "text");
        pub_artifact.visibility = "public".into();
        pub_artifact.content_hash = crypto::hash_content(b"p");
        s.publish(&pub_artifact, b"p", None).unwrap();

        let mut priv_artifact = KnowledgeArtifact::new("Private", "u", "t", "text");
        priv_artifact.visibility = "private".into();
        priv_artifact.content_hash = crypto::hash_content(b"s");
        s.publish(&priv_artifact, b"s", None).unwrap();

        let ids = s.get_artifact_ids_since(None).unwrap();
        assert_eq!(ids, vec![pub_artifact.id.clone()]);
        let ids_future = s.get_artifact_ids_since(Some("2999-01-01T00:00:00+00:00")).unwrap();
        assert!(ids_future.is_empty());
    }

    #[test]
    fn sync_queue_enqueue_dequeue_ack() {
        let s = store();
        let urls = vec!["https://p1".to_string(), "https://p2".to_string()];
        assert_eq!(s.enqueue_sync("artifact-1", &urls).unwrap(), 2);
        // Duplicate enqueue is ignored (UNIQUE constraint)
        assert_eq!(s.enqueue_sync("artifact-1", &urls).unwrap(), 0);

        let batch = s.dequeue_pending_sync(10).unwrap();
        assert_eq!(batch.len(), 2);
        // Claimed items are no longer pending
        assert!(s.dequeue_pending_sync(10).unwrap().is_empty());

        s.ack_sync(batch[0].id).unwrap();
        let replication = s.get_replication_summary().unwrap();
        assert_eq!(replication, vec![("artifact-1".to_string(), 1)]);
    }

    #[test]
    fn nack_sync_schedules_retry_then_fails() {
        let s = store();
        s.enqueue_sync("a1", &["https://p1".to_string()]).unwrap();
        let item = s.dequeue_pending_sync(10).unwrap().remove(0);
        s.nack_sync(item.id, "boom", 7).unwrap();

        // Retry scheduled in the future → not immediately claimable.
        assert!(s.dequeue_pending_sync(10).unwrap().is_empty());
        let stats = s.sync_queue_stats().unwrap();
        assert_eq!(stats, vec![("https://p1".to_string(), "pending".to_string(), 1)]);

        // Past max attempts → permanently failed.
        s.conn
            .execute("UPDATE kcp_sync_queue SET attempts = 7 WHERE id = ?", params![item.id])
            .unwrap();
        s.nack_sync(item.id, "boom", 7).unwrap();
        assert_eq!(
            s.sync_queue_stats().unwrap(),
            vec![("https://p1".to_string(), "failed".to_string(), 1)]
        );
    }

    #[test]
    fn nack_unknown_queue_id_is_noop() {
        assert!(store().nack_sync(999, "err", 7).is_ok());
    }

    #[test]
    fn replication_status_shape() {
        let s = store();
        s.record_replication("a1", "https://p1").unwrap();
        s.record_replication_ack("a1", "https://p2").unwrap();
        let status = s.get_replication_status("a1").unwrap();
        assert_eq!(status["count"], json!(2));
        assert_eq!(status["replicated_to"].as_array().unwrap().len(), 2);
        assert_eq!(s.get_replication_summary().unwrap(), vec![("a1".to_string(), 2)]);
    }

    #[test]
    fn log_sync_writes_row() {
        let s = store();
        s.log_sync("peer-1", "push", 3, "ok", "3 artifacts").unwrap();
        let count: i64 = s
            .conn
            .query_row("SELECT COUNT(*) FROM kcp_sync_log", [], |r| r.get(0))
            .unwrap();
        assert_eq!(count, 1);
    }

    #[test]
    fn rebuild_fts_reindexes_existing_rows() {
        let s = store();
        let (a, content) = artifact("Reindex Me", "alpha content");
        s.publish(&a, &content, None).unwrap();
        s.conn.execute_batch("DROP TABLE kcp_fts").unwrap();
        rebuild_fts(&s.conn).unwrap();
        assert_eq!(s.search("Reindex", None, 20, 0).unwrap().results.len(), 1);
    }

    #[test]
    fn encrypted_content_is_not_indexed_but_metadata_is() {
        let s = store();
        let key = crypto::derive_content_key(&[7u8; 32], "id");
        let blob = crypto::encrypt_content(b"top secret keyword", &key).unwrap();
        let mut a = KnowledgeArtifact::new("Secret Title", "u", "t", "text");
        a.content_hash = crypto::hash_content(b"top secret keyword");
        s.publish(&a, &blob, None).unwrap();
        assert_eq!(s.search("Secret", None, 20, 0).unwrap().results.len(), 1);
        // The ciphertext must not leak into the searchable index.
        assert!(s.search("keyword", None, 20, 0).unwrap().results.is_empty());
    }

    #[test]
    fn open_creates_missing_directories() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("nested/deeper/kcp.db");
        let s = LocalStore::open(&path).unwrap();
        assert!(path.exists());
        drop(s);
    }

    #[test]
    fn reopen_preserves_data() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("kcp.db");
        let id = {
            let s = LocalStore::open(&path).unwrap();
            let (a, content) = artifact("Persisted", "bytes");
            s.publish(&a, &content, None).unwrap();
            a.id
        };
        let s2 = LocalStore::open(&path).unwrap();
        assert!(s2.get(&id).unwrap().is_some());
    }

    #[test]
    fn extract_text_skips_encrypted_and_empty() {
        assert_eq!(extract_text(b""), "");
        assert_eq!(extract_text(ENCRYPTION_MAGIC), "");
        assert_eq!(extract_text(b"plain"), "plain");
    }

    #[test]
    fn relevance_formula_matches_reference() {
        assert_eq!(relevance_from_bm25(Some(0.0)), 1.0);
        assert_eq!(relevance_from_bm25(Some(-1.0)), 0.5);
        assert_eq!(relevance_from_bm25(None), 0.5);
    }
}
