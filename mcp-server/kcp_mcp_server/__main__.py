"""
Entry point for `python -m kcp_mcp_server`
"""

import asyncio
import sys
from .server import create_server
from mcp.server.stdio import stdio_server


def main():
    """Run the KCP MCP server over stdio (Claude Desktop / Cursor compatible)."""
    server = create_server()

    async def _run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
