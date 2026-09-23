"""
KCP Cryptographic Operations

Ed25519 signing + SHA-256 hashing + AES-256-GCM content encryption.

Encryption model:
  - Content key derived from Ed25519 private key via HKDF-SHA256
  - AES-256-GCM with random 12-byte nonce (prepended to ciphertext)
  - Only artifacts with visibility="private" are encrypted at rest
  - Public artifacts are stored as plaintext (discoverable by design)
"""

from __future__ import annotations

import hashlib
import json

#: Raised verbatim by every entry point when the optional dependency is missing.
_MISSING_CRYPTO_MSG = "KCP crypto requires 'cryptography' package. Install with: pip install cryptography"


def generate_keypair() -> tuple[bytes, bytes]:
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
    except ImportError as exc:
        raise ImportError(_MISSING_CRYPTO_MSG) from exc


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
    except ImportError as exc:
        raise ImportError(_MISSING_CRYPTO_MSG) from exc

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
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise ImportError(_MISSING_CRYPTO_MSG) from exc

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


# ─── AES-256-GCM Content Encryption ───────────────────────────

_ENCRYPTION_MAGIC = b"KCPENC1"  # 7-byte magic prefix — marks encrypted blobs


def derive_content_key(private_key: bytes, artifact_id: str) -> bytes:
    """
    Derive a 256-bit AES key from the Ed25519 private key + artifact ID.

    Uses HKDF-SHA256 so each artifact gets a unique key even from the
    same private key. The artifact ID is the HKDF info parameter.

    Args:
        private_key: Ed25519 private key bytes (32 bytes)
        artifact_id: UUID string of the artifact

    Returns:
        32-byte AES-256 key
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=f"kcp-content-key:{artifact_id}".encode(),
    )
    return hkdf.derive(private_key)


def encrypt_content(content: bytes, key: bytes) -> bytes:
    """
    Encrypt content with AES-256-GCM.

    Wire format:
        KCPENC1 (7 bytes) | nonce (12 bytes) | ciphertext+tag (N+16 bytes)

    Args:
        content: Plaintext bytes
        key: 32-byte AES-256 key (from derive_content_key)

    Returns:
        Encrypted blob with magic prefix
    """
    import os

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, content, None)  # no AAD
    return _ENCRYPTION_MAGIC + nonce + ciphertext


def decrypt_content(blob: bytes, key: bytes) -> bytes:
    """
    Decrypt an AES-256-GCM encrypted blob.

    Args:
        blob: Encrypted blob (with KCPENC1 magic prefix)
        key: 32-byte AES-256 key (from derive_content_key)

    Returns:
        Plaintext bytes

    Raises:
        ValueError: If blob is not a valid KCP encrypted blob
        cryptography.exceptions.InvalidTag: If decryption fails (tampered)
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    magic_len = len(_ENCRYPTION_MAGIC)
    if not blob[:magic_len] == _ENCRYPTION_MAGIC:
        raise ValueError("Not a KCP encrypted blob (missing KCPENC1 magic)")

    nonce = blob[magic_len : magic_len + 12]
    ciphertext = blob[magic_len + 12 :]

    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


def is_encrypted(blob: bytes) -> bool:
    """Return True if the blob was encrypted by KCP."""
    return blob[: len(_ENCRYPTION_MAGIC)] == _ENCRYPTION_MAGIC
