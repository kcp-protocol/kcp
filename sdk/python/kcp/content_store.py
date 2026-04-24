"""
KCP Filesystem Content Store — RFC KCP-003 Phase 3

Stores artifact content as individual files in a sharded directory tree
instead of BLOBs inside SQLite. This keeps kcp.db lean (metadata only)
and makes large-scale deployments practical.

Directory layout:
    <base_dir>/content/{year}/{month}/{day}/{sha256}.bin

Example:
    ~/.kcp/content/2026/03/21/a3f7c9d1e2b4...sha256....bin

Design decisions:
  - Sharding by date (not just hash prefix) so directories stay small
    and browsable. A busy peer writing 1000 artifacts/day gets ~1000
    files per directory — well within filesystem limits.
  - Filename IS the content_hash (SHA-256 hex). No index needed to
    locate content — the hash is the address.
  - Files are written atomically (write to .tmp, then rename) so a
    crash mid-write never leaves a corrupt file.
  - Content is immutable: same hash = same bytes. Safe to cache or
    serve from CDN directly.
  - Migration: one-time copy of SQLite BLOBs → filesystem on first
    LocalStore init (see LocalStore._migrate_blobs_to_filesystem).
"""

from __future__ import annotations

import os
import shutil
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("kcp.content_store")


class ContentStore:
    """
    Filesystem-backed content store with date-based sharding.

    Thread-safe for concurrent reads. Writes are atomic via
    write-to-temp-then-rename strategy.

    Args:
        base_dir: Root directory. Content is stored under
                  <base_dir>/content/{year}/{month}/{day}/.
                  Defaults to the same directory as kcp.db.
    """

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir).expanduser().resolve()
        self.content_root = self.base_dir / "content"
        self.content_root.mkdir(parents=True, exist_ok=True)

    # ─── Core operations ───────────────────────────────────────

    def write(
        self,
        content_hash: str,
        data: bytes,
        timestamp: Optional[str] = None,
    ) -> Path:
        """
        Write content bytes to the filesystem shard.

        Idempotent: if a file with the same hash already exists,
        it is NOT overwritten (content is immutable by definition).

        Args:
            content_hash: SHA-256 hex string (used as filename).
            data: Raw bytes to store.
            timestamp: ISO-8601 timestamp to determine shard date.
                       Defaults to current UTC time.

        Returns:
            Absolute Path where the content was (or already is) stored.
        """
        path = self._path_for(content_hash, timestamp)

        if path.exists():
            return path  # already stored — immutable, skip write

        # Ensure directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write: write to .tmp, then rename
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_bytes(data)
            tmp.rename(path)
        except Exception as e:
            logger.warning("ContentStore: atomic write failed for %s: %s", content_hash[:8], e)
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            raise

        logger.debug(f"ContentStore: wrote {len(data)} bytes → {path.relative_to(self.base_dir)}")
        return path

    def read(self, content_hash: str) -> Optional[bytes]:
        """
        Read content bytes for a given hash.

        Searches all shards (year/month/day) since we may not know the
        original write date. Uses the hash index file for O(1) lookup
        when available; falls back to directory scan otherwise.

        Returns:
            Raw bytes, or None if not found.
        """
        # Fast path: try hash-index lookup first
        indexed = self._find_by_index(content_hash)
        if indexed and indexed.exists():
            return indexed.read_bytes()

        # Slow path: scan all shards (only happens once per hash —
        # after that we write to the index)
        found = self._scan_for_hash(content_hash)
        if found:
            self._write_index(content_hash, found)
            return found.read_bytes()

        return None

    def exists(self, content_hash: str) -> bool:
        """Return True if content for this hash is stored."""
        indexed = self._find_by_index(content_hash)
        if indexed and indexed.exists():
            return True
        found = self._scan_for_hash(content_hash)
        return found is not None

    def delete(self, content_hash: str) -> bool:
        """
        Remove content file (and index entry) for a hash.
        Returns True if a file was deleted.
        """
        path = self._find_by_index(content_hash) or self._scan_for_hash(content_hash)
        if path and path.exists():
            path.unlink()
            self._remove_index(content_hash)
            logger.debug(f"ContentStore: deleted {content_hash[:16]}…")
            return True
        return False

    def shard_path(self, content_hash: str, timestamp: Optional[str] = None) -> Path:
        """Return the expected shard path for a hash (may not exist yet)."""
        return self._path_for(content_hash, timestamp)

    # ─── Stats ─────────────────────────────────────────────────

    def stats(self) -> dict:
        """Return basic stats: total files, total bytes, shard count."""
        total_files = 0
        total_bytes = 0
        shards = set()

        for path in self.content_root.rglob("*.bin"):
            total_files += 1
            total_bytes += path.stat().st_size
            shards.add(path.parent)

        return {
            "total_files": total_files,
            "total_bytes": total_bytes,
            "total_bytes_human": _human_size(total_bytes),
            "shard_count": len(shards),
            "content_root": str(self.content_root),
        }

    # ─── Internal ──────────────────────────────────────────────

    def _path_for(self, content_hash: str, timestamp: Optional[str] = None) -> Path:
        """Compute shard path: content/{year}/{month}/{day}/{hash}.bin"""
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp)
            except ValueError:
                dt = datetime.now(timezone.utc)
        else:
            dt = datetime.now(timezone.utc)

        return (
            self.content_root
            / f"{dt.year:04d}"
            / f"{dt.month:02d}"
            / f"{dt.day:02d}"
            / f"{content_hash}.bin"
        )

    # ── Hash index: a flat file mapping hash → relative shard path ──
    # Stored at <content_root>/.index — one line per hash.
    # Format: "<hash> <relative/path/to/file.bin>\n"
    # This makes read() O(1) after first access without needing SQLite.

    @property
    def _index_path(self) -> Path:
        return self.content_root / ".index"

    def _find_by_index(self, content_hash: str) -> Optional[Path]:
        """Look up hash in the flat index file. Returns absolute Path or None."""
        if not self._index_path.exists():
            return None
        try:
            with self._index_path.open("r") as f:
                for line in f:
                    h, _, rel = line.strip().partition(" ")
                    if h == content_hash:
                        return self.content_root / rel
        except Exception as e:
            logger.debug("ContentStore: index read error: %s", e)
        return None

    def _write_index(self, content_hash: str, path: Path):
        """Append a hash → path mapping to the index file."""
        rel = path.relative_to(self.content_root)
        try:
            with self._index_path.open("a") as f:
                f.write(f"{content_hash} {rel}\n")
        except Exception as e:
            logger.debug("ContentStore: index write error: %s", e)  # index is best-effort

    def _remove_index(self, content_hash: str):
        """Remove a hash entry from the index file."""
        if not self._index_path.exists():
            return
        try:
            lines = self._index_path.read_text().splitlines(keepends=True)
            kept = [l for l in lines if not l.startswith(content_hash + " ")]
            self._index_path.write_text("".join(kept))
        except Exception as e:
            logger.debug("ContentStore: index remove error: %s", e)

    def _scan_for_hash(self, content_hash: str) -> Optional[Path]:
        """Walk all shards looking for {hash}.bin. O(n) — last resort."""
        target = f"{content_hash}.bin"
        for path in self.content_root.rglob(target):
            return path
        return None


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024
    return f"{n:.1f} PB"
