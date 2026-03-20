# KCP MCP Server

> **KCP as MCP backend** — exposes a KCPNode as a [Model Context Protocol](https://modelcontextprotocol.io/) server.

AI assistants (Claude, Cursor, Windsurf) can call KCP tools directly:
- **Persist** knowledge artifacts with cryptographic identity
- **Search** past work before generating new content
- **Trace lineage** — see how knowledge evolved
- **Bridge** ephemeral MCP sessions with persistent KCP storage

This implements **RFC KCP-002** — the KCP-to-MCP Bridge.

---

## How It Works

```
Claude / Cursor / Windsurf
       │  MCP protocol (stdio)
       ▼
┌─────────────────────────┐
│   KCP MCP Server        │  ← this package
│   kcp_publish           │
│   kcp_search            │
│   kcp_get               │
│   kcp_lineage           │
│   kcp_list              │
│   kcp_stats             │
└──────────┬──────────────┘
           │  KCPNode Python SDK
           ▼
    SQLite (~/.kcp/kcp.db)
    Ed25519 keys (~/.kcp/keys/)
```

Every AI output published via `kcp_publish` is:
- **Signed** with Ed25519
- **Content-addressed** with SHA-256
- **Indexed** for full-text search
- **Linked** in a lineage DAG via `parent_id`
- **Addressed** with a `kcp://` URI

---

## Install

```bash
cd mcp-server

# Install KCP SDK from local source
pip install -e ../sdk/python

# Install MCP server
pip install -e ".[dev]"
```

---

## Quick Test

```bash
pytest tests/ -v
```

Expected output:
```
tests/test_bridge.py::test_publish_basic PASSED
tests/test_bridge.py::test_publish_with_mcp_session_id PASSED
tests/test_bridge.py::test_publish_with_derived_from PASSED
...
tests/test_bridge.py::test_full_bridge_workflow PASSED
```

---

## Claude Desktop Integration

Add to `~/.claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "kcp": {
      "command": "python",
      "args": ["-m", "kcp_mcp_server"],
      "env": {
        "KCP_USER_ID": "you@example.com",
        "KCP_TENANT_ID": "my-org",
        "KCP_DB_PATH": "~/.kcp/kcp.db",
        "KCP_KEYS_DIR": "~/.kcp/keys"
      }
    }
  }
}
```

Then restart Claude Desktop. You'll see the KCP tools available in the tool panel.

---

## Cursor / Windsurf Integration

Add to your project's `.cursor/mcp.json` or Windsurf MCP config:

```json
{
  "mcpServers": {
    "kcp": {
      "command": "python",
      "args": ["-m", "kcp_mcp_server"],
      "env": {
        "KCP_USER_ID": "dev@example.com",
        "KCP_TENANT_ID": "engineering"
      }
    }
  }
}
```

---

## Tools Reference

### `kcp_publish`

Publish a knowledge artifact. Use this to persist any valuable AI-generated content.

```json
{
  "title": "Rate Limiting Strategies",
  "content": "## Token Bucket\n\nThe most common approach...",
  "format": "markdown",
  "tags": ["architecture", "rate-limiting"],
  "summary": "Overview of rate limiting patterns",
  "visibility": "org",
  "derived_from": "<parent-artifact-id>",
  "source": "claude-3.7-sonnet",
  "mcp_session_id": "session-abc123"
}
```

Returns:
```json
{
  "artifact_id": "550e8400-...",
  "content_hash": "sha256:...",
  "signature": "a1b2c3d4...",
  "kcp_uri": "kcp://local/artifact/550e8400-...",
  "message": "✅ Artifact published and signed."
}
```

---

### `kcp_search`

Search existing knowledge before generating new content.

```json
{ "query": "rate limiting", "limit": 5 }
```

Returns:
```json
{
  "query": "rate limiting",
  "total": 2,
  "results": [
    {
      "artifact_id": "550e8400-...",
      "title": "Rate Limiting Strategies",
      "tags": ["architecture", "rate-limiting"],
      "kcp_uri": "kcp://local/artifact/550e8400-..."
    }
  ],
  "tip": "Use kcp_get(artifact_id=...) to retrieve full content."
}
```

---

### `kcp_get`

Retrieve full metadata + content of an artifact.

```json
{ "artifact_id": "550e8400-...", "include_content": true }
```

---

### `kcp_lineage`

Trace the full lineage chain (DAG root → current artifact).

```json
{ "artifact_id": "550e8400-..." }
```

Returns the chain of all parent artifacts, showing how knowledge evolved.

---

### `kcp_list`

List recent artifacts, optionally filtered by tags.

```json
{ "limit": 20, "tags": ["architecture"] }
```

---

### `kcp_stats`

Get node statistics (artifact count, storage size, node identity).

---

## Example Workflow

Here's what happens when Claude uses KCP:

```
User: "Analyze rate limiting strategies and save your analysis"

Claude:
  1. kcp_search("rate limiting") → 0 results
  2. [Generates analysis]
  3. kcp_publish(title="Rate Limiting Strategies", content="...", tags=["arch"])
     → artifact_id: abc-123, kcp_uri: kcp://local/artifact/abc-123

User: "Now apply that to our gRPC services"

Claude:
  1. kcp_search("rate limiting") → finds abc-123
  2. kcp_get(abc-123) → full content as context
  3. [Generates derived analysis using abc-123 as context]
  4. kcp_publish(title="gRPC Rate Limiting", derived_from="abc-123", ...)
     → artifact_id: def-456, lineage: abc-123 → def-456

User: "Show me the lineage"

Claude:
  1. kcp_lineage(def-456) → [abc-123 (root), def-456 (current)]
```

**The AI has memory. The knowledge is persistent. The lineage is cryptographically verified.**

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `KCP_USER_ID` | `mcp-agent` | Identity of the MCP client |
| `KCP_TENANT_ID` | `local` | Organization/tenant context |
| `KCP_DB_PATH` | `~/.kcp/kcp.db` | SQLite database path |
| `KCP_KEYS_DIR` | `~/.kcp/keys` | Ed25519 key storage |

---

## Architecture

See [RFC KCP-002](../rfcs/kcp-002-mcp-bridge.md) for the full specification of the Bridge mode, including:
- Schema extensions (`mcp_session_id`, `mcp_tool_call`)
- The `kcp://` URI scheme
- Security considerations
- Open questions

---

## License

MIT — same as the KCP protocol.
