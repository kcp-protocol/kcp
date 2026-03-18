"""
KCP Local Storage Backend

SQLite-based storage for Knowledge Artifacts.
Zero config — just a file. Portable, shareable, browser-compatible (via sql.js).

Usage:
    store = LocalStore("~/.kcp/kcp.db")
    store.publish(artifact, content=b"...")
    results = store.search("machine learning")
    artifact = store.get("artifact-id")
"""

import json
import sqlite3
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import KnowledgeArtifact, SearchResponse, SearchResult


# ─── Schema ────────────────────────────────────────────────────

SCHEMA_SQL = """
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
"""

FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS kcp_fts USING fts5(
    id UNINDEXED,
    title,
    summary,
    tags,
    source
);
"""


class LocalStore:
    """
    SQLite-based local storage for KCP artifacts.

    Thread-safe, zero-config, single file.
    Compatible with sql.js for browser-based viewing.
    """

    def __init__(self, db_path: str = "~/.kcp/kcp.db"):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self):
        """Initialize database with schema."""
        conn = self._get_conn()
        conn.executescript(SCHEMA_SQL)
        try:
            conn.executescript(FTS_SQL)
        except sqlite3.OperationalError:
            pass  # FTS5 not available — degrade gracefully
        conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        """Get or create SQLite connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # ─── CRUD ──────────────────────────────────────────────────

    def publish(
        self,
        artifact: KnowledgeArtifact,
        content: bytes = b"",
        derived_from: Optional[str] = None,
    ) -> KnowledgeArtifact:
        """
        Store a knowledge artifact with its content.

        Args:
            artifact: The artifact metadata
            content: Raw content bytes
            derived_from: ID of parent artifact (for lineage tracking)

        Returns:
            The stored artifact
        """
        conn = self._get_conn()

        # Store content
        if content:
            conn.execute(
                "INSERT OR IGNORE INTO kcp_content (content_hash, content, size_bytes) VALUES (?, ?, ?)",
                (artifact.content_hash, content, len(content)),
            )

        # Store metadata
        conn.execute(
            """INSERT OR REPLACE INTO kcp_artifacts
            (id, version, user_id, tenant_id, team, tags, source, created_at,
             format, visibility, title, summary, lineage, content_hash,
             content_url, signature, acl, derived_from)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                artifact.id,
                artifact.version,
                artifact.user_id,
                artifact.tenant_id,
                artifact.team,
                json.dumps(artifact.tags) if artifact.tags else "[]",
                artifact.source,
                artifact.timestamp,
                artifact.format,
                artifact.visibility,
                artifact.title,
                artifact.summary,
                json.dumps(artifact.lineage.to_dict()) if artifact.lineage else None,
                artifact.content_hash,
                artifact.content_url,
                artifact.signature,
                json.dumps(artifact.acl.to_dict()) if artifact.acl else None,
                derived_from,
            ),
        )

        # Update FTS index
        try:
            conn.execute(
                "INSERT OR REPLACE INTO kcp_fts (id, title, summary, tags, source) VALUES (?, ?, ?, ?, ?)",
                (
                    artifact.id,
                    artifact.title,
                    artifact.summary or "",
                    " ".join(artifact.tags) if artifact.tags else "",
                    artifact.source or "",
                ),
            )
        except sqlite3.OperationalError:
            pass  # FTS5 not available

        # Audit
        self._audit(artifact.user_id, "publish", artifact.id)

        conn.commit()
        return artifact

    def get(self, artifact_id: str) -> Optional[KnowledgeArtifact]:
        """Retrieve artifact metadata by ID."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM kcp_artifacts WHERE id = ? AND deleted_at IS NULL",
            (artifact_id,),
        ).fetchone()

        if not row:
            return None

        return self._row_to_artifact(row)

    def get_content(self, content_hash: str) -> Optional[bytes]:
        """Retrieve raw content by hash."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT content FROM kcp_content WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        return row["content"] if row else None

    def delete(self, artifact_id: str, user_id: str = "") -> bool:
        """Soft-delete an artifact."""
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        result = conn.execute(
            "UPDATE kcp_artifacts SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
            (now, artifact_id),
        )
        if result.rowcount > 0:
            self._audit(user_id, "delete", artifact_id)
            conn.commit()
            return True
        return False

    def list_artifacts(
        self,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        tags: Optional[list[str]] = None,
        format_filter: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[KnowledgeArtifact]:
        """List artifacts with optional filters."""
        conn = self._get_conn()
        query = "SELECT * FROM kcp_artifacts WHERE deleted_at IS NULL"
        params: list = []

        if tenant_id:
            query += " AND tenant_id = ?"
            params.append(tenant_id)
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        if format_filter:
            query += " AND format = ?"
            params.append(format_filter)
        if tags:
            for tag in tags:
                query += " AND tags LIKE ?"
                params.append(f"%{tag}%")

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        return [self._row_to_artifact(r) for r in rows]

    def search(
        self,
        query: str,
        tenant_id: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResponse:
        """Full-text search across artifacts."""
        conn = self._get_conn()
        start = datetime.now(timezone.utc)

        try:
            # Try FTS5 first
            sql = """
                SELECT a.*, rank
                FROM kcp_fts f
                JOIN kcp_artifacts a ON f.id = a.id
                WHERE kcp_fts MATCH ? AND a.deleted_at IS NULL
            """
            params: list = [query]

            if tenant_id:
                sql += " AND a.tenant_id = ?"
                params.append(tenant_id)

            sql += " ORDER BY rank LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(sql, params).fetchall()

        except sqlite3.OperationalError:
            # Fallback: LIKE search
            sql = """
                SELECT * FROM kcp_artifacts
                WHERE deleted_at IS NULL
                AND (title LIKE ? OR summary LIKE ? OR tags LIKE ?)
            """
            like = f"%{query}%"
            params = [like, like, like]

            if tenant_id:
                sql += " AND tenant_id = ?"
                params.append(tenant_id)

            sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(sql, params).fetchall()

        elapsed = (datetime.now(timezone.utc) - start).total_seconds() * 1000

        results = []
        for row in rows:
            results.append(
                SearchResult(
                    id=row["id"],
                    title=row["title"],
                    summary=row["summary"] or "",
                    created_at=row["created_at"],
                    relevance=1.0,
                    format=row["format"],
                )
            )

        # Count total
        count_sql = "SELECT COUNT(*) as c FROM kcp_artifacts WHERE deleted_at IS NULL"
        count_params: list = []
        if tenant_id:
            count_sql += " AND tenant_id = ?"
            count_params.append(tenant_id)
        total = conn.execute(count_sql, count_params).fetchone()["c"]

        return SearchResponse(
            results=results,
            total=total,
            query_time_ms=int(elapsed),
        )

    # ─── Lineage ───────────────────────────────────────────────

    def get_lineage(self, artifact_id: str) -> list[dict]:
        """
        Get the full lineage chain for an artifact.
        Returns list from root → current (oldest first).
        """
        conn = self._get_conn()
        chain = []
        current_id = artifact_id
        visited = set()

        while current_id and current_id not in visited:
            visited.add(current_id)
            row = conn.execute(
                "SELECT id, title, user_id, created_at, derived_from FROM kcp_artifacts WHERE id = ?",
                (current_id,),
            ).fetchone()

            if not row:
                break

            chain.append({
                "id": row["id"],
                "title": row["title"],
                "author": row["user_id"],
                "created_at": row["created_at"],
                "derived_from": row["derived_from"],
            })
            current_id = row["derived_from"]

        chain.reverse()  # Root first
        return chain

    def get_derivatives(self, artifact_id: str) -> list[dict]:
        """Get all artifacts derived from this one."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, title, user_id, created_at FROM kcp_artifacts WHERE derived_from = ? AND deleted_at IS NULL",
            (artifact_id,),
        ).fetchall()
        return [
            {"id": r["id"], "title": r["title"], "author": r["user_id"], "created_at": r["created_at"]}
            for r in rows
        ]

    # ─── Peers ─────────────────────────────────────────────────

    def add_peer(self, peer_id: str, url: str, name: str = "", public_key: str = ""):
        """Register a peer node."""
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT OR REPLACE INTO kcp_peers (id, url, name, public_key, last_seen, added_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (peer_id, url, name, public_key, now, now),
        )
        conn.commit()

    def get_peers(self) -> list[dict]:
        """List all known peers."""
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM kcp_peers ORDER BY last_seen DESC").fetchall()
        return [dict(r) for r in rows]

    def update_peer_seen(self, peer_id: str):
        """Update last_seen for a peer."""
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("UPDATE kcp_peers SET last_seen = ? WHERE id = ?", (now, peer_id))
        conn.commit()

    # ─── Sync ──────────────────────────────────────────────────

    def get_artifact_ids_since(self, since: Optional[str] = None) -> list[str]:
        """Get artifact IDs created after a given timestamp (for sync)."""
        conn = self._get_conn()
        if since:
            rows = conn.execute(
                "SELECT id FROM kcp_artifacts WHERE created_at > ? AND deleted_at IS NULL ORDER BY created_at",
                (since,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id FROM kcp_artifacts WHERE deleted_at IS NULL ORDER BY created_at"
            ).fetchall()
        return [r["id"] for r in rows]

    def get_artifact_with_content(self, artifact_id: str) -> Optional[dict]:
        """Get artifact metadata + content for sync export."""
        artifact = self.get(artifact_id)
        if not artifact:
            return None

        content = self.get_content(artifact.content_hash)
        result = artifact.to_dict()
        if content:
            import base64
            result["_content_b64"] = base64.b64encode(content).decode("utf-8")
        return result

    def import_artifact(self, data: dict) -> bool:
        """Import an artifact from sync (peer push). Returns True if new."""
        conn = self._get_conn()
        existing = conn.execute(
            "SELECT id FROM kcp_artifacts WHERE id = ?", (data["id"],)
        ).fetchone()

        if existing:
            return False  # Already have it

        artifact = KnowledgeArtifact.from_dict(data)
        content = b""
        if "_content_b64" in data:
            import base64
            content = base64.b64decode(data["_content_b64"])

        self.publish(artifact, content=content, derived_from=data.get("derived_from"))
        return True

    def log_sync(self, peer_id: str, direction: str, count: int, status: str = "ok", details: str = ""):
        """Log a sync event."""
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO kcp_sync_log (peer_id, direction, artifacts_synced, timestamp, status, details) VALUES (?, ?, ?, ?, ?, ?)",
            (peer_id, direction, count, now, status, details),
        )
        conn.commit()

    # ─── Config ────────────────────────────────────────────────

    def get_config(self, key: str, default: str = "") -> str:
        """Get a config value."""
        conn = self._get_conn()
        row = conn.execute("SELECT value FROM kcp_config WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_config(self, key: str, value: str):
        """Set a config value."""
        conn = self._get_conn()
        conn.execute("INSERT OR REPLACE INTO kcp_config (key, value) VALUES (?, ?)", (key, value))
        conn.commit()

    # ─── Stats ─────────────────────────────────────────────────

    def stats(self) -> dict:
        """Get storage statistics."""
        conn = self._get_conn()
        artifacts = conn.execute(
            "SELECT COUNT(*) as c FROM kcp_artifacts WHERE deleted_at IS NULL"
        ).fetchone()["c"]
        content_size = conn.execute(
            "SELECT COALESCE(SUM(size_bytes), 0) as s FROM kcp_content"
        ).fetchone()["s"]
        peers = conn.execute("SELECT COUNT(*) as c FROM kcp_peers").fetchone()["c"]
        db_size = os.path.getsize(str(self.db_path)) if self.db_path.exists() else 0

        return {
            "artifacts": artifacts,
            "content_size_bytes": content_size,
            "content_size_human": self._human_size(content_size),
            "peers": peers,
            "db_size_bytes": db_size,
            "db_size_human": self._human_size(db_size),
            "db_path": str(self.db_path),
        }

    # ─── Internal ──────────────────────────────────────────────

    def _row_to_artifact(self, row: sqlite3.Row) -> KnowledgeArtifact:
        """Convert a database row to KnowledgeArtifact."""
        from .models import Lineage, ACL

        data = dict(row)
        data["tags"] = json.loads(data.get("tags") or "[]")
        data["timestamp"] = data.pop("created_at", "")

        lineage_raw = data.pop("lineage", None)
        if lineage_raw:
            data["lineage"] = json.loads(lineage_raw)

        acl_raw = data.pop("acl", None)
        if acl_raw:
            data["acl"] = json.loads(acl_raw)

        # Remove fields not in model
        for key in ["deleted_at", "derived_from"]:
            data.pop(key, None)

        return KnowledgeArtifact.from_dict(data)

    def _audit(self, user_id: str, action: str, artifact_id: str = "", details: str = ""):
        """Record an audit event."""
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO kcp_audit (timestamp, user_id, action, artifact_id, details) VALUES (?, ?, ?, ?, ?)",
            (now, user_id, action, artifact_id, details),
        )

    @staticmethod
    def _human_size(size_bytes: int) -> str:
        """Convert bytes to human readable string."""
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"
