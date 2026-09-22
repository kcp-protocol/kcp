#!/usr/bin/env python3
"""
Generate cross-language test vectors for the KCP Rust SDK.

This script executes the **reference Python implementation**
(`sdk/python/kcp/models.py` + `sdk/python/kcp/crypto.py`) and dumps the
resulting canonical payloads, Ed25519 signatures, SHA-256 hashes, HKDF keys
and AES-256-GCM blobs to `vectors.json`. The Rust test-suite loads that file
and asserts byte-for-byte compatibility.

Usage (from the repository root, one container at a time):

    docker run --rm -v "$PWD:/w" -v /tmp/kcp-pylibs:/pylibs \
        -e PYTHONPATH=/pylibs python:3.12-slim \
        python /w/sdk/rust/tests/fixtures/gen_vectors.py

The modules are loaded by file path (not `import kcp`) so that the package
`__init__.py` (which pulls optional deps such as httpx/fastapi) is not needed.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys

REPO = os.environ.get("KCP_REPO", "/w")
PKG = os.path.join(REPO, "sdk", "python", "kcp")
OUT = os.path.join(REPO, "sdk", "rust", "tests", "fixtures", "vectors.json")


def load_module(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


models = load_module(os.path.join(PKG, "models.py"), "kcp_ref_models")
crypto = load_module(os.path.join(PKG, "crypto.py"), "kcp_ref_crypto")

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402

# Fixed seed → fully deterministic vectors. cryptography's raw private key
# bytes are the 32-byte Ed25519 seed, which is exactly what ed25519-dalek's
# `SigningKey::from_bytes` expects.
SEED = bytes(range(32))
_priv_obj = Ed25519PrivateKey.from_private_bytes(SEED)
PRIV = _priv_obj.private_bytes_raw()
PUB = _priv_obj.public_key().public_bytes_raw()
assert PRIV == SEED


def canonical_of(d: dict) -> str:
    payload = {k: v for k, v in d.items() if k != "signature"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def artifact_vector(name: str, data: dict) -> dict:
    artifact = models.KnowledgeArtifact.from_dict(data)
    d = artifact.to_dict()
    return {
        "name": name,
        "input": data,
        "to_dict": d,
        "canonical": canonical_of(d),
        "signature": crypto.sign_artifact(d, PRIV),
    }


TS = "2026-01-02T03:04:05.123456+00:00"
H_HELLO = crypto.hash_content(b"hello kcp")

CASES = [
    (
        "minimal_public",
        {
            "id": "11111111-1111-4111-8111-111111111111",
            "version": "1",
            "user_id": "alice@acme.com",
            "tenant_id": "acme-corp",
            "timestamp": TS,
            "format": "markdown",
            "visibility": "public",
            "title": "Minimal Artifact",
            "content_hash": H_HELLO,
        },
    ),
    (
        "full_optional_fields",
        {
            "id": "22222222-2222-4222-8222-222222222222",
            "version": "2",
            "user_id": "bob@acme.com",
            "tenant_id": "acme-corp",
            "timestamp": TS,
            "format": "json",
            "visibility": "team",
            "title": "Quarterly Revenue Analysis",
            "content_hash": H_HELLO,
            "team": "finance",
            "tags": ["finance", "revenue", "q1"],
            "source": "agent:analyst-v3",
            "summary": "Revenue up 12% QoQ",
            "content_url": "https://cdn.example.com/a.json",
            "lineage": {
                "query": "quarterly revenue 2026",
                "data_sources": ["warehouse:finance", "csv:ledger"],
                "agent": "analyst-v3",
                "parent_reports": ["33333333-3333-4333-8333-333333333333"],
            },
            "acl": {
                "allowed_tenants": ["acme-corp"],
                "allowed_users": ["bob@acme.com", "carol@acme.com"],
                "allowed_teams": ["finance"],
            },
            "embeddings": [0.5, 0.25, 1.0, -0.125],
        },
    ),
    (
        "unicode_and_escaping",
        {
            "id": "44444444-4444-4444-8444-444444444444",
            "version": "1",
            "user_id": "josé@acme.com",
            "tenant_id": "acme-corp",
            "timestamp": TS,
            "format": "text",
            "visibility": "org",
            "title": 'Relatório ção ã ê — 🚀 "quoted" \\slash\\ tab\there',
            "summary": "line1\nline2 with emoji 🧠 and çedilla",
            "content_hash": crypto.hash_content("Conteúdo com acentos: ção".encode()),
            "tags": ["ñandú", "ação"],
        },
    ),
    (
        "empty_content_hash",
        {
            "id": "55555555-5555-4555-8555-555555555555",
            "version": "1",
            "user_id": "alice@acme.com",
            "tenant_id": "acme-corp",
            "timestamp": TS,
            "format": "text",
            "visibility": "private",
            "title": "Untitled",
            "content_hash": "",
        },
    ),
    (
        "lineage_only",
        {
            "id": "66666666-6666-4666-8666-666666666666",
            "version": "1",
            "user_id": "alice@acme.com",
            "tenant_id": "acme-corp",
            "timestamp": TS,
            "format": "csv",
            "visibility": "public",
            "title": "Derived Report",
            "content_hash": crypto.hash_content(b"derived"),
            "lineage": {"query": "q", "data_sources": [], "agent": "", "parent_reports": []},
        },
    ),
]

HASH_INPUTS = [b"", b"hello kcp", "Conteúdo com acentos: ção".encode(), bytes(range(256))]

CONTENT_KEY_IDS = [
    "11111111-1111-4111-8111-111111111111",
    "artifact-123",
    "🐍-unicode-id",
]

AES_CASES = [
    ("aes-hello", "artifact-123", bytes(range(12)), b"hello world"),
    ("aes-unicode", "11111111-1111-4111-8111-111111111111", bytes(range(12, 24)),
     "Conteúdo secreto ção 🚀".encode()),
    ("aes-empty", "empty-id", bytes(range(12)), b""),
]

RAW_PAYLOADS = [
    {"title": "Test", "user_id": "alice", "tenant_id": "corp"},
    {"b": "x", "a": 1, "c": [1, 2, 3], "d": {"z": True, "y": None}},
    {"title": 'Quote " and é and \\ backslash'},
]


def main() -> int:
    vectors = {
        "generator": "sdk/python/kcp (models.py + crypto.py, reference implementation)",
        "seed_hex": SEED.hex(),
        "private_key_hex": PRIV.hex(),
        "public_key_hex": PUB.hex(),
        "artifacts": [artifact_vector(n, d) for n, d in CASES],
        "hashes": [
            {
                "input_hex": b.hex(),
                "input_utf8": b.decode("utf-8", "replace"),
                "sha256": crypto.hash_content(b),
            }
            for b in HASH_INPUTS
        ],
        "content_keys": [
            {"artifact_id": aid, "key_hex": crypto.derive_content_key(PRIV, aid).hex()}
            for aid in CONTENT_KEY_IDS
        ],
        "aes_gcm": [
            {
                "name": name,
                "artifact_id": aid,
                "key_hex": crypto.derive_content_key(PRIV, aid).hex(),
                "nonce_hex": nonce.hex(),
                "plaintext_hex": pt.hex(),
                "plaintext_utf8": pt.decode("utf-8", "replace"),
                # Reference wire format: magic(7) | nonce(12) | ciphertext+tag
                "blob_hex": (b"KCPENC1" + nonce + AESGCM(crypto.derive_content_key(PRIV, aid)).encrypt(nonce, pt, None)).hex(),
            }
            for name, aid, nonce, pt in AES_CASES
        ],
        "raw_sign": [
            {
                "payload": p,
                "canonical": canonical_of(p),
                "signature": crypto.sign_artifact(p, PRIV),
            }
            for p in RAW_PAYLOADS
        ],
        "is_encrypted_false": ["", "plain text", "KCPEN", "KCPENC"],
    }

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(vectors, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    print(f"wrote {OUT}")
    print(f"public_key={PUB.hex()}")
    for v in vectors["artifacts"]:
        print(f"  {v['name']}: sig={v['signature'][:32]}... canon_len={len(v['canonical'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
