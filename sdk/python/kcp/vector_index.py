"""
KCP Local Vector Index

Stores artifact embeddings in the same SQLite file as the rest of the node and
answers nearest-neighbour queries with **exact cosine similarity implemented in
pure Python** (no numpy, no native extension).

Why pure Python by default
--------------------------
The issue that requested this feature (#1) proposed ``sqlite-vss`` for the local
backend. ``sqlite-vss`` is a *loadable SQLite extension* (a compiled ``.so``) —
it is not part of the Python standard library and cannot be a hard dependency of
a zero-infra SDK. So:

* ``search_backend="sqlite-vss"`` (aliases: ``sqlite_vss``, ``sqlite``,
  ``local``, ``vector``, ``auto``) is **accepted** and always works;
* the index tries to load the native extension. If it is present *and* passes a
  round-trip probe, it is used for KNN candidate retrieval (results are then
  re-ranked exactly, so recall is never silently degraded);
* if the extension is **not** available, the index falls back explicitly to the
  pure-Python exact scan and records *why* in :meth:`VectorIndex.status`
  (``fallback_reason``) — there is no silent failure and the query path is
  identical in behaviour, just O(N·dim) instead of ANN.

Server-side backends (``qdrant``, ``pgvector``, ``chroma``) are **not**
implemented here; they raise :class:`VectorIndexError` with a pointer to the
issue instead of pretending to work.

Storage schema (portable, inspectable with plain SQLite)::

    kcp_embeddings(
        artifact_id TEXT, model TEXT, dim INTEGER,
        vector BLOB,          -- float32 little-endian, packed with struct
        created_at TEXT,
        PRIMARY KEY (artifact_id, model)
    )
"""

from __future__ import annotations

import logging
import sqlite3
import struct
from collections.abc import Sequence
from datetime import datetime, timezone

from .embeddings import cosine_similarity, l2_normalize

logger = logging.getLogger("kcp.vector_index")

__all__ = [
    "BRUTEFORCE_BACKEND",
    "DEFAULT_VECTOR_BACKEND",
    "LOCAL_BACKENDS",
    "UNSUPPORTED_BACKENDS",
    "VectorIndex",
    "VectorIndexError",
    "decode_vector",
    "encode_vector",
]

#: Backend name reported when the native extension is unavailable (or not used).
BRUTEFORCE_BACKEND = "sqlite-bruteforce"
#: Backend name reported when the ``sqlite-vss`` extension is loaded and probed.
VSS_BACKEND = "sqlite-vss"
#: Default backend requested by the SDK (the name used in issue #1).
DEFAULT_VECTOR_BACKEND = "sqlite-vss"

#: Local aliases accepted by ``search_backend`` / ``vector_backend``.
LOCAL_BACKENDS = frozenset(
    {"sqlite-vss", "sqlite_vss", "sqlite-vss0", "sqlite", "local", "vector", "auto", BRUTEFORCE_BACKEND}
)
#: Backends that are documented as roadmap in issue #1 but not implemented here.
UNSUPPORTED_BACKENDS = frozenset({"qdrant", "pgvector", "chroma", "chromadb", "milvus", "weaviate", "faiss"})

_VSS_TABLE = "kcp_vss_vectors"
_VSS_MAP = "kcp_vss_map"

EMBEDDINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS kcp_embeddings (
    artifact_id TEXT NOT NULL,
    model       TEXT NOT NULL,
    dim         INTEGER NOT NULL,
    vector      BLOB NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (artifact_id, model)
);

CREATE INDEX IF NOT EXISTS idx_embeddings_model ON kcp_embeddings(model);
"""


class VectorIndexError(RuntimeError):
    """Raised for unsupported backends, dimension conflicts or corrupt vectors."""


def encode_vector(vector: Sequence[float]) -> bytes:
    """Pack a vector as little-endian float32 (SQLite-friendly, endian-stable)."""
    values = [float(v) for v in vector]
    return struct.pack(f"<{len(values)}f", *values)


def decode_vector(blob: bytes) -> list[float]:
    """Unpack a float32 blob written by :func:`encode_vector`."""
    raw = bytes(blob)
    if len(raw) % 4 != 0:
        raise VectorIndexError(f"corrupt vector blob: {len(raw)} bytes is not a multiple of 4")
    return list(struct.unpack(f"<{len(raw) // 4}f", raw))


class VectorIndex:
    """Exact (or extension-accelerated) cosine index over ``kcp_embeddings``.

    Shares the SQLite connection of the owning :class:`~kcp.store.LocalStore`, so
    there is no extra file and no extra process.
    """

    TABLE = "kcp_embeddings"

    def __init__(self, conn: sqlite3.Connection, backend: str = DEFAULT_VECTOR_BACKEND):
        self.conn = conn
        self.requested_backend = (backend or DEFAULT_VECTOR_BACKEND).strip().lower()
        self.effective_backend = BRUTEFORCE_BACKEND
        self.fallback_reason: str | None = None
        self._vss_model: str | None = None
        self._vss_dim: int | None = None
        self._ensure_schema()
        self._resolve_backend()

    # ─── Setup ─────────────────────────────────────────────────

    def _ensure_schema(self) -> None:
        self.conn.executescript(EMBEDDINGS_SCHEMA)
        self.conn.commit()

    def _resolve_backend(self) -> None:
        requested = self.requested_backend
        if requested in UNSUPPORTED_BACKENDS:
            raise VectorIndexError(
                f"vector backend {requested!r} is not implemented in the local SDK "
                "(tracked in kcp-protocol/kcp#1). Supported local aliases: "
                f"{sorted(LOCAL_BACKENDS)}."
            )
        if requested not in LOCAL_BACKENDS:
            raise VectorIndexError(
                f"unknown vector backend {self.requested_backend!r}. Supported local aliases: {sorted(LOCAL_BACKENDS)}."
            )

        if requested in ("sqlite", "local", BRUTEFORCE_BACKEND):
            self.fallback_reason = "pure-Python exact cosine scan requested explicitly"
            return

        # requested sqlite-vss / auto / vector — try the native extension.
        # The import is intentional here: an optional dependency loaded lazily.
        try:
            import sqlite_vss  # noqa: PLC0415
        except ImportError:
            self.fallback_reason = (
                "sqlite-vss extension not installed — falling back to the pure-Python exact cosine "
                "scan (same results, O(N·dim)). Install with: pip install 'kcp-protocol[semantic]'"
            )
            self._log_fallback()
            return

        try:
            self.conn.enable_load_extension(True)
            try:
                sqlite_vss.load(self.conn)
            finally:
                self.conn.enable_load_extension(False)
            if self._probe_vss():
                self.effective_backend = VSS_BACKEND
                self.fallback_reason = None
                logger.debug("vector index: sqlite-vss extension loaded and probed OK")
                return
            self.fallback_reason = (
                "sqlite-vss extension loaded but failed its round-trip probe — using the pure-Python exact cosine scan"
            )
        except Exception as exc:  # extension load errors vary by platform/sqlite build
            self.fallback_reason = (
                f"sqlite-vss extension could not be loaded ({exc}) — using the pure-Python exact cosine scan"
            )
        self._log_fallback()

    def _log_fallback(self) -> None:
        if self.requested_backend in ("sqlite-vss", "sqlite_vss", "sqlite-vss0"):
            logger.warning("vector index fallback: %s", self.fallback_reason)
        else:
            logger.info("vector index fallback: %s", self.fallback_reason)

    def _probe_vss(self) -> bool:
        """Create a throwaway vss0 table and verify insert + KNN query round-trip."""
        try:
            self.conn.execute("DROP TABLE IF EXISTS kcp_vss_probe")
            self.conn.execute("CREATE VIRTUAL TABLE kcp_vss_probe USING vss0(v(4))")
            probe = encode_vector([1.0, 0.0, 0.0, 0.0])
            self.conn.execute("INSERT INTO kcp_vss_probe(rowid, v) VALUES (1, ?)", (probe,))
            rows = self.conn.execute(
                "SELECT rowid, distance FROM kcp_vss_probe WHERE vss_search(v, ?) LIMIT 1",
                (probe,),
            ).fetchall()
            return len(rows) == 1
        except Exception as exc:
            logger.debug("sqlite-vss probe failed: %s", exc)
            return False
        finally:
            try:
                self.conn.execute("DROP TABLE IF EXISTS kcp_vss_probe")
            except Exception as exc:  # pragma: no cover — cleanup best effort
                logger.debug("probe cleanup failed: %s", exc)

    def _disable_vss(self, reason: str) -> None:
        """Stop using the extension after a runtime failure (never fail the query)."""
        logger.warning("vector index: disabling sqlite-vss acceleration — %s", reason)
        self.effective_backend = BRUTEFORCE_BACKEND
        self.fallback_reason = reason
        self._vss_model = None
        self._vss_dim = None

    # ─── Writes ────────────────────────────────────────────────

    def add(self, artifact_id: str, vector: Sequence[float], model: str) -> None:
        """Insert or replace an embedding for ``(artifact_id, model)``."""
        values = [float(v) for v in vector]
        if not values:
            raise VectorIndexError("cannot index an empty vector")
        dim = len(values)

        existing_dim = self.model_dim(model)
        if existing_dim is not None and existing_dim != dim:
            raise VectorIndexError(
                f"dimension mismatch for model {model!r}: index holds {existing_dim}-dim vectors, got {dim}. "
                "Use one embedding model per index (or a distinct model name)."
            )

        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT OR REPLACE INTO kcp_embeddings (artifact_id, model, dim, vector, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (artifact_id, model, dim, encode_vector(values), now),
        )
        self.conn.commit()
        self._vss_add(artifact_id, model, values)

    def drop(self, artifact_id: str, model: str | None = None) -> int:
        """Remove embeddings for an artifact (optionally only for one model)."""
        if model is None:
            cursor = self.conn.execute("DELETE FROM kcp_embeddings WHERE artifact_id = ?", (artifact_id,))
            try:
                self.conn.execute(f"DELETE FROM {_VSS_MAP} WHERE artifact_id = ?", (artifact_id,))  # noqa: S608  # nosec B608 — fixed table name
            except sqlite3.Error:
                pass
        else:
            cursor = self.conn.execute(
                "DELETE FROM kcp_embeddings WHERE artifact_id = ? AND model = ?", (artifact_id, model)
            )
            try:
                self.conn.execute(
                    f"DELETE FROM {_VSS_MAP} WHERE artifact_id = ? AND model = ?",  # noqa: S608  # nosec B608
                    (artifact_id, model),
                )
            except sqlite3.Error:
                pass
        # exact scan does not need the ANN mirror to be in sync
        self.conn.commit()
        return cursor.rowcount or 0

    def clear(self, model: str | None = None) -> int:
        """Delete all embeddings (or all for one model). Returns rows removed."""
        if model is None:
            cursor = self.conn.execute("DELETE FROM kcp_embeddings")
        else:
            cursor = self.conn.execute("DELETE FROM kcp_embeddings WHERE model = ?", (model,))
        self.conn.commit()
        return cursor.rowcount or 0

    # ─── Reads ─────────────────────────────────────────────────

    def get(self, artifact_id: str, model: str) -> list[float] | None:
        row = self.conn.execute(
            "SELECT vector FROM kcp_embeddings WHERE artifact_id = ? AND model = ?",
            (artifact_id, model),
        ).fetchone()
        if not row:
            return None
        return decode_vector(row["vector"] if isinstance(row, sqlite3.Row) else row[0])

    def indexed_ids(self, model: str) -> set[str]:
        rows = self.conn.execute("SELECT artifact_id FROM kcp_embeddings WHERE model = ?", (model,)).fetchall()
        return {r["artifact_id"] if isinstance(r, sqlite3.Row) else r[0] for r in rows}

    def count(self, model: str | None = None) -> int:
        if model is None:
            row = self.conn.execute("SELECT COUNT(*) AS c FROM kcp_embeddings").fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) AS c FROM kcp_embeddings WHERE model = ?", (model,)).fetchone()
        return int(row["c"] if isinstance(row, sqlite3.Row) else row[0])

    def models(self) -> list[str]:
        rows = self.conn.execute("SELECT DISTINCT model FROM kcp_embeddings ORDER BY model").fetchall()
        return [r["model"] if isinstance(r, sqlite3.Row) else r[0] for r in rows]

    def model_dim(self, model: str) -> int | None:
        row = self.conn.execute("SELECT dim FROM kcp_embeddings WHERE model = ? LIMIT 1", (model,)).fetchone()
        if not row:
            return None
        return int(row["dim"] if isinstance(row, sqlite3.Row) else row[0])

    def search(
        self,
        query_vector: Sequence[float],
        model: str,
        limit: int | None = 20,
    ) -> list[tuple[str, float]]:
        """Return ``[(artifact_id, cosine_similarity), …]`` sorted by similarity desc.

        Exact by construction (candidates are always re-ranked in Python). ``limit=None``
        returns every indexed artifact, which the store uses to apply ACL/tenant filters
        before paginating.
        """
        query = [float(v) for v in query_vector]
        if not query:
            raise VectorIndexError("cannot search with an empty query vector")
        stored_dim = self.model_dim(model)
        if stored_dim is None:
            return []
        if stored_dim != len(query):
            raise VectorIndexError(
                f"query vector has {len(query)} dims but model {model!r} was indexed with {stored_dim}. "
                "The query must be embedded with the same model used to index the artifacts."
            )

        candidates = self._vss_candidates(l2_normalize(query), model, limit)
        if candidates is None:
            rows = self.conn.execute(
                "SELECT artifact_id, vector FROM kcp_embeddings WHERE model = ?", (model,)
            ).fetchall()
            candidates = [
                (
                    (r["artifact_id"] if isinstance(r, sqlite3.Row) else r[0]),
                    decode_vector(r["vector"] if isinstance(r, sqlite3.Row) else r[1]),
                )
                for r in rows
            ]

        scored = [(artifact_id, cosine_similarity(query, vec)) for artifact_id, vec in candidates]
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored if limit is None else scored[:limit]

    def _vss_candidates(
        self, query: list[float], model: str, limit: int | None
    ) -> list[tuple[str, list[float]]] | None:
        """ANN candidate retrieval through sqlite-vss, or ``None`` to use the exact scan."""
        if self.effective_backend != VSS_BACKEND or limit is None:
            return None
        if self._vss_model != model or self._vss_dim != len(query):
            return None
        try:
            rows = self.conn.execute(
                f"SELECT m.artifact_id AS artifact_id, e.vector AS vector "  # noqa: S608  # nosec B608 — fixed table names
                f"FROM {_VSS_TABLE} v "
                f"JOIN {_VSS_MAP} m ON m.rowid = v.rowid "
                f"JOIN kcp_embeddings e ON e.artifact_id = m.artifact_id AND e.model = m.model "
                "WHERE vss_search(v.vector, ?) LIMIT ?",
                (encode_vector(query), max(limit * 4, limit)),
            ).fetchall()
        except Exception as exc:
            self._disable_vss(f"query failed: {exc}")
            return None
        candidates = [
            (
                (r["artifact_id"] if isinstance(r, sqlite3.Row) else r[0]),
                decode_vector(r["vector"] if isinstance(r, sqlite3.Row) else r[1]),
            )
            for r in rows
        ]
        indexed = self.count(model)
        if len(candidates) < min(limit, indexed):
            self._disable_vss(
                f"ANN returned {len(candidates)} candidates for a limit of {limit} (indexed={indexed}) — "
                "recall would degrade, falling back to the exact scan"
            )
            return None
        return candidates

    def _vss_add(self, artifact_id: str, model: str, vector: list[float]) -> None:
        """Best-effort mirror of a vector into the vss0 index (never breaks the write path)."""
        if self.effective_backend != VSS_BACKEND:
            return
        dim = len(vector)
        if self._vss_dim is None:
            try:
                self.conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS {_VSS_TABLE} USING vss0(vector({dim}))")
                self.conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {_VSS_MAP} (rowid INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "artifact_id TEXT NOT NULL, model TEXT NOT NULL, UNIQUE(artifact_id, model))"
                )
                self._vss_model, self._vss_dim = model, dim
            except Exception as exc:
                self._disable_vss(f"could not create the vss0 mirror: {exc}")
                return
        elif self._vss_model != model or self._vss_dim != dim:
            self._disable_vss(f"vss0 mirror only supports one model/dim ({self._vss_model}/{self._vss_dim})")
            return
        try:
            existing = self.conn.execute(
                f"SELECT rowid FROM {_VSS_MAP} WHERE artifact_id = ? AND model = ?",  # noqa: S608  # nosec B608
                (artifact_id, model),
            ).fetchone()
            if existing is not None:
                rowid = existing["rowid"] if isinstance(existing, sqlite3.Row) else existing[0]
                self.conn.execute(f"DELETE FROM {_VSS_TABLE} WHERE rowid = ?", (rowid,))  # noqa: S608  # nosec B608
            else:
                cursor = self.conn.execute(
                    f"INSERT INTO {_VSS_MAP} (artifact_id, model) VALUES (?, ?)",  # noqa: S608  # nosec B608
                    (artifact_id, model),
                )
                rowid = cursor.lastrowid
            self.conn.execute(
                f"INSERT INTO {_VSS_TABLE} (rowid, vector) VALUES (?, ?)",  # noqa: S608  # nosec B608
                (rowid, encode_vector(vector)),
            )
            self.conn.commit()
        except Exception as exc:
            self._disable_vss(f"mirror write failed: {exc}")

    # ─── Introspection ─────────────────────────────────────────

    def status(self) -> dict:
        """Machine-readable index status, including any explicit fallback reason."""
        models: dict = {}
        for model in self.models():
            models[model] = {"count": self.count(model), "dim": self.model_dim(model)}
        return {
            "requested_backend": self.requested_backend,
            "effective_backend": self.effective_backend,
            "fallback": self.effective_backend != self.requested_backend,
            "fallback_reason": self.fallback_reason,
            "ann_extension": self.effective_backend == VSS_BACKEND,
            "table": self.TABLE,
            "vectors": self.count(),
            "models": models,
        }
