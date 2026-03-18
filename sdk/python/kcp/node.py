"""
KCP Embedded Node

Runs in-process — no separate server needed.
Handles publish, search, lineage, sync, and optional HTTP serving.

Usage (embedded — no server):
    node = KCPNode(user_id="alice@acme.com", tenant_id="acme-corp")
    atom = node.publish("JWT Auth Guide", content=b"...", format="markdown")
    results = node.search("authentication")

Usage (with HTTP server for P2P/sharing):
    node = KCPNode(user_id="alice@acme.com", tenant_id="acme-corp")
    node.serve(port=8800)  # Starts FastAPI server
"""

import os
import json
import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from .models import KnowledgeArtifact, Lineage, ACL, SearchResponse
from .crypto import generate_keypair, sign_artifact, verify_artifact, hash_content
from .store import LocalStore


class KCPNode:
    """
    Embedded KCP node. Runs in-process, stores locally.
    Optionally serves HTTP for P2P sharing.
    """

    def __init__(
        self,
        user_id: str = "anonymous",
        tenant_id: str = "local",
        db_path: str = "~/.kcp/kcp.db",
        keys_dir: str = "~/.kcp/keys",
    ):
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.store = LocalStore(db_path)
        self.keys_dir = Path(keys_dir).expanduser()
        self.keys_dir.mkdir(parents=True, exist_ok=True)

        # Load or generate keys
        self.private_key, self.public_key = self._load_or_generate_keys()

        # Store identity in config
        self.store.set_config("user_id", user_id)
        self.store.set_config("tenant_id", tenant_id)
        self.store.set_config("public_key", self.public_key.hex())
        self.store.set_config("node_id", self._get_or_create_node_id())

    @property
    def node_id(self) -> str:
        return self.store.get_config("node_id")

    # ─── Core Operations ───────────────────────────────────────

    def publish(
        self,
        title: str,
        content: bytes | str,
        format: str = "markdown",
        tags: Optional[list[str]] = None,
        summary: str = "",
        visibility: str = "public",
        derived_from: Optional[str] = None,
        source: str = "",
        lineage: Optional[Lineage] = None,
    ) -> KnowledgeArtifact:
        """
        Publish a knowledge artifact.

        Args:
            title: Human-readable title
            content: Raw content (bytes or string)
            format: Content type (markdown, html, json, text, csv, pdf)
            tags: Discovery keywords
            summary: Brief description
            visibility: Access tier (public, org, team, private)
            derived_from: Parent artifact ID (lineage tracking)
            source: What generated this (agent name, tool, etc)
            lineage: Detailed provenance info

        Returns:
            Signed, stored KnowledgeArtifact
        """
        if isinstance(content, str):
            content = content.encode("utf-8")

        artifact = KnowledgeArtifact(
            title=title,
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            format=format,
            visibility=visibility,
            tags=tags or [],
            summary=summary,
            source=source,
            lineage=lineage,
            content_hash=hash_content(content),
        )

        # Sign
        artifact.signature = sign_artifact(artifact.to_dict(), self.private_key)

        # Store
        self.store.publish(artifact, content=content, derived_from=derived_from)

        return artifact

    def get(self, artifact_id: str) -> Optional[KnowledgeArtifact]:
        """Get artifact by ID."""
        return self.store.get(artifact_id)

    def get_content(self, artifact_id: str) -> Optional[bytes]:
        """Get raw content for an artifact."""
        artifact = self.store.get(artifact_id)
        if not artifact:
            return None
        return self.store.get_content(artifact.content_hash)

    def search(self, query: str, limit: int = 20) -> SearchResponse:
        """Search artifacts by text."""
        return self.store.search(query, tenant_id=None, limit=limit)

    def list(self, limit: int = 50, tags: Optional[list[str]] = None) -> list[KnowledgeArtifact]:
        """List recent artifacts."""
        return self.store.list_artifacts(limit=limit, tags=tags)

    def delete(self, artifact_id: str) -> bool:
        """Soft-delete an artifact."""
        return self.store.delete(artifact_id, self.user_id)

    def lineage(self, artifact_id: str) -> list[dict]:
        """Get full lineage chain (root → current)."""
        return self.store.get_lineage(artifact_id)

    def derivatives(self, artifact_id: str) -> list[dict]:
        """Get all artifacts derived from this one."""
        return self.store.get_derivatives(artifact_id)

    def verify(self, artifact: KnowledgeArtifact, public_key: Optional[bytes] = None) -> bool:
        """Verify artifact signature."""
        key = public_key or self.public_key
        return verify_artifact(artifact.to_dict(), key)

    def stats(self) -> dict:
        """Get node statistics."""
        s = self.store.stats()
        s["node_id"] = self.node_id
        s["user_id"] = self.user_id
        s["tenant_id"] = self.tenant_id
        return s

    # ─── Peer / Sync ──────────────────────────────────────────

    def add_peer(self, url: str, name: str = ""):
        """Register a peer node for sync."""
        peer_id = str(uuid4())
        self.store.add_peer(peer_id, url, name)
        return peer_id

    def get_peers(self) -> list[dict]:
        """List known peers."""
        return self.store.get_peers()

    def sync_push(self, peer_url: str, since: Optional[str] = None) -> dict:
        """Push local artifacts to a peer."""
        try:
            import httpx
        except ImportError:
            return {"error": "httpx required for sync. pip install httpx"}

        ids = self.store.get_artifact_ids_since(since)
        pushed = 0

        for aid in ids:
            data = self.store.get_artifact_with_content(aid)
            if data:
                try:
                    resp = httpx.post(
                        f"{peer_url.rstrip('/')}/kcp/v1/sync/push",
                        json=data,
                        timeout=30.0,
                    )
                    if resp.status_code in (200, 201):
                        pushed += 1
                except Exception:
                    continue

        return {"pushed": pushed, "total": len(ids)}

    def sync_pull(self, peer_url: str, since: Optional[str] = None) -> dict:
        """Pull artifacts from a peer."""
        try:
            import httpx
        except ImportError:
            return {"error": "httpx required for sync. pip install httpx"}

        try:
            params = {}
            if since:
                params["since"] = since

            resp = httpx.get(
                f"{peer_url.rstrip('/')}/kcp/v1/sync/list",
                params=params,
                timeout=30.0,
            )
            remote_ids = resp.json().get("ids", [])

            pulled = 0
            for rid in remote_ids:
                # Check if we already have it
                if self.store.get(rid):
                    continue

                resp = httpx.get(
                    f"{peer_url.rstrip('/')}/kcp/v1/sync/artifact/{rid}",
                    timeout=30.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if self.store.import_artifact(data):
                        pulled += 1

            return {"pulled": pulled, "available": len(remote_ids)}

        except Exception as e:
            return {"error": str(e)}

    # ─── HTTP Server ───────────────────────────────────────────

    def create_app(self):
        """Create FastAPI app for HTTP serving (P2P + Web UI)."""
        try:
            from fastapi import FastAPI, HTTPException
            from fastapi.responses import HTMLResponse, JSONResponse
        except ImportError:
            raise ImportError("FastAPI required for HTTP serving. pip install fastapi uvicorn")

        app = FastAPI(title="KCP Node", version="0.1.0")

        @app.get("/kcp/v1/health")
        def health():
            return self.stats()

        @app.get("/kcp/v1/artifacts")
        def list_artifacts(limit: int = 50, q: Optional[str] = None, tags: Optional[str] = None):
            if q:
                return self.search(q, limit=limit).__dict__
            tag_list = tags.split(",") if tags else None
            artifacts = self.list(limit=limit, tags=tag_list)
            return {"artifacts": [a.to_dict() for a in artifacts], "total": len(artifacts)}

        @app.get("/kcp/v1/artifacts/{artifact_id}")
        def get_artifact(artifact_id: str):
            a = self.get(artifact_id)
            if not a:
                raise HTTPException(404, "Artifact not found")
            return a.to_dict()

        @app.get("/kcp/v1/artifacts/{artifact_id}/content")
        def get_content(artifact_id: str):
            content = self.get_content(artifact_id)
            if content is None:
                raise HTTPException(404, "Content not found")
            return JSONResponse({"content": base64.b64encode(content).decode()})

        @app.get("/kcp/v1/artifacts/{artifact_id}/lineage")
        def get_lineage(artifact_id: str):
            return {"lineage": self.lineage(artifact_id)}

        @app.post("/kcp/v1/artifacts")
        def publish_artifact(body: dict):
            content = b""
            if "_content_b64" in body:
                content = base64.b64decode(body["_content_b64"])
            elif "content" in body:
                content = body["content"].encode("utf-8") if isinstance(body["content"], str) else body["content"]

            artifact = self.publish(
                title=body.get("title", "Untitled"),
                content=content,
                format=body.get("format", "text"),
                tags=body.get("tags", []),
                summary=body.get("summary", ""),
                visibility=body.get("visibility", "public"),
                derived_from=body.get("derived_from"),
                source=body.get("source", ""),
            )
            return artifact.to_dict()

        # Sync endpoints
        @app.get("/kcp/v1/sync/list")
        def sync_list(since: Optional[str] = None):
            ids = self.store.get_artifact_ids_since(since)
            return {"ids": ids, "total": len(ids)}

        @app.get("/kcp/v1/sync/artifact/{artifact_id}")
        def sync_get(artifact_id: str):
            data = self.store.get_artifact_with_content(artifact_id)
            if not data:
                raise HTTPException(404, "Not found")
            return data

        @app.post("/kcp/v1/sync/push")
        def sync_receive(body: dict):
            is_new = self.store.import_artifact(body)
            return {"accepted": is_new}

        # Peers
        @app.get("/kcp/v1/peers")
        def list_peers():
            return {"peers": self.get_peers()}

        @app.post("/kcp/v1/peers")
        def register_peer(body: dict):
            pid = self.add_peer(body.get("url", ""), body.get("name", ""))
            return {"peer_id": pid}

        # Web UI
        @app.get("/ui", response_class=HTMLResponse)
        def web_ui():
            ui_path = Path(__file__).parent / "ui" / "index.html"
            if ui_path.exists():
                return ui_path.read_text()
            return "<h1>KCP Node</h1><p>Web UI not found.</p>"

        return app

    def serve(self, host: str = "0.0.0.0", port: int = 8800):
        """Start HTTP server for P2P sharing and Web UI."""
        try:
            import uvicorn
        except ImportError:
            raise ImportError("uvicorn required. pip install uvicorn")

        app = self.create_app()
        print(f"🌐 KCP Node serving at http://{host}:{port}")
        print(f"📡 Web UI: http://localhost:{port}/ui")
        print(f"🔑 Node ID: {self.node_id}")
        print(f"👤 User: {self.user_id}")
        uvicorn.run(app, host=host, port=port, log_level="info")

    # ─── Internal ──────────────────────────────────────────────

    def _load_or_generate_keys(self) -> tuple[bytes, bytes]:
        """Load existing keypair or generate new one."""
        priv_path = self.keys_dir / "private.key"
        pub_path = self.keys_dir / "public.key"

        if priv_path.exists() and pub_path.exists():
            return priv_path.read_bytes(), pub_path.read_bytes()

        private_key, public_key = generate_keypair()
        priv_path.write_bytes(private_key)
        pub_path.write_bytes(public_key)

        # Restrict private key permissions
        os.chmod(str(priv_path), 0o600)

        return private_key, public_key

    def _get_or_create_node_id(self) -> str:
        """Get or create a persistent node ID."""
        nid = self.store.get_config("node_id")
        if not nid:
            nid = str(uuid4())
            self.store.set_config("node_id", nid)
        return nid
