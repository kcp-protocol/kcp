"""
KCP Client

Main client for interacting with a KCP node.
"""

import json
from typing import Optional
from pathlib import Path

from .models import KnowledgeArtifact, Lineage, ACL, SearchResult, SearchResponse
from .crypto import sign_artifact, verify_artifact, hash_content


class KCPClient:
    """
    Client for the Knowledge Context Protocol.

    Usage:
        client = KCPClient(
            node_url="http://localhost:8080",
            tenant_id="acme-corp",
            user_id="alice@example.com",
            private_key=private_key_bytes
        )

        # Publish a report
        artifact = client.publish(
            title="Q1 Analysis",
            content=html_bytes,
            format="html",
            tags=["analytics"],
            lineage=Lineage(query="...", data_sources=["..."])
        )

        # Search
        results = client.search("customer retention")
    """

    def __init__(
        self,
        node_url: str,
        tenant_id: str,
        user_id: str,
        private_key: Optional[bytes] = None,
        team: Optional[str] = None,
    ):
        self.node_url = node_url.rstrip("/")
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.private_key = private_key
        self.default_team = team

    def publish(
        self,
        title: str,
        content: bytes,
        format: str,
        visibility: str = "team",
        tags: Optional[list[str]] = None,
        team: Optional[str] = None,
        source: str = "",
        summary: str = "",
        lineage: Optional[Lineage] = None,
        acl: Optional[ACL] = None,
    ) -> KnowledgeArtifact:
        """
        Publish a knowledge artifact to the KCP node.

        Args:
            title: Human-readable title
            content: Raw content bytes
            format: Content format (html, json, markdown, pdf, png, csv, text)
            visibility: Access tier (public, org, team, private)
            tags: Keywords for discovery
            team: Team within tenant (defaults to client's default_team)
            source: Agent identifier that generated this
            summary: Brief description (max 500 chars)
            lineage: Provenance information
            acl: Fine-grained access control

        Returns:
            The published KnowledgeArtifact with id, content_hash, and signature
        """
        # Create artifact
        artifact = KnowledgeArtifact(
            title=title,
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            format=format,
            visibility=visibility,
            team=team or self.default_team,
            tags=tags or [],
            source=source,
            summary=summary,
            lineage=lineage,
            acl=acl,
        )

        # Compute content hash
        artifact.content_hash = hash_content(
            content if isinstance(content, bytes) else content.encode("utf-8")
        )

        # Sign artifact
        if self.private_key:
            artifact.signature = sign_artifact(artifact.to_dict(), self.private_key)

        # Send to node
        self._post("/kcp/v1/reports", artifact.to_dict(), content)

        return artifact

    def search(
        self,
        query: str = "",
        tags: Optional[list[str]] = None,
        team: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> SearchResponse:
        """
        Search for knowledge artifacts.

        Args:
            query: Full-text search query
            tags: Filter by tags
            team: Filter by team
            from_date: Start date (ISO 8601)
            to_date: End date (ISO 8601)
            limit: Max results
            offset: Pagination offset

        Returns:
            SearchResponse with results, total count, and query time
        """
        params = {
            "tenant_id": self.tenant_id,
            "limit": limit,
            "offset": offset,
        }
        if query:
            params["q"] = query
        if tags:
            params["tags"] = ",".join(tags)
        if team:
            params["team"] = team
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date

        data = self._get("/kcp/v1/reports", params)
        return SearchResponse.from_dict(data)

    def get(self, artifact_id: str) -> KnowledgeArtifact:
        """Retrieve artifact metadata by ID."""
        data = self._get(f"/kcp/v1/reports/{artifact_id}")
        return KnowledgeArtifact.from_dict(data)

    def get_content(self, artifact_id: str) -> bytes:
        """Retrieve artifact content by ID."""
        return self._get_raw(f"/kcp/v1/reports/{artifact_id}/content")

    def delete(self, artifact_id: str) -> dict:
        """Soft-delete an artifact."""
        return self._delete(f"/kcp/v1/reports/{artifact_id}")

    def verify(self, artifact: KnowledgeArtifact, public_key: bytes) -> bool:
        """Verify an artifact's signature."""
        return verify_artifact(artifact.to_dict(), public_key)

    # ─── HTTP helpers (to be implemented with httpx/requests) ───

    def _post(self, path: str, payload: dict, content: bytes = b"") -> dict:
        """POST request to KCP node."""
        try:
            import httpx
            response = httpx.post(
                f"{self.node_url}{path}",
                json=payload,
                headers=self._headers(),
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()
        except ImportError:
            # Fallback: return payload as-is (for testing without server)
            return payload

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        """GET request to KCP node."""
        try:
            import httpx
            response = httpx.get(
                f"{self.node_url}{path}",
                params=params,
                headers=self._headers(),
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()
        except ImportError:
            return {}

    def _get_raw(self, path: str) -> bytes:
        """GET raw content from KCP node."""
        try:
            import httpx
            response = httpx.get(
                f"{self.node_url}{path}",
                headers=self._headers(),
                timeout=60.0,
            )
            response.raise_for_status()
            return response.content
        except ImportError:
            return b""

    def _delete(self, path: str) -> dict:
        """DELETE request to KCP node."""
        try:
            import httpx
            response = httpx.delete(
                f"{self.node_url}{path}",
                headers=self._headers(),
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()
        except ImportError:
            return {}

    def _headers(self) -> dict:
        """Common headers for KCP requests."""
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-KCP-Tenant": self.tenant_id,
            "X-KCP-User": self.user_id,
        }
