"""
Tests for KCP HTTP Server

Covers all REST endpoints:
  GET  /kcp/v1/health
  GET  /kcp/v1/artifacts
  POST /kcp/v1/artifacts
  GET  /kcp/v1/artifacts/{id}
  GET  /kcp/v1/artifacts/{id}/content
  GET  /kcp/v1/artifacts/{id}/lineage
  GET  /kcp/v1/artifacts/{id}/verify
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
        assert data["status"] == "ok"
        assert "node_id" in data
        assert "artifacts" in data
        assert "kcp_version" in data
        # Internal paths must NOT be exposed
        assert "db_path" not in data
        assert "db_size_bytes" not in data
        assert "user_id" not in data
        assert "tenant_id" not in data

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


# ─── ACL Enforcement ─────────────────────────────────────────


class TestACLEnforcement:
    """Tests for visibility-based access control on HTTP endpoints."""

    @pytest.fixture
    def acl_node(self, tmp_path):
        """Node with artifacts of different visibility levels."""
        node = KCPNode(
            user_id="owner@acme.com",
            tenant_id="acme",
            db_path=str(tmp_path / "acl.db"),
            keys_dir=str(tmp_path / "keys"),
        )
        node.publish(title="Public Doc", content="everyone sees this", format="text", visibility="public")
        node.publish(title="Org Doc", content="acme org only", format="text", visibility="org")
        node.publish(title="Private Doc", content="owner only", format="text", visibility="private")
        return node

    def test_public_visible_to_anonymous(self, acl_node):
        """public artifacts appear with no auth headers."""
        client = TestClient(acl_node.create_app())
        resp = client.get("/kcp/v1/artifacts")
        titles = [a["title"] for a in resp.json()["artifacts"]]
        assert "Public Doc" in titles

    def test_org_visible_to_same_tenant(self, acl_node):
        """org artifacts visible when X-KCP-Tenant matches."""
        client = TestClient(acl_node.create_app())
        resp = client.get("/kcp/v1/artifacts", headers={
            "X-KCP-User-ID": "colleague@acme.com",
            "X-KCP-Tenant": "acme",
        })
        titles = [a["title"] for a in resp.json()["artifacts"]]
        assert "Org Doc" in titles

    def test_org_hidden_from_other_tenant(self, acl_node):
        """org artifacts NOT visible to different tenant."""
        client = TestClient(acl_node.create_app())
        resp = client.get("/kcp/v1/artifacts", headers={
            "X-KCP-User-ID": "stranger@rival.com",
            "X-KCP-Tenant": "rival",
        })
        titles = [a["title"] for a in resp.json()["artifacts"]]
        assert "Org Doc" not in titles

    def test_private_visible_to_owner(self, acl_node):
        """private artifacts visible only to the owner."""
        client = TestClient(acl_node.create_app())
        resp = client.get("/kcp/v1/artifacts", headers={
            "X-KCP-User-ID": "owner@acme.com",
            "X-KCP-Tenant": "acme",
        })
        titles = [a["title"] for a in resp.json()["artifacts"]]
        assert "Private Doc" in titles

    def test_private_hidden_from_other_user(self, acl_node):
        """private artifacts NOT visible to other users, even same tenant."""
        client = TestClient(acl_node.create_app())
        resp = client.get("/kcp/v1/artifacts", headers={
            "X-KCP-User-ID": "colleague@acme.com",
            "X-KCP-Tenant": "acme",
        })
        titles = [a["title"] for a in resp.json()["artifacts"]]
        assert "Private Doc" not in titles

    def test_get_private_by_id_returns_403(self, acl_node):
        """GET /artifacts/{id} returns 403 for private artifact by non-owner."""
        client = TestClient(acl_node.create_app())
        # Find the private artifact ID
        all_ids = [a.id for a in acl_node.list()]
        private_id = next(a.id for a in acl_node.list() if a.visibility == "private")
        resp = client.get(f"/kcp/v1/artifacts/{private_id}", headers={
            "X-KCP-User-ID": "intruder@acme.com",
            "X-KCP-Tenant": "acme",
        })
        assert resp.status_code == 403

    def test_get_org_by_id_returns_403_wrong_tenant(self, acl_node):
        """GET /artifacts/{id} returns 403 for org artifact from wrong tenant."""
        client = TestClient(acl_node.create_app())
        org_id = next(a.id for a in acl_node.list() if a.visibility == "org")
        resp = client.get(f"/kcp/v1/artifacts/{org_id}", headers={
            "X-KCP-Tenant": "other-org",
        })
        assert resp.status_code == 403

    def test_anonymous_sees_only_public(self, acl_node):
        """With no headers, only public artifacts are returned."""
        # Override node identity to be 'anonymous' (no matching tenant/user)
        from kcp.node import KCPNode
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            viewer = KCPNode(
                user_id="anon@external.com",
                tenant_id="external",
                db_path=os.path.join(tmp, "v.db"),
                keys_dir=os.path.join(tmp, "k"),
            )
        # Use acl_node app but send external headers
        client = TestClient(acl_node.create_app())
        resp = client.get("/kcp/v1/artifacts", headers={
            "X-KCP-User-ID": "anon@external.com",
            "X-KCP-Tenant": "external",
        })
        titles = [a["title"] for a in resp.json()["artifacts"]]
        assert "Public Doc" in titles
        assert "Org Doc" not in titles
        assert "Private Doc" not in titles

    def test_sync_list_excludes_private(self, acl_node):
        """Sync endpoints should never expose private artifacts."""
        client = TestClient(acl_node.create_app())
        resp = client.get(
            "/kcp/v1/sync/list",
            headers={"X-KCP-Client": "kcp-test/1.0"},
        )
        ids = resp.json()["ids"]
        # Private artifact should not be in sync list
        private_ids = [a.id for a in acl_node.list() if a.visibility == "private"]
        for pid in private_ids:
            assert pid not in ids


# ─── Peer Discovery ──────────────────────────────────────────


class TestPeerDiscovery:
    """Tests for /kcp/v1/peers, /kcp/v1/peers/announce, and discover_peers()."""

    def test_list_peers_empty(self, client):
        """GET /kcp/v1/peers returns empty list when no peers known."""
        resp = client.get("/kcp/v1/peers")
        assert resp.status_code == 200
        data = resp.json()
        assert "peers" in data
        assert "total" in data
        assert "node_id" in data

    def test_register_peer_via_post(self, client, tmp_node):
        """POST /kcp/v1/peers registers a peer."""
        resp = client.post("/kcp/v1/peers", json={
            "url": "https://peer04.kcp-protocol.org",
            "name": "Test Peer",
        })
        assert resp.status_code == 200
        assert "peer_id" in resp.json()

    def test_registered_peer_appears_in_list(self, client, tmp_node):
        """Peer registered via POST appears in GET /kcp/v1/peers."""
        client.post("/kcp/v1/peers", json={
            "url": "https://peer05.kcp-protocol.org",
            "name": "Peer 05",
        })
        resp = client.get("/kcp/v1/peers")
        urls = [p["url"] for p in resp.json()["peers"]]
        assert "https://peer05.kcp-protocol.org" in urls

    def test_peers_list_includes_node_id(self, client, tmp_node):
        """GET /kcp/v1/peers includes this node's node_id."""
        resp = client.get("/kcp/v1/peers")
        assert resp.json()["node_id"] == tmp_node.node_id

    def test_announce_peer_endpoint(self, client, tmp_node):
        """POST /kcp/v1/peers/announce registers announcing peer."""
        resp = client.post("/kcp/v1/peers/announce", json={
            "url": "https://peer07.kcp-protocol.org",
            "node_id": "test-node-007",
            "name": "Peer 07",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["accepted"] is True
        assert body["node_id"] == tmp_node.node_id

    def test_announced_peer_appears_in_list(self, client, tmp_node):
        """Announced peer appears in /kcp/v1/peers."""
        client.post("/kcp/v1/peers/announce", json={
            "url": "https://announced.example.com",
            "node_id": "abc-123",
        })
        resp = client.get("/kcp/v1/peers")
        urls = [p["url"] for p in resp.json()["peers"]]
        assert "https://announced.example.com" in urls

    def test_announce_without_url_returns_400(self, client):
        """POST /kcp/v1/peers/announce without url returns 400."""
        resp = client.post("/kcp/v1/peers/announce", json={"name": "no-url"})
        assert resp.status_code == 400

    def test_upsert_peer_updates_existing(self, tmp_node):
        """upsert_peer updates name/last_seen for existing URL."""
        tmp_node.store.upsert_peer("https://p.example.com", name="Old Name")
        tmp_node.store.upsert_peer("https://p.example.com", name="New Name")
        peers = tmp_node.store.get_peers()
        matching = [p for p in peers if p["url"] == "https://p.example.com"]
        assert len(matching) == 1
        assert matching[0]["name"] == "New Name"

    def test_update_peer_seen_by_url(self, tmp_node):
        """update_peer_seen_by_url updates last_seen."""
        tmp_node.store.upsert_peer("https://timed.example.com", name="T")
        tmp_node.store.update_peer_seen_by_url("https://timed.example.com")
        peers = tmp_node.store.get_peers()
        p = next(x for x in peers if x["url"] == "https://timed.example.com")
        assert p["last_seen"] is not None

    def test_discover_peers_network_unavailable(self, tmp_node):
        """discover_peers gracefully handles network errors."""
        result = tmp_node.discover_peers(
            bootstrap_url="https://invalid.kcp-protocol.example",
            gossip=False,
        )
        # Should return summary dict without raising
        assert "discovered" in result
        assert "bootstrap" in result
        assert "gossip" in result

    def test_gossip_from_peer_with_known_peers(self, tmp_path):
        """Gossip: node A learns peer C by querying peer B's /kcp/v1/peers."""
        import os
        # Node A — the discoverer
        node_a = KCPNode(
            user_id="a@test.com",
            db_path=str(tmp_path / "a.db"),
            keys_dir=str(tmp_path / "ka"),
        )
        # Node B — has peer C registered
        node_b = KCPNode(
            user_id="b@test.com",
            db_path=str(tmp_path / "b.db"),
            keys_dir=str(tmp_path / "kb"),
        )
        node_b.store.upsert_peer("https://peer-c.example.com", name="Peer C")

        # Register node B in node A's store
        node_a.store.upsert_peer("http://testserver", name="Node B")

        # Serve node B and let node A gossip
        app_b = node_b.create_app()
        client_b = TestClient(app_b)

        # Simulate gossip: node A calls node B's /kcp/v1/peers
        resp = client_b.get("/kcp/v1/peers")
        assert resp.status_code == 200
        peers_from_b = resp.json()["peers"]
        urls_from_b = [p["url"] for p in peers_from_b]
        assert "https://peer-c.example.com" in urls_from_b

    def test_peers_list_self_entry_when_env_set(self, tmp_path, monkeypatch):
        """When KCP_SELF_URL is set, GET /kcp/v1/peers includes self."""
        monkeypatch.setenv("KCP_SELF_URL", "https://self.example.com")
        node = KCPNode(
            user_id="me@test.com",
            db_path=str(tmp_path / "s.db"),
            keys_dir=str(tmp_path / "ks"),
        )
        client = TestClient(node.create_app())
        resp = client.get("/kcp/v1/peers")
        urls = [p["url"] for p in resp.json()["peers"]]
        assert "https://self.example.com" in urls


# ─── Replication ─────────────────────────────────────────────────

class TestReplication:
    """Tests for multi-peer replication factor tracking."""

    def test_replication_status_empty(self, tmp_node):
        """New artifact has count=0 and empty replicated_to list."""
        art = tmp_node.publish(title="Rep test", content="hello", format="text")
        status = tmp_node.store.get_replication_status(art.id)
        assert status["artifact_id"] == art.id
        assert status["count"] == 0
        assert status["replicated_to"] == []

    def test_record_replication_manual(self, tmp_node):
        """record_replication() upserts a peer entry."""
        art = tmp_node.publish(title="Manual", content="data", format="text")
        tmp_node.store.record_replication(art.id, "https://peer-a.example.com")
        status = tmp_node.store.get_replication_status(art.id)
        assert status["count"] == 1
        assert "https://peer-a.example.com" in status["replicated_to"]

    def test_ack_sync_auto_records_replication(self, tmp_node):
        """ack_sync() automatically records replication from queue row."""
        art = tmp_node.publish(title="Auto", content="data", format="text")
        tmp_node.store.enqueue_sync(art.id, ["https://peer-b.example.com"])
        # Dequeue to get ID
        items = tmp_node.store.dequeue_pending_sync(batch_size=10)
        assert len(items) == 1
        queue_id = items[0]["id"]
        tmp_node.store.ack_sync(queue_id)
        status = tmp_node.store.get_replication_status(art.id)
        assert status["count"] == 1
        assert "https://peer-b.example.com" in status["replicated_to"]

    def test_replication_idempotent(self, tmp_node):
        """Double-ACK for the same peer keeps count=1."""
        art = tmp_node.publish(title="Idem", content="data", format="text")
        tmp_node.store.record_replication(art.id, "https://peer-c.example.com")
        tmp_node.store.record_replication(art.id, "https://peer-c.example.com")
        status = tmp_node.store.get_replication_status(art.id)
        assert status["count"] == 1

    def test_replication_multiple_peers(self, tmp_node):
        """Multiple peers ACKing increments count correctly."""
        art = tmp_node.publish(title="Multi", content="data", format="text")
        tmp_node.store.record_replication(art.id, "https://peer-1.example.com")
        tmp_node.store.record_replication(art.id, "https://peer-2.example.com")
        tmp_node.store.record_replication(art.id, "https://peer-3.example.com")
        status = tmp_node.store.get_replication_status(art.id)
        assert status["count"] == 3
        assert len(status["replicated_to"]) == 3

    def test_replication_endpoint_returns_factor(self, client_with_artifact):
        """GET /kcp/v1/artifacts/{id}/replication returns replication_factor."""
        client, artifact, node = client_with_artifact
        resp = client.get(f"/kcp/v1/artifacts/{artifact.id}/replication")
        assert resp.status_code == 200
        data = resp.json()
        assert "replication_factor" in data
        assert "complete" in data
        assert data["artifact_id"] == artifact.id

    def test_replication_endpoint_not_found(self, client):
        """GET /kcp/v1/artifacts/nonexistent/replication returns 404."""
        resp = client.get("/kcp/v1/artifacts/nonexistent-id/replication")
        assert resp.status_code == 404

    def test_set_replication_factor(self, tmp_node):
        """set_replication_factor() persists the value in kcp_config."""
        tmp_node.set_replication_factor(3)
        val = tmp_node.store.get_config("replication_factor")
        assert val == "3"

    def test_complete_flag_false_when_insufficient(self, client_with_artifact):
        """complete=False when count < replication_factor."""
        client, artifact, node = client_with_artifact
        node.set_replication_factor(5)
        node.store.record_replication(artifact.id, "https://only-one.example.com")
        resp = client.get(f"/kcp/v1/artifacts/{artifact.id}/replication")
        data = resp.json()
        assert data["count"] == 1
        assert data["replication_factor"] == 5
        assert data["complete"] is False

    def test_complete_flag_true_when_met(self, client_with_artifact):
        """complete=True when count >= replication_factor."""
        client, artifact, node = client_with_artifact
        node.set_replication_factor(2)
        node.store.record_replication(artifact.id, "https://peer-x.example.com")
        node.store.record_replication(artifact.id, "https://peer-y.example.com")
        resp = client.get(f"/kcp/v1/artifacts/{artifact.id}/replication")
        data = resp.json()
        assert data["count"] == 2
        assert data["complete"] is True

    def test_replication_summary(self, tmp_node):
        """get_replication_summary() returns dict of artifact_id → peer count."""
        a1 = tmp_node.publish(title="A1", content="x", format="text")
        a2 = tmp_node.publish(title="A2", content="y", format="text")
        tmp_node.store.record_replication(a1.id, "https://p1.example.com")
        tmp_node.store.record_replication(a1.id, "https://p2.example.com")
        tmp_node.store.record_replication(a2.id, "https://p1.example.com")
        summary = tmp_node.store.get_replication_summary()
        assert summary[a1.id] == 2
        assert summary[a2.id] == 1


# ─── Signature Verification ───────────────────────────────────


class TestVerifySignature:
    def test_verify_endpoint_returns_200(self, client_with_artifact):
        """GET /kcp/v1/artifacts/{id}/verify is exposed."""
        client, artifact, _ = client_with_artifact
        resp = client.get(f"/kcp/v1/artifacts/{artifact.id}/verify")
        assert resp.status_code == 200

    def test_verify_self_published_is_valid(self, client_with_artifact):
        """Artifact signed by this node verifies against its own identity key."""
        client, artifact, node = client_with_artifact
        data = client.get(f"/kcp/v1/artifacts/{artifact.id}/verify").json()
        assert data["artifact_id"] == artifact.id
        assert data["status"] == "valid"
        assert data["signer"] == node.node_id
        assert data["key_fingerprint"]
        assert data["candidates"] >= 1

    def test_verify_unsigned_artifact(self, client_with_artifact):
        """An artifact with no signature reports 'unsigned'."""
        client, artifact, node = client_with_artifact
        node.store._conn.execute("UPDATE kcp_artifacts SET signature = '' WHERE id = ?", (artifact.id,))
        node.store._conn.commit()
        data = client.get(f"/kcp/v1/artifacts/{artifact.id}/verify").json()
        assert data["status"] == "unsigned"
        assert data["signer"] is None

    def test_verify_malformed_signature_is_invalid(self, client_with_artifact):
        """A signature that is not a 64-byte hex blob reports 'invalid'."""
        client, artifact, node = client_with_artifact
        node.store._conn.execute("UPDATE kcp_artifacts SET signature = ? WHERE id = ?", ("not-a-signature", artifact.id))
        node.store._conn.commit()
        data = client.get(f"/kcp/v1/artifacts/{artifact.id}/verify").json()
        assert data["status"] == "invalid"
        assert data["signer"] is None

    def test_verify_tampered_payload_is_invalid(self, client_with_artifact):
        """Payload modified after signing (same user) reports 'invalid'."""
        client, artifact, node = client_with_artifact
        node.store._conn.execute("UPDATE kcp_artifacts SET title = ? WHERE id = ?", ("Tampered title", artifact.id))
        node.store._conn.commit()
        data = client.get(f"/kcp/v1/artifacts/{artifact.id}/verify").json()
        assert data["status"] == "invalid"

    def test_verify_unknown_key_for_foreign_artifact(self, tmp_path):
        """Artifact from a node whose key we do not know reports 'unknown_key'."""
        node_a = KCPNode(
            user_id="alice@example.com",
            tenant_id="org-a",
            db_path=str(tmp_path / "a.db"),
            keys_dir=str(tmp_path / "keys_a"),
        )
        node_b = KCPNode(
            user_id="bob@example.com",
            tenant_id="org-b",
            db_path=str(tmp_path / "b.db"),
            keys_dir=str(tmp_path / "keys_b"),
        )
        artifact = node_a.publish("Peer Artifact", content="signed elsewhere", format="text")
        assert node_b.store.import_artifact(artifact.to_dict())

        client = TestClient(node_b.create_app())
        data = client.get(f"/kcp/v1/artifacts/{artifact.id}/verify").json()
        assert data["status"] == "unknown_key"
        assert data["signer"] is None

    def test_verify_peer_public_key_makes_it_valid(self, tmp_path):
        """Once the signer's public key is known as a peer, the artifact verifies."""
        node_a = KCPNode(
            user_id="alice@example.com",
            tenant_id="org-a",
            db_path=str(tmp_path / "a.db"),
            keys_dir=str(tmp_path / "keys_a"),
        )
        node_b = KCPNode(
            user_id="bob@example.com",
            tenant_id="org-b",
            db_path=str(tmp_path / "b.db"),
            keys_dir=str(tmp_path / "keys_b"),
        )
        artifact = node_a.publish("Peer Artifact", content="signed elsewhere", format="text")
        node_b.store.add_peer("node-a", "https://a.example.com", "A", public_key=node_a.public_key.hex())
        assert node_b.store.import_artifact(artifact.to_dict())

        client = TestClient(node_b.create_app())
        data = client.get(f"/kcp/v1/artifacts/{artifact.id}/verify").json()
        assert data["status"] == "valid"
        assert data["signer"] == "node-a"
        assert data["candidates"] == 2  # own identity key + the peer key

    def test_verify_ignores_garbage_peer_key(self, tmp_path):
        """A malformed peer public_key is skipped, not used to verify."""
        tmp_node = KCPNode(
            user_id="test@example.com",
            tenant_id="test-org",
            db_path=str(tmp_path / "n.db"),
            keys_dir=str(tmp_path / "keys"),
        )
        tmp_node.store.add_peer("bad-peer", "https://bad.example.com", "Bad", public_key="zzzz")
        artifact = tmp_node.publish("Solo", content="x", format="text")
        client = TestClient(tmp_node.create_app())
        data = client.get(f"/kcp/v1/artifacts/{artifact.id}/verify").json()
        assert data["status"] == "valid"
        assert data["candidates"] == 1

    def test_verify_not_found_returns_404(self, client):
        """Unknown artifact id returns 404, like the neighbouring routes."""
        resp = client.get("/kcp/v1/artifacts/does-not-exist/verify")
        assert resp.status_code == 404
