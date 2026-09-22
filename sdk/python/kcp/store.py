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

from __future__ import annotations

import json
import sqlite3
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import (
    KnowledgeArtifact,
    SearchResponse,
    SearchResult,
    normalize_expires_at,
    is_expired,
)
from .content_store import ContentStore


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
    deleted_at TEXT,
    canonical_id TEXT,
    expires_at TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    superseded_by TEXT
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

-- Replication tracking: how many peers have ACKed each artifact
CREATE TABLE IF NOT EXISTS kcp_replication (
    artifact_id  TEXT NOT NULL,
    peer_url     TEXT NOT NULL,
    acked_at     TEXT NOT NULL,
    PRIMARY KEY (artifact_id, peer_url)
);

CREATE INDEX IF NOT EXISTS idx_replication_artifact ON kcp_replication(artifact_id);
"""

FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS kcp_fts USING fts5(
    id UNINDEXED,
    title,
    summary,
    tags,
    source,
    content_text,
    tokenize = 'porter unicode61'
);
"""

FTS_MIGRATE_SQL = """
ALTER TABLE kcp_fts ADD COLUMN content_text;
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
        # Filesystem content store — sibling dir of the .db file
        self.content_store = ContentStore(self.db_path.parent)
        self._init_db()

    def _init_db(self):
        """Initialize database with schema."""
        conn = self._get_conn()
        conn.executescript(SCHEMA_SQL)
        # Idempotent migration for databases created before issue #4
        # (TTL / status / versioning). Must run AFTER executescript because the
        # new indexes reference columns that legacy tables don't have yet.
        self._migrate_ttl_versioning(conn)
        try:
            # Try to create FTS table fresh
            conn.executescript(FTS_SQL)
        except sqlite3.OperationalError:
            pass  # FTS5 not available — degrade gracefully
        # Migrate existing FTS tables that lack content_text column
        try:
            conn.execute("SELECT content_text FROM kcp_fts LIMIT 1")
        except sqlite3.OperationalError:
            # Old schema — rebuild FTS from scratch
            try:
                conn.execute("DROP TABLE IF EXISTS kcp_fts")
                conn.executescript(FTS_SQL)
                # Re-index existing artifacts
                self._rebuild_fts(conn)
            except sqlite3.OperationalError:
                pass
        conn.commit()
        # One-time migration: move BLOBs from kcp_content → filesystem
        self._migrate_blobs_to_filesystem(conn)

    def _migrate_ttl_versioning(self, conn: sqlite3.Connection):
        """
        Add TTL / status / versioning columns to an existing database.

        Idempotent: a column is only ALTERed in when it is missing, so this is
        safe to run on every LocalStore init (fresh and legacy DBs alike).
        Existing rows get ``status='active'`` and ``expires_at=NULL`` — i.e. a
        legacy artifact behaves exactly as before (never expires, active).
        ``canonical_id`` is intentionally left NULL for legacy rows and resolved
        lazily as ``COALESCE(canonical_id, id)`` so that signatures computed
        before this extension keep verifying.
        """
        migrations = (
            ("kcp_artifacts", "canonical_id", "TEXT"),
            ("kcp_artifacts", "expires_at", "TEXT"),
            ("kcp_artifacts", "status", "TEXT NOT NULL DEFAULT 'active'"),
            ("kcp_artifacts", "superseded_by", "TEXT"),
        )
        for table, column, ddl in migrations:
            cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_artifacts_canonical "
            "ON kcp_artifacts(canonical_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_artifacts_status ON kcp_artifacts(status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_artifacts_expires "
            "ON kcp_artifacts(expires_at)"
        )
        conn.commit()

    def _sweep_expired(self, conn: Optional[sqlite3.Connection] = None) -> int:
        """
        Lazily persist the ``active`` → ``expired`` transition.

        An artifact is *derived* as expired when ``expires_at <= now`` (UTC).
        Rather than running a background janitor, every read entry point
        (get/search/list/get_current/versions) calls this sweep first, so the
        stored ``status`` is authoritative for SQL filters at query time.
        ``superseded`` is terminal: a superseded artifact is never re-marked
        expired (precedence: superseded > expired).

        Returns the number of rows transitioned.
        """
        conn = conn or self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        cursor = conn.execute(
            "UPDATE kcp_artifacts SET status = 'expired' "
            "WHERE status = 'active' AND expires_at IS NOT NULL AND expires_at <= ?",
            (now,),
        )
        # Always commit: Python's sqlite3 opens an implicit transaction on DML
        # even when 0 rows match, which would otherwise hold a write lock.
        conn.commit()
        return cursor.rowcount

    @staticmethod
    def _status_filters(
        alias: str,
        include_superseded: bool,
        include_expired: bool,
        status: Optional[str] = None,
    ) -> tuple[list[str], list]:
        """Build SQL conditions restricting rows by lifecycle status.

        Default (both flags False) → only ``active`` artifacts are returned.
        Passing ``status`` explicitly bypasses the boolean flags.
        """
        if status:
            return [f"{alias}.status = ?"], [status]
        conds: list[str] = []
        params: list = []
        if not include_superseded:
            conds.append(f"{alias}.status != 'superseded'")
        if not include_expired:
            conds.append(f"{alias}.status != 'expired'")
        return conds, params

    def _rebuild_fts(self, conn: sqlite3.Connection):
        """Re-index all artifacts into FTS (used after schema migration)."""
        rows = conn.execute(
            "SELECT a.id, a.title, a.summary, a.tags, a.source, c.content "
            "FROM kcp_artifacts a LEFT JOIN kcp_content c ON a.content_hash = c.content_hash "
            "WHERE a.deleted_at IS NULL"
        ).fetchall()
        for row in rows:
            content_text = ""
            if row["content"]:
                try:
                    raw = row["content"]
                    if isinstance(raw, bytes):
                        # Skip encrypted blobs (magic KCP1)
                        if not raw[:4] == b"KCP1":
                            content_text = raw.decode("utf-8", errors="ignore")[:50000]
                    else:
                        content_text = str(raw)[:50000]
                except Exception:
                    pass
            conn.execute(
                "INSERT OR REPLACE INTO kcp_fts (id, title, summary, tags, source, content_text) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (row["id"], row["title"], row["summary"] or "",
                 row["tags"] or "", row["source"] or "", content_text),
            )

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
        canonical_id: Optional[str] = None,
        expires_at: Optional[str] = None,
        status: Optional[str] = None,
    ) -> KnowledgeArtifact:
        """
        Store a knowledge artifact with its content.

        Args:
            artifact: The artifact metadata
            content: Raw content bytes
            derived_from: ID of parent artifact (for lineage tracking)
            canonical_id: Stable ID shared by all versions of this artifact
                (default: the artifact's own id — a standalone artifact)
            expires_at: ISO 8601 TTL deadline (default: artifact.expires_at)
            status: Lifecycle status (default: artifact.status)

        Returns:
            The stored artifact
        """
        conn = self._get_conn()

        # ── Lifecycle / versioning resolution (issue #4) ──
        canonical_id = (
            canonical_id
            if canonical_id is not None
            else (getattr(artifact, "canonical_id", "") or artifact.id)
        )
        expires_at = normalize_expires_at(
            expires_at if expires_at is not None else getattr(artifact, "expires_at", None)
        )
        status = status or getattr(artifact, "status", "") or "active"
        # An artifact published with an already-past deadline is born expired.
        if status == "active" and is_expired(expires_at):
            status = "expired"
        # Keep the in-memory object consistent with what we persist
        artifact.canonical_id = canonical_id
        artifact.expires_at = expires_at
        artifact.status = status

        # Store content — filesystem primary, SQLite as fallback index
        if content:
            # Write to filesystem shard (idempotent)
            self.content_store.write(
                artifact.content_hash,
                content,
                timestamp=artifact.timestamp,
            )
            # Keep kcp_content as a lightweight index (hash + size, no blob)
            conn.execute(
                "INSERT OR IGNORE INTO kcp_content (content_hash, content, size_bytes) "
                "VALUES (?, ?, ?)",
                (artifact.content_hash, b"", len(content)),
            )

        # Store metadata
        conn.execute(
            """INSERT OR REPLACE INTO kcp_artifacts
            (id, version, user_id, tenant_id, team, tags, source, created_at,
             format, visibility, title, summary, lineage, content_hash,
             content_url, signature, acl, derived_from,
             canonical_id, expires_at, status, superseded_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                canonical_id,
                expires_at,
                status,
                getattr(artifact, "superseded_by", "") or None,
            ),
        )

        # Update FTS index — include content_text for full-content search
        try:
            # Extract text from content (skip encrypted blobs)
            content_text = ""
            if content:
                if not content[:4] == b"KCP1":
                    content_text = content.decode("utf-8", errors="ignore")[:50000]
            conn.execute(
                "INSERT OR REPLACE INTO kcp_fts "
                "(id, title, summary, tags, source, content_text) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    artifact.id,
                    artifact.title,
                    artifact.summary or "",
                    " ".join(artifact.tags) if artifact.tags else "",
                    artifact.source or "",
                    content_text,
                ),
            )
        except sqlite3.OperationalError:
            pass  # FTS5 not available

        # Audit
        self._audit(artifact.user_id, "publish", artifact.id)
        if canonical_id != artifact.id and getattr(artifact, "version", "1") != "1":
            self._audit(
                artifact.user_id,
                "publish_version",
                artifact.id,
                details=f"canonical_id={canonical_id} version={artifact.version}",
            )

        conn.commit()
        return artifact

    def get(
        self,
        artifact_id: str,
        include_superseded: bool = True,
        include_expired: bool = True,
    ) -> Optional[KnowledgeArtifact]:
        """Retrieve artifact metadata by ID.

        By default returns the artifact whatever its lifecycle status
        (``superseded`` / ``expired`` included) — callers that want only
        current knowledge should use ``get_current()`` or the search defaults.
        """
        conn = self._get_conn()
        self._sweep_expired(conn)
        row = conn.execute(
            "SELECT * FROM kcp_artifacts WHERE id = ? AND deleted_at IS NULL",
            (artifact_id,),
        ).fetchone()

        if not row:
            return None

        return self._row_to_artifact(row)

    def get_content(self, content_hash: str) -> Optional[bytes]:
        """Retrieve raw content by hash — filesystem first, SQLite blob fallback."""
        # Primary: filesystem shard
        data = self.content_store.read(content_hash)
        if data:
            return data

        # Fallback: legacy SQLite blob (pre-migration data or non-migrated peers)
        conn = self._get_conn()
        row = conn.execute(
            "SELECT content FROM kcp_content WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        if row and row["content"]:
            blob = bytes(row["content"])
            if blob:
                # Opportunistically migrate to filesystem
                self.content_store.write(content_hash, blob)
                return blob

        return None

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
        include_superseded: bool = False,
        include_expired: bool = False,
        canonical_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[KnowledgeArtifact]:
        """List artifacts with optional filters.

        Lifecycle defaults mirror search: only ``active`` artifacts are
        listed unless ``include_superseded`` / ``include_expired`` is set.
        """
        conn = self._get_conn()
        self._sweep_expired(conn)
        query = "SELECT * FROM kcp_artifacts WHERE deleted_at IS NULL"
        params: list = []

        conds, cond_params = self._status_filters(
            "kcp_artifacts", include_superseded, include_expired, status
        )
        for cond in conds:
            query += f" AND {cond}"
        params.extend(cond_params)

        if canonical_id:
            query += " AND COALESCE(canonical_id, id) = ?"
            params.append(canonical_id)
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
        include_superseded: bool = False,
        include_expired: bool = False,
        canonical_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> SearchResponse:
        """
        Full-text search across artifacts.

        Uses FTS5 with porter stemmer (stemming) and BM25 ranking.
        Searches: title, summary, tags, source, and full content_text.
        Falls back to LIKE search if FTS5 is unavailable.

        TTL / versioning (issue #4): by default only ``active`` artifacts are
        returned — superseded versions and expired knowledge are excluded.
        Pass ``include_superseded=True`` / ``include_expired=True`` (or an
        explicit ``status``) to widen the result set.
        """
        conn = self._get_conn()
        self._sweep_expired(conn)
        start = datetime.now(timezone.utc)

        status_conds, status_params = self._status_filters(
            "a", include_superseded, include_expired, status
        )
        status_sql = "".join(f" AND {c}" for c in status_conds)

        # Sanitize query for FTS5 — wrap multi-word in quotes to avoid syntax errors
        fts_query = query.strip()
        if not fts_query:
            fts_query = '""'

        try:
            # FTS5 with BM25 ranking — bm25() returns negative, lower = better match
            sql = """
                SELECT a.*, bm25(kcp_fts) AS bm25_score
                FROM kcp_fts f
                JOIN kcp_artifacts a ON f.id = a.id
                WHERE kcp_fts MATCH ? AND a.deleted_at IS NULL
            """
            params: list = [fts_query]

            if tenant_id:
                sql += " AND a.tenant_id = ?"
                params.append(tenant_id)
            if canonical_id:
                sql += " AND COALESCE(a.canonical_id, a.id) = ?"
                params.append(canonical_id)

            sql += status_sql
            params.extend(status_params)

            sql += " ORDER BY bm25_score LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(sql, params).fetchall()
            use_fts = True

        except sqlite3.OperationalError:
            # Fallback: LIKE search across all text fields
            use_fts = False
            sql = """
                SELECT *, NULL AS bm25_score FROM kcp_artifacts
                WHERE deleted_at IS NULL
                AND (title LIKE ? OR summary LIKE ? OR tags LIKE ? OR source LIKE ?)
            """
            like = f"%{query}%"
            params = [like, like, like, like]

            if tenant_id:
                sql += " AND tenant_id = ?"
                params.append(tenant_id)
            if canonical_id:
                sql += " AND COALESCE(canonical_id, id) = ?"
                params.append(canonical_id)

            for cond in status_conds:
                sql += f" AND {cond.replace('a.', '')}"
            params.extend(status_params)

            sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(sql, params).fetchall()

        elapsed = (datetime.now(timezone.utc) - start).total_seconds() * 1000

        results = []
        for row in rows:
            # BM25 is negative — convert to 0.0–1.0 relevance score
            bm25 = row["bm25_score"] if use_fts and row["bm25_score"] is not None else -1.0
            relevance = max(0.0, min(1.0, 1.0 / (1.0 + abs(bm25)))) if bm25 != 0 else 1.0
            results.append(
                SearchResult(
                    id=row["id"],
                    title=row["title"],
                    summary=row["summary"] or "",
                    created_at=row["created_at"],
                    relevance=round(relevance, 4),
                    format=row["format"],
                    status=row["status"] if "status" in row.keys() else "active",
                    canonical_id=row["canonical_id"]
                    if "canonical_id" in row.keys()
                    else "",
                )
            )

        # Count total matching
        try:
            count_sql = """
                SELECT COUNT(*) as c FROM kcp_fts f
                JOIN kcp_artifacts a ON f.id = a.id
                WHERE kcp_fts MATCH ? AND a.deleted_at IS NULL
            """
            count_params: list = [fts_query]
            if tenant_id:
                count_sql += " AND a.tenant_id = ?"
                count_params.append(tenant_id)
            if canonical_id:
                count_sql += " AND COALESCE(a.canonical_id, a.id) = ?"
                count_params.append(canonical_id)
            count_sql += status_sql
            count_params.extend(status_params)
            total = conn.execute(count_sql, count_params).fetchone()["c"]
        except sqlite3.OperationalError:
            total = len(results)

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

    def get_all_records(self) -> list[dict]:
        """
        Return lightweight metadata records for every live artifact.

        Used by the lineage graph / CRDT sync layer (RFC KCP-003): each record
        carries ``id`` + ``derived_from`` so parent/child edges can be rebuilt on
        the receiving node without transferring content.
        """
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, user_id, tenant_id, title, format, visibility, "
            "content_hash, signature, derived_from, created_at "
            "FROM kcp_artifacts WHERE deleted_at IS NULL"
        ).fetchall()
        return [
            {
                "id": r["id"],
                "user_id": r["user_id"],
                "tenant_id": r["tenant_id"],
                "title": r["title"],
                "format": r["format"],
                "visibility": r["visibility"],
                "content_hash": r["content_hash"],
                "signature": r["signature"] or "",
                "derived_from": r["derived_from"],
                "timestamp": r["created_at"],
            }
            for r in rows
        ]

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

    # ─── Versioning & TTL (issue #4) ───────────────────────────

    def resolve_canonical_id(self, artifact_id: str) -> Optional[str]:
        """Return the canonical id of an artifact (itself if standalone)."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT COALESCE(canonical_id, id) AS cid FROM kcp_artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
        return row["cid"] if row else None

    def next_version(self, canonical_id: str) -> int:
        """Next monotonic version number for a canonical artifact (max + 1)."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT version FROM kcp_artifacts WHERE COALESCE(canonical_id, id) = ?",
            (canonical_id,),
        ).fetchall()
        highest = 0
        for row in rows:
            try:
                highest = max(highest, int(str(row["version"]).split(".")[0]))
            except (TypeError, ValueError):
                continue
        return highest + 1

    def supersede_versions(
        self,
        canonical_id: str,
        superseded_by: str = "",
        except_id: str = "",
    ) -> int:
        """
        Mark every active (or expired-but-not-yet-superseded) version of a
        canonical artifact as ``superseded``.

        Args:
            canonical_id: stable id shared by the versions
            superseded_by: id of the new (current) version
            except_id: id to leave untouched (normally the new version)

        Returns the number of rows transitioned.
        """
        conn = self._get_conn()
        cursor = conn.execute(
            "UPDATE kcp_artifacts SET status = 'superseded', superseded_by = ? "
            "WHERE COALESCE(canonical_id, id) = ? AND deleted_at IS NULL "
            "AND status IN ('active', 'expired') AND id != ?",
            (superseded_by or None, canonical_id, except_id or ""),
        )
        conn.commit()
        return cursor.rowcount

    def expire_artifact(self, artifact_id: str, expires_at: Optional[str] = None) -> bool:
        """Force an artifact into ``expired`` status (optionally setting expires_at)."""
        conn = self._get_conn()
        if expires_at is not None:
            conn.execute(
                "UPDATE kcp_artifacts SET expires_at = ?, status = 'expired' WHERE id = ?",
                (normalize_expires_at(expires_at), artifact_id),
            )
        else:
            conn.execute(
                "UPDATE kcp_artifacts SET status = 'expired' WHERE id = ?",
                (artifact_id,),
            )
        conn.commit()
        return True

    def get_current(self, canonical_id: str) -> Optional[KnowledgeArtifact]:
        """
        Return the most recent ACTIVE version of a canonical artifact.

        Active means status='active' after the expiry sweep — a canonical whose
        only versions are expired/superseded yields ``None`` (use
        ``get_versions()`` to inspect the whole family).
        """
        if not canonical_id:
            return None
        conn = self._get_conn()
        self._sweep_expired(conn)
        row = conn.execute(
            "SELECT * FROM kcp_artifacts "
            "WHERE COALESCE(canonical_id, id) = ? AND deleted_at IS NULL "
            "AND status = 'active' "
            "ORDER BY CAST(version AS INTEGER) DESC, created_at DESC LIMIT 1",
            (canonical_id,),
        ).fetchone()
        return self._row_to_artifact(row) if row else None

    def get_versions(self, canonical_id: str) -> list[KnowledgeArtifact]:
        """All versions of a canonical artifact, oldest → newest (any status)."""
        conn = self._get_conn()
        self._sweep_expired(conn)
        rows = conn.execute(
            "SELECT * FROM kcp_artifacts "
            "WHERE COALESCE(canonical_id, id) = ? AND deleted_at IS NULL "
            "ORDER BY CAST(version AS INTEGER) ASC, created_at ASC",
            (canonical_id,),
        ).fetchall()
        return [self._row_to_artifact(r) for r in rows]

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

    def upsert_peer(self, url: str, name: str = "", node_id: str = "",
                    public_key: str = "", artifact_count: int = 0):
        """
        Insert or update a peer by URL.
        Used for gossip-discovered peers — no pre-assigned ID needed.
        """
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        existing = conn.execute(
            "SELECT id FROM kcp_peers WHERE url = ?", (url,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE kcp_peers SET "
                "name = COALESCE(NULLIF(?, ''), name), "
                "id = COALESCE(NULLIF(?, ''), id), "
                "last_seen = ?, "
                "public_key = COALESCE(NULLIF(?, ''), public_key) "
                "WHERE url = ?",
                (name, node_id, now, public_key, url),
            )
        else:
            import uuid
            peer_id = node_id or str(uuid.uuid4())
            conn.execute(
                "INSERT INTO kcp_peers (id, url, name, public_key, last_seen, added_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
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

    def update_peer_seen_by_url(self, url: str):
        """Update last_seen for a peer by URL."""
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("UPDATE kcp_peers SET last_seen = ? WHERE url = ?", (now, url))
        conn.commit()

    # ─── Sync ──────────────────────────────────────────────────

    def get_artifact_ids_since(self, since: Optional[str] = None) -> list[str]:
        """Get artifact IDs created after a given timestamp (for sync).
        Only returns public artifacts — private/org/team are never synced.
        """
        conn = self._get_conn()
        if since:
            rows = conn.execute(
                "SELECT id FROM kcp_artifacts WHERE created_at > ? AND deleted_at IS NULL "
                "AND visibility = 'public' ORDER BY created_at",
                (since,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id FROM kcp_artifacts WHERE deleted_at IS NULL "
                "AND visibility = 'public' ORDER BY created_at"
            ).fetchall()
        return [r["id"] for r in rows]

    def get_artifact_with_content(self, artifact_id: str) -> Optional[dict]:
        """Get artifact metadata + content for sync export."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM kcp_artifacts WHERE id = ? AND deleted_at IS NULL",
            (artifact_id,),
        ).fetchone()
        if not row:
            return None

        artifact = self._row_to_artifact(row)
        content = self.get_content(artifact.content_hash)
        result = artifact.to_dict(include_lifecycle=True)

        # Include derived_from for lineage preservation across nodes
        if row["derived_from"]:
            result["derived_from"] = row["derived_from"]

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
        fs_stats = self.content_store.stats()

        return {
            "artifacts": artifacts,
            "content_size_bytes": content_size,
            "content_size_human": self._human_size(content_size),
            "peers": peers,
            "db_size_bytes": db_size,
            "db_size_human": self._human_size(db_size),
            "db_path": str(self.db_path),
            "filesystem": {
                "files": fs_stats["total_files"],
                "size_bytes": fs_stats["total_bytes"],
                "size_human": fs_stats["total_bytes_human"],
                "shards": fs_stats["shard_count"],
                "content_root": fs_stats["content_root"],
            },
        }

    # ─── Internal ──────────────────────────────────────────────

    def _migrate_blobs_to_filesystem(self, conn: sqlite3.Connection):
        """
        One-time migration: copy BLOBs from kcp_content → filesystem shards.

        Runs on every LocalStore init but is fast after first run because
        the filesystem files already exist (ContentStore.write is idempotent).

        After copying, the BLOB column is cleared to free SQLite page space.
        The row itself is kept (with content=b'') so size_bytes stays accurate.
        """
        import logging
        log = logging.getLogger("kcp.store.migrate")

        # Find rows that still have a real BLOB (non-empty content)
        rows = conn.execute(
            "SELECT content_hash, content FROM kcp_content WHERE length(content) > 0"
        ).fetchall()

        if not rows:
            return  # Nothing to migrate

        migrated = 0
        for row in rows:
            content_hash = row["content_hash"]
            blob = bytes(row["content"])
            if not blob:
                continue

            # Try to find the artifact's timestamp for correct shard path
            art_row = conn.execute(
                "SELECT created_at FROM kcp_artifacts WHERE content_hash = ? LIMIT 1",
                (content_hash,),
            ).fetchone()
            timestamp = art_row["created_at"] if art_row else None

            try:
                self.content_store.write(content_hash, blob, timestamp=timestamp)
                # Clear the blob from SQLite — keep the row for size tracking
                conn.execute(
                    "UPDATE kcp_content SET content = x'' WHERE content_hash = ?",
                    (content_hash,),
                )
                migrated += 1
            except Exception as e:
                log.warning(f"Migration failed for {content_hash[:16]}…: {e}")

        if migrated:
            conn.commit()
            log.info(f"Migrated {migrated} blob(s) from SQLite → filesystem")

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

    # ─── Sync Queue ────────────────────────────────────────────

    def enqueue_sync(self, artifact_id: str, peer_urls: list) -> int:
        """
        Enqueue an artifact for delivery to one or more peers.
        Uses INSERT OR IGNORE to avoid duplicates.
        Returns number of new entries added.
        """
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        added = 0
        for url in peer_urls:
            result = conn.execute(
                "INSERT OR IGNORE INTO kcp_sync_queue "
                "(artifact_id, peer_url, status, created_at, next_attempt) VALUES (?, ?, 'pending', ?, ?)",
                (artifact_id, url, now, now),
            )
            added += result.rowcount
        conn.commit()
        return added

    def dequeue_pending_sync(self, batch_size: int = 10) -> list:
        """
        Fetch up to batch_size pending sync items whose next_attempt <= now.
        Marks them as in_flight atomically.
        Returns list of dicts with artifact_id, peer_url, attempts, id.
        """
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        rows = conn.execute(
            "SELECT id, artifact_id, peer_url, attempts FROM kcp_sync_queue "
            "WHERE status = 'pending' AND (next_attempt IS NULL OR next_attempt <= ?) "
            "ORDER BY created_at LIMIT ?",
            (now, batch_size),
        ).fetchall()
        if not rows:
            return []
        ids = [r["id"] for r in rows]
        conn.execute(
            f"UPDATE kcp_sync_queue SET status = 'in_flight', last_attempt = ? "
            f"WHERE id IN ({','.join('?' * len(ids))})",
            [now] + ids,
        )
        conn.commit()
        return [dict(r) for r in rows]

    def ack_sync(self, queue_id: int):
        """Mark a sync queue entry as successfully delivered — also records replication."""
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        # Fetch artifact_id + peer_url before updating
        row = conn.execute(
            "SELECT artifact_id, peer_url FROM kcp_sync_queue WHERE id = ?", (queue_id,)
        ).fetchone()
        conn.execute(
            "UPDATE kcp_sync_queue SET status = 'done', acked_at = ?, error = NULL WHERE id = ?",
            (now, queue_id),
        )
        # Record successful replication
        if row:
            conn.execute(
                "INSERT OR REPLACE INTO kcp_replication (artifact_id, peer_url, acked_at) VALUES (?, ?, ?)",
                (row["artifact_id"], row["peer_url"], now),
            )
        conn.commit()

    def nack_sync(self, queue_id: int, error: str, max_attempts: int = 7):
        """
        Mark a sync entry as failed and schedule retry with exponential backoff.
        After max_attempts, marks as permanently failed.
        """
        conn = self._get_conn()
        row = conn.execute(
            "SELECT attempts FROM kcp_sync_queue WHERE id = ?", (queue_id,)
        ).fetchone()
        if not row:
            return

        attempts = row["attempts"] + 1
        now = datetime.now(timezone.utc)

        if attempts >= max_attempts:
            conn.execute(
                "UPDATE kcp_sync_queue SET status = 'failed', attempts = ?, error = ? WHERE id = ?",
                (attempts, error, queue_id),
            )
        else:
            # Exponential backoff: 30s, 2m, 10m, 1h, 6h, 24h
            delays = [30, 120, 600, 3600, 21600, 86400]
            delay = delays[min(attempts - 1, len(delays) - 1)]
            from datetime import timedelta
            next_attempt = (now + timedelta(seconds=delay)).isoformat()
            conn.execute(
                "UPDATE kcp_sync_queue SET status = 'pending', attempts = ?, "
                "error = ?, next_attempt = ? WHERE id = ?",
                (attempts, error, next_attempt, queue_id),
            )
        conn.commit()

    def sync_queue_stats(self) -> dict:
        """Return sync queue status counts per peer."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT peer_url, status, COUNT(*) as cnt FROM kcp_sync_queue GROUP BY peer_url, status"
        ).fetchall()
        peers: dict = {}
        for row in rows:
            url = row["peer_url"]
            if url not in peers:
                peers[url] = {"pending": 0, "in_flight": 0, "done": 0, "failed": 0}
            peers[url][row["status"]] = peers[url].get(row["status"], 0) + row["cnt"]
        return peers

    # ─── Replication ───────────────────────────────────────────

    def record_replication(self, artifact_id: str, peer_url: str):
        """Mark that a peer has successfully ACKed this artifact."""
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO kcp_replication (artifact_id, peer_url, acked_at) VALUES (?, ?, ?)",
            (artifact_id, peer_url, now),
        )
        conn.commit()

    def get_replication_status(self, artifact_id: str) -> dict:
        """
        Return replication info for an artifact.
        {
          "artifact_id": "...",
          "replicated_to": ["https://peer04...", ...],
          "count": 2,
        }
        """
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT peer_url, acked_at FROM kcp_replication WHERE artifact_id = ? ORDER BY acked_at",
            (artifact_id,),
        ).fetchall()
        return {
            "artifact_id": artifact_id,
            "replicated_to": [r["peer_url"] for r in rows],
            "acked_at": {r["peer_url"]: r["acked_at"] for r in rows},
            "count": len(rows),
        }

    def record_replication_ack(self, artifact_id: str, peer_url: str):
        """
        Record that a peer has acknowledged receiving this artifact.
        Called by:
        - SyncWorker after successful push
        - sync_receive endpoint when receiving from another peer
        """
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO kcp_replication (artifact_id, peer_url, acked_at) VALUES (?, ?, ?)",
            (artifact_id, peer_url, now),
        )
        conn.commit()

    def get_replication_summary(self) -> dict:
        """Return replication counts per artifact (useful for dashboard)."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT artifact_id, COUNT(*) as peer_count FROM kcp_replication GROUP BY artifact_id"
        ).fetchall()
        return {r["artifact_id"]: r["peer_count"] for r in rows}

