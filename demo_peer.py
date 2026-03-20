"""
KCP Peer Sync Demo

Demonstrates two independent KCP nodes syncing knowledge over HTTP
without any cloud infrastructure — using in-process HTTP (FastAPI TestClient).

This proves:
  1. Node A can publish artifacts locally
  2. Node B can discover and pull them via KCP REST API
  3. Lineage is preserved across node boundaries
  4. Signatures remain valid after sync

Run: make peer-demo
"""

from __future__ import annotations

import os
import sys
import tempfile

# Allow running from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "sdk/python"))

from fastapi.testclient import TestClient

from kcp.node import KCPNode


def run():
    tmp = tempfile.mkdtemp()

    # ── Create two independent nodes ────────────────────────────
    node_a = KCPNode(
        user_id="alice@local",
        tenant_id="org-a",
        db_path=os.path.join(tmp, "node_a.db"),
        keys_dir=os.path.join(tmp, "keys_a"),
    )
    node_b = KCPNode(
        user_id="bob@local",
        tenant_id="org-b",
        db_path=os.path.join(tmp, "node_b.db"),
        keys_dir=os.path.join(tmp, "keys_b"),
    )

    print("=" * 56)
    print("  KCP Peer Sync Demo — Two Nodes, One Protocol")
    print("=" * 56)
    print()

    # ── Node A: publish knowledge ────────────────────────────────
    print("📝  Node A (alice@local) — publishing knowledge...")
    a1 = node_a.publish(
        title="Architecture Decision Record",
        content="# ADR-001\n\nUse SQLite for the MVP phase.\n"
                "PostgreSQL can be added as a hub backend in Phase 2.",
        format="markdown",
        tags=["architecture", "adr", "sqlite"],
    )
    a2 = node_a.publish(
        title="Security Checklist",
        content="- Ed25519 signatures on all artifacts\n"
                "- Content-addressed via SHA-256\n"
                "- Keys stored at 0600 permissions",
        format="markdown",
        tags=["security", "checklist"],
    )
    a3 = node_a.publish(
        title="Security Checklist — v2",
        content="- Ed25519 signatures on all artifacts\n"
                "- Content-addressed via SHA-256\n"
                "- Keys stored at 0600 permissions\n"
                "- Added: rate limiting recommendations",
        format="markdown",
        tags=["security", "checklist"],
        derived_from=a2.id,
    )

    print(f"   ✅ [{a1.id[:8]}...] {a1.title}")
    print(f"   ✅ [{a2.id[:8]}...] {a2.title}")
    print(f"   ✅ [{a3.id[:8]}...] {a3.title}  (derived from a2)")
    print()

    # ── Node B: has zero knowledge ───────────────────────────────
    print("📊  Node B (bob@local) — stats before sync:")
    print(f"   artifacts: {node_b.stats()['artifacts']}")
    print()

    # ── Sync: B pulls from A via HTTP ───────────────────────────
    print("📡  Syncing A → B via KCP REST API...")

    # In production: client_b would call real HTTP at https://peer-url/kcp/v1/...
    # Here: TestClient simulates the network call in-process
    client_b = TestClient(node_b.create_app())

    ids = node_a.store.get_artifact_ids_since()
    pulled = 0
    for aid in ids:
        payload = node_a.store.get_artifact_with_content(aid)
        resp = client_b.post("/kcp/v1/sync/push", json=payload)
        if resp.json().get("accepted"):
            pulled += 1

    print(f"   ✅ Pulled {pulled}/{len(ids)} artifacts")
    print()

    # ── Node B: search and verify ────────────────────────────────
    print("🔍  Node B searching synced knowledge...")
    results = node_b.search("security")
    for r in results.results:
        print(f"   📄 [{r.id[:8]}...] {r.title}  (relevance: {r.relevance:.2f})")
    print()

    # ── Lineage preserved ────────────────────────────────────────
    print("🌳  Lineage chain preserved after sync (root → latest):")
    chain = node_b.lineage(a3.id)
    for i, node in enumerate(chain):
        connector = "└──" if i == len(chain) - 1 else "├──"
        indent = "   " * i
        print(f"   {indent}{connector} {node['title']}  ({node['id'][:8]}...)")
    print()

    # ── Signature verification ───────────────────────────────────
    print("🔐  Verifying signatures on Node B (cross-node)...")
    for aid in [a1.id, a2.id, a3.id]:
        artifact = node_b.get(aid)
        # Recover public key from export metadata
        export = node_a.export_artifact(aid)
        pub_key = bytes.fromhex(export["_kcp_export"]["public_key"])
        valid = node_b.verify(artifact, public_key=pub_key)
        status = "✅ VALID" if valid else "❌ INVALID"
        print(f"   {status}  {artifact.title}")
    print()

    print("=" * 56)
    print("  ✅ Peer sync complete!")
    print()
    print("  In production:")
    print("    kcp serve --port 8800          # Node A goes live")
    print("    kcp peer add https://node-a.example.com")
    print("    kcp sync https://node-a.example.com --pull")
    print("=" * 56)

    import shutil
    shutil.rmtree(tmp)


if __name__ == "__main__":
    run()
