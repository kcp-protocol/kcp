"""
KCP Cryptographic Operations

Ed25519 signing and verification + SHA-256 content hashing.
"""

import hashlib
import json
from typing import Tuple


def generate_keypair() -> Tuple[bytes, bytes]:
    """
    Generate an Ed25519 keypair.

    Returns:
        (private_key, public_key) as bytes
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        private_key = Ed25519PrivateKey.generate()
        private_bytes = private_key.private_bytes_raw()
        public_bytes = private_key.public_key().public_bytes_raw()
        return private_bytes, public_bytes
    except ImportError:
        raise ImportError(
            "KCP crypto requires 'cryptography' package. "
            "Install with: pip install cryptography"
        )


def sign_artifact(artifact_dict: dict, private_key: bytes) -> str:
    """
    Sign a KCP artifact using Ed25519.

    Args:
        artifact_dict: The artifact payload (without signature)
        private_key: Ed25519 private key bytes

    Returns:
        Hex-encoded Ed25519 signature
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        raise ImportError(
            "KCP crypto requires 'cryptography' package. "
            "Install with: pip install cryptography"
        )

    # Remove signature field if present
    payload = {k: v for k, v in artifact_dict.items() if k != "signature"}

    # Canonical JSON (sorted keys, compact)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))

    # Sign
    key = Ed25519PrivateKey.from_private_bytes(private_key)
    signature = key.sign(canonical.encode("utf-8"))

    return signature.hex()


def verify_artifact(artifact_dict: dict, public_key: bytes) -> bool:
    """
    Verify the Ed25519 signature of a KCP artifact.

    Args:
        artifact_dict: The full artifact payload (with signature)
        public_key: Ed25519 public key bytes

    Returns:
        True if signature is valid, False otherwise
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except ImportError:
        raise ImportError(
            "KCP crypto requires 'cryptography' package. "
            "Install with: pip install cryptography"
        )

    signature_hex = artifact_dict.get("signature", "")
    if not signature_hex:
        return False

    # Reconstruct canonical payload
    payload = {k: v for k, v in artifact_dict.items() if k != "signature"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))

    try:
        key = Ed25519PublicKey.from_public_bytes(public_key)
        key.verify(bytes.fromhex(signature_hex), canonical.encode("utf-8"))
        return True
    except (InvalidSignature, ValueError):
        return False


def hash_content(content: bytes) -> str:
    """
    Compute SHA-256 hash of content.

    Args:
        content: Raw content bytes

    Returns:
        Lowercase hex-encoded SHA-256 hash
    """
    return hashlib.sha256(content).hexdigest()
