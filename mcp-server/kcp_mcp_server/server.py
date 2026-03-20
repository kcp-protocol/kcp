"""
KCP MCP Server — Core

Implements the MCP server exposing KCPNode as tools.
"""

from __future__ import annotations

import os
import json
import sys
from typing import Any

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from kcp import KCPNode
from kcp.models import Lineage


# ─── Node Singleton ───────────────────────────────────────────

def _create_node() -> KCPNode:
    return KCPNode(
        user_id=os.environ.get("KCP_USER_ID", "mcp-agent"),
        tenant_id=os.environ.get("KCP_TENANT_ID", "local"),
        db_path=os.environ.get("KCP_DB_PATH", "~/.kcp/kcp.db"),
        keys_dir=os.environ.get("KCP_KEYS_DIR", "~/.kcp/keys"),
    )


# ─── Server Factory ───────────────────────────────────────────

def create_server() -> Server:
    node = _create_node()
    server = Server("kcp-mcp-server")

    # ── List Tools ────────────────────────────────────────────

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="kcp_publish",
                description=(
                    "Publish a knowledge artifact to KCP. "
                    "Use this to persist any valuable AI-generated content — analyses, "
                    "summaries, decisions, code reviews, etc. — with cryptographic "
                    "identity and lineage tracking."
                ),
                inputSchema={
                    "type": "object",
                    "required": ["title", "content"],
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Human-readable title for the artifact",
                        },
                        "content": {
                            "type": "string",
                            "description": "The content to persist (markdown, text, JSON, etc.)",
                        },
                        "format": {
                            "type": "string",
                            "enum": ["markdown", "text", "json", "html", "csv"],
                            "default": "markdown",
                            "description": "Content format",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Keywords for discovery (e.g. ['architecture', 'rate-limiting'])",
                        },
                        "summary": {
                            "type": "string",
                            "description": "Brief description (max 500 chars) for search results",
                        },
                        "visibility": {
                            "type": "string",
                            "enum": ["public", "org", "team", "private"],
                            "default": "private",
                            "description": "Access control tier",
                        },
                        "derived_from": {
                            "type": "string",
                            "description": "artifact_id of parent artifact (lineage tracking)",
                        },
                        "source": {
                            "type": "string",
                            "description": "What generated this (e.g. 'claude-3.7-sonnet', 'cursor-agent')",
                        },
                        "mcp_session_id": {
                            "type": "string",
                            "description": "MCP session identifier for bridge lineage tracking",
                        },
                    },
                },
            ),
            types.Tool(
                name="kcp_search",
                description=(
                    "Search KCP knowledge artifacts by text query. "
                    "Use this BEFORE generating new content to check if relevant "
                    "knowledge already exists. Enables the AI to build on past work "
                    "instead of starting from scratch."
                ),
                inputSchema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Natural language search query",
                        },
                        "limit": {
                            "type": "integer",
                            "default": 10,
                            "description": "Maximum number of results to return",
                        },
                    },
                },
            ),
            types.Tool(
                name="kcp_get",
                description=(
                    "Retrieve a specific knowledge artifact by its artifact_id. "
                    "Returns full metadata and content. Use after kcp_search to "
                    "get the full content of a relevant artifact."
                ),
                inputSchema={
                    "type": "object",
                    "required": ["artifact_id"],
                    "properties": {
                        "artifact_id": {
                            "type": "string",
                            "description": "UUID of the artifact to retrieve",
                        },
                        "include_content": {
                            "type": "boolean",
                            "default": True,
                            "description": "Whether to include the full content body",
                        },
                    },
                },
            ),
            types.Tool(
                name="kcp_lineage",
                description=(
                    "Trace the full lineage chain of a knowledge artifact. "
                    "Returns the DAG from root to current artifact, showing "
                    "how knowledge evolved over time."
                ),
                inputSchema={
                    "type": "object",
                    "required": ["artifact_id"],
                    "properties": {
                        "artifact_id": {
                            "type": "string",
                            "description": "UUID of the artifact to trace",
                        },
                    },
                },
            ),
            types.Tool(
                name="kcp_list",
                description=(
                    "List recent knowledge artifacts. "
                    "Optionally filter by tags."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "default": 20,
                            "description": "Maximum number of artifacts to return",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by tags",
                        },
                    },
                },
            ),
            types.Tool(
                name="kcp_stats",
                description="Get KCP node statistics (artifact count, storage, node identity).",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
        ]

    # ── Call Tools ────────────────────────────────────────────

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict[str, Any]
    ) -> list[types.TextContent]:

        try:
            if name == "kcp_publish":
                return await _kcp_publish(node, arguments)
            elif name == "kcp_search":
                return await _kcp_search(node, arguments)
            elif name == "kcp_get":
                return await _kcp_get(node, arguments)
            elif name == "kcp_lineage":
                return await _kcp_lineage(node, arguments)
            elif name == "kcp_list":
                return await _kcp_list(node, arguments)
            elif name == "kcp_stats":
                return await _kcp_stats(node, arguments)
            else:
                return [types.TextContent(
                    type="text",
                    text=json.dumps({"error": f"Unknown tool: {name}"}),
                )]
        except Exception as e:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": str(e), "tool": name}),
            )]

    return server


# ─── Tool Implementations ─────────────────────────────────────

async def _kcp_publish(node: KCPNode, args: dict) -> list[types.TextContent]:
    title = args["title"]
    content = args["content"]
    fmt = args.get("format", "markdown")
    tags = args.get("tags", [])
    summary = args.get("summary", "")
    visibility = args.get("visibility", "private")
    derived_from = args.get("derived_from")
    source = args.get("source", "mcp-bridge")
    mcp_session_id = args.get("mcp_session_id")

    # Build lineage with MCP bridge fields
    lineage = Lineage(
        query=f"Published via MCP tool call: {title}",
        agent=source,
        data_sources=[],
    )
    # Attach MCP session metadata as extra agent info
    if mcp_session_id:
        lineage.agent = f"{source} [mcp_session:{mcp_session_id}]"

    artifact = node.publish(
        title=title,
        content=content,
        format=fmt,
        tags=tags,
        summary=summary,
        visibility=visibility,
        derived_from=derived_from,
        source=source,
        lineage=lineage,
    )

    result = {
        "artifact_id": artifact.id,
        "title": artifact.title,
        "content_hash": artifact.content_hash,
        "signature": artifact.signature[:16] + "...",
        "tags": artifact.tags,
        "visibility": artifact.visibility,
        "timestamp": artifact.timestamp,
        "derived_from": derived_from,
        "kcp_uri": f"kcp://local/artifact/{artifact.id}",
        "message": f"✅ Artifact published and signed. ID: {artifact.id}",
    }
    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]


async def _kcp_search(node: KCPNode, args: dict) -> list[types.TextContent]:
    query = args["query"]
    limit = args.get("limit", 10)

    response = node.search(query, limit=limit)

    results = []
    for r in response.results:
        results.append({
            "artifact_id": r.id,
            "title": r.title,
            "summary": r.summary,
            "tags": getattr(r, "tags", []),
            "score": round(r.relevance, 4) if r.relevance else None,
            "kcp_uri": f"kcp://local/artifact/{r.id}",
        })

    result = {
        "query": query,
        "total": response.total,
        "results": results,
        "tip": "Use kcp_get(artifact_id=...) to retrieve full content of any result.",
    }
    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]


async def _kcp_get(node: KCPNode, args: dict) -> list[types.TextContent]:
    artifact_id = args["artifact_id"]
    include_content = args.get("include_content", True)

    artifact = node.get(artifact_id)
    if not artifact:
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": f"Artifact not found: {artifact_id}"}),
        )]

    result: dict[str, Any] = {
        "artifact_id": artifact.id,
        "title": artifact.title,
        "format": artifact.format,
        "tags": artifact.tags,
        "summary": artifact.summary,
        "visibility": artifact.visibility,
        "user_id": artifact.user_id,
        "tenant_id": artifact.tenant_id,
        "timestamp": artifact.timestamp,
        "content_hash": artifact.content_hash,
        "signature": artifact.signature[:16] + "..." if artifact.signature else None,
        "kcp_uri": f"kcp://local/artifact/{artifact.id}",
    }

    if artifact.lineage:
        result["lineage"] = {
            "query": artifact.lineage.query,
            "agent": artifact.lineage.agent,
            "data_sources": artifact.lineage.data_sources,
            "parent_reports": artifact.lineage.parent_reports,
        }

    if include_content:
        raw = node.get_content(artifact_id)
        if raw:
            try:
                result["content"] = raw.decode("utf-8")
            except UnicodeDecodeError:
                result["content"] = f"<binary content, {len(raw)} bytes>"

    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]


async def _kcp_lineage(node: KCPNode, args: dict) -> list[types.TextContent]:
    artifact_id = args["artifact_id"]

    chain = node.lineage(artifact_id)
    if not chain:
        artifact = node.get(artifact_id)
        if not artifact:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": f"Artifact not found: {artifact_id}"}),
            )]
        # Root artifact with no parents
        chain = [{
            "artifact_id": artifact.id,
            "title": artifact.title,
            "timestamp": artifact.timestamp,
            "depth": 0,
            "is_root": True,
        }]

    result = {
        "artifact_id": artifact_id,
        "chain_length": len(chain),
        "chain": chain,
        "description": (
            f"Lineage has {len(chain)} artifact(s). "
            "Root is at index 0, current artifact at the end."
        ),
    }
    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]


async def _kcp_list(node: KCPNode, args: dict) -> list[types.TextContent]:
    limit = args.get("limit", 20)
    tags = args.get("tags")

    artifacts = node.list(limit=limit, tags=tags)

    items = []
    for a in artifacts:
        items.append({
            "artifact_id": a.id,
            "title": a.title,
            "format": a.format,
            "tags": a.tags,
            "visibility": a.visibility,
            "timestamp": a.timestamp,
            "kcp_uri": f"kcp://local/artifact/{a.id}",
        })

    result = {
        "total": len(items),
        "limit": limit,
        "filter_tags": tags,
        "artifacts": items,
    }
    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]


async def _kcp_stats(node: KCPNode, args: dict) -> list[types.TextContent]:
    stats = node.stats()
    # normalize key for MCP clients
    stats["artifact_count"] = stats.get("artifacts", 0)
    stats["server"] = "kcp-mcp-server v0.1.0"
    stats["protocol"] = "KCP v0.2 + MCP Bridge (RFC KCP-002)"
    stats["tools"] = ["kcp_publish", "kcp_search", "kcp_get", "kcp_lineage", "kcp_list", "kcp_stats"]
    return [types.TextContent(type="text", text=json.dumps(stats, indent=2))]
