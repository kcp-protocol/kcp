"""
KCP — Knowledge Context Protocol
Python SDK v0.2.0

Reference implementation: embedded node, local storage, hub client, P2P sync.

Quick start (embedded — no server needed):
    from kcp import KCPNode
    node = KCPNode(user_id="alice@acme.com")
    atom = node.publish("My Analysis", content="...", format="markdown", tags=["data"])
    results = node.search("analysis")

Semantic/hybrid search (opt-in, local vector index):
    node = KCPNode(user_id="alice@acme.com", search_backend="sqlite-vss",
                   embedding_model="ollama:nomic-embed-text")  # or "hash" (offline)
    results = node.search("rate limiting", mode="semantic")   # or mode="hybrid"

With HTTP server (for P2P sharing):
    node = KCPNode(user_id="alice@acme.com")
    node.serve(port=8800)  # Opens Web UI at http://localhost:8800/ui

Identity management:
    from kcp.identity import create_identity, recover_identity
    identity = create_identity()  # Shows 12-word recovery phrase
    # Or: kcp identity create (CLI)
"""

__version__ = "0.2.0"
__protocol_version__ = "1"

from .client import KCPClient
from .crdt import GSet
from .crypto import generate_keypair, hash_content, sign_artifact, verify_artifact
from .embeddings import (
    BaseEmbeddingProvider,
    CallableEmbeddingProvider,
    EmbeddingError,
    HashEmbeddingProvider,
    OllamaEmbeddingProvider,
    OpenAIEmbeddingProvider,
    SemanticSearchUnavailableError,
    resolve_embedding_provider,
)
from .hub import HubBackend
from .lineage_graph import ForkPair, LineageGraph, SyncProof, detect_forks
from .merkle import LineageVerificationError, MerkleDAG, MerkleProof, verify_proof
from .models import ACL, KnowledgeArtifact, Lineage, SearchResponse, SearchResult
from .node import KCPNode
from .store import LocalStore
from .vector_index import VectorIndex, VectorIndexError

# Identity (optional import - requires mnemonic package)
try:
    from .identity import (
        IdentityStrength as IdentityStrength,
    )
    from .identity import (
        KCPIdentity as KCPIdentity,
    )
    from .identity import (
        create_identity as create_identity,
    )
    from .identity import (
        recover_identity as recover_identity,
    )

    _HAS_IDENTITY = True
except ImportError:
    _HAS_IDENTITY = False

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
    # Lineage · Merkle · CRDT (RFC KCP-005)
    "LineageGraph",
    "MerkleDAG",
    "MerkleProof",
    "verify_proof",
    "LineageVerificationError",
    "GSet",
    "ForkPair",
    "SyncProof",
    "detect_forks",
    # Semantic search (issue #1)
    "VectorIndex",
    "VectorIndexError",
    "BaseEmbeddingProvider",
    "CallableEmbeddingProvider",
    "EmbeddingError",
    "HashEmbeddingProvider",
    "OllamaEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "SemanticSearchUnavailableError",
    "resolve_embedding_provider",
    # Crypto
    "generate_keypair",
    "sign_artifact",
    "verify_artifact",
    "hash_content",
]

# Add identity exports if available
if _HAS_IDENTITY:
    __all__.extend(
        [
            "create_identity",
            "recover_identity",
            "KCPIdentity",
            "IdentityStrength",
        ]
    )
