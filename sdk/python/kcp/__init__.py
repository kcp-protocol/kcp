"""
KCP — Knowledge Context Protocol
Python SDK v0.1.0

Reference implementation of the KCP client.
"""

__version__ = "0.1.0"
__protocol_version__ = "1"

from .client import KCPClient
from .models import KnowledgeArtifact, Lineage, ACL, SearchResult
from .crypto import generate_keypair, sign_artifact, verify_artifact

__all__ = [
    "KCPClient",
    "KnowledgeArtifact",
    "Lineage",
    "ACL",
    "SearchResult",
    "generate_keypair",
    "sign_artifact",
    "verify_artifact",
]
