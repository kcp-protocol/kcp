"""
KCP MCP Server
==============

Exposes a KCPNode as a Model Context Protocol (MCP) server.
AI assistants (Claude, Cursor, Windsurf) can call KCP tools directly.

Tools exposed:
  - kcp_publish   → KCPNode.publish()
  - kcp_search    → KCPNode.search()
  - kcp_get       → KCPNode.get() + get_content()
  - kcp_lineage   → KCPNode.lineage()
  - kcp_list      → KCPNode.list()
  - kcp_stats     → KCPNode.stats()

Usage:
    python -m kcp_mcp_server

Claude Desktop config (~/.claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "kcp": {
          "command": "python",
          "args": ["-m", "kcp_mcp_server"],
          "env": {
            "KCP_USER_ID": "alice@example.com",
            "KCP_TENANT_ID": "my-org",
            "KCP_DB_PATH": "~/.kcp/kcp.db"
          }
        }
      }
    }
"""

from .server import create_server

__all__ = ["create_server"]
__version__ = "0.1.0"
