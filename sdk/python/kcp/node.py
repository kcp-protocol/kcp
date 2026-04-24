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

from __future__ import annotations

import logging
import os
import json
import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from .models import KnowledgeArtifact, Lineage, ACL, SearchResponse
from .crypto import (
    generate_keypair, sign_artifact, verify_artifact, hash_content,
    encrypt_content, decrypt_content, derive_content_key, is_encrypted,
)
from .store import LocalStore
from .sync_worker import SyncWorker

logger = logging.getLogger("kcp.node")

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

        # Peer sync — parse KCP_PEERS=url1,url2 and start background worker
        raw_peers = os.environ.get("KCP_PEERS", "")
        self.peers: list[str] = [p.strip() for p in raw_peers.split(",") if p.strip()]
        self._sync_worker: Optional[SyncWorker] = None
        self._port: int = 0  # set by serve(); used by network-status for localhost probing
        if self.peers:
            self._sync_worker = SyncWorker(self.store, self.peers)
            self._sync_worker.start()

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

        # content_hash always computed on PLAINTEXT (for integrity verification)
        plaintext_hash = hash_content(content)

        # Encrypt at rest if private
        stored_content = content
        if visibility == "private":
            # Derive a temporary ID for HKDF — will be replaced after artifact is created
            import uuid
            temp_id = str(uuid.uuid4())
            content_key = derive_content_key(self.private_key, temp_id)
            stored_content = encrypt_content(content, content_key)
            # Store the temp_id in source so we can re-derive the key later
            # We embed it as a non-user-visible field via a dedicated key store
            self._store_content_key_id(temp_id)
        else:
            temp_id = None

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
            content_hash=plaintext_hash,  # always hash of plaintext
        )

        # Sign over metadata (includes plaintext hash — tamper-evident)
        artifact.signature = sign_artifact(artifact.to_dict(), self.private_key)

        # Store encrypted content keyed by artifact.id for key retrieval
        if visibility == "private" and temp_id:
            # Re-derive with the real artifact.id
            content_key = derive_content_key(self.private_key, artifact.id)
            stored_content = encrypt_content(content, content_key)
            self._store_content_key_id(artifact.id)

        # Store
        self.store.publish(artifact, content=stored_content, derived_from=derived_from)

        # Enqueue for async delivery to peers (non-blocking)
        if visibility != "private" and self.peers:
            self.store.enqueue_sync(artifact.id, self.peers)

        return artifact

    def get(self, artifact_id: str) -> Optional[KnowledgeArtifact]:
        """Get artifact by ID."""
        return self.store.get(artifact_id)

    def get_content(self, artifact_id: str) -> Optional[bytes]:
        """Get raw content for an artifact — decrypts private artifacts automatically."""
        artifact = self.store.get(artifact_id)
        if not artifact:
            return None
        raw = self.store.get_content(artifact.content_hash)
        if raw is None:
            return None
        # Auto-decrypt if we own the key and blob is encrypted
        if is_encrypted(raw) and self._can_decrypt(artifact_id):
            content_key = derive_content_key(self.private_key, artifact_id)
            try:
                return decrypt_content(raw, content_key)
            except Exception:
                logger.debug("Decryption failed for %s — key mismatch", artifact_id)
                return None  # key mismatch (artifact from another node)
        return raw

    def _store_content_key_id(self, artifact_id: str):
        """Record that we have the encryption key for this artifact."""
        self.store.set_config(f"enc_key:{artifact_id}", "1")

    def _can_decrypt(self, artifact_id: str) -> bool:
        """Return True if this node holds the encryption key for the artifact."""
        return bool(self.store.get_config(f"enc_key:{artifact_id}"))

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
        """Get node statistics — full (internal use only)."""
        s = self.store.stats()
        s["node_id"] = self.node_id
        s["user_id"] = self.user_id
        s["tenant_id"] = self.tenant_id
        return s

    def public_stats(self) -> dict:
        """Get sanitized stats safe to expose via HTTP health endpoint."""
        s = self.store.stats()
        return {
            "status": "ok",
            "node_id": self.node_id,
            "artifacts": s["artifacts"],
            "peers": s["peers"],
            "kcp_version": "0.2.0",
            "protocol": "KCP/1",
        }

    def sync_status(self) -> dict:
        """Return sync worker status + per-peer queue stats."""
        if self._sync_worker:
            return self._sync_worker.status()
        return {
            "running": False,
            "peers": {},
        }

    def replication_status(self, artifact_id: str) -> dict:
        """Return how many peers have a confirmed copy of this artifact."""
        status = self.store.get_replication_status(artifact_id)
        rf = int(self.store.get_config("replication_factor") or len(self.peers) or 1)
        status["replication_factor"] = rf
        status["complete"] = status["count"] >= rf
        return status

    def set_replication_factor(self, n: int):
        """
        Set the desired replication factor — how many peers must ACK
        before an artifact is considered fully replicated.
        Default: number of known peers (full replication).
        """
        self.store.set_config("replication_factor", str(n))

    def close(self):
        """Gracefully stop background workers."""
        if self._sync_worker:
            self._sync_worker.stop()

    # ─── Peer / Sync ──────────────────────────────────────────

    def add_peer(self, url: str, name: str = ""):
        """Register a peer node for sync."""
        peer_id = str(uuid4())
        self.store.add_peer(peer_id, url, name)
        return peer_id

    def get_peers(self) -> list[dict]:
        """List known peers."""
        return self.store.get_peers()

    def discover_peers(
        self,
        bootstrap_url: str = "https://kcp-protocol.org/peers.json",
        gossip: bool = True,
    ) -> dict:
        """
        Peer discovery via two complementary mechanisms:

        1. **Bootstrap registry** — fetches the official peers.json from
           the KCP project site. Safe, curated, always up-to-date.

        2. **Gossip** — queries each known peer's /kcp/v1/peers endpoint
           and learns about their known peers recursively (1 hop).

        All discovered peers are upserted into the local kcp_peers table
        so they become available for future sync and for exposing via
        this node's own /kcp/v1/peers endpoint (P2P propagation).

        Returns a summary: {"discovered": N, "bootstrap": N, "gossip": N}
        """
        try:
            import httpx
        except ImportError:
            return {"error": "httpx required. pip install httpx"}

        discovered_total = 0
        bootstrap_count = 0
        gossip_count = 0

        # ── 1. Bootstrap from official registry ──────────────
        try:
            resp = httpx.get(bootstrap_url, timeout=10.0, follow_redirects=True)
            if resp.status_code == 200:
                registry = resp.json()
                for peer in registry.get("peers", []):
                    url = peer.get("url", "").rstrip("/")
                    if url and url != self._self_url():
                        self.store.upsert_peer(
                            url=url,
                            name=peer.get("name", ""),
                            node_id=peer.get("node_id", ""),
                            public_key=peer.get("public_key", ""),
                        )
                        bootstrap_count += 1
                        discovered_total += 1
        except Exception as e:
            logger.debug("Bootstrap registry unavailable — continuing with gossip: %s", e)

        # ── 2. Gossip from currently known peers ─────────────
        if gossip:
            known_peers = self.store.get_peers()
            known_urls = {p["url"] for p in known_peers}

            for peer in known_peers:
                peer_url = peer["url"].rstrip("/")
                try:
                    resp = httpx.get(
                        f"{peer_url}/kcp/v1/peers",
                        headers=self._KCP_CLIENT_HEADER,
                        timeout=8.0,
                    )
                    if resp.status_code == 200:
                        remote_peers = resp.json().get("peers", [])
                        for rp in remote_peers:
                            rurl = rp.get("url", "").rstrip("/")
                            if rurl and rurl not in known_urls and rurl != self._self_url():
                                self.store.upsert_peer(
                                    url=rurl,
                                    name=rp.get("name", ""),
                                    node_id=rp.get("node_id", ""),
                                    public_key=rp.get("public_key", ""),
                                )
                                known_urls.add(rurl)
                                gossip_count += 1
                                discovered_total += 1
                        # Mark peer as reachable
                        self.store.update_peer_seen_by_url(peer_url)
                except Exception as e:
                    logger.debug("Peer %s unreachable during gossip: %s", peer_url, e)
                    continue

        return {
            "discovered": discovered_total,
            "bootstrap": bootstrap_count,
            "gossip": gossip_count,
        }

    def _self_url(self) -> str:
        """Return this node's own public URL (from KCP_SELF_URL env), or empty string."""
        return os.environ.get("KCP_SELF_URL", "").rstrip("/")

    # Header sent on all outbound peer requests — required by public peers
    _KCP_CLIENT_HEADER = {"X-KCP-Client": f"kcp-python/0.2.0"}

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
                        headers=self._KCP_CLIENT_HEADER,
                        timeout=30.0,
                    )
                    if resp.status_code in (200, 201):
                        pushed += 1
                except Exception as e:
                    logger.debug("Failed to push artifact %s to %s: %s", aid[:8], peer_url, e)
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
                headers=self._KCP_CLIENT_HEADER,
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
                    headers=self._KCP_CLIENT_HEADER,
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
            from fastapi import FastAPI, HTTPException, Request, Header, Depends
            from fastapi.middleware.cors import CORSMiddleware
            from fastapi.responses import HTMLResponse, JSONResponse
        except ImportError:
            raise ImportError("FastAPI required for HTTP serving. pip install fastapi uvicorn")

        app = FastAPI(title="KCP Node", version="0.2.0")
        
        # Enable CORS for /kcp/v1/network-status (browser fetch from kcp-protocol.org)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["https://kcp-protocol.org", "http://localhost:*"],
            allow_methods=["GET"],
            allow_headers=["*"],
        )

        def _caller_identity(
            x_kcp_user_id: Optional[str] = Header(default=None, alias="X-KCP-User-ID"),
            x_kcp_tenant: Optional[str] = Header(default=None, alias="X-KCP-Tenant"),
        ) -> tuple:
            """Extract caller identity from request headers."""
            return (
                x_kcp_user_id or self.user_id,
                x_kcp_tenant or self.tenant_id,
            )

        def _can_read(artifact, caller_user: str, caller_tenant: str) -> bool:
            """
            ACL enforcement rules:
              public  → everyone
              org     → same tenant_id only
              team    → in ACL.allowed_users OR in ACL.allowed_teams (future)
              private → owner (user_id) only
            """
            v = artifact.visibility
            if v == "public":
                return True
            if v == "org":
                return artifact.tenant_id == caller_tenant
            if v == "team":
                if artifact.acl is None:
                    return artifact.tenant_id == caller_tenant
                if caller_user in (artifact.acl.allowed_users or []):
                    return True
                return False
            if v == "private":
                return artifact.user_id == caller_user
            return False

        @app.get("/kcp/v1/health")
        def health():
            return self.public_stats()

        @app.get("/kcp/v1/artifacts")
        def list_artifacts(
            limit: int = 50,
            q: Optional[str] = None,
            tags: Optional[str] = None,
            caller: tuple = Depends(_caller_identity),
        ):
            caller_user, caller_tenant = caller
            tag_list = tags.split(",") if tags else None
            if q:
                resp = self.search(q, limit=limit)
                visible = [r for r in resp.results if (a := self.get(r.id)) and _can_read(a, caller_user, caller_tenant)]
                resp.results = visible
                resp.total = len(visible)
                return resp.__dict__
            artifacts = self.list(limit=limit, tags=tag_list)
            visible = [a for a in artifacts if _can_read(a, caller_user, caller_tenant)]
            return {"artifacts": [a.to_dict() for a in visible], "total": len(visible)}

        @app.get("/kcp/v1/artifacts/{artifact_id}")
        def get_artifact(artifact_id: str, caller: tuple = Depends(_caller_identity)):
            caller_user, caller_tenant = caller
            a = self.get(artifact_id)
            if not a:
                raise HTTPException(404, "Artifact not found")
            if not _can_read(a, caller_user, caller_tenant):
                raise HTTPException(403, "Access denied")
            return a.to_dict()

        @app.get("/kcp/v1/artifacts/{artifact_id}/content")
        def get_content(artifact_id: str, caller: tuple = Depends(_caller_identity)):
            caller_user, caller_tenant = caller
            a = self.get(artifact_id)
            if not a:
                raise HTTPException(404, "Content not found")
            if not _can_read(a, caller_user, caller_tenant):
                raise HTTPException(403, "Access denied")
            content = self.get_content(artifact_id)
            if content is None:
                raise HTTPException(404, "Content not found")
            return JSONResponse({"content": base64.b64encode(content).decode()})

        @app.get("/kcp/v1/artifacts/{artifact_id}/lineage")
        def get_lineage(artifact_id: str):
            return {"lineage": self.lineage(artifact_id)}

        @app.get("/kcp/v1/artifacts/{artifact_id}/replication")
        def get_replication(artifact_id: str):
            """Return replication status — how many peers have a confirmed copy."""
            a = self.get(artifact_id)
            if not a:
                raise HTTPException(404, "Artifact not found")
            status = self.store.get_replication_status(artifact_id)
            # Enrich with replication factor config
            rf = int(self.store.get_config("replication_factor") or len(self.peers) or 1)
            status["replication_factor"] = rf
            status["complete"] = status["count"] >= rf
            return status

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
            """
            Receive artifact from another peer via sync.
            Records replication ACK.
            """
            artifact_id = body.get("id", "")
            is_new = self.store.import_artifact(body)
            
            # Record replication ACK (sender identified via user_id in payload)
            if artifact_id:
                try:
                    # Use peer's user_id from payload as identifier
                    sender_id = body.get("user_id", "unknown")
                    self.store.record_replication_ack(artifact_id, sender_id)
                except Exception:
                    # Don't fail sync if ACK recording fails
                    pass
            
            return {"accepted": is_new, "id": artifact_id}

        # Peers — discovery & registry
        @app.get("/kcp/v1/peers")
        def list_peers():
            """
            Return all known peers enriched with this node's own info.
            Used by clients and other peers for gossip-based discovery.
            """
            raw = self.get_peers()
            peers_out = []
            for p in raw:
                peers_out.append({
                    "node_id": p.get("id", ""),
                    "url": p.get("url", ""),
                    "name": p.get("name", ""),
                    "last_seen": p.get("last_seen", ""),
                    "added_at": p.get("added_at", ""),
                })
            # Also expose self so other peers can learn about us
            self_url = self._self_url()
            if self_url:
                self_entry = {
                    "node_id": self.node_id,
                    "url": self_url,
                    "name": self.store.get_config("node_name") or "",
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                    "added_at": "",
                }
                # Prepend self if not already listed
                if not any(p["url"].rstrip("/") == self_url for p in peers_out):
                    peers_out.insert(0, self_entry)
            return {"peers": peers_out, "total": len(peers_out), "node_id": self.node_id}

        @app.post("/kcp/v1/peers")
        def register_peer(body: dict):
            """Register a peer manually by URL."""
            pid = self.add_peer(body.get("url", ""), body.get("name", ""))
            return {"peer_id": pid}

        @app.post("/kcp/v1/peers/announce")
        def announce_peer(body: dict):
            """
            A peer announces itself to this node.
            Body: {"url": "https://...", "node_id": "...", "name": "..."}
            Triggers gossip: this node learns the announcing peer's known peers.
            """
            url = body.get("url", "").rstrip("/")
            if not url:
                raise HTTPException(400, "url required")
            self.store.upsert_peer(
                url=url,
                name=body.get("name", ""),
                node_id=body.get("node_id", ""),
                public_key=body.get("public_key", ""),
            )
            return {"accepted": True, "node_id": self.node_id}

        @app.get("/kcp/v1/network-status")
        def network_status():
            """
            Server-side health aggregation of all known peers.
            Called by status.html so the browser never needs to reach peer hostnames
            directly — this node probes them internally (localhost or LAN) and
            returns a single JSON payload with CORS headers.
            """
            import urllib.request
            import urllib.error
            import time

            # Build probe list: self (via localhost) + all known peers
            known = self.store.get_peers()
            self_url = self._self_url()
            self_public_url = self_url  # used for display only

            # Probe self via localhost if port is known (no DNS needed)
            self_probe_url = self_public_url
            if hasattr(self, '_port') and self._port:
                self_probe_url = f"http://127.0.0.1:{self._port}"

            probe_urls: list[dict] = []
            if self_probe_url:
                probe_urls.append({
                    "url": self_probe_url,
                    "display_url": self_public_url or self_probe_url,
                    "name": "self",
                })
            for p in known:
                u = p.get("url", "").rstrip("/")
                if u and u != self_url.rstrip("/"):
                    probe_urls.append({"url": u, "display_url": u, "name": p.get("name", "")})

            results = []
            for entry in probe_urls:
                probe_url = entry["url"].rstrip("/") + "/kcp/v1/health"
                display_url = entry.get("display_url", entry["url"])
                t0 = time.monotonic()
                try:
                    req = urllib.request.Request(probe_url, headers={"User-Agent": "kcp-network-status/1.0"})
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        ms = int((time.monotonic() - t0) * 1000)
                        data = json.loads(resp.read().decode())
                        results.append({
                            "name": entry["name"],
                            "url": display_url,
                            "status": "online",
                            "latency_ms": ms,
                            "node_id": data.get("node_id", ""),
                            "artifacts": data.get("artifacts"),
                            "peers": data.get("peers"),
                            "kcp_version": data.get("kcp_version", ""),
                        })
                except Exception as e:
                    ms = int((time.monotonic() - t0) * 1000)
                    results.append({
                        "name": entry["name"],
                        "url": display_url,
                        "status": "offline",
                        "latency_ms": ms,
                        "error": str(e)[:120],
                    })

            online = sum(1 for r in results if r["status"] == "online")
            total = len(results)
            return {
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "summary": "operational" if online == total else ("degraded" if online > 0 else "down"),
                "online": online,
                "total": total,
                "peers": results,
            }

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

        self._port = port  # stored so network-status can probe self via localhost
        app = self.create_app()
        logger.info("KCP Node serving at http://%s:%d", host, port)
        logger.info("Web UI: http://localhost:%d/ui", port)
        logger.info("Node ID: %s", self.node_id)
        logger.info("User: %s", self.user_id)
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


    # ─── Export / Import (offline sharing) ─────────────────────

    def export_artifact(self, artifact_id: str, include_content: bool = True) -> dict | None:
        """
        Export an artifact as a portable, self-contained JSON dict.
        Can be saved to file and shared by any means (email, drive, chat).
        The recipient can import it and verify the signature.
        """
        artifact = self.store.get(artifact_id)
        if not artifact:
            return None

        export = artifact.to_dict()
        export["_kcp_export"] = {
            "version": "1",
            "exported_by": self.user_id,
            "exported_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(),
            "node_id": self.node_id,
            "public_key": self.public_key.hex(),
        }

        if include_content:
            content = self.store.get_content(artifact.content_hash)
            if content:
                import base64
                export["_content_b64"] = base64.b64encode(content).decode("utf-8")

        # Include lineage chain
        chain = self.store.get_lineage(artifact_id)
        if len(chain) > 1:
            export["_lineage"] = chain

        return export

    def export_to_file(self, artifact_id: str, output_path: str = "") -> str | None:
        """Export artifact to a JSON file. Returns the file path."""
        data = self.export_artifact(artifact_id)
        if not data:
            return None

        if not output_path:
            slug = data.get("title", "artifact").lower()
            slug = __import__("re").sub(r"[^a-z0-9]+", "-", slug).strip("-")[:50]
            output_path = str(
                __import__("pathlib").Path.home() / "Downloads" / f"kcp-{slug}.json"
            )

        import json
        __import__("pathlib").Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        __import__("pathlib").Path(output_path).write_text(
            json.dumps(data, indent=2, ensure_ascii=False)
        )
        return output_path

    def import_from_dict(self, data: dict, verify: bool = True) -> tuple[bool, str]:
        """
        Import an artifact from an exported dict.
        Verifies signature if public key is available.
        Returns (success, message).
        """
        # Check if already exists
        if self.store.get(data.get("id", "")):
            return False, f"Artifact already exists: {data['id']}"

        # Verify signature if requested
        if verify and "_kcp_export" in data:
            pub_hex = data["_kcp_export"].get("public_key", "")
            if pub_hex:
                try:
                    pub_key = bytes.fromhex(pub_hex)
                    from .crypto import verify_artifact
                    clean = {k: v for k, v in data.items() if not k.startswith("_")}
                    if not verify_artifact(clean, pub_key):
                        return False, "⚠️ Signature verification FAILED. Artifact may be tampered."
                except Exception as e:
                    return False, f"Signature check error: {e}"

        # Import
        is_new = self.store.import_artifact(data)
        if is_new:
            author = data.get("user_id", "unknown")
            return True, f"✅ Imported: '{data.get('title', 'Untitled')}' by {author}"
        return False, "Artifact already exists"

    def import_from_file(self, file_path: str, verify: bool = True) -> tuple[bool, str]:
        """Import artifact from a JSON file."""
        import json
        content = __import__("pathlib").Path(file_path).read_text()
        data = json.loads(content)
        return self.import_from_dict(data, verify=verify)
