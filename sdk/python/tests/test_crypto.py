"""
Tests for KCP Cryptographic Operations (crypto.py)
"""
import pytest
from kcp.crypto import generate_keypair, sign_artifact, hash_content, verify_artifact


class TestGenerateKeypair:
    def test_returns_two_byte_objects(self):
        priv, pub = generate_keypair()
        assert isinstance(priv, bytes)
        assert isinstance(pub, bytes)

    def test_private_key_32_bytes(self):
        priv, _ = generate_keypair()
        assert len(priv) == 32

    def test_public_key_32_bytes(self):
        _, pub = generate_keypair()
        assert len(pub) == 32

    def test_each_call_generates_unique_keys(self):
        priv1, pub1 = generate_keypair()
        priv2, pub2 = generate_keypair()
        assert priv1 != priv2
        assert pub1 != pub2


class TestHashContent:
    def test_returns_hex_string(self):
        h = hash_content(b"hello")
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 = 32 bytes = 64 hex chars

    def test_deterministic(self):
        assert hash_content(b"test") == hash_content(b"test")

    def test_different_content_different_hash(self):
        assert hash_content(b"foo") != hash_content(b"bar")

    def test_empty_bytes(self):
        h = hash_content(b"")
        assert len(h) == 64

    def test_known_value(self):
        # SHA-256 of empty string
        expected = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert hash_content(b"") == expected


class TestSignAndVerify:
    def test_sign_returns_hex_string(self):
        priv, _ = generate_keypair()
        payload = {"title": "Test", "user_id": "alice", "tenant_id": "corp"}
        sig = sign_artifact(payload, priv)
        assert isinstance(sig, str)
        assert len(sig) == 128  # Ed25519 = 64 bytes = 128 hex chars

    def test_verify_valid_signature(self):
        priv, pub = generate_keypair()
        payload = {"title": "Test", "user_id": "alice", "tenant_id": "corp"}
        sig = sign_artifact(payload, priv)
        payload["signature"] = sig
        assert verify_artifact(payload, pub) is True

    def test_verify_invalid_signature(self):
        priv, pub = generate_keypair()
        payload = {"title": "Test", "user_id": "alice", "tenant_id": "corp"}
        payload["signature"] = "a" * 128  # fake sig
        assert verify_artifact(payload, pub) is False

    def test_verify_wrong_public_key(self):
        priv, _ = generate_keypair()
        _, wrong_pub = generate_keypair()
        payload = {"title": "Test", "user_id": "alice", "tenant_id": "corp"}
        sig = sign_artifact(payload, priv)
        payload["signature"] = sig
        assert verify_artifact(payload, wrong_pub) is False

    def test_verify_missing_signature(self):
        _, pub = generate_keypair()
        payload = {"title": "Test", "user_id": "alice", "tenant_id": "corp"}
        assert verify_artifact(payload, pub) is False

    def test_sign_ignores_existing_signature_field(self):
        priv, pub = generate_keypair()
        payload = {
            "title": "Test",
            "user_id": "alice",
            "tenant_id": "corp",
            "signature": "old-sig",
        }
        sig = sign_artifact(payload, priv)
        payload["signature"] = sig
        assert verify_artifact(payload, pub) is True

    def test_tampered_payload_fails_verification(self):
        priv, pub = generate_keypair()
        payload = {"title": "Original", "user_id": "alice", "tenant_id": "corp"}
        sig = sign_artifact(payload, priv)
        payload["signature"] = sig
        # Tamper after signing
        payload["title"] = "Tampered"
        assert verify_artifact(payload, pub) is False
