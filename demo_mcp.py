#!/usr/bin/env python3
"""
KCP MCP Bridge Demo
===================
Simulates a complete MCP session — no Claude Desktop required.

Demonstrates the 6 tools available to any AI assistant via the MCP Bridge:
  kcp_publish   — persist a knowledge artifact (signed + hashed)
  kcp_search    — full-text search across artifacts
  kcp_get       — retrieve a specific artifact by ID
  kcp_lineage   — trace the derivation DAG
  kcp_list      — list recent artifacts
  kcp_stats     — node statistics

Run:
    python demo_mcp.py

Or with make:
    make demo-mcp
    make demo-mcp-clean
"""

import os
import sys

# Allow running from repo root without installing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "sdk", "python"))

DB_PATH  = "/tmp/kcp-mcp-demo.db"
KEYS_DIR = "/tmp/kcp-mcp-demo-keys"


def _box(title: str):
    w = 60
    print("\n" + "═" * w)
    print(f"  {title}")
    print("═" * w)


def _step(emoji: str, tool: str, kwargs: dict):
    print(f"\n{emoji}  Tool: \033[36m{tool}\033[0m")
    for k, v in kwargs.items():
        s = str(v)
        print(f"   {k}: {s[:68]}{'…' if len(s) > 68 else ''}")


def _field(key: str, val):
    s = str(val) if val is not None else "—"
    print(f"   \033[32m{key}\033[0m: {s[:75]}{'…' if len(s) > 75 else ''}")


# ─── Tool implementations ─────────────────────────────────────

def tool_publish(node, title, content, tags=None, fmt="markdown",
                 summary="", visibility="private",
                 derived_from=None, mcp_session_id="demo"):
    from kcp.models import Lineage  # noqa: PLC0415
    lineage = Lineage(
        query=title,
        agent=f"mcp-demo | session:{mcp_session_id}",
    )
    artifact = node.publish(
        title=title,
        content=content,
        format=fmt,
        tags=tags or [],
        summary=summary,
        visibility=visibility,
        lineage=lineage,
        derived_from=derived_from,
    )
    return {
        "artifact_id": artifact.id,
        "uri": f"kcp://local/artifact/{artifact.id}",
        "content_hash": artifact.content_hash,
        "signature": artifact.signature,
    }


def tool_search(node, query, limit=10):
    resp = node.search(query, limit=limit)
    return {
        "total": resp.total,
        "results": [
            {
                "id": r.id,
                "title": r.title,
                "relevance": r.relevance,
                "uri": f"kcp://local/artifact/{r.id}",
            }
            for r in resp.results
        ],
    }


def tool_get(node, artifact_id, include_content=False):
    artifact = node.get(artifact_id)
    if not artifact:
        return {"error": f"Not found: {artifact_id}"}
    result = {
        "artifact_id": artifact.id,
        "title": artifact.title,
        "tags": artifact.tags,
        "format": artifact.format,
        "timestamp": artifact.timestamp,
        "content_hash": artifact.content_hash,
        "signature": artifact.signature,
        "uri": f"kcp://local/artifact/{artifact.id}",
    }
    if include_content:
        result["content"] = node.get_content(artifact_id) or ""
    return result


def tool_lineage(node, artifact_id):
    chain = node.lineage(artifact_id)
    return {"artifact_id": artifact_id, "depth": len(chain), "lineage": chain}


def tool_list(node, limit=10):
    artifacts = node.list(limit=limit)
    return {
        "total": len(artifacts),
        "artifacts": [
            {"id": a.id, "title": a.title, "uri": f"kcp://local/artifact/{a.id}"}
            for a in artifacts
        ],
    }


def tool_stats(node):
    s = node.stats()
    return {
        "artifact_count": s.get("artifacts", 0),
        "node_id": s.get("node_id", "local"),
        "db_path": DB_PATH,
    }


# ─── Main ─────────────────────────────────────────────────────

def main():
    from kcp import KCPNode

    _box("KCP MCP Bridge Demo — 6 tools simulation")
    print("  Simulates an AI assistant (Claude / Cursor / Windsurf)")
    print("  calling KCP tools to build a persistent knowledge base.")
    print(f"  Database: {DB_PATH}")

    node = KCPNode(
        user_id="mcp-demo-agent",
        tenant_id="demo",
        db_path=DB_PATH,
        keys_dir=KEYS_DIR,
    )

    # ── 1. kcp_publish — base artifact ──────────────────────
    _step("📝", "kcp_publish", {
        "title": "Distributed Tracing Best Practices",
        "tags": ["observability", "tracing", "opentelemetry"],
    })
    r1 = tool_publish(
        node,
        title="Distributed Tracing Best Practices",
        content=(
            "## OpenTelemetry Setup\n\n"
            "Use W3C TraceContext headers. Sampling: 10% prod / 100% dev.\n\n"
            "## Span Naming\n\nUse `service.operation` format.\n\n"
            "## Key Attributes\n\n`http.method`, `http.status_code`, `db.statement`."
        ),
        tags=["observability", "tracing", "opentelemetry"],
        summary="Best practices for distributed tracing with OpenTelemetry",
        mcp_session_id="demo-session-001",
    )
    artifact_id = r1["artifact_id"]
    _field("artifact_id", artifact_id[:16] + "…")
    _field("uri", r1["uri"])
    _field("signature", r1["signature"][:24] + "…")

    # ── 2. kcp_publish — derived ─────────────────────────────
    _step("📝", "kcp_publish (derived)", {
        "title": "Tracing in Async Python (asyncio + FastAPI)",
        "derived_from": artifact_id[:16] + "…",
    })
    r2 = tool_publish(
        node,
        title="Tracing in Async Python (asyncio + FastAPI)",
        content=(
            "## Building on Distributed Tracing Best Practices\n\n"
            "In async Python, context propagation is explicit:\n\n"
            "```python\n"
            "tracer = trace.get_tracer(__name__)\n"
            "async def handler():\n"
            "    with tracer.start_as_current_span('handler'):\n"
            "        await do_work()\n"
            "```"
        ),
        tags=["python", "asyncio", "tracing", "observability"],
        derived_from=artifact_id,
        mcp_session_id="demo-session-001",
    )
    derived_id = r2["artifact_id"]
    _field("artifact_id", derived_id[:16] + "…")
    _field("uri", r2["uri"])

    # ── 3. kcp_search ────────────────────────────────────────
    _step("🔍", "kcp_search", {"query": "opentelemetry tracing"})
    r3 = tool_search(node, "opentelemetry tracing")
    _field("total", r3["total"])
    for item in r3["results"][:3]:
        print(f"     - [{item['id'][:8]}…] {item['title']}  (relevance: {item['relevance']:.2f})")

    # ── 4. kcp_get ───────────────────────────────────────────
    _step("📄", "kcp_get", {"artifact_id": artifact_id[:16] + "…", "include_content": True})
    r4 = tool_get(node, artifact_id, include_content=True)
    _field("title", r4["title"])
    _field("tags", r4["tags"])
    _field("content_hash", r4["content_hash"][:32] + "…")
    _field("signature", r4["signature"][:24] + "…")
    preview = (r4.get("content") or b"")
    if isinstance(preview, bytes):
        preview = preview.decode("utf-8", errors="replace")
    preview = preview[:80].replace("\n", " ")
    _field("content", preview + "…")

    # ── 5. kcp_lineage ───────────────────────────────────────
    _step("🌳", "kcp_lineage", {"artifact_id": derived_id[:16] + "…"})
    r5 = tool_lineage(node, derived_id)
    _field("depth", r5["depth"])
    for i, item in enumerate(r5["lineage"]):
        indent = "  " * i
        parent = item.get("derived_from")
        suffix = f" ← from [{parent[:8]}…]" if parent else " (root)"
        print(f"     {indent}[{item['id'][:8]}…] {item['title']}{suffix}")

    # ── 6. kcp_list ──────────────────────────────────────────
    _step("📋", "kcp_list", {"limit": 5})
    r6 = tool_list(node, limit=5)
    _field("total", r6["total"])
    for item in r6["artifacts"]:
        print(f"     - [{item['id'][:8]}…] {item['title']}")

    # ── 7. kcp_stats ─────────────────────────────────────────
    _step("📊", "kcp_stats", {})
    r7 = tool_stats(node)
    _field("artifact_count", r7["artifact_count"])
    _field("node_id", r7["node_id"])
    _field("db_path", r7["db_path"])

    # ── Summary ──────────────────────────────────────────────
    print("\n" + "─" * 60)
    print("  ✅ All 6 MCP tools working!")
    print()
    print("  To connect Claude Desktop:")
    cfg = "~/Library/Application Support/Claude/claude_desktop_config.json"
    print(f"  $ cp mcp-server/claude_desktop_config.json '{cfg}'")
    print("  Restart Claude Desktop → tools appear automatically.")
    print()
    print("  To connect Cursor / Windsurf:")
    print("  Add mcp-server/ path to your editor's MCP settings.")
    print()
    print("  Full docs: mcp-server/README.md")
    print("─" * 60 + "\n")


if __name__ == "__main__":
    main()
