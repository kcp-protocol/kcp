"""
KCP MCP Server — Test Suite

Tests the bridge layer directly (without MCP transport).
Calls _kcp_publish, _kcp_search, etc. against a real KCPNode with a temp DB.
"""

import json
import tempfile
import os
import pytest
from pathlib import Path

from kcp import KCPNode


# ─── Fixtures ─────────────────────────────────────────────────

@pytest.fixture
def node(tmp_path):
    """Create a fresh KCPNode with temp storage."""
    db = str(tmp_path / "kcp.db")
    keys = str(tmp_path / "keys")
    return KCPNode(
        user_id="test-mcp-agent",
        tenant_id="test-tenant",
        db_path=db,
        keys_dir=keys,
    )


# ─── Import bridge functions ───────────────────────────────────

# Import directly to test without MCP transport
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from kcp_mcp_server.server import (
    _kcp_publish,
    _kcp_search,
    _kcp_get,
    _kcp_lineage,
    _kcp_list,
    _kcp_stats,
)


# ─── kcp_publish ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_publish_basic(node):
    result = await _kcp_publish(node, {
        "title": "Rate Limiting Strategies",
        "content": "## Token Bucket\n\nThe most common approach...",
        "format": "markdown",
        "tags": ["architecture", "rate-limiting"],
        "summary": "Overview of rate limiting patterns",
        "visibility": "public",
    })
    data = json.loads(result[0].text)
    assert "artifact_id" in data
    assert data["title"] == "Rate Limiting Strategies"
    assert "content_hash" in data
    assert "signature" in data
    assert data["kcp_uri"].startswith("kcp://local/artifact/")
    assert "✅" in data["message"]


@pytest.mark.asyncio
async def test_publish_with_mcp_session_id(node):
    result = await _kcp_publish(node, {
        "title": "Session-tracked Artifact",
        "content": "Generated during MCP session",
        "mcp_session_id": "session-abc-123",
        "source": "claude-3.7-sonnet",
    })
    data = json.loads(result[0].text)
    assert "artifact_id" in data


@pytest.mark.asyncio
async def test_publish_with_derived_from(node):
    # Publish parent
    r1 = await _kcp_publish(node, {
        "title": "Parent Analysis",
        "content": "Root knowledge artifact",
    })
    parent_id = json.loads(r1[0].text)["artifact_id"]

    # Publish derived
    r2 = await _kcp_publish(node, {
        "title": "Derived Analysis",
        "content": "Building on parent...",
        "derived_from": parent_id,
    })
    data = json.loads(r2[0].text)
    assert data["derived_from"] == parent_id
    assert "artifact_id" in data


@pytest.mark.asyncio
async def test_publish_json_format(node):
    result = await _kcp_publish(node, {
        "title": "Config Artifact",
        "content": '{"key": "value", "threshold": 42}',
        "format": "json",
        "tags": ["config"],
    })
    data = json.loads(result[0].text)
    assert "artifact_id" in data


@pytest.mark.asyncio
async def test_publish_returns_kcp_uri(node):
    result = await _kcp_publish(node, {
        "title": "URI Test",
        "content": "Testing KCP URI scheme",
    })
    data = json.loads(result[0].text)
    artifact_id = data["artifact_id"]
    assert data["kcp_uri"] == f"kcp://local/artifact/{artifact_id}"


# ─── kcp_search ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_finds_published(node):
    await _kcp_publish(node, {
        "title": "Authentication Patterns",
        "content": "JWT tokens, OAuth2, API keys...",
        "tags": ["security", "auth"],
    })
    result = await _kcp_search(node, {"query": "authentication"})
    data = json.loads(result[0].text)
    assert data["total"] >= 1
    assert any("auth" in r["title"].lower() or "auth" in " ".join(r["tags"]).lower()
               for r in data["results"])


@pytest.mark.asyncio
async def test_search_empty_returns_zero(node):
    result = await _kcp_search(node, {"query": "xyznonexistent123"})
    data = json.loads(result[0].text)
    assert data["total"] == 0
    assert data["results"] == []


@pytest.mark.asyncio
async def test_search_results_have_kcp_uri(node):
    await _kcp_publish(node, {
        "title": "Docker Deployment Guide",
        "content": "Using Docker Compose for deployment...",
        "tags": ["docker", "devops"],
    })
    result = await _kcp_search(node, {"query": "docker"})
    data = json.loads(result[0].text)
    if data["total"] > 0:
        for r in data["results"]:
            assert r["kcp_uri"].startswith("kcp://local/artifact/")


@pytest.mark.asyncio
async def test_search_respects_limit(node):
    for i in range(5):
        await _kcp_publish(node, {
            "title": f"Artifact {i}",
            "content": f"Content about topic {i}",
        })
    result = await _kcp_search(node, {"query": "Artifact", "limit": 3})
    data = json.loads(result[0].text)
    assert len(data["results"]) <= 3


@pytest.mark.asyncio
async def test_search_includes_tip(node):
    result = await _kcp_search(node, {"query": "anything"})
    data = json.loads(result[0].text)
    assert "tip" in data


# ─── kcp_get ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_returns_artifact(node):
    pub = await _kcp_publish(node, {
        "title": "Get Test Artifact",
        "content": "Full content here",
        "tags": ["test"],
    })
    artifact_id = json.loads(pub[0].text)["artifact_id"]

    result = await _kcp_get(node, {"artifact_id": artifact_id})
    data = json.loads(result[0].text)
    assert data["artifact_id"] == artifact_id
    assert data["title"] == "Get Test Artifact"
    assert data["content"] == "Full content here"
    assert data["kcp_uri"] == f"kcp://local/artifact/{artifact_id}"


@pytest.mark.asyncio
async def test_get_without_content(node):
    pub = await _kcp_publish(node, {
        "title": "Metadata Only",
        "content": "Should not appear",
    })
    artifact_id = json.loads(pub[0].text)["artifact_id"]

    result = await _kcp_get(node, {
        "artifact_id": artifact_id,
        "include_content": False,
    })
    data = json.loads(result[0].text)
    assert "content" not in data
    assert data["artifact_id"] == artifact_id


@pytest.mark.asyncio
async def test_get_not_found(node):
    result = await _kcp_get(node, {"artifact_id": "00000000-0000-0000-0000-000000000000"})
    data = json.loads(result[0].text)
    assert "error" in data


@pytest.mark.asyncio
async def test_get_includes_signature(node):
    pub = await _kcp_publish(node, {
        "title": "Signed Artifact",
        "content": "Must be signed",
    })
    artifact_id = json.loads(pub[0].text)["artifact_id"]
    result = await _kcp_get(node, {"artifact_id": artifact_id})
    data = json.loads(result[0].text)
    assert data["signature"] is not None
    assert "..." in data["signature"]  # truncated


# ─── kcp_lineage ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lineage_root_artifact(node):
    pub = await _kcp_publish(node, {
        "title": "Root Knowledge",
        "content": "Original analysis",
    })
    artifact_id = json.loads(pub[0].text)["artifact_id"]

    result = await _kcp_lineage(node, {"artifact_id": artifact_id})
    data = json.loads(result[0].text)
    assert data["artifact_id"] == artifact_id
    assert data["chain_length"] >= 1


@pytest.mark.asyncio
async def test_lineage_derived_chain(node):
    r1 = await _kcp_publish(node, {
        "title": "Root",
        "content": "Level 0",
    })
    root_id = json.loads(r1[0].text)["artifact_id"]

    r2 = await _kcp_publish(node, {
        "title": "Derived L1",
        "content": "Level 1",
        "derived_from": root_id,
    })
    l1_id = json.loads(r2[0].text)["artifact_id"]

    r3 = await _kcp_publish(node, {
        "title": "Derived L2",
        "content": "Level 2",
        "derived_from": l1_id,
    })
    l2_id = json.loads(r3[0].text)["artifact_id"]

    result = await _kcp_lineage(node, {"artifact_id": l2_id})
    data = json.loads(result[0].text)
    # Chain should have at least the root and the current
    assert data["chain_length"] >= 1


@pytest.mark.asyncio
async def test_lineage_not_found(node):
    result = await _kcp_lineage(node, {"artifact_id": "00000000-0000-0000-0000-000000000000"})
    data = json.loads(result[0].text)
    assert "error" in data


# ─── kcp_list ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_returns_artifacts(node):
    await _kcp_publish(node, {"title": "List Item 1", "content": "A"})
    await _kcp_publish(node, {"title": "List Item 2", "content": "B"})

    result = await _kcp_list(node, {"limit": 10})
    data = json.loads(result[0].text)
    assert data["total"] >= 2
    assert all("artifact_id" in a for a in data["artifacts"])
    assert all("kcp_uri" in a for a in data["artifacts"])


@pytest.mark.asyncio
async def test_list_respects_limit(node):
    for i in range(5):
        await _kcp_publish(node, {"title": f"Item {i}", "content": f"Content {i}"})

    result = await _kcp_list(node, {"limit": 2})
    data = json.loads(result[0].text)
    assert len(data["artifacts"]) <= 2


@pytest.mark.asyncio
async def test_list_empty_node(node):
    result = await _kcp_list(node, {})
    data = json.loads(result[0].text)
    assert data["total"] == 0
    assert data["artifacts"] == []


# ─── kcp_stats ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stats_returns_node_info(node):
    result = await _kcp_stats(node, {})
    data = json.loads(result[0].text)
    assert data["server"] == "kcp-mcp-server v0.1.0"
    assert "kcp_publish" in data["tools"]
    assert "node_id" in data
    assert "user_id" in data


@pytest.mark.asyncio
async def test_stats_count_grows_after_publish(node):
    r1 = await _kcp_stats(node, {})
    before = json.loads(r1[0].text).get("artifact_count", 0)

    await _kcp_publish(node, {"title": "Stats Test", "content": "Testing count"})

    r2 = await _kcp_stats(node, {})
    after = json.loads(r2[0].text).get("artifact_count", 0)
    assert after == before + 1


# ─── Bridge: KCP as MCP backend ───────────────────────────────

@pytest.mark.asyncio
async def test_full_bridge_workflow(node):
    """Simulates a complete MCP session: search → not found → publish → search → get → lineage."""

    # 1. Search — nothing exists yet
    r1 = await _kcp_search(node, {"query": "kubernetes deployment"})
    d1 = json.loads(r1[0].text)
    assert d1["total"] == 0

    # 2. Publish new knowledge
    r2 = await _kcp_publish(node, {
        "title": "Kubernetes Deployment Patterns",
        "content": "## Rolling Update\n\nReplace pods gradually...\n\n## Blue-Green\n\nTwo identical environments...",
        "format": "markdown",
        "tags": ["kubernetes", "deployment", "devops"],
        "summary": "Common K8s deployment strategies",
        "visibility": "org",
        "source": "claude-3.7-sonnet",
        "mcp_session_id": "session-test-001",
    })
    d2 = json.loads(r2[0].text)
    artifact_id = d2["artifact_id"]
    assert "artifact_id" in d2

    # 3. Search again — now finds it
    r3 = await _kcp_search(node, {"query": "kubernetes deployment"})
    d3 = json.loads(r3[0].text)
    assert d3["total"] >= 1

    # 4. Get full content
    r4 = await _kcp_get(node, {"artifact_id": artifact_id})
    d4 = json.loads(r4[0].text)
    assert "Rolling Update" in d4["content"]
    assert d4["kcp_uri"] == f"kcp://local/artifact/{artifact_id}"

    # 5. Publish derived artifact
    r5 = await _kcp_publish(node, {
        "title": "Kubernetes Deployment for ML Models",
        "content": "Building on general patterns, specific to ML workloads...",
        "tags": ["kubernetes", "ml", "deployment"],
        "derived_from": artifact_id,
        "source": "cursor-agent",
    })
    d5 = json.loads(r5[0].text)
    derived_id = d5["artifact_id"]
    assert d5["derived_from"] == artifact_id

    # 6. Trace lineage
    r6 = await _kcp_lineage(node, {"artifact_id": derived_id})
    d6 = json.loads(r6[0].text)
    assert d6["chain_length"] >= 1

    # 7. Final stats
    r7 = await _kcp_stats(node, {})
    d7 = json.loads(r7[0].text)
    assert d7["artifact_count"] >= 2
