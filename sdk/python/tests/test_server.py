"""
Tests for KCP HTTP Server

Covers all REST endpoints:
  GET  /kcp/v1/health
  GET  /kcp/v1/artifacts
  POST /kcp/v1/artifacts
  GET  /kcp/v1/artifacts/{id}
  GET  /kcp/v1/artifacts/{id}/content
  GET  /kcp/v1/artifacts/{id}/lineage
  GET  /kcp/v1/sync/list
  GET  /kcp/v1/sync/artifact/{id}
  POST /kcp/v1/sync/push
  GET  /kcp/v1/peers
  POST /kcp/v1/peers
  GET  /ui
"""

from __future__ import annotations

import base64
import pytest
from fastapi.testclient import TestClient

from kcp.node import KCPNode


# ─── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def tmp_node(tmp_path):
    """A KCPNode with a temporary database."""
    db = str(tmp_path / "kcp_test.db")
    keys = str(tmp_path / "keys")
    return KCPNode(user_id="test@example.com", tenant_id="test-org", db_path=db, keys_dir=keys)


@pytest.fixture
def client(tmp_node):
    """FastAPI TestClient wrapping tmp_node."""
    app = tmp_node.create_app()
    return TestClient(app)


@pytest.fixture
def client_with_artifact(tmp_node):
    """TestClient with one pre-published artifact."""
    artifact = tmp_node.publish(
        title="Test Knowledge",
        content="This is the content of the test artifact.",
        format="text",
        tags=["test", "knowledge"],
        summary="A test artifact for HTTP server tests",
    )
    app = tmp_node.create_app()
    return TestClient(app), artifact, tmp_node


@pytest.fixture
def two_nodes(tmp_path):
    """Two independent KCPNodes for sync tests."""
    node_a = KCPNode(
        user_id="alice@example.com",
        tenant_id="org-a",
        db_path=str(tmp_path / "node_a.db"),
        keys_dir=str(tmp_path / "keys_a"),
    )
    node_b = KCPNode(
        user_id="bob@example.com",
        tenant_id="org-b",
        db_path=str(tmp_path / "node_b.db"),
        keys_dir=str(tmp_path / "keys_b"),
    )
    return node_a, node_b


# ─── Health ──────────────────────────────────────────────────


class TestHealth:
    def test_health_returns_200(self, client):
        resp = client.get("/kcp/v1/health")
        assert resp.status_code == 200

    def test_health_returns_node_info(self, client, tmp_node):
        resp = client.get("/kcp/v1/health")
        data = resp.json()
        assert data["user_id"] == "test@example.com"
        assert data["tenant_id"] == "test-org"
        assert "node_id" in data
        assert "artifacts" in data

    def test_health_initial_artifact_count_is_zero(self, client):
        resp = client.get("/kcp/v1/health")
        assert resp.json()["artifacts"] == 0


# ─── List Artifacts ──────────────────────────────────────────


class TestListArtifacts:
    def test_list_empty(self, client):
        resp = client.get("/kcp/v1/artifacts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["artifacts"] == []
        assert data["total"] == 0

    def test_list_returns_published_artifact(self, client_with_artifact):
        client, artifact, _ = client_with_artifact
        resp = client.get("/kcp/v1/artifacts")
        data = resp.json()
        assert data["total"] == 1
        assert data["artifacts"][0]["id"] == artifact.id
        assert data["artifacts"][0]["title"] == "Test Knowledge"

    def test_list_respects_limit(self, tmp_node):
        for i in range(5):
            tmp_node.publish(f"Artifact {i}", content=f"content {i}", format="text")
        app = tmp_node.create_app()
        client = TestClient(app)
        resp = client.get("/kcp/v1/artifacts?limit=3")
        assert len(resp.json()["artifacts"]) == 3

    def test_list_search_with_q_param(self, client_with_artifact):
        client, artifact, _ = client_with_artifact
        resp = client.get("/kcp/v1/artifacts?q=knowledge")
        data = resp.json()
        assert "results" in data or "artifacts" in data  # search returns SearchResponse


# ─── Publish ─────────────────────────────────────────────────


class TestPublishArtifact:
    def test_publish_returns_201_or_200(self, client):
        resp = client.post("/kcp/v1/artifacts", json={
            "title": "New Artifact",
            "content": "Hello World",
            "format": "text",
        })
        assert resp.status_code in (200, 201)

    def test_publish_returns_artifact_with_id(self, client):
        resp = client.post("/kcp/v1/artifacts", json={
            "title": "My Report",
            "content": "# Report\nSome analysis here.",
            "format": "markdown",
            "tags": ["report", "analysis"],
        })
        data = resp.json()
        assert "id" in data
        assert len(data["id"]) == 36  # UUID format
        assert data["title"] == "My Report"
        assert data["format"] == "markdown"

    def test_publish_with_base64_content(self, client):
        raw = b"Binary content here"
        encoded = base64.b64encode(raw).decode()
        resp = client.post("/kcp/v1/artifacts", json={
            "title": "Binary Artifact",
            "_content_b64": encoded,
            "format": "text",
        })
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert "id" in data

    def test_publish_with_derived_from(self, client_with_artifact):
        client, parent, _ = client_with_artifact
        resp = client.post("/kcp/v1/artifacts", json={
            "title": "Derived Analysis",
            "content": "Building on the original...",
            "format": "text",
            "derived_from": parent.id,
        })
        assert resp.status_code in (200, 201)
        assert "id" in resp.json()

    def test_publish_increments_artifact_count(self, client):
        client.post("/kcp/v1/artifacts", json={"title": "A", "content": "a", "format": "text"})
        client.post("/kcp/v1/artifacts", json={"title": "B", "content": "b", "format": "text"})
        resp = client.get("/kcp/v1/health")
        assert resp.json()["artifacts"] == 2


# ─── Get Artifact ─────────────────────────────────────────────


class TestGetArtifact:
    def test_get_existing_artifact(self, client_with_artifact):
        client, artifact, _ = client_with_artifact
        resp = client.get(f"/kcp/v1/artifacts/{artifact.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == artifact.id
        assert data["title"] == "Test Knowledge"

    def test_get_returns_signature(self, client_with_artifact):
        client, artifact, _ = client_with_artifact
        resp = client.get(f"/kcp/v1/artifacts/{artifact.id}")
        data = resp.json()
        assert "signature" in data
        assert len(data["signature"]) > 0

    def test_get_returns_tags(self, client_with_artifact):
        client, artifact, _ = client_with_artifact
        resp = client.get(f"/kcp/v1/artifacts/{artifact.id}")
        assert "test" in resp.json()["tags"]

    def test_get_nonexistent_returns_404(self, client):
        resp = client.get("/kcp/v1/artifacts/does-not-exist")
        assert resp.status_code == 404

    def test_get_content_endpoint(self, client_with_artifact):
        client, artifact, _ = client_with_artifact
        resp = client.get(f"/kcp/v1/artifacts/{artifact.id}/content")
        assert resp.status_code == 200
        data = resp.json()
        assert "content" in data
        # Decode base64 content
        decoded = base64.b64decode(data["content"]).decode("utf-8")
        assert "content of the test artifact" in decoded

    def test_get_content_nonexistent_returns_404(self, client):
        resp = client.get("/kcp/v1/artifacts/nonexistent/content")
        assert resp.status_code == 404


# ─── Lineage ──────────────────────────────────────────────────


class TestLineage:
    def test_lineage_single_artifact(self, client_with_artifact):
        client, artifact, _ = client_with_artifact
        resp = client.get(f"/kcp/v1/artifacts/{artifact.id}/lineage")
        assert resp.status_code == 200
        data = resp.json()
        assert "lineage" in data
        assert len(data["lineage"]) == 1
        assert data["lineage"][0]["id"] == artifact.id

    def test_lineage_chain_depth_two(self, tmp_node):
        root = tmp_node.publish("Root", content="root content", format="text")
        derived = tmp_node.publish("Derived", content="derived content", format="text", derived_from=root.id)
        app = tmp_node.create_app()
        client = TestClient(app)

        resp = client.get(f"/kcp/v1/artifacts/{derived.id}/lineage")
        chain = resp.json()["lineage"]
        assert len(chain) == 2
        assert chain[0]["id"] == root.id
        assert chain[1]["id"] == derived.id

    def test_lineage_chain_depth_three(self, tmp_node):
        a = tmp_node.publish("A", content="a", format="text")
        b = tmp_node.publish("B", content="b", format="text", derived_from=a.id)
        c = tmp_node.publish("C", content="c", format="text", derived_from=b.id)
        app = tmp_node.create_app()
        client = TestClient(app)

        resp = client.get(f"/kcp/v1/artifacts/{c.id}/lineage")
        chain = resp.json()["lineage"]
        assert len(chain) == 3
        assert chain[0]["id"] == a.id
        assert chain[-1]["id"] == c.id


# ─── Sync ─────────────────────────────────────────────────────


class TestSync:
    def test_sync_list_empty(self, client):
        resp = client.get("/kcp/v1/sync/list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ids"] == []
        assert data["total"] == 0

    def test_sync_list_returns_artifact_ids(self, client_with_artifact):
        client, artifact, _ = client_with_artifact
        resp = client.get("/kcp/v1/sync/list")
        data = resp.json()
        assert artifact.id in data["ids"]
        assert data["total"] == 1

    def test_sync_list_since_filter(self, tmp_node):
        import time
        a = tmp_node.publish("Before", content="old", format="text")
        time.sleep(0.01)
        cutoff = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        time.sleep(0.01)
        b = tmp_node.publish("After", content="new", format="text")

        app = tmp_node.create_app()
        client = TestClient(app)
        resp = client.get(f"/kcp/v1/sync/list?since={cutoff}")
        ids = resp.json()["ids"]
        assert b.id in ids
        assert a.id not in ids

    def test_sync_get_artifact(self, client_with_artifact):
        client, artifact, _ = client_with_artifact
        resp = client.get(f"/kcp/v1/sync/artifact/{artifact.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == artifact.id
        assert "_content_b64" in data

    def test_sync_get_nonexistent_returns_404(self, client):
        resp = client.get("/kcp/v1/sync/artifact/nonexistent")
        assert resp.status_code == 404

    def test_sync_push_accepts_artifact(self, client, tmp_node):
        """Push an artifact payload directly to the sync endpoint."""
        other_node = tmp_node  # reuse, since we just want a valid payload
        artifact = other_node.publish("Remote Artifact", content="from remote", format="text")
        payload = other_node.store.get_artifact_with_content(artifact.id)

        # Use a fresh client
        import tempfile, os
        with tempfile.TemporaryDirectory() as td:
            receiver = KCPNode(
                user_id="receiver@example.com",
                db_path=os.path.join(td, "recv.db"),
                keys_dir=os.path.join(td, "keys"),
            )
            recv_app = receiver.create_app()
            recv_client = TestClient(recv_app)

            resp = recv_client.post("/kcp/v1/sync/push", json=payload)
            assert resp.status_code == 200
            assert resp.json()["accepted"] is True

            # Second push of same artifact → not accepted (dedup)
            resp2 = recv_client.post("/kcp/v1/sync/push", json=payload)
            assert resp2.json()["accepted"] is False

    def test_sync_push_makes_artifact_searchable(self, tmp_node):
        """After sync push, artifact is discoverable via search."""
        import tempfile, os
        artifact = tmp_node.publish("Synced Knowledge", content="synced content", format="text")
        payload = tmp_node.store.get_artifact_with_content(artifact.id)

        with tempfile.TemporaryDirectory() as td:
            receiver = KCPNode(
                user_id="receiver@example.com",
                db_path=os.path.join(td, "recv.db"),
                keys_dir=os.path.join(td, "keys"),
            )
            recv_app = receiver.create_app()
            recv_client = TestClient(recv_app)

            recv_client.post("/kcp/v1/sync/push", json=payload)

            # Should be findable now
            resp = recv_client.get("/kcp/v1/artifacts")
            artifacts = resp.json()["artifacts"]
            assert any(a["id"] == artifact.id for a in artifacts)


# ─── Peers ────────────────────────────────────────────────────


class TestPeers:
    def test_list_peers_empty(self, client):
        resp = client.get("/kcp/v1/peers")
        assert resp.status_code == 200
        assert resp.json()["peers"] == []

    def test_register_peer(self, client):
        resp = client.post("/kcp/v1/peers", json={
            "url": "https://peer.example.com",
            "name": "Test Peer",
        })
        assert resp.status_code == 200
        assert "peer_id" in resp.json()

    def test_list_peers_after_register(self, client):
        client.post("/kcp/v1/peers", json={"url": "https://peer-a.example.com", "name": "Peer A"})
        client.post("/kcp/v1/peers", json={"url": "https://peer-b.example.com", "name": "Peer B"})
        resp = client.get("/kcp/v1/peers")
        peers = resp.json()["peers"]
        assert len(peers) == 2
        urls = [p["url"] for p in peers]
        assert "https://peer-a.example.com" in urls
        assert "https://peer-b.example.com" in urls


# ─── Web UI ───────────────────────────────────────────────────


class TestWebUI:
    def test_ui_endpoint_returns_html(self, client):
        resp = client.get("/ui")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")


# ─── Node-level Sync (in-process) ─────────────────────────────


class TestNodeSync:
    def test_sync_push_via_node(self, two_nodes):
        """Node A pushes artifacts to Node B via HTTP TestClient (no real network)."""
        node_a, node_b = two_nodes

        # Node A publishes
        a1 = node_a.publish("AI Insights", content="Deep insights from AI", format="text", tags=["ai"])
        a2 = node_a.publish("Report", content="Quarterly report", format="markdown")

        # Node B creates its server
        app_b = node_b.create_app()
        client_b = TestClient(app_b)

        # Get all artifacts from A and push to B
        ids = node_a.store.get_artifact_ids_since()
        pushed = 0
        for aid in ids:
            data = node_a.store.get_artifact_with_content(aid)
            resp = client_b.post("/kcp/v1/sync/push", json=data)
            if resp.json().get("accepted"):
                pushed += 1

        assert pushed == 2

        # B now has A's artifacts
        resp = client_b.get("/kcp/v1/artifacts")
        b_ids = [a["id"] for a in resp.json()["artifacts"]]
        assert a1.id in b_ids
        assert a2.id in b_ids

    def test_sync_preserves_lineage(self, two_nodes):
        """Lineage chain is preserved after sync between nodes."""
        node_a, node_b = two_nodes

        root = node_a.publish("Root", content="root", format="text")
        child = node_a.publish("Child", content="child", format="text", derived_from=root.id)

        app_b = node_b.create_app()
        client_b = TestClient(app_b)

        for aid in [root.id, child.id]:
            data = node_a.store.get_artifact_with_content(aid)
            client_b.post("/kcp/v1/sync/push", json=data)

        resp = client_b.get(f"/kcp/v1/artifacts/{child.id}/lineage")
        chain = resp.json()["lineage"]
        assert len(chain) == 2
        assert chain[0]["id"] == root.id
        assert chain[1]["id"] == child.id

    def test_sync_pull_via_node_list(self, two_nodes):
        """Node B pulls artifact list from A's sync API."""
        node_a, node_b = two_nodes
        a1 = node_a.publish("Alpha", content="alpha content", format="text")
        a2 = node_a.publish("Beta", content="beta content", format="text")

        app_a = node_a.create_app()
        client_a = TestClient(app_a)

        # B asks A for the list
        resp = client_a.get("/kcp/v1/sync/list")
        ids = resp.json()["ids"]
        assert a1.id in ids
        assert a2.id in ids

        # B fetches each
        for rid in ids:
            resp = client_a.get(f"/kcp/v1/sync/artifact/{rid}")
            data = resp.json()
            node_b.store.import_artifact(data)

        # Verify B has them
        assert node_b.get(a1.id) is not None
        assert node_b.get(a2.id) is not None
        assert node_b.get(a1.id).title == "Alpha"
