"""
Tests for knowledge expiry (TTL) + artifact versioning — KCP issue #4.

Covers:
  * schema migration (idempotent, legacy databases)
  * ``expires_at`` / ``status`` lifecycle and lazily-persisted expiry
  * ``canonical_id`` version families
  * node.publish_version / node.get_current
  * default search/list filtering of superseded + expired artifacts
  * CLI surface (--ttl / --expires-at / --include-* / versions)
"""

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import pytest

from kcp.models import (
    KnowledgeArtifact,
    SearchResult,
    is_expired,
    normalize_expires_at,
)
from kcp.node import KCPNode
from kcp.store import LocalStore


# ─── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path):
    return LocalStore(str(tmp_path / "kcp.db"))


@pytest.fixture
def node(tmp_path):
    return KCPNode(
        user_id="ttl@example.com",
        tenant_id="ttl-corp",
        db_path=str(tmp_path / "kcp.db"),
        keys_dir=str(tmp_path / "keys"),
    )


def _past(seconds: int = 60) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def _future(seconds: int = 3600) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


# ─── Schema / migration ────────────────────────────────────────

LEGACY_SCHEMA = """
CREATE TABLE kcp_artifacts (
    id TEXT PRIMARY KEY,
    version TEXT NOT NULL DEFAULT '1',
    user_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    team TEXT,
    tags TEXT,
    source TEXT,
    created_at TEXT NOT NULL,
    format TEXT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'private',
    title TEXT NOT NULL,
    summary TEXT,
    lineage TEXT,
    content_hash TEXT NOT NULL,
    content_url TEXT,
    signature TEXT,
    acl TEXT,
    derived_from TEXT,
    deleted_at TEXT
);
CREATE TABLE kcp_content (
    content_hash TEXT PRIMARY KEY,
    content BLOB NOT NULL,
    size_bytes INTEGER NOT NULL
);
"""


class TestSchemaMigration:
    def test_fresh_db_has_ttl_columns(self, store):
        cols = {r["name"] for r in store._get_conn().execute("PRAGMA table_info(kcp_artifacts)")}
        assert {"canonical_id", "expires_at", "status", "superseded_by"} <= cols

    def test_legacy_db_gets_columns_added(self, tmp_path):
        db_path = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript(LEGACY_SCHEMA)
        conn.execute(
            "INSERT INTO kcp_artifacts (id, version, user_id, tenant_id, created_at,"
            " format, title, content_hash, signature, tags) "
            "VALUES ('legacy-1', '1', 'old@example.com', 'old-corp', ?, 'text',"
            " 'Legacy Artifact', 'deadbeef', 'sig', '[]')",
            (_future(-3600),),
        )
        conn.commit()
        conn.close()

        # Old row must survive the migration untouched.
        store = LocalStore(str(db_path))
        cols = {r["name"] for r in store._get_conn().execute("PRAGMA table_info(kcp_artifacts)")}
        assert {"canonical_id", "expires_at", "status", "superseded_by"} <= cols

        artifact = store.get("legacy-1")
        assert artifact is not None
        assert artifact.title == "Legacy Artifact"
        assert artifact.status == "active"      # default applied by ADD COLUMN
        assert artifact.expires_at is None      # legacy knowledge never expires
        assert artifact.canonical_id == ""      # resolved lazily as COALESCE(canonical_id, id)
        assert store.resolve_canonical_id("legacy-1") == "legacy-1"

    def test_migration_is_idempotent(self, tmp_path):
        db_path = tmp_path / "kcp.db"
        LocalStore(str(db_path))
        # Second + third init must not raise (no duplicate column errors)
        LocalStore(str(db_path))
        store = LocalStore(str(db_path))
        assert store.stats()["artifacts"] == 0


# ─── TTL / status semantics ────────────────────────────────────


class TestExpiry:
    def test_normalize_expires_at_z_suffix(self):
        assert normalize_expires_at("2026-12-31T23:59:59Z") == "2026-12-31T23:59:59+00:00"

    def test_normalize_expires_at_naive_is_utc(self):
        assert normalize_expires_at("2026-12-31T23:59:59") == "2026-12-31T23:59:59+00:00"

    def test_normalize_expires_at_none_and_empty(self):
        assert normalize_expires_at(None) is None
        assert normalize_expires_at("") is None

    def test_normalize_expires_at_invalid_raises(self):
        with pytest.raises(ValueError):
            normalize_expires_at("not-a-date")

    def test_is_expired(self):
        assert is_expired(_past()) is True
        assert is_expired(_future()) is False
        assert is_expired(None) is False

    def test_publish_with_ttl_sets_expires_at(self, node):
        artifact = node.publish("TTL doc", content="body", ttl_seconds=3600)
        assert artifact.expires_at is not None
        assert not is_expired(artifact.expires_at)
        assert artifact.status == "active"

    def test_publish_with_explicit_expires_at_is_normalized(self, node):
        artifact = node.publish("Deadline doc", content="body", expires_at="2099-01-01T00:00:00Z")
        assert artifact.expires_at == "2099-01-01T00:00:00+00:00"

    def test_expires_at_wins_over_ttl(self, node):
        artifact = node.publish(
            "Both", content="x", ttl_seconds=1, expires_at="2099-01-01T00:00:00+00:00"
        )
        assert artifact.expires_at == "2099-01-01T00:00:00+00:00"

    def test_publish_with_past_deadline_is_born_expired(self, node):
        artifact = node.publish("Stale", content="x", expires_at=_past())
        assert artifact.status == "expired"
        assert node.store.get(artifact.id).status == "expired"

    def test_expired_artifact_is_not_searchable_by_default(self, node):
        node.publish("Ephemeral secrets guide", content="ephemeral knowledge", expires_at=_past())
        node.publish("Durable guide", content="durable knowledge")

        default = node.search("knowledge")
        assert all("Ephemeral" not in r.title for r in default.results)

        widened = node.search("knowledge", include_expired=True)
        assert any("Ephemeral" in r.title for r in widened.results)

    def test_expiry_transition_is_persisted_on_read(self, node):
        artifact = node.publish("Aging doc", content="aging knowledge")
        # Deadline passes after publish → next read sweeps active → expired
        node.store._get_conn().execute(
            "UPDATE kcp_artifacts SET expires_at = ? WHERE id = ?",
            (_past(), artifact.id),
        )
        node.store._get_conn().commit()

        assert node.search("aging").total == 0
        assert node.store.get(artifact.id).status == "expired"

    def test_expired_excluded_from_list_by_default(self, node):
        node.publish("Old snapshot", content="a", expires_at=_past())
        node.publish("Fresh snapshot", content="b")
        assert len(node.list()) == 1
        assert len(node.list(include_expired=True)) == 2

    def test_expire_artifact_forces_status(self, store):
        artifact = KnowledgeArtifact(
            title="Force", user_id="u", tenant_id="t", format="text", content_hash="h"
        )
        store.publish(artifact)
        assert store.expire_artifact(artifact.id) is True
        assert store.get(artifact.id).status == "expired"


# ─── Versioning ────────────────────────────────────────────────


class TestVersioning:
    def test_standalone_publish_sets_canonical_id_to_own_id(self, node):
        artifact = node.publish("Standalone", content="x")
        assert artifact.canonical_id == artifact.id
        assert artifact.version == "1"
        assert artifact.status == "active"

    def test_publish_version_creates_new_id_same_canonical(self, node):
        v1 = node.publish("Rate Limiting", content="v1 content", tags=["rate"])
        v2 = node.publish_version(v1.id, content="v2 content")

        assert v2.id != v1.id
        assert v2.canonical_id == v1.id
        assert v2.version == "2"
        assert v2.status == "active"
        # Previous version is superseded
        assert node.get(v1.id).status == "superseded"
        assert node.get(v1.id).superseded_by == v2.id

    def test_publish_version_inherits_metadata_and_content_when_omitted(self, node):
        v1 = node.publish(
            "Inherited", content="original body", tags=["a", "b"], summary="sum",
            format="markdown", source="agent-x",
        )
        v2 = node.publish_version(v1.id)  # nothing overridden

        assert v2.title == v1.title
        assert v2.tags == ["a", "b"]
        assert v2.summary == "sum"
        assert v2.format == "markdown"
        assert v2.source == "agent-x"
        assert node.get_content(v2.id) == b"original body"
        assert v2.content_hash == v1.content_hash

    def test_publish_version_increments_from_latest(self, node):
        v1 = node.publish("Doc", content="1")
        v2 = node.publish_version(v1.id, content="2")
        v3 = node.publish_version(v2.id, content="3")
        v4 = node.publish_version(v1.id, content="4")  # any version → same family

        assert [v.version for v in (v1, v2, v3, v4)] == ["1", "2", "3", "4"]
        assert len({v.canonical_id for v in (v1, v2, v3, v4)}) == 1

    def test_publish_version_unknown_id_raises(self, node):
        with pytest.raises(ValueError):
            node.publish_version("does-not-exist", content="x")

    def test_get_current_returns_latest_active(self, node):
        v1 = node.publish("Current test", content="1")
        v2 = node.publish_version(v1.id, content="2")
        assert node.get_current(v1.id).id == v2.id
        assert node.get_current(v2.canonical_id).id == v2.id

    def test_get_current_returns_none_when_all_expired(self, node):
        v1 = node.publish("Expiring", content="1")
        node.publish_version(v1.id, content="2", expires_at=_past())
        assert node.get_current(v1.id) is None

    def test_get_current_still_active_after_expiry_of_older_version(self, node):
        v1 = node.publish("Mixed", content="1", expires_at=_past())
        v2 = node.publish_version(v1.id, content="2")
        current = node.get_current(v1.id)
        assert current is not None and current.id == v2.id
        assert node.get(v1.id).status == "superseded"  # superseded wins over expired

    def test_get_versions_orders_oldest_to_newest(self, node):
        v1 = node.publish("Ordered", content="1")
        v2 = node.publish_version(v1.id, content="2")
        versions = node.versions(v1.id)
        assert [v.version for v in versions] == ["1", "2"]
        assert [v.status for v in versions] == ["superseded", "active"]
        assert versions[-1].id == v2.id

    def test_versions_without_canonical_id_returns_self(self, node):
        artifact = node.publish("Solo", content="x")
        assert [v.id for v in node.versions(artifact.canonical_id)] == [artifact.id]

    def test_superseded_excluded_from_search_by_default(self, node):
        v1 = node.publish("Rate limiting strategies", content="token bucket")
        v2 = node.publish_version(v1.id, content="token bucket plus sliding window")

        default = node.search("token bucket")
        assert [r.id for r in default.results] == [v2.id]

        widened = node.search("token bucket", include_superseded=True)
        assert {r.id for r in widened.results} == {v1.id, v2.id}

    def test_search_result_exposes_status_and_canonical_id(self, node):
        v1 = node.publish("Status probe", content="probe content")
        node.publish_version(v1.id, content="probe content v2")
        result = node.search("probe").results[0]
        assert isinstance(result, SearchResult)
        assert result.status == "active"
        assert result.canonical_id == v1.id

    def test_superseded_artifact_signature_still_verifies(self, node):
        v1 = node.publish("Signed", content="original")
        node.publish_version(v1.id, content="new")
        stale = node.get(v1.id)
        assert stale.status == "superseded"
        assert node.verify(stale) is True

    def test_superseded_excluded_from_list_by_default(self, node):
        v1 = node.publish("Listed", content="1")
        node.publish_version(v1.id, content="2")
        assert len(node.list()) == 1
        assert len(node.list(include_superseded=True)) == 2

    def test_delete_then_versions(self, node):
        v1 = node.publish("Deleted", content="1")
        node.delete(v1.id)
        assert node.versions(v1.id) == []


# ─── Payload / model contract ──────────────────────────────────


class TestArtifactPayload:
    def test_to_dict_includes_ttl_and_canonical_id(self):
        artifact = KnowledgeArtifact(
            title="T", user_id="u", tenant_id="t", format="text",
            canonical_id="canon-1", expires_at="2027-01-01T00:00:00+00:00",
        )
        data = artifact.to_dict()
        assert data["canonical_id"] == "canon-1"
        assert data["expires_at"] == "2027-01-01T00:00:00+00:00"

    def test_to_dict_excludes_lifecycle_by_default(self):
        artifact = KnowledgeArtifact(
            title="T", user_id="u", tenant_id="t", format="text",
            status="superseded", superseded_by="new-id",
        )
        assert "status" not in artifact.to_dict()
        assert "superseded_by" not in artifact.to_dict()
        # …but they are available on demand (API responses)
        assert artifact.to_dict(include_lifecycle=True)["status"] == "superseded"

    def test_to_canonical_json_excludes_lifecycle(self):
        artifact = KnowledgeArtifact(
            title="T", user_id="u", tenant_id="t", format="text",
            status="expired", superseded_by="x",
        )
        parsed = json.loads(artifact.to_canonical_json())
        assert "status" not in parsed
        assert "superseded_by" not in parsed

    def test_legacy_payload_roundtrip_unchanged(self):
        """A v1 payload (no TTL/versioning fields) must serialize byte-identically."""
        legacy = {
            "id": "abc-123",
            "version": "1",
            "user_id": "alice",
            "tenant_id": "corp",
            "timestamp": "2026-03-20T00:00:00+00:00",
            "format": "markdown",
            "visibility": "public",
            "title": "Legacy",
            "content_hash": "a" * 64,
            "signature": "sig",
        }
        artifact = KnowledgeArtifact.from_dict(legacy)
        assert artifact.to_dict() == legacy

    def test_from_dict_reads_lifecycle_fields(self):
        data = {
            "id": "v2",
            "version": "2",
            "canonical_id": "v1",
            "expires_at": "2030-01-01T00:00:00+00:00",
            "status": "superseded",
            "superseded_by": "v3",
            "user_id": "u",
            "tenant_id": "t",
            "format": "text",
            "title": "T",
        }
        artifact = KnowledgeArtifact.from_dict(data)
        assert artifact.canonical_id == "v1"
        assert artifact.expires_at == "2030-01-01T00:00:00+00:00"
        assert artifact.status == "superseded"
        assert artifact.superseded_by == "v3"


# ─── Store-level API ───────────────────────────────────────────


class TestStoreVersioning:
    def test_next_version_empty_family(self, store):
        assert store.next_version("no-such-canonical") == 1

    def test_supersede_versions_returns_count(self, store):
        a1 = KnowledgeArtifact(title="A", user_id="u", tenant_id="t", format="text", content_hash="h1")
        store.publish(a1)
        a2 = KnowledgeArtifact(
            title="A", user_id="u", tenant_id="t", format="text",
            content_hash="h2", canonical_id=a1.id, version="2",
        )
        store.publish(a2, canonical_id=a1.id)
        assert store.supersede_versions(a1.id, superseded_by=a2.id, except_id=a2.id) == 1
        assert store.get(a1.id).status == "superseded"
        assert store.get_current(a1.id).id == a2.id

    def test_publish_canonical_id_override(self, store):
        artifact = KnowledgeArtifact(title="A", user_id="u", tenant_id="t", format="text", content_hash="h")
        store.publish(artifact, canonical_id="family-42")
        assert store.get(artifact.id).canonical_id == "family-42"
        assert store.get_current("family-42").id == artifact.id

    def test_search_canonical_id_filter(self, node):
        v1 = node.publish("Family search", content="family tokens")
        node.publish_version(v1.id, content="family tokens two")
        other = node.publish("Other family search", content="family tokens three")
        resp = node.search("family tokens", canonical_id=v1.id)
        assert {r.id for r in resp.results} == {node.get_current(v1.id).id}
        assert other.id not in {r.id for r in resp.results}

    def test_search_explicit_status_override(self, store):
        artifact = KnowledgeArtifact(
            title="Expired probe", user_id="u", tenant_id="t", format="text",
            content_hash="h", expires_at=_past(),
        )
        store.publish(artifact)
        assert store.search("expired probe").total == 0
        assert store.search("expired probe", status="expired").total == 1


# ─── HTTP surface ──────────────────────────────────────────────


class TestServerEndpoints:
    @pytest.fixture
    def client(self, node):
        from fastapi.testclient import TestClient

        return TestClient(node.create_app())

    def test_publish_with_ttl_via_http(self, client, node):
        resp = client.post(
            "/kcp/v1/artifacts",
            json={"title": "HTTP TTL", "content": "body", "format": "text", "ttl_seconds": 300},
        )
        assert resp.status_code == 200
        assert resp.json()["expires_at"] is not None

    def test_versions_endpoint(self, client, node):
        v1 = node.publish("HTTP versions", content="1")
        v2 = node.publish_version(v1.id, content="2")
        resp = client.get(f"/kcp/v1/artifacts/{v1.id}/versions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["canonical_id"] == v1.id
        assert [v["id"] for v in body["versions"]] == [v1.id, v2.id]

    def test_current_endpoint(self, client, node):
        v1 = node.publish("HTTP current", content="1")
        v2 = node.publish_version(v1.id, content="2")
        resp = client.get(f"/kcp/v1/artifacts/{v1.id}/current")
        assert resp.status_code == 200
        assert resp.json()["id"] == v2.id

    def test_current_endpoint_404_when_expired(self, client, node):
        v1 = node.publish("HTTP expired", content="1", expires_at=_past())
        resp = client.get(f"/kcp/v1/artifacts/{v1.id}/current")
        assert resp.status_code == 404

    def test_search_excludes_superseded_via_http(self, client, node):
        v1 = node.publish("HTTP searchable", content="searchable alpha")
        node.publish_version(v1.id, content="searchable alpha v2")
        default = client.get("/kcp/v1/artifacts", params={"q": "searchable"}).json()
        assert default["total"] == 1
        widened = client.get(
            "/kcp/v1/artifacts", params={"q": "searchable", "include_superseded": "true"}
        ).json()
        assert widened["total"] == 2


# ─── CLI ───────────────────────────────────────────────────────


class TestCli:
    @pytest.fixture
    def cli_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KCP_DB", str(tmp_path / "cli.db"))
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("KCP_PEERS", raising=False)
        monkeypatch.setenv("KCP_USER", "cli@example.com")
        monkeypatch.setenv("KCP_TENANT", "cli-corp")
        return tmp_path

    def _run(self, monkeypatch, capsys, *argv):
        from kcp import cli

        monkeypatch.setattr(sys, "argv", ["kcp", *argv])
        cli.main()
        return capsys.readouterr().out

    def test_publish_with_ttl_then_versions(self, cli_env, monkeypatch, capsys):
        doc = cli_env / "doc.md"
        doc.write_text("first body")
        out = self._run(monkeypatch, capsys, "publish", "--title", "CLI Doc", "--ttl", "3600", str(doc))
        assert "Expires:" in out
        first_id = [line for line in out.splitlines() if line.startswith("✅ Published:")][0].split(": ")[1]

        doc.write_text("second body")
        out = self._run(monkeypatch, capsys, "publish", "--version-of", first_id, str(doc))
        assert "Published version 2" in out

        out = self._run(monkeypatch, capsys, "versions", first_id)
        assert "v1" in out and "v2" in out
        assert "superseded" in out
        assert "← current" in out

    def test_search_flags(self, cli_env, monkeypatch, capsys):
        from kcp.node import KCPNode

        node = KCPNode(
            user_id="cli@example.com",
            tenant_id="cli-corp",
            db_path=str(cli_env / "cli.db"),
            keys_dir=str(cli_env / "keys"),
        )
        v1 = node.publish("CLI Searchable", content="searchable beta")
        node.publish_version(v1.id, content="searchable beta two")

        out = self._run(monkeypatch, capsys, "search", "searchable")
        assert "active only" in out
        assert "Status: active" in out

        out = self._run(monkeypatch, capsys, "search", "searchable", "--include-superseded")
        assert "Status: superseded" in out

    def test_publish_with_expires_at_and_include_expired(self, cli_env, monkeypatch, capsys):
        doc = cli_env / "stale.md"
        doc.write_text("stale body")
        past = _past()
        self._run(monkeypatch, capsys, "publish", "--title", "Stale CLI", "--expires-at", past, str(doc))

        out = self._run(monkeypatch, capsys, "search", "stale")
        assert "No results" in out

        out = self._run(monkeypatch, capsys, "search", "stale", "--include-expired")
        assert "Stale CLI" in out
