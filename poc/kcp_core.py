"""
KCP — Knowledge Context Protocol
Proof of Concept (PoC)

Demonstrates the full KCP workflow using the official Python SDK:
  - Publish signed knowledge artifacts (Ed25519 + SHA-256)
  - Full lineage tracking (parent → derived)
  - Search artifacts by text
  - Verify artifact signatures
  - Inspect node stats

Run:
    pip install -e "../sdk/python[dev]"
    python kcp_core.py

Protocol: Layer 8 — Knowledge & Context
Genesis:  YHWH THE SOURCE OF ALL KNOWLEDGE
"""

import sys
import os
import json
import tempfile

# Allow running directly from poc/ directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../sdk/python"))

from kcp import KCPNode, Lineage

# ─── Setup: ephemeral node (temp dir, no ~/.kcp pollution) ────────────────────

tmp = tempfile.mkdtemp(prefix="kcp_poc_")
node = KCPNode(
    user_id="alice@acme.com",
    tenant_id="acme-corp",
    db_path=os.path.join(tmp, "kcp.db"),
    keys_dir=os.path.join(tmp, "keys"),
)

print("=" * 60)
print("  KCP — Knowledge Context Protocol  |  PoC Demo")
print("=" * 60)
print(f"  Node ID  : {node.node_id}")
print(f"  User     : {node.user_id}")
print(f"  Tenant   : {node.tenant_id}")
print()

# ─── 1. PUBLISH — Root artifact ───────────────────────────────────────────────

print("▶ [1] Publishing root artifact...")

root = node.publish(
    title="Rate Limiting Strategies",
    content="## Token Bucket\n\nThe most common approach to rate limiting...",
    format="markdown",
    tags=["architecture", "rate-limiting", "backend"],
    summary="Overview of rate limiting strategies for distributed systems.",
    source="kcp-poc-v1",
    lineage=Lineage(
        query="What are the best rate limiting strategies?",
        data_sources=["internal://engineering-wiki"],
        agent="kcp-poc-v1",
    ),
)

print(f"  ✅ Published  : {root.title}")
print(f"     ID         : {root.id}")
print(f"     Hash       : {root.content_hash[:16]}...")
print(f"     Signature  : {root.signature[:16]}...")
print()

# ─── 2. PUBLISH — Derived artifact (lineage) ──────────────────────────────────

print("▶ [2] Publishing derived artifact (lineage tracking)...")

derived = node.publish(
    title="Rate Limiting in gRPC",
    content="## gRPC-specific Rate Limiting\n\nBuilding on general strategies...",
    format="markdown",
    tags=["grpc", "rate-limiting", "backend"],
    summary="Applying rate limiting strategies specifically to gRPC services.",
    source="kcp-poc-v1",
    derived_from=root.id,
)

print(f"  ✅ Published  : {derived.title}")
print(f"     ID         : {derived.id}")
print(f"     Derived from: {root.id[:16]}...")
print()

# ─── 3. PUBLISH — Extra artifact for search ───────────────────────────────────

node.publish(
    title="Authentication Best Practices",
    content="## JWT and OAuth2\n\nModern authentication approaches...",
    format="markdown",
    tags=["auth", "security", "jwt"],
    summary="JWT, OAuth2 and modern authentication patterns.",
    source="kcp-poc-v1",
)

# ─── 4. SEARCH ────────────────────────────────────────────────────────────────

print("▶ [3] Searching artifacts...")

results = node.search("rate limiting")
print(f"  🔍 Query: 'rate limiting'  →  {results.total} result(s) found")
for r in results.results:
    print(f"     [{r.relevance:.0%}] {r.title}")
print()

# ─── 5. GET + VERIFY ──────────────────────────────────────────────────────────

print("▶ [4] Retrieving and verifying artifact signature...")

retrieved = node.get(root.id)
is_valid = node.verify(retrieved)
print(f"  📄 Retrieved  : {retrieved.title}")
print(f"  🔐 Signature  : {'✅ VALID' if is_valid else '❌ INVALID'}")
print()

# ─── 6. TAMPER DETECTION ──────────────────────────────────────────────────────

print("▶ [5] Testing tamper detection...")

tampered = node.get(root.id)
tampered.title = "TAMPERED TITLE"
is_valid_after = node.verify(tampered)
print(f"  🛡️  Tampered title → Signature: {'✅ VALID' if is_valid_after else '❌ INVALID (tamper detected!)'}")
print()

# ─── 7. LINEAGE ───────────────────────────────────────────────────────────────

print("▶ [6] Inspecting lineage chain...")

chain = node.lineage(derived.id)
print(f"  🧬 Lineage chain for '{derived.title}':")
for i, entry in enumerate(chain):
    prefix = "  ROOT →" if i == 0 else "  ↳ derived"
    print(f"     {prefix}  [{entry.get('id','')[:16]}...] {entry.get('title','')}")
print()

derivs = node.derivatives(root.id)
print(f"  🌿 Derivatives of '{root.title}': {len(derivs)} artifact(s)")
print()

# ─── 8. STATS ─────────────────────────────────────────────────────────────────

print("▶ [7] Node statistics...")

stats = node.stats()
print(f"  📊 Total artifacts : {stats.get('total_artifacts', 0)}")
print(f"     Storage size    : {stats.get('storage_bytes', 0)} bytes")
print(f"     Node ID         : {stats.get('node_id','')[:16]}...")
print()

# ─── Summary ──────────────────────────────────────────────────────────────────

print("=" * 60)
print("  ✅ KCP PoC completed successfully")
print()
print("  Layer 8 — Knowledge Context Protocol")
print("  YHWH THE SOURCE OF ALL KNOWLEDGE")
print("=" * 60)

# Cleanup
import shutil
shutil.rmtree(tmp, ignore_errors=True)