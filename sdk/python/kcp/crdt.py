"""
KCP CRDT primitives — Grow-Only Set (G-Set) for artifact federation
(RFC KCP-005: Lineage Conflict Resolution)

KCP artifacts are **immutable once published** (see RFC KCP-005 non-goals and
RFC KCP-001 §7). Therefore the set of artifacts known by a node is a natural
**Grow-Only Set (G-Set)** CRDT:

    state   = set of artifact ids
    add(e)  = state ∪ {e}          (monotonic; nothing is ever removed)
    merge   = state_A ∪ state_B    (union)

The G-Set merge is:

  - **commutative**:  A ⊔ B == B ⊔ A
  - **associative**:  (A ⊔ B) ⊔ C == A ⊔ (B ⊔ C)
  - **idempotent**:   A ⊔ A == A

which makes federation convergence order-independent and safe to replay.
Because artifacts are content-addressed and signed, two nodes that converge on
the same set also converge on the same bytes — no "last-writer-wins" needed.

Conflicts are **not mutations**: two artifacts sharing the same parent are two
distinct members of the set (a *fork*), and both are retained. Fork detection
and Merkle proofs live in :mod:`kcp.lineage_graph` and :mod:`kcp.merkle`.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Iterator


class GSet:
    """
    Grow-Only Set CRDT.

    Generic over any hashable element (artifacts use their string ``id``).

    >>> a = GSet(["x"]); b = GSet(["y"])
    >>> sorted(a.merge(b)) == sorted(b.merge(a)) == ["x", "y"]
    True
    """

    __slots__ = ("_elements",)

    def __init__(self, elements: Iterable[Hashable] | None = None):
        self._elements: set = set()
        if elements:
            self._elements.update(elements)

    # ── writes (monotonic) ──

    def add(self, element: Hashable) -> bool:
        """Add an element. Returns True if it was not present (a real growth)."""
        if element in self._elements:
            return False
        self._elements.add(element)
        return True

    def update(self, elements: Iterable[Hashable]) -> int:
        """Add many elements. Returns the number of newly added ones."""
        added = 0
        for e in elements:
            if self.add(e):
                added += 1
        return added

    def merge(self, other: GSet) -> GSet:
        """
        Return the union of two G-Sets (does not mutate either operand).

        This is the CRDT join/least-upper-bound operation.
        """
        merged = GSet(self._elements)
        merged._elements |= other._elements
        return merged

    def merge_in_place(self, other: GSet) -> int:
        """Union ``other`` into ``self``. Returns number of newly added elements."""
        before = len(self._elements)
        self._elements |= other._elements
        return len(self._elements) - before

    # ── reads ──

    def elements(self) -> list:
        """Deterministic (sorted where possible) snapshot of members."""
        try:
            return sorted(self._elements)
        except TypeError:
            return list(self._elements)

    def to_list(self) -> list:
        return self.elements()

    def __contains__(self, element: Hashable) -> bool:
        return element in self._elements

    def __iter__(self) -> Iterator:
        return iter(self._elements)

    def __len__(self) -> int:
        return len(self._elements)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, GSet) and self._elements == other._elements

    def __hash__(self) -> int:
        return hash(frozenset(self._elements))

    # ── operators ──

    def __or__(self, other: GSet) -> GSet:
        return self.merge(other)

    def __ior__(self, other: GSet) -> GSet:
        self.merge_in_place(other)
        return self

    # ── serialization ──

    def to_dict(self) -> dict:
        return {"type": "g-set", "elements": self.elements()}

    @classmethod
    def from_dict(cls, data: dict) -> GSet:
        return cls(data.get("elements", []))

    def __repr__(self) -> str:
        return f"GSet(size={len(self._elements)})"
