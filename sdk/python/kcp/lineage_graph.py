"""
KCP Lineage Graph — fork detection + CRDT sync proof
(RFC KCP-005: Lineage Conflict Resolution)

Two nodes in a federation can independently derive artifacts from the same
parent (``derived_from``). When they sync there is no mutation to reconcile —
both children are legitimate, immutable members — but the divergence must be
**detected and represented faithfully** so downstream consumers can see that
the parent has more than one continuation.

This module provides:

  - :func:`detect_forks` — pure function: artifacts sharing a parent → forks
  - :class:`ForkPair`    — the conflict record (parent + diverging children)
  - :class:`LineageGraph`— G-Set of artifact records + DAG navigation, with
    :meth:`LineageGraph.merge` (CRDT union) and :meth:`LineageGraph.sync`
  - :class:`SyncProof`   — result of a sync: ``conflicts[]`` + ``merged`` count

The graph is a **G-Set keyed by artifact id** (see :mod:`kcp.crdt`): merge is
always union, duplicates are idempotent, and no artifact is ever dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from .crdt import GSet
from .merkle import (
    LineageVerificationError,
    MerkleDAG,
    MerkleProof,
    normalize_record,
)


# ─── Fork detection ───────────────────────────────────────────

@dataclass
class ForkPair:
    """
    A detected fork: one parent with ≥ 2 children (diverging branches).

    ``fork_id`` mirrors the RFC's ``artifact.lineage.fork_id`` proposal — it is
    the common parent id, i.e. the point where the lineages diverge.
    """

    parent_id: str
    children: list[str] = field(default_factory=list)
    fork_seq: int = 1

    @property
    def fork_id(self) -> str:
        return self.parent_id

    @property
    def branches(self) -> int:
        return len(self.children)

    def pairs(self) -> list[tuple[str, str]]:
        """All unordered child pairs that diverge at this parent."""
        out: list[tuple[str, str]] = []
        for i in range(len(self.children)):
            for j in range(i + 1, len(self.children)):
                out.append((self.children[i], self.children[j]))
        return out

    def to_dict(self) -> dict:
        return {
            "fork_id": self.parent_id,
            "parent_id": self.parent_id,
            "fork_seq": self.fork_seq,
            "children": list(self.children),
            "branches": len(self.children),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ForkPair":
        parent = data.get("parent_id") or data.get("fork_id") or ""
        return cls(
            parent_id=parent,
            children=list(data.get("children", [])),
            fork_seq=int(data.get("fork_seq", 1)),
        )


def detect_forks(records: Iterable[dict]) -> list[ForkPair]:
    """
    Detect forks in a set of artifact records.

    A fork exists whenever two or more artifacts declare the same parent
    (``derived_from``/``parent_id``). Returns one :class:`ForkPair` per such
    parent, children sorted deterministically.
    """
    children_by_parent: dict[str, list[str]] = {}
    for rec in records:
        norm = normalize_record(rec)
        parent = norm["parent_id"]
        if parent:
            children_by_parent.setdefault(parent, []).append(norm["id"])

    forks: list[ForkPair] = []
    for parent, children in children_by_parent.items():
        if len(children) >= 2:
            forks.append(ForkPair(parent_id=parent, children=sorted(children)))
    forks.sort(key=lambda f: f.parent_id)
    return forks


# ─── Sync proof ───────────────────────────────────────────────

@dataclass
class SyncProof:
    """
    Result of ``node_a.sync(node_b)`` / ``graph_a.sync(graph_b)``.

    Attributes
    ----------
    conflicts : list[ForkPair]
        Fork pairs observed after the merge — i.e. every parent that now has
        more than one child across the union of both nodes.
    merged : int
        Total number of distinct artifacts in the merged (union) set.
    added : int
        How many artifacts this merge actually introduced locally.
    root_hash : str
        Merkle digest of the whole merged DAG (``MerkleDAG.global_root_hash``).
        Both nodes converge to the same value for the same artifact set.
    """

    conflicts: list[ForkPair] = field(default_factory=list)
    merged: int = 0
    added: int = 0
    root_hash: str = ""

    @property
    def has_conflicts(self) -> bool:
        return len(self.conflicts) > 0

    @property
    def conflict_count(self) -> int:
        return len(self.conflicts)

    def to_dict(self) -> dict:
        return {
            "conflicts": [c.to_dict() for c in self.conflicts],
            "merged": self.merged,
            "added": self.added,
            "root_hash": self.root_hash,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SyncProof":
        return cls(
            conflicts=[ForkPair.from_dict(c) for c in data.get("conflicts", [])],
            merged=int(data.get("merged", 0)),
            added=int(data.get("added", 0)),
            root_hash=data.get("root_hash", ""),
        )


# ─── Lineage graph (G-Set of artifacts + DAG views) ──────────

class LineageGraph:
    """
    A grow-only set of artifact records with DAG navigation.

    The membership set is a :class:`~kcp.crdt.GSet` of artifact ids; records are
    kept alongside. Merging two graphs is CRDT union (idempotent, commutative,
    associative).
    """

    def __init__(self, records: Optional[Iterable[dict]] = None):
        self._ids: GSet = GSet()
        self.records: dict[str, dict] = {}
        if records:
            for rec in records:
                self.add(rec)

    # ── writes ──

    def add(self, record: dict) -> bool:
        """Add a record. Returns True if new (G-Set growth, idempotent)."""
        rec = normalize_record(record)
        is_new = self._ids.add(rec["id"])
        if is_new:
            self.records[rec["id"]] = rec
        return is_new

    def merge(self, other: "LineageGraph") -> "LineageGraph":
        """CRDT union — returns a new graph, mutating neither operand."""
        merged = LineageGraph()
        merged._ids = self._ids.merge(other._ids)
        merged.records = {**self.records, **other.records}
        return merged

    def merge_in_place(self, other: "LineageGraph") -> int:
        """Union ``other`` into ``self``. Returns number of newly added records."""
        added = 0
        for nid, rec in other.records.items():
            if self.add(rec):
                added += 1
        return added

    # ── reads ──

    @property
    def size(self) -> int:
        return len(self.records)

    def ids(self) -> list[str]:
        return sorted(self.records)

    def get(self, artifact_id: str) -> Optional[dict]:
        return self.records.get(artifact_id)

    def children_of(self, parent_id: str) -> list[str]:
        return sorted(
            nid for nid, rec in self.records.items()
            if rec["parent_id"] == parent_id
        )

    def parent_of(self, artifact_id: str) -> Optional[str]:
        rec = self.records.get(artifact_id)
        return rec["parent_id"] if rec else None

    # ── forks ──

    def detect_forks(self) -> list[ForkPair]:
        """All fork pairs in the current (merged) graph."""
        return detect_forks(self.records.values())

    def has_fork(self, parent_id: str) -> bool:
        return len(self.children_of(parent_id)) >= 2

    # ── Merkle ──

    def merkle(self) -> MerkleDAG:
        return MerkleDAG(list(self.records.values()))

    def verify_lineage(self, leaf_id: str, root_id: str) -> MerkleProof:
        """Build + verify a Merkle lineage proof (raises on failure)."""
        return self.merkle().verify_lineage(leaf_id, root_id)

    def global_root_hash(self) -> str:
        return self.merkle().global_root_hash()

    # ── sync (CRDT merge + fork report) ──

    def sync(self, other: "LineageGraph") -> SyncProof:
        """
        Merge ``other`` into ``self`` (in place) and return a :class:`SyncProof`.

        Semantics: G-Set union. ``proof.merged`` is the size of the merged set;
        ``proof.conflicts`` lists forks visible in the union.
        """
        added = self.merge_in_place(other)
        conflicts = self.detect_forks()
        return SyncProof(
            conflicts=conflicts,
            merged=self.size,
            added=added,
            root_hash=self.global_root_hash(),
        )

    def __len__(self) -> int:
        return len(self.records)

    def __contains__(self, artifact_id: str) -> bool:
        return artifact_id in self._ids

    def __repr__(self) -> str:
        return f"LineageGraph(size={self.size}, forks={len(self.detect_forks())})"


__all__ = [
    "ForkPair",
    "LineageGraph",
    "SyncProof",
    "detect_forks",
    "normalize_record",
    "MerkleProof",
    "MerkleDAG",
    "LineageVerificationError",
]
