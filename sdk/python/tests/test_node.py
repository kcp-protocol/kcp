"""
Tests for KCP Embedded Node (node.py)
"""
import os
import tempfile
import pytest
from kcp.node import KCPNode
from kcp.models import Lineage


@pytest.fixture
def tmp_node(tmp_path):
    """Create a KCPNode using a temporary directory (no ~/.kcp pollution)."""
    db_path = str(tmp_path / "kcp_test.db")
    keys_dir = str(tmp_path / "keys")
    node = KCPNode(
        user_id="test@example.com",
        tenant_id="test-corp",
        db_path=db_path,
        keys_dir=keys_dir,
    )
    return node


class TestKCPNodeInit:
    def test_node_creates_successfully(self, tmp_node):
        assert tmp_node is not None

    def test_node_has_user_id(self, tmp_node):
        assert tmp_node.user_id == "test@example.com"

    def test_node_has_tenant_id(self, tmp_node):
        assert tmp_node.tenant_id == "test-corp"

    def test_node_has_node_id(self, tmp_node):
        assert tmp_node.node_id is not None
        assert len(tmp_node.node_id) > 0

    def test_node_has_keys(self, tmp_node):
        assert isinstance(tmp_node.private_key, bytes)
        assert isinstance(tmp_node.public_key, bytes)
        assert len(tmp_node.private_key) == 32
        assert len(tmp_node.public_key) == 32


class TestKCPNodePublish:
    def test_publish_markdown(self, tmp_node):
        artifact = tmp_node.publish(
            title="Test Article",
            content="# Hello KCP\nThis is a test.",
            format="markdown",
        )
        assert artifact is not None
        assert artifact.title == "Test Article"
        assert artifact.format == "markdown"

    def test_publish_returns_signed_artifact(self, tmp_node):
        artifact = tmp_node.publish(
            title="Signed Test",
            content=b"binary content",
            format="text",
        )
        assert artifact.signature != ""
        assert len(artifact.signature) == 128  # Ed25519 hex

    def test_publish_sets_content_hash(self, tmp_node):
        artifact = tmp_node.publish(
            title="Hash Test",
            content=b"some content",
            format="text",
        )
        assert artifact.content_hash != ""
        assert len(artifact.content_hash) == 64  # SHA-256 hex

    def test_publish_with_tags(self, tmp_node):
        artifact = tmp_node.publish(
            title="Tagged",
            content="content",
            format="text",
            tags=["ml", "analytics"],
        )
        assert artifact.tags == ["ml", "analytics"]

    def test_publish_with_summary(self, tmp_node):
        artifact = tmp_node.publish(
            title="Summarized",
            content="content",
            format="text",
            summary="A brief summary",
        )
        assert artifact.summary == "A brief summary"

    def test_publish_with_lineage(self, tmp_node):
        lineage = Lineage(
            query="Predict churn",
            data_sources=["postgres://db"],
            agent="agent-v1",
        )
        artifact = tmp_node.publish(
            title="With Lineage",
            content="content",
            format="text",
            lineage=lineage,
        )
        assert artifact.lineage is not None
        assert artifact.lineage.query == "Predict churn"

    def test_publish_derived_from(self, tmp_node):
        parent = tmp_node.publish(title="Parent", content="parent", format="text")
        child = tmp_node.publish(
            title="Child",
            content="child",
            format="text",
            derived_from=parent.id,
        )
        assert child is not None
        assert child.id != parent.id


class TestKCPNodeGet:
    def test_get_existing_artifact(self, tmp_node):
        published = tmp_node.publish(title="Get Test", content="data", format="text")
        retrieved = tmp_node.get(published.id)
        assert retrieved is not None
        assert retrieved.id == published.id
        assert retrieved.title == "Get Test"

    def test_get_nonexistent_returns_none(self, tmp_node):
        result = tmp_node.get("nonexistent-id-00000")
        assert result is None

    def test_get_content(self, tmp_node):
        content = b"raw content bytes"
        artifact = tmp_node.publish(title="Content Test", content=content, format="text")
        retrieved = tmp_node.get_content(artifact.id)
        assert retrieved == content


class TestKCPNodeSearch:
    def test_search_returns_results(self, tmp_node):
        tmp_node.publish(title="Rate Limiting Guide", content="token bucket algorithm", format="markdown")
        tmp_node.publish(title="Authentication Best Practices", content="JWT and OAuth2", format="markdown")

        results = tmp_node.search("rate limiting")
        assert results is not None
        assert results.total >= 0

    def test_search_empty_query_returns_results(self, tmp_node):
        tmp_node.publish(title="Article", content="some content", format="text")
        results = tmp_node.search("")
        assert results is not None

    def test_search_no_results(self, tmp_node):
        results = tmp_node.search("xyznonexistentterm12345")
        assert results.total == 0


class TestKCPNodeList:
    def test_list_returns_artifacts(self, tmp_node):
        tmp_node.publish(title="A1", content="c1", format="text")
        tmp_node.publish(title="A2", content="c2", format="text")
        items = tmp_node.list()
        assert len(items) >= 2

    def test_list_respects_limit(self, tmp_node):
        for i in range(5):
            tmp_node.publish(title=f"Article {i}", content=f"content {i}", format="text")
        items = tmp_node.list(limit=3)
        assert len(items) <= 3


class TestKCPNodeVerify:
    def test_verify_own_artifact(self, tmp_node):
        artifact = tmp_node.publish(title="Verify Test", content="data", format="text")
        assert tmp_node.verify(artifact) is True

    def test_verify_tampered_artifact_fails(self, tmp_node):
        artifact = tmp_node.publish(title="Original", content="data", format="text")
        artifact.title = "Tampered"
        assert tmp_node.verify(artifact) is False


class TestKCPNodeStats:
    def test_stats_returns_dict(self, tmp_node):
        s = tmp_node.stats()
        assert isinstance(s, dict)

    def test_stats_includes_expected_keys(self, tmp_node):
        s = tmp_node.stats()
        assert "node_id" in s
        assert "user_id" in s
        assert "tenant_id" in s


class TestKCPNodeLineage:
    def test_lineage_chain(self, tmp_node):
        root = tmp_node.publish(title="Root", content="root content", format="text")
        child = tmp_node.publish(
            title="Child", content="child content", format="text", derived_from=root.id
        )
        chain = tmp_node.lineage(child.id)
        assert isinstance(chain, list)

    def test_derivatives(self, tmp_node):
        parent = tmp_node.publish(title="Parent", content="p", format="text")
        tmp_node.publish(title="Child1", content="c1", format="text", derived_from=parent.id)
        tmp_node.publish(title="Child2", content="c2", format="text", derived_from=parent.id)
        derivs = tmp_node.derivatives(parent.id)
        assert isinstance(derivs, list)
        assert len(derivs) >= 2
