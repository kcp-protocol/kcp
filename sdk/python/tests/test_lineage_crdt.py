"""
Tests for RFC KCP-005 — Lineage Conflict Resolution (Merkle DAG + G-Set CRDT).

Covers:
  - Merkle primitives (leaf/node hashing, domain separation)
  - Merkle lineage proofs: build, verify offline, tamper detection
  - G-Set CRDT laws: idempotent, commutative, associative
  - Fork detection (two artifacts sharing a parent → fork pair)
  - LineageGraph merge + SyncProof (conflicts[] / merged)
  - KCPNode integration: detect_forks(), verify_lineage(), sync()
"""

from __future__ import annotations

import pytest

from kcp.crdt import GSet
from kcp.merkle import (
    LineageVerificationError,
    MerkleDAG,
    MerkleProof,
    canonical_record,
    leaf_hash,
    node_hash,
    verify_proof,
)
from kcp.lineage_graph import (
    ForkPair,
    LineageGraph,
    SyncProof,
    detect_forks,
)
from kcp.node import KCPNode


# ─── Helpers ──────────────────────────────────────────────────

def rec(rid, parent=None, content="c", ts="2026-03-21T00:00:00+00:00", user="a@x"):
    return {
        "id": rid,
        "derived_from": parent,
        "content_hash": content,
        "timestamp": ts,
        "user_id": user,
    }


@pytest.fixture
def chain_dag():
    """R → B → C → L, with a sibling branch D off B."""
    records = [
        rec("R", None, "hR"),
        rec("B", "R", "hB"),
        rec("C", "B", "hC"),
        rec("D", "B", "hD"),   # fork sibling at B
        rec("L", "C", "hL"),
    ]
    return MerkleDAG(records)


@pytest.fixture
def tmp_node(tmp_path, monkeypatch):
    monkeypatch.delenv("KCP_PEERS", raising=False)
    return KCPNode(
        user_id="test@example.com",
        tenant_id="test-corp",
        db_path=str(tmp_path / "kcp.db"),
        keys_dir=str(tmp_path / "keys"),
    )


# ─── Merkle primitives ────────────────────────────────────────

class TestMerklePrimitives:
    def test_leaf_hash_deterministic(self):
        assert leaf_hash(rec("A", None, "x")) == leaf_hash(rec("A", None, "x"))

    def test_leaf_hash_changes_with_content(self):
        assert leaf_hash(rec("A", None, "x")) != leaf_hash(rec("A", None, "y"))

    def test_node_hash_order_independent(self):
        r = rec("P", None, "hP")
        assert node_hash(r, ["a", "b"]) == node_hash(r, ["b", "a"])

    def test_node_hash_commits_children(self):
        r = rec("P", None, "hP")
        assert node_hash(r, []) != node_hash(r, ["childhash"])

    def test_normalize_accepts_parent_id_alias(self):
        a = canonical_record({"id": "A", "parent_id": "P", "content_hash": "h"})
        b = canonical_record({"id": "A", "derived_from": "P", "content_hash": "h"})
        assert a == b


# ─── Merkle DAG + proofs ──────────────────────────────────────

class TestMerkleDAG:
    def test_size_and_roots(self, chain_dag):
        assert chain_dag.size == 5
        assert chain_dag.roots() == ["R"]

    def test_ancestors_chain(self, chain_dag):
        assert chain_dag.ancestors("L") == ["L", "C", "B", "R"]

    def test_is_descendant(self, chain_dag):
        assert chain_dag.is_descendant("L", "R")
        assert not chain_dag.is_descendant("R", "L")
        assert not chain_dag.is_descendant("D", "C")

    def test_verify_lineage_single_hop(self, chain_dag):
        proof = chain_dag.verify_lineage("L", "C")
        assert isinstance(proof, MerkleProof)
        assert proof.verify()
        assert proof.path[0]["node"]["id"] == "C"

    def test_verify_lineage_multihop(self, chain_dag):
        proof = chain_dag.verify_lineage("L", "R")
        assert proof.verify()
        ids = [step["node"]["id"] for step in proof.path]
        assert ids == ["C", "B", "R"]

    def test_verify_lineage_leaf_is_root(self, chain_dag):
        proof = chain_dag.verify_lineage("B", "B")
        assert proof.path == []
        assert proof.verify()

    def test_verify_lineage_unknown_node_raises(self, chain_dag):
        with pytest.raises(LineageVerificationError):
            chain_dag.verify_lineage("missing", "R")

    def test_verify_lineage_not_ancestor_raises(self, chain_dag):
        with pytest.raises(LineageVerificationError):
            chain_dag.verify_lineage("D", "C")

    def test_proof_carries_fork_siblings(self, chain_dag):
        proof = chain_dag.verify_lineage("D", "B")
        # Sibling of D at B is the C subtree — its hash is embedded in the proof.
        assert proof.path[0]["siblings"] == [chain_dag.node_hash("C")]

    def test_proof_verifies_without_origin_dag(self, chain_dag):
        """A proof is verifiable locally by someone who never saw the graph."""
        proof = chain_dag.verify_lineage("L", "R")
        wire = proof.to_dict()
        assert verify_proof(wire) is True

    def test_proof_roundtrip_serialization(self, chain_dag):
        proof = chain_dag.verify_lineage("L", "R")
        restored = MerkleProof.from_dict(proof.to_dict())
        assert restored.verify()
        assert restored.root_hash == proof.root_hash

    def test_tampered_root_hash_fails(self, chain_dag):
        wire = chain_dag.verify_lineage("L", "R").to_dict()
        wire["root_hash"] = "0" * 64
        assert verify_proof(wire) is False

    def test_tampered_leaf_fails(self, chain_dag):
        wire = chain_dag.verify_lineage("L", "R").to_dict()
        wire["leaf"]["content_hash"] = "forged"
        assert verify_proof(wire) is False

    def test_tampered_sibling_hash_fails(self, chain_dag):
        wire = chain_dag.verify_lineage("D", "B").to_dict()
        wire["path"][0]["siblings"] = ["deadbeef"]
        assert verify_proof(wire) is False

    def test_tampered_path_node_fails(self, chain_dag):
        wire = chain_dag.verify_lineage("L", "R").to_dict()
        wire["path"][0]["node"]["id"] = "X"
        assert verify_proof(wire) is False

    def test_global_root_hash_converges(self):
        base = [rec("R", None, "hR"), rec("B", "R", "hB"), rec("C", "B", "hC")]
        d1 = MerkleDAG(base)
        d2 = MerkleDAG(list(reversed(base)))
        assert d1.global_root_hash() == d2.global_root_hash()

    def test_global_root_hash_empty(self):
        assert MerkleDAG([]).global_root_hash() == MerkleDAG([]).global_root_hash()


# ─── G-Set CRDT laws ──────────────────────────────────────────

class TestGSet:
    def test_add_reports_growth(self):
        s = GSet()
        assert s.add("a") is True
        assert s.add("a") is False
        assert len(s) == 1

    def test_merge_is_union(self):
        merged = GSet(["a", "b"]).merge(GSet(["b", "c"]))
        assert merged.elements() == ["a", "b", "c"]

    def test_merge_idempotent(self):
        a = GSet(["a", "b"])
        assert a.merge(a) == a

    def test_merge_commutative(self):
        a, b = GSet(["a", "x"]), GSet(["b", "y"])
        assert a.merge(b) == b.merge(a)

    def test_merge_associative(self):
        a, b, c = GSet(["a"]), GSet(["b"]), GSet(["c"])
        assert a.merge(b).merge(c) == a.merge(b.merge(c))

    def test_merge_in_place_counts_new(self):
        a = GSet(["a", "b"])
        assert a.merge_in_place(GSet(["b", "c"])) == 1
        assert a.elements() == ["a", "b", "c"]

    def test_update_counts_new(self):
        s = GSet(["a"])
        assert s.update(["a", "b", "c"]) == 2

    def test_serialization_roundtrip(self):
        s = GSet(["a", "b"])
        assert GSet.from_dict(s.to_dict()) == s


# ─── Fork detection ───────────────────────────────────────────

class TestForkDetection:
    def test_single_chain_has_no_fork(self):
        assert detect_forks([rec("R"), rec("A", "R"), rec("B", "A")]) == []

    def test_two_children_same_parent_is_fork(self):
        forks = detect_forks([rec("R"), rec("A", "R"), rec("B", "R")])
        assert len(forks) == 1
        f = forks[0]
        assert isinstance(f, ForkPair)
        assert f.parent_id == "R"
        assert f.fork_id == "R"
        assert f.children == ["A", "B"]
        assert f.pairs() == [("A", "B")]

    def test_three_children_one_fork_pair(self):
        forks = detect_forks([rec("R"), rec("A", "R"), rec("B", "R"), rec("C", "R")])
        assert len(forks) == 1
        assert forks[0].children == ["A", "B", "C"]
        assert len(forks[0].pairs()) == 3

    def test_multiple_forks(self):
        forks = detect_forks([
            rec("R"), rec("A", "R"), rec("B", "R"),
            rec("X"), rec("Y", "X"), rec("Z", "X"),
        ])
        assert [f.parent_id for f in forks] == ["R", "X"]

    def test_fork_pair_serialization(self):
        f = ForkPair(parent_id="R", children=["A", "B"])
        assert ForkPair.from_dict(f.to_dict()).children == ["A", "B"]


# ─── LineageGraph merge ───────────────────────────────────────

class TestLineageGraph:
    def test_merge_unions_records(self):
        g1 = LineageGraph([rec("R", None, "hR"), rec("A", "R", "hA")])
        g2 = LineageGraph([rec("R", None, "hR"), rec("B", "R", "hB")])
        merged = g1.merge(g2)
        assert merged.size == 3
        assert sorted(merged.ids()) == ["A", "B", "R"]
        # operands untouched
        assert g1.size == 2 and g2.size == 2

    def test_children_of_and_has_fork(self):
        g = LineageGraph([rec("R"), rec("A", "R"), rec("B", "R")])
        assert g.children_of("R") == ["A", "B"]
        assert g.has_fork("R") is True

    def test_merge_in_place_returns_added(self):
        g1 = LineageGraph([rec("R"), rec("A", "R")])
        assert g1.merge_in_place(LineageGraph([rec("R"), rec("B", "R")])) == 1

    def test_sync_proof_reports_conflicts_and_merged(self):
        ga = LineageGraph([rec("R"), rec("A", "R")])
        gb = LineageGraph([rec("R"), rec("B", "R")])
        proof = ga.sync(gb)
        assert isinstance(proof, SyncProof)
        assert proof.has_conflicts
        assert proof.conflict_count == 1
        assert proof.conflicts[0].children == ["A", "B"]
        assert proof.merged == 3
        assert proof.added == 1
        assert proof.root_hash

    def test_sync_is_idempotent(self):
        ga = LineageGraph([rec("R"), rec("A", "R")])
        gb = LineageGraph([rec("R"), rec("B", "R")])
        first = ga.sync(gb)
        second = ga.sync(gb)
        assert second.added == 0
        assert second.merged == first.merged == 3

    def test_sync_proof_serialization(self):
        proof = LineageGraph([rec("R"), rec("A", "R")]).sync(
            LineageGraph([rec("R"), rec("B", "R")])
        )
        restored = SyncProof.from_dict(proof.to_dict())
        assert restored.merged == 3
        assert restored.conflicts[0].fork_id == "R"

    def test_no_conflict_when_disjoint_chains(self):
        ga = LineageGraph([rec("R"), rec("A", "R")])
        gb = LineageGraph([rec("S"), rec("B", "S")])
        proof = ga.sync(gb)
        assert not proof.has_conflicts
        assert proof.merged == 4


# ─── KCPNode integration ──────────────────────────────────────

class TestKCPNodeIntegration:
    def test_detect_forks_from_published_artifacts(self, tmp_node):
        root = tmp_node.publish(title="Root", content="r", format="text")
        tmp_node.publish(title="A", content="a", format="text", derived_from=root.id)
        tmp_node.publish(title="B", content="b", format="text", derived_from=root.id)

        forks = tmp_node.detect_forks()
        assert len(forks) == 1
        assert forks[0].parent_id == root.id
        assert len(forks[0].children) == 2

    def test_detect_forks_none_on_linear_chain(self, tmp_node):
        a = tmp_node.publish(title="A", content="a", format="text")
        b = tmp_node.publish(title="B", content="b", format="text", derived_from=a.id)
        tmp_node.publish(title="C", content="c", format="text", derived_from=b.id)
        assert tmp_node.detect_forks() == []

    def test_verify_lineage_end_to_end(self, tmp_node):
        root = tmp_node.publish(title="Root", content="r", format="text")
        mid = tmp_node.publish(title="Mid", content="m", format="text", derived_from=root.id)
        leaf = tmp_node.publish(title="Leaf", content="l", format="text", derived_from=mid.id)

        proof = tmp_node.verify_lineage(leaf.id, root.id)
        assert proof.verify()
        assert verify_proof(proof.to_dict())

    def test_verify_lineage_missing_path_raises(self, tmp_node):
        a = tmp_node.publish(title="A", content="a", format="text")
        b = tmp_node.publish(title="B", content="b", format="text")
        with pytest.raises(LineageVerificationError):
            tmp_node.verify_lineage(a.id, b.id)

    def test_sync_returns_proof_with_conflicts_and_merged(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KCP_PEERS", raising=False)
        node_a = KCPNode(
            user_id="a@x", tenant_id="t",
            db_path=str(tmp_path / "a.db"), keys_dir=str(tmp_path / "ka"),
        )
        node_b = KCPNode(
            user_id="b@x", tenant_id="t",
            db_path=str(tmp_path / "b.db"), keys_dir=str(tmp_path / "kb"),
        )

        # Shared parent replicated to B, then independent derivations on each side.
        root = node_a.publish(title="Root", content="r", format="text")
        node_b.store.import_artifact(node_a.store.get_all_records()[0])
        node_a.publish(title="A", content="a", format="text", derived_from=root.id)
        node_b.publish(title="B", content="b", format="text", derived_from=root.id)

        proof = node_a.sync(node_b)
        assert proof.has_conflicts
        assert proof.conflicts[0].fork_id == root.id
        assert proof.merged == 3          # root + A + B
        assert proof.added == 1           # only B was new to A
        assert len(node_a.detect_forks()) == 1

    def test_sync_is_idempotent_on_node(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KCP_PEERS", raising=False)
        node_a = KCPNode(
            user_id="a@x", tenant_id="t",
            db_path=str(tmp_path / "a.db"), keys_dir=str(tmp_path / "ka"),
        )
        node_b = KCPNode(
            user_id="b@x", tenant_id="t",
            db_path=str(tmp_path / "b.db"), keys_dir=str(tmp_path / "kb"),
        )
        node_b.publish(title="Only", content="o", format="text")

        first = node_a.sync(node_b)
        second = node_a.sync(node_b)
        assert first.added == 1
        assert second.added == 0
        assert first.merged == second.merged == 1

    def test_merkle_root_converges_across_nodes(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KCP_PEERS", raising=False)
        node_a = KCPNode(
            user_id="a@x", tenant_id="t",
            db_path=str(tmp_path / "a.db"), keys_dir=str(tmp_path / "ka"),
        )
        node_b = KCPNode(
            user_id="b@x", tenant_id="t",
            db_path=str(tmp_path / "b.db"), keys_dir=str(tmp_path / "kb"),
        )
        node_b.publish(title="X", content="x", format="text")
        node_b.publish(title="Y", content="y", format="text")

        node_a.sync(node_b)
        # Same artifact set → same Merkle root on both sides.
        assert node_a.merkle_root_hash() == node_b.merkle_root_hash()
