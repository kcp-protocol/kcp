"""
KCP Merkle DAG — auditable lineage proofs (RFC KCP-005: Lineage Conflict Resolution)

Every artifact is a node in a Merkle DAG. Edges go parent → child
(`derived_from` / `parent_id`). Each node commits to:

  1. its own canonical metadata record (id, content_hash, parent, timestamp, author), and
  2. the *sorted hashes of its direct children*.

That gives a single hash per node that binds its whole descendant subtree.
From that we build **Merkle lineage proofs**:

    proof = dag.build_proof(leaf_id, root_id)      # produced by whoever holds the graph
    ok    = proof.verify()                          # verifiable by anyone, offline

The verifier needs only the proof and the *expected root hash* (a trust anchor).
It never has to trust the node that produced the proof — it recomputes the root
commitment from the leaf record plus the sibling hashes carried in the proof.

The "sibling hashes" at each level are exactly the *other branches* leaving the
same ancestor. In KCP's federated model those siblings are precisely the
conflicting forks (issue #2), so the very same structure serves fork detection.

Design notes
------------
- Hash domain separation: ``0x00`` for leaves' own record, ``0x01`` for nodes
  with children. Prevents second-preimage confusion between the two.
  (Both are the same computation here — ``node_hash`` with zero children is a
  leaf commitment — but the prefix constant keeps the wire format explicit and
  future-proof, e.g. if a leaf were reduced to ``H(content)``.)
- Node identity in the DAG is the artifact ``id``; the content commitment is
  ``content_hash`` (already computed over plaintext by the SDK).
- Proofs are pure JSON-serializable dicts (``MerkleProof.to_dict``).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

# ─── Constants ────────────────────────────────────────────────

MERKLE_VERSION = "kcp-merkle-v1"
LEAF_PREFIX = b"\x00"
NODE_PREFIX = b"\x01"


class LineageVerificationError(Exception):
    """Raised when a lineage path does not exist or a proof fails to verify."""


# ─── Canonical record + hashing ───────────────────────────────


def normalize_record(record: dict) -> dict:
    """
    Reduce an artifact row/dict to the canonical subset committed by the DAG.

    Accepts either ``parent_id`` or ``derived_from`` as the parent field so it
    works directly with ``LocalStore`` rows and with sync payloads.
    """
    parent = record.get("parent_id")
    if parent is None:
        parent = record.get("derived_from")
    return {
        "id": str(record["id"]),
        "parent_id": str(parent) if parent else None,
        "content_hash": record.get("content_hash") or "",
        "timestamp": record.get("timestamp") or record.get("created_at") or "",
        "user_id": record.get("user_id") or record.get("author") or "",
    }


def canonical_record(record: dict) -> bytes:
    """Stable canonical JSON bytes for a node's own commitment."""
    rec = normalize_record(record)
    return json.dumps(rec, sort_keys=True, separators=(",", ":")).encode("utf-8")


def leaf_hash(record: dict) -> str:
    """
    Hash of a node's own record, ignoring children.

    Used for leaf/tip artifacts and as the base of :func:`node_hash`.
    """
    return hashlib.sha256(LEAF_PREFIX + canonical_record(record)).hexdigest()


def node_hash(record: dict, child_hashes: list[str] | None = None) -> str:
    """
    Merkle node hash = H(0x01 || canonical(record) || sorted(child_hashes)).

    The sorted, length-prepended child hashes make the commitment order-independent
    (a parent with children {A, B} has one hash regardless of discovery order).
    """
    h = hashlib.sha256(NODE_PREFIX + canonical_record(record))
    for child in sorted(child_hashes or []):
        h.update(child.encode("utf-8"))
    return h.hexdigest()


# ─── Merkle proof ─────────────────────────────────────────────


@dataclass
class MerkleProof:
    """
    A self-contained proof that ``leaf`` is an ancestor of ``root`` in the DAG.

    Wire format (JSON, all fields hex/plain):

        {
          "version": "kcp-merkle-v1",
          "leaf":      {canonical record},
          "leaf_children": ["<hash>", ...],     # hashes of leaf's own children
          "root_id":   "…",
          "root_hash": "<hex>",                 # trust anchor
          "path": [
            {"node": {canonical record}, "siblings": ["<hash>", ...]},
            ...
          ]   # ordered leaf's parent → root
        }

    ``verify()`` recomputes ``node_hash`` from the leaf upward and compares the
    final value to ``root_hash``. No network access, no trust in the producer.
    """

    leaf: dict
    leaf_children: list[str] = field(default_factory=list)
    root_id: str = ""
    root_hash: str = ""
    path: list[dict] = field(default_factory=list)
    version: str = MERKLE_VERSION

    # ── verification ──

    def verify(self) -> bool:
        """Recompute the commitment from the leaf and compare with root_hash."""
        try:
            leaf = normalize_record(self.leaf)
            if not self.root_id or not self.root_hash:
                return False

            # Compute the leaf's own node hash (includes its children).
            current = node_hash(leaf, self.leaf_children)

            if not self.path:
                # Leaf *is* the root.
                return leaf["id"] == self.root_id and current == self.root_hash

            # The first hop must be the leaf's declared parent.
            first = normalize_record(self.path[0]["node"])
            if leaf["parent_id"] != first["id"]:
                return False

            for step in self.path:
                node = normalize_record(step["node"])
                siblings = list(step.get("siblings", []))
                current = node_hash(node, siblings + [current])

            last = normalize_record(self.path[-1]["node"])
            if last["id"] != self.root_id:
                return False
            return current == self.root_hash
        except Exception:
            return False

    # ── serialization ──

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "leaf": normalize_record(self.leaf),
            "leaf_children": list(self.leaf_children),
            "root_id": self.root_id,
            "root_hash": self.root_hash,
            "path": [{"node": normalize_record(s["node"]), "siblings": list(s.get("siblings", []))} for s in self.path],
        }

    @classmethod
    def from_dict(cls, data: dict) -> MerkleProof:
        return cls(
            leaf=data["leaf"],
            leaf_children=list(data.get("leaf_children", [])),
            root_id=data.get("root_id", ""),
            root_hash=data.get("root_hash", ""),
            path=list(data.get("path", [])),
            version=data.get("version", MERKLE_VERSION),
        )


def verify_proof(proof: MerkleProof | dict) -> bool:
    """
    Verify a proof locally, without any access to the origin graph.

    Accepts a :class:`MerkleProof` or its ``to_dict()`` form.
    """
    if isinstance(proof, dict):
        proof = MerkleProof.from_dict(proof)
    return proof.verify()


# ─── Merkle DAG ───────────────────────────────────────────────


class MerkleDAG:
    """
    Content-addressed Merkle DAG over a set of artifact records.

    ``records`` is any iterable of dicts containing at least ``id`` and
    optionally ``derived_from``/``parent_id``, ``content_hash``, ``timestamp``,
    ``user_id``.
    """

    def __init__(self, records: list[dict] | None = None):
        self.records: dict[str, dict] = {}
        self.children: dict[str, list[str]] = {}
        self._hash_cache: dict[str, str] = {}
        if records:
            for rec in records:
                self.add(rec)

    # ── construction ──

    def add(self, record: dict) -> None:
        """Add/replace a node. Idempotent (grow-only by design)."""
        rec = normalize_record(record)
        self.records[rec["id"]] = rec
        self._rebuild_children()
        self._hash_cache.clear()

    def _rebuild_children(self) -> None:
        self.children = {}
        for nid, rec in self.records.items():
            parent = rec["parent_id"]
            if parent and parent in self.records:
                self.children.setdefault(parent, []).append(nid)
        for lst in self.children.values():
            lst.sort()

    @property
    def size(self) -> int:
        return len(self.records)

    def roots(self) -> list[str]:
        """Nodes with no parent present in the DAG (chain heads)."""
        return sorted(
            nid for nid, rec in self.records.items() if not rec["parent_id"] or rec["parent_id"] not in self.records
        )

    # ── hashing ──

    def node_hash(self, node_id: str) -> str:
        """Recursive, memoized node hash (commits to the whole subtree)."""
        if node_id in self._hash_cache:
            return self._hash_cache[node_id]
        rec = self.records[node_id]
        child_hashes = [self.node_hash(c) for c in self.children.get(node_id, [])]
        h = node_hash(rec, child_hashes)
        self._hash_cache[node_id] = h
        return h

    def global_root_hash(self) -> str:
        """
        Single digest of the entire DAG — H over the sorted root node hashes.

        Empty DAG → SHA-256 of the empty string.
        """
        root_hashes = sorted(self.node_hash(r) for r in self.roots())
        h = hashlib.sha256(MERKLE_VERSION.encode("utf-8"))
        for rh in root_hashes:
            h.update(rh.encode("utf-8"))
        return h.hexdigest()

    # ── lineage ──

    def ancestors(self, node_id: str) -> list[str]:
        """Ordered chain [node_id, parent, grandparent, …, head]."""
        chain: list[str] = []
        seen: set[str] = set()
        current: str | None = node_id
        while current and current in self.records and current not in seen:
            seen.add(current)
            chain.append(current)
            current = self.records[current]["parent_id"]
        return chain

    def is_descendant(self, leaf_id: str, root_id: str) -> bool:
        """True if root_id appears in leaf_id's ancestor chain (or they are equal)."""
        return root_id in self.ancestors(leaf_id)

    def build_proof(self, leaf_id: str, root_id: str) -> MerkleProof:
        """
        Build a Merkle lineage proof for ``leaf_id`` anchored at ``root_id``.

        Raises :class:`LineageVerificationError` if either node is unknown or if
        ``root_id`` is not an ancestor of ``leaf_id``.
        """
        if leaf_id not in self.records:
            raise LineageVerificationError(f"unknown leaf artifact: {leaf_id}")
        if root_id not in self.records:
            raise LineageVerificationError(f"unknown root artifact: {root_id}")

        chain = self.ancestors(leaf_id)
        if root_id not in chain:
            raise LineageVerificationError(f"{root_id} is not an ancestor of {leaf_id}")

        leaf = self.records[leaf_id]
        leaf_children = [self.node_hash(c) for c in self.children.get(leaf_id, [])]

        # Walk leaf → root, recording sibling hashes at each ancestor.
        path: list[dict] = []
        if leaf_id != root_id:
            child_on_path = leaf_id
            idx = 1
            while idx < len(chain):
                ancestor_id = chain[idx]
                ancestor = self.records[ancestor_id]
                siblings = [self.node_hash(c) for c in self.children.get(ancestor_id, []) if c != child_on_path]
                path.append({"node": ancestor, "siblings": siblings})
                child_on_path = ancestor_id
                idx += 1
                if ancestor_id == root_id:
                    break

        return MerkleProof(
            leaf=leaf,
            leaf_children=leaf_children,
            root_id=root_id,
            root_hash=self.node_hash(root_id),
            path=path,
        )

    def verify_lineage(self, leaf_id: str, root_id: str) -> MerkleProof:
        """
        Build **and verify** a lineage proof locally.

        Returns the proof on success; raises :class:`LineageVerificationError`
        if no provable path exists.
        """
        proof = self.build_proof(leaf_id, root_id)
        if not proof.verify():
            raise LineageVerificationError(f"proof failed verification: {leaf_id} ⇒ {root_id}")
        return proof
