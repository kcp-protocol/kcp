"""
KCP Hub Backend

HTTP client for corporate KCP hubs.
When configured, all operations route to the central hub instead of local storage.
The user doesn't know the difference — same API, different backend.

Usage:
    hub = HubBackend(url="https://kcp.acme-corp.internal", api_key="...")
    hub.publish(artifact, content)
    results = hub.search("deployment strategies")
"""

import json
import base64
from typing import Optional

from .models import KnowledgeArtifact, Lineage, ACL, SearchResponse, SearchResult


class HubBackend:
    """
    HTTP client for a corporate KCP Hub.

    Implements the same interface as LocalStore so the Node
    can swap backends transparently.
    """

    def __init__(
        self,
        url: str,
        api_key: str = "",
        user_id: str = "",
        tenant_id: str = "",
    ):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.user_id = user_id
        self.tenant_id = tenant_id

    def _headers(self) -> dict:
        h = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-KCP-Tenant": self.tenant_id,
            "X-KCP-User": self.user_id,
        }
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _request(self, method: str, path: str, **kwargs) -> dict:
        """Make HTTP request to hub."""
        try:
            import httpx
            resp = httpx.request(
                method,
                f"{self.url}{path}",
                headers=self._headers(),
                timeout=60.0,
                **kwargs,
            )
            resp.raise_for_status()
            return resp.json()
        except ImportError:
            raise ImportError("httpx required for Hub backend. pip install httpx")

    # ─── Same interface as LocalStore ──────────────────────────

    def publish(
        self,
        artifact: KnowledgeArtifact,
        content: bytes = b"",
        derived_from: Optional[str] = None,
    ) -> KnowledgeArtifact:
        """Publish artifact to hub."""
        payload = artifact.to_dict()
        if content:
            payload["_content_b64"] = base64.b64encode(content).decode()
        if derived_from:
            payload["derived_from"] = derived_from

        result = self._request("POST", "/kcp/v1/artifacts", json=payload)
        return KnowledgeArtifact.from_dict(result)

    def get(self, artifact_id: str) -> Optional[KnowledgeArtifact]:
        """Get artifact from hub."""
        try:
            data = self._request("GET", f"/kcp/v1/artifacts/{artifact_id}")
            return KnowledgeArtifact.from_dict(data)
        except Exception:
            return None

    def get_content(self, content_hash: str) -> Optional[bytes]:
        """Get content from hub by hash."""
        try:
            data = self._request("GET", f"/kcp/v1/content/{content_hash}")
            if "content" in data:
                return base64.b64decode(data["content"])
            return None
        except Exception:
            return None

    def delete(self, artifact_id: str, user_id: str = "") -> bool:
        """Delete artifact on hub."""
        try:
            self._request("DELETE", f"/kcp/v1/artifacts/{artifact_id}")
            return True
        except Exception:
            return False

    def search(
        self,
        query: str,
        tenant_id: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResponse:
        """Search artifacts on hub."""
        params = {"q": query, "limit": limit, "offset": offset}
        if tenant_id:
            params["tenant_id"] = tenant_id

        data = self._request("GET", "/kcp/v1/artifacts", params=params)

        results = []
        for item in data.get("artifacts", data.get("results", [])):
            results.append(SearchResult(
                id=item["id"],
                title=item["title"],
                summary=item.get("summary", ""),
                created_at=item.get("timestamp", ""),
                relevance=item.get("relevance", 1.0),
                format=item.get("format", ""),
            ))

        return SearchResponse(
            results=results,
            total=data.get("total", len(results)),
            query_time_ms=data.get("query_time_ms", 0),
        )

    def list_artifacts(
        self,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        tags: Optional[list[str]] = None,
        format_filter: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[KnowledgeArtifact]:
        """List artifacts from hub."""
        params: dict = {"limit": limit, "offset": offset}
        if tenant_id:
            params["tenant_id"] = tenant_id
        if user_id:
            params["user_id"] = user_id
        if tags:
            params["tags"] = ",".join(tags)
        if format_filter:
            params["format"] = format_filter

        data = self._request("GET", "/kcp/v1/artifacts", params=params)
        return [
            KnowledgeArtifact.from_dict(a)
            for a in data.get("artifacts", [])
        ]

    def get_lineage(self, artifact_id: str) -> list[dict]:
        """Get lineage from hub."""
        data = self._request("GET", f"/kcp/v1/artifacts/{artifact_id}/lineage")
        return data.get("lineage", [])

    def get_derivatives(self, artifact_id: str) -> list[dict]:
        """Get derivatives from hub."""
        data = self._request("GET", f"/kcp/v1/artifacts/{artifact_id}/derivatives")
        return data.get("derivatives", [])

    # ─── Peers (hub manages federation) ────────────────────────

    def get_peers(self) -> list[dict]:
        data = self._request("GET", "/kcp/v1/peers")
        return data.get("peers", [])

    def add_peer(self, peer_id: str, url: str, name: str = "", public_key: str = ""):
        self._request("POST", "/kcp/v1/peers", json={
            "id": peer_id, "url": url, "name": name, "public_key": public_key,
        })

    # ─── Stats ─────────────────────────────────────────────────

    def stats(self) -> dict:
        return self._request("GET", "/kcp/v1/health")

    # ─── Config (stored on hub) ────────────────────────────────

    def get_config(self, key: str, default: str = "") -> str:
        try:
            data = self._request("GET", f"/kcp/v1/config/{key}")
            return data.get("value", default)
        except Exception:
            return default

    def set_config(self, key: str, value: str):
        self._request("PUT", f"/kcp/v1/config/{key}", json={"value": value})

    # Stub methods for interface compatibility
    def get_artifact_ids_since(self, since=None):
        params = {"since": since} if since else {}
        data = self._request("GET", "/kcp/v1/sync/list", params=params)
        return data.get("ids", [])

    def get_artifact_with_content(self, artifact_id):
        return self._request("GET", f"/kcp/v1/sync/artifact/{artifact_id}")

    def import_artifact(self, data):
        result = self._request("POST", "/kcp/v1/sync/push", json=data)
        return result.get("accepted", False)

    def log_sync(self, peer_id, direction, count, status="ok", details=""):
        pass  # Hub handles its own sync logging

    def update_peer_seen(self, peer_id):
        pass  # Hub handles this

    def close(self):
        pass  # No persistent connection to close
