#!/usr/bin/env python3
"""
Reverse-direction interop check: read a database written by the **Rust SDK**
with the **reference Python SDK** and re-verify every Ed25519 signature.

Usage (from the repository root, after `cargo run --example roundtrip_write`):

    docker run --rm -v "$PWD:/w" -v /tmp/kcp-pylibs:/pylibs \
        -e PYTHONPATH=/pylibs python:3.12-slim \
        python /w/sdk/rust/tests/fixtures/verify_rust_db.py /tmp/kcp-db

Exits non-zero if any check fails.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile

REPO = os.environ.get("KCP_REPO", "/w")
PY_SRC = os.path.join(REPO, "sdk", "python", "kcp")


def reference_modules():
    """Load the reference package from a scratch copy so `store`'s relative
    imports work without pulling the optional HTTP deps."""
    pkg_root = tempfile.mkdtemp(prefix="kcp-ref-")
    pkg_dir = os.path.join(pkg_root, "kcp")
    os.makedirs(pkg_dir, exist_ok=True)
    for name in ["__init__.py", "models.py", "crypto.py", "store.py", "content_store.py"]:
        src = os.path.join(PY_SRC, name)
        if name == "__init__.py":
            open(os.path.join(pkg_dir, name), "w").close()
            continue
        shutil.copy(src, pkg_dir)
    sys.path.insert(0, pkg_root)
    sys.modules.pop("kcp", None)
    import kcp.store as store  # noqa: E402
    import kcp.crypto as crypto  # noqa: E402
    return store, crypto


def main() -> int:
    db_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kcp-db"
    report_path = os.path.join(db_dir, "rust_report.json")
    report = json.load(open(report_path))
    store_mod, crypto = reference_modules()

    store = store_mod.LocalStore(os.path.join(db_dir, "kcp.db"))
    public_key = bytes.fromhex(report["public_key_hex"])

    failures = []
    for expected in report["artifacts"]:
        artifact = store.get(expected["id"])
        if artifact is None:
            failures.append(f"{expected['id']}: not found by the Python SDK")
            continue

        if artifact.title != expected["title"]:
            failures.append(f"{expected['id']}: title mismatch {artifact.title!r}")
        if artifact.content_hash != expected["content_hash"]:
            failures.append(f"{expected['id']}: content_hash mismatch")
        if artifact.signature != expected["signature"]:
            failures.append(f"{expected['id']}: signature mismatch")

        # Re-verify the Ed25519 signature with the reference verifier.
        if not crypto.verify_artifact(artifact.to_dict(), public_key):
            failures.append(f"{expected['id']}: Python could NOT verify the Rust signature")

        print(f"ok  {expected['title']:<28} {artifact.visibility:<8} sig={artifact.signature[:16]}…")

    # Lineage written by Rust must be walkable by Python.
    derived = report["artifacts"][1]["id"]
    chain = store.get_lineage(derived)
    if [e["title"] for e in chain] != ["Rust written artifact", "Rust derived artifact"]:
        failures.append(f"lineage chain mismatch: {[e['title'] for e in chain]}")
    else:
        print(f"ok  lineage chain root→leaf: {[e['title'] for e in chain]}")

    # Search (FTS5 index written by Rust) must work from Python.
    hits = store.search("Python").results
    if not any(h.id == report["artifacts"][0]["id"] for h in hits):
        failures.append("FTS5 search from Python did not find the Rust-written artifact")
    else:
        print(f"ok  FTS5 search from Python: {len(hits)} hit(s)")

    # Public content must read back verbatim.
    content = store.get_content(report["artifacts"][0]["content_hash"])
    if not content or b"Written by the Rust SDK" not in content:
        failures.append("public content not readable / corrupted")
    else:
        print("ok  public content read back verbatim")

    # Private content must still be an encrypted blob Python cannot read.
    private_blob = store.get_content(report["artifacts"][2]["content_hash"])
    if private_blob is None or not private_blob[:7] == b"KCPENC1":
        failures.append("private artifact is not a KCPENC1 blob")
    else:
        print("ok  private content kept encrypted (KCPENC1)")

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(" -", f)
        return 1
    print("\nAll cross-language checks passed (Rust → Python).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
