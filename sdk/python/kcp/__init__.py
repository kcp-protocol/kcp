"""
KCP — Knowledge Context Protocol
Python SDK v0.2.0

Reference implementation: embedded node, local storage, hub client, P2P sync.

Quick start (embedded — no server needed):
    from kcp import KCPNode
    node = KCPNode(user_id="alice@acme.com")
    atom = node.publish("My Analysis", content="...", format="markdown", tags=["data"])
    results = node.search("analysis")

With HTTP server (for P2P sharing):
    node = KCPNode(user_id="alice@acme.com")
    node.serve(port=8800)  # Opens Web UI at http://localhost:8800/ui
"""

__version__ = "0.2.0"
__protocol_version__ = "1"

from .models import KnowledgeArtifact, Lineage, ACL, SearchResult, SearchResponse
from .crypto import generate_keypair, sign_artifact, verify_artifact, hash_content
from .store import LocalStore
from .node import KCPNode
from .hub import HubBackend
from .client import KCPClient

__all__ = [
    # Core
    "KCPNode",
    "LocalStore",
    "HubBackend",
    "KCPClient",
    # Models
    "KnowledgeArtifact",
    "Lineage",
    "ACL",
    "SearchResult",
    "SearchResponse",
    # Crypto
    "generate_keypair",
    "sign_artifact",
    "verify_artifact",
    "hash_content",
]
