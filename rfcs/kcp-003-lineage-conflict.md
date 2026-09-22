# RFC KCP-003: Lineage Conflict Resolution via Merkle DAG + CRDTs

**RFC Number:** KCP-003
**Title:** Lineage Conflict Resolution — Fork Detection, Merkle Lineage Proofs, and G-Set CRDT Sync
**Status:** Draft
**Date:** September 2026
**Author:** Thiago Silva
**Suggested by:** Claude 3.7 Sonnet and Grok 2 (LLM evaluations, see issue #2)
**Related:** [RFC KCP-001](kcp-001-core.md) §5 (Federation), [RFC KCP-002](kcp-002-mcp-bridge.md) (MCP Bridge)

---

> ## ⚠️ RFC numbering collision (must be resolved)
>
> This document is **KCP-003 by issue numbering**, but a *different* RFC already
> occupies that slot: [`rfcs/kcp-003-sync-storage.md`](kcp-003-sync-storage.md)
> ("Adaptive Sync Engine + Hybrid Storage Architecture").
>
> This RFC does **not** modify, rename, or supersede that file. Instead:
>
> - It is filed as `rfcs/kcp-003-lineage-conflict.md` (distinct filename, per issue #2).
> - **Recommendation:** renumber the sync/storage RFC from **KCP-003 → KCP-005**
>   (the next free number after KCP-004 "Network Deployment Models"). That
>   document is a storage/sync-engine RFC; this one is a protocol-semantics RFC.
> - Note that `kcp-003-sync-storage.md` §7 currently lists *"No CRDT / conflict
>   resolution"* as a **non-goal**. This RFC makes conflict resolution an explicit,
>   in-scope protocol concern (goals §1.2). The two RFCs are complementary:
>   the sync engine moves bytes; this RFC defines what the bytes *mean* when two
>   nodes diverge. The renumbering also removes that apparent contradiction.

---

## Abstract

In federated mode, two agents at different nodes can independently derive
artifacts from the same `parent_id`. KCP artifacts are immutable, so this is not
a mutation to overwrite — it is a **fork** in the lineage DAG that must be
detected, represented faithfully, and merged without losing provenance.

This RFC specifies:

1. **Fork detection** — the deterministic algorithm that turns a set of artifact
   records into a list of fork pairs (one parent, ≥ 2 children).
2. **Merkle lineage proofs** — a structure by which any party can verify that
   `leaf_id` descends from `root_id` **locally, without trusting the origin node**.
3. **CRDT merge semantics** — artifact sets modeled as a **Grow-Only Set (G-Set)**;
   merge is always union, order-independent and idempotent.

A reference implementation ships with the Python SDK
(`kcp/merkle.py`, `kcp/crdt.py`, `kcp/lineage_graph.py`, plus `KCPNode` methods).

---

## 1. Motivation

### 1.1 The gap

KCP-001 §5 defines federation (hub-to-hub sync). KCP-003 (sync/storage) defines
*reliable delivery* of artifacts between peers. Neither defines what happens when
two nodes legitimately add a child to the same parent while partitioned.

```
                    ┌─────────────────────────────┐
                    │   node A            node B   │
                    └─────────────────────────────┘
   R (shared parent)            R
   ├── A1  (derived_from R)     └── B1 (derived_from R)
   │
   │        after sync:  R ──┬── A1
   │                         └── B1        ← fork: R now has two children
```

Without a protocol rule:

1. Nodes cannot tell whether divergence is expected (fork) or wrong (corruption).
2. A naive "keep one" merge silently **discards provenance** — unacceptable for
   an auditable knowledge protocol.
3. A consumer receiving a lineage claim has no way to verify it without trusting
   the node that made it.

### 1.2 Design goals

- **Faithful** — both branches are retained; nothing is ever deleted.
- **Verifiable** — lineage claims are provable offline against a root commitment.
- **Convergent** — any two nodes that exchange the same artifacts reach the same
  state, regardless of message order.
- **Backward compatible** — no change to the artifact wire format or existing
  sync endpoints; new fields/methods are additive.
- **No consensus, no coordinator** — pure data structure + signatures.

### 1.3 Non-goals

- **No mutation / no last-writer-wins.** Artifacts are immutable; KCP has no
  "update in place". (Content changes always create a *new* artifact via
  `derived_from`.)
- **No automatic conflict "resolution"** in the sense of picking a winner. KCP
  *reports* forks; choosing a branch is an application/policy decision.
- **No consensus protocol** (no Raft/Paxos), no global ordering.
- **No deletion / tombstones.** A G-Set cannot remove; retraction is a future
  RFC (would require a different CRDT, e.g. 2P-Set or OR-Set).

---

## 2. Terminology

| Term | Meaning |
|---|---|
| **Artifact / node** | A signed KCP artifact; its `id` is its DAG identity. |
| **Edge** | `child.derived_from == parent.id` (also `parent_id`). |
| **Fork** | A parent with ≥ 2 children in the sampled set (the divergence point). |
| **fork_id** | The common parent id — where lineages diverge (matches issue #2). |
| **Leaf proof** | A Merkle proof that a given artifact descends from a given root. |
| **Root commitment** | The Merkle hash of an ancestor node, used as trust anchor. |
| **G-Set** | Grow-Only Set CRDT: join = union. |

---

## 3. Artifact lineage fields (additive)

This RFC does **not** require new mandatory fields. Fork information is derived,
not stored, so old nodes keep working. For producers that want to *advertise* the
fork at publish time, the following optional extension is defined (as proposed in
issue #2):

```json
{
  "artifact_id": "uuid-B",
  "lineage": {
    "parent_id": "uuid-A",
    "fork_id": "uuid-A",
    "fork_seq": 1
  }
}
```

- `parent_id` — the parent artifact (existing concept, exposed as `derived_from`).
- `fork_id` — the divergence point. By convention equal to `parent_id` for a
  direct fork (a node may set it to a deeper shared ancestor to indicate a
  sibling branch).
- `fork_seq` — ordinal of the branch at that fork point (1-based, local hint;
  **not** authoritative — the receiving node recomputes forks from the graph).

> **Normative note:** `fork_seq` is a *hint* only. Two nodes must not rely on it
> for ordering. The authoritative fork set is computed by the algorithm in §4.

---

## 4. Fork detection algorithm

**Input:** a set of artifact records, each with `id` and `parent_id`
(`derived_from`) and optionally `content_hash`, `timestamp`, `author`.

**Output:** a list of fork pairs, one per parent with ≥ 2 children.

```
detect_forks(records):
    children_by_parent := {}
    for r in records:
        p := r.parent_id
        if p != null:
            children_by_parent[p].append(r.id)

    forks := []
    for (parent, children) in children_by_parent:
        if len(children) >= 2:
            forks.append(ForkPair(parent_id=parent,
                                  children=sort(children),
                                  fork_seq=1))
    return sort(forks, by=parent_id)
```

Properties:

- **Deterministic** — output depends only on the set of records (children sorted),
  never on arrival order. Two nodes with the same set compute the *same* forks.
- **O(n)** — single pass plus a sort.
- **No false positives on linear chains** — a parent with exactly one child is
  not a fork.
- **k-way forks** — a parent with `k` children yields **one** `ForkPair` with `k`
  children (plus `k·(k−1)/2` deriving unordered child pairs via `ForkPair.pairs()`).

A fork pair corresponds directly to the issue's "two artifacts that derive from
the same parent".

---

## 5. Merkle lineage proofs

### 5.1 Node commitment

Each artifact node commits to (a) its own canonical metadata and (b) the hashes
of its direct children:

```
leaf(record)      = SHA-256( 0x00 ‖ canonical(record) )
node(record, C)   = SHA-256( 0x01 ‖ canonical(record) ‖ sort(C)[0] ‖ sort(C)[1] ‖ … )
```

where `C` is the list of *direct child node hashes* and

```
canonical(record) = JSON({ id, parent_id, content_hash, timestamp, user_id },
                         sort_keys=True, separators=(",",":"))
```

- **Domain separation** (`0x00`/`0x01`) prevents leaf/internal second-preimage mixups.
- **Sorted children** make a node's hash independent of discovery order.
- A node's hash therefore **commits to its entire descendant subtree**.
- `content_hash` (already SHA-256 over plaintext, per the SDK) is folded in, so the
  commitment also binds artifact content.

### 5.2 Proof structure

A proof that `leaf` descends from `root`:

```json
{
  "version": "kcp-merkle-v1",
  "leaf": { "id": "L", "parent_id": "C", "content_hash": "…", "timestamp": "…", "user_id": "…" },
  "leaf_children": ["<hash>", "…"],
  "root_id": "R",
  "root_hash": "<hex>",
  "path": [
    { "node": { "id": "C", … }, "siblings": ["<hash of C's other children>"] },
    { "node": { "id": "B", … }, "siblings": ["<hash of B's other children>"] },
    { "node": { "id": "R", … }, "siblings": [] }
  ]
}
```

`path` is ordered **leaf's parent → root**. At each step, `siblings` carries the
hashes of the ancestor's *other* children — i.e. the **fork branches** that share
that ancestor. If `leaf == root`, `path` is empty.

### 5.3 Verification (local, trustless)

```
verify(proof):
    h := node(proof.leaf, proof.leaf_children)
    if proof.path is empty:
        return proof.leaf.id == proof.root_id and h == proof.root_hash
    if proof.leaf.parent_id != proof.path[0].node.id: return False
    for step in proof.path:
        h := node(step.node, step.siblings ∪ {h})
    return proof.path[-1].node.id == proof.root_id and h == proof.root_hash
```

- The verifier needs **only** the proof and the expected `root_hash` (a trust
  anchor obtained out-of-band — e.g. the root artifact's signed metadata, or a
  peer's advertised Merkle root it already trusts).
- It **recomputes** the root commitment from the leaf upward. It never trusts the
  producing node, and needs no network access.
- Any tampering with the leaf, any path node, any sibling hash, or the root hash
  changes the recomputed value → verification fails.

### 5.4 Whole-graph digest

`global_root_hash = SHA-256("kcp-merkle-v1" ‖ sort(node_hash(r) for r in roots))`
is a single digest of an entire artifact set. Two nodes that have converged on the
same artifacts produce the **same** digest — a cheap convergence check.

> **Security note:** A valid proof shows *"this leaf record, with this
> content_hash, descends from a root whose commitment is H"*. It does **not**
> prove the leaf's *signature* is valid — that remains the job of the existing
> Ed25519 verification (`verify_artifact`). The two checks are orthogonal and
> should both be applied by consumers.

---

## 6. CRDT merge semantics (G-Set)

### 6.1 Model

The set of artifacts known by a node is a **Grow-Only Set**:

```
state       = set of artifact ids
add(e)      = state ∪ {e}                 -- monotonic, never removes
merge(A,B)  = A ∪ B                       -- join / least upper bound
```

Because artifacts are immutable and content-addressed, "the same artifact" always
means the same bytes — so merging id sets and merging records coincide, and there
is **nothing to reconcile** beyond set membership.

### 6.2 Laws

| Law | Statement | Why it holds |
|---|---|---|
| Idempotent | `A ⊔ A = A` | union with itself |
| Commutative | `A ⊔ B = B ⊔ A` | union is symmetric |
| Associative | `(A ⊔ B) ⊔ C = A ⊔ (B ⊔ C)` | union is associative |
| Monotonic | `A ⊆ A ⊔ B` | grow-only |

These make federation convergence **order-independent** and safe to replay after
network partitions or duplicate deliveries.

### 6.3 Sync

```
node_a.sync(node_b) -> SyncProof
```

Semantics:

1. **Union** — call `import_artifact` for each record of `node_b` (idempotent;
   existing ids are no-ops). This is `proof.added`.
2. **Report** — compute `detect_forks()` over the merged set. This is
   `proof.conflicts`.
3. **Digest** — compute the merged `global_root_hash()`.

```python
proof = node_a.sync(node_b)
proof.conflicts   # [ForkPair(fork_id=R, children=[A1, B1]), ...]
proof.merged      # total distinct artifacts after merge
proof.added       # newly introduced by this sync
proof.root_hash   # Merkle digest of the merged DAG
```

`SyncProof` also carries `has_conflicts` / `conflict_count` convenience accessors
and JSON serialization (`to_dict` / `from_dict`).

**Convergence:** after `a.sync(b)` and `b.sync(a)`, both nodes hold the same set
and therefore the same `root_hash` and the same fork list.

### 6.4 Why G-Set (and not LWW / OR-Set)

- Artifacts are immutable → no writes to lose → **no need for timestamps/vector
  clocks** to break ties. "Conflict" is not a write conflict; it is legitimate
  branching.
- A G-Set cannot delete, which matches KCP's auditability requirement today.
- When redaction becomes a requirement, it will be a **separate RFC** introducing
  an OR-Set/2P-Set with tombstones — deliberately out of scope here.

---

## 7. Reference implementation (Python SDK)

| Module | Contents |
|---|---|
| `kcp/merkle.py` | `leaf_hash`, `node_hash`, `MerkleDAG`, `MerkleProof`, `verify_proof`, `LineageVerificationError` |
| `kcp/crdt.py` | `GSet` (union merge, laws, serialization) |
| `kcp/lineage_graph.py` | `ForkPair`, `detect_forks`, `LineageGraph`, `SyncProof` |
| `kcp/node.py` | `KCPNode.lineage_graph()`, `.detect_forks()`, `.verify_lineage(leaf,root)`, `.merkle_root_hash()`, `.sync(other)` |
| `kcp/store.py` | `LocalStore.get_all_records()` (id + parent edges for graph rebuild) |

All additions are **additive**. No existing signature, endpoint, or table changes;
the existing 227-test suite continues to pass.

### 7.1 HTTP endpoints (future work)

To expose proofs remotely, a follow-up can add:

```
GET  /kcp/v1/artifacts/{leaf_id}/lineage-proof?root={root_id}   → MerkleProof (JSON)
POST /kcp/v1/sync/merge                                          → SyncProof
```

Not implemented in this RFC's first cut (SDK reference only).

---

## 8. Security considerations

- **Trustless verification** — proofs are checked locally against a root anchor;
  a malicious peer cannot forge a lineage path without breaking SHA-256.
- **Signature orthogonality** — proofs bind *structure + content hash*; Ed25519
  signatures bind *authorship*. Verify both (see §5.4).
- **Fork spam / DoS** — a peer could flood forks. Mitigations (rate limits,
  per-tenant fork budgets, ignoring unverifiable branches) are policy, not
  protocol; deferred.
- **`fork_seq` is untrusted** — never use it for ordering or tie-breaking (§3).
- **Root anchor trust** — the `root_hash` must come from a trusted source (a
  signed artifact or an already-verified peer root). A proof against an attacker
  supplied root proves nothing.

---

## 9. Acceptance criteria ↔ implementation

| Criterion (issue #2) | Where |
|---|---|
| RFC in `rfcs/kcp-003-lineage-conflict.md` | this file |
| Fork detection algorithm defined | §4 + `lineage_graph.detect_forks` |
| Merkle proof structure specified | §5 + `merkle.MerkleProof` |
| CRDT merge semantics defined | §6 + `crdt.GSet` |
| Python SDK reference implementation | modules in §7 |
| Tests: conflict detection + merge | `sdk/python/tests/test_lineage_crdt.py` |

---

## 10. Open questions

1. **Multi-parent DAGs** — the current commitment handles a single parent per
   artifact. Should merges become first-class artifacts with multiple parents
   (a real DAG, not a tree)? That would make forks explicit "merge nodes".
2. **Proof compression** — for deep chains, is a per-level sibling list
   acceptable, or should we adopt a sparse-Merkle / log-based proof?
3. **Fork policy profiles** — should KCP define named policies (`report`,
   `quarantine`, `auto-merge-by-agent`)? Likely application-layer.
4. **Retraction** — a future CRDT (OR-Set with tombstones) for redaction.
5. **Cross-tenant forks** — visibility rules for exposing a fork whose branches
   have different ACLs.

---

*RFC KCP-003 (lineage-conflict, Draft) — feedback: https://github.com/kcp-protocol/kcp/issues/2*
