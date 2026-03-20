"""
Tests for KCP Data Models (models.py)
"""
import json
import pytest
from uuid import UUID
from kcp.models import KnowledgeArtifact, Lineage, ACL, SearchResult, SearchResponse


class TestLineage:
    def test_create_minimal(self):
        l = Lineage(query="test query")
        assert l.query == "test query"
        assert l.data_sources == []
        assert l.agent == ""
        assert l.parent_reports == []

    def test_create_full(self):
        l = Lineage(
            query="predict churn",
            data_sources=["postgres://db/customers"],
            agent="jupyter-agent-v1",
            parent_reports=["report-id-001"],
        )
        assert l.data_sources == ["postgres://db/customers"]
        assert l.agent == "jupyter-agent-v1"

    def test_to_dict(self):
        l = Lineage(query="test", data_sources=["src1"], agent="bot")
        d = l.to_dict()
        assert d["query"] == "test"
        assert d["data_sources"] == ["src1"]
        assert d["agent"] == "bot"
        assert "parent_reports" in d


class TestACL:
    def test_create_empty(self):
        acl = ACL()
        assert acl.allowed_tenants == []
        assert acl.allowed_users == []
        assert acl.allowed_teams == []

    def test_create_with_values(self):
        acl = ACL(
            allowed_tenants=["acme-corp"],
            allowed_users=["alice@example.com"],
            allowed_teams=["data-science"],
        )
        assert "acme-corp" in acl.allowed_tenants

    def test_to_dict(self):
        acl = ACL(allowed_users=["bob@example.com"])
        d = acl.to_dict()
        assert "bob@example.com" in d["allowed_users"]
        assert "allowed_tenants" in d
        assert "allowed_teams" in d


class TestKnowledgeArtifact:
    def test_create_minimal(self):
        a = KnowledgeArtifact(
            title="Test Report",
            user_id="alice@example.com",
            tenant_id="acme-corp",
            format="markdown",
        )
        assert a.title == "Test Report"
        assert a.user_id == "alice@example.com"
        assert a.tenant_id == "acme-corp"
        assert a.format == "markdown"
        assert a.visibility == "private"

    def test_auto_generated_id(self):
        a = KnowledgeArtifact(
            title="T", user_id="u", tenant_id="t", format="text"
        )
        # Must be a valid UUID
        UUID(a.id)

    def test_two_artifacts_have_different_ids(self):
        a1 = KnowledgeArtifact(title="T1", user_id="u", tenant_id="t", format="text")
        a2 = KnowledgeArtifact(title="T2", user_id="u", tenant_id="t", format="text")
        assert a1.id != a2.id

    def test_to_dict_required_fields(self):
        a = KnowledgeArtifact(
            title="Analysis", user_id="alice", tenant_id="corp", format="html"
        )
        d = a.to_dict()
        for key in ["id", "version", "user_id", "tenant_id", "timestamp", "format", "visibility", "title"]:
            assert key in d

    def test_to_dict_optional_fields_excluded_when_empty(self):
        a = KnowledgeArtifact(
            title="T", user_id="u", tenant_id="t", format="text"
        )
        d = a.to_dict()
        assert "team" not in d
        assert "tags" not in d
        assert "lineage" not in d

    def test_to_dict_includes_optional_when_set(self):
        a = KnowledgeArtifact(
            title="T", user_id="u", tenant_id="t", format="text",
            team="data-science",
            tags=["ml", "churn"],
            summary="Brief",
        )
        d = a.to_dict()
        assert d["team"] == "data-science"
        assert d["tags"] == ["ml", "churn"]
        assert d["summary"] == "Brief"

    def test_to_canonical_json_excludes_signature(self):
        a = KnowledgeArtifact(
            title="T", user_id="u", tenant_id="t", format="text",
            signature="some-sig"
        )
        canonical = a.to_canonical_json()
        parsed = json.loads(canonical)
        assert "signature" not in parsed

    def test_to_canonical_json_sorted_keys(self):
        a = KnowledgeArtifact(
            title="T", user_id="u", tenant_id="t", format="text"
        )
        canonical = a.to_canonical_json()
        parsed = json.loads(canonical)
        keys = list(parsed.keys())
        assert keys == sorted(keys)

    def test_from_dict_roundtrip(self):
        a = KnowledgeArtifact(
            title="Roundtrip Test",
            user_id="bob@example.com",
            tenant_id="corp",
            format="json",
            tags=["test"],
            summary="Testing roundtrip",
        )
        d = a.to_dict()
        b = KnowledgeArtifact.from_dict(d)
        assert b.id == a.id
        assert b.title == a.title
        assert b.user_id == a.user_id
        assert b.tags == a.tags

    def test_from_dict_with_lineage(self):
        data = {
            "id": "abc-123",
            "version": "1",
            "user_id": "alice",
            "tenant_id": "corp",
            "timestamp": "2026-03-20T00:00:00Z",
            "format": "markdown",
            "title": "Report",
            "lineage": {
                "query": "test query",
                "data_sources": ["db://test"],
                "agent": "agent-v1",
                "parent_reports": [],
            },
        }
        a = KnowledgeArtifact.from_dict(data)
        assert a.lineage is not None
        assert a.lineage.query == "test query"

    def test_from_dict_with_acl(self):
        data = {
            "id": "abc-456",
            "version": "1",
            "user_id": "alice",
            "tenant_id": "corp",
            "timestamp": "2026-03-20T00:00:00Z",
            "format": "html",
            "title": "Report",
            "acl": {
                "allowed_tenants": ["acme"],
                "allowed_users": [],
                "allowed_teams": ["eng"],
            },
        }
        a = KnowledgeArtifact.from_dict(data)
        assert a.acl is not None
        assert "acme" in a.acl.allowed_tenants


class TestSearchResult:
    def test_from_dict(self):
        data = {
            "id": "r-001",
            "title": "Q1 Analysis",
            "summary": "Summary here",
            "created_at": "2026-01-01T00:00:00Z",
            "relevance": 0.95,
            "format": "html",
            "preview": "First lines...",
        }
        r = SearchResult.from_dict(data)
        assert r.id == "r-001"
        assert r.relevance == 0.95
        assert r.format == "html"


class TestSearchResponse:
    def test_from_dict(self):
        data = {
            "results": [
                {
                    "id": "r-001",
                    "title": "Test",
                    "summary": "",
                    "created_at": "2026-01-01T00:00:00Z",
                    "relevance": 0.8,
                    "format": "markdown",
                }
            ],
            "total": 1,
            "query_time_ms": 5,
        }
        resp = SearchResponse.from_dict(data)
        assert resp.total == 1
        assert resp.query_time_ms == 5
        assert len(resp.results) == 1
        assert resp.results[0].title == "Test"
