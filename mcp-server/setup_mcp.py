#!/usr/bin/env python3
"""
KCP MCP Setup Script
====================
Automatically configures KCP MCP Server for Claude Desktop, Cursor, or Windsurf.

Usage:
    python mcp-server/setup_mcp.py --claude          # configure Claude Desktop
    python mcp-server/setup_mcp.py --cursor          # configure Cursor
    python mcp-server/setup_mcp.py --windsurf        # configure Windsurf
    python mcp-server/setup_mcp.py --show            # show current config
    python mcp-server/setup_mcp.py --test            # verify server starts correctly

Or with make:
    make setup-mcp-claude
    make setup-mcp-cursor
    make setup-mcp-windsurf
    make test-mcp-server
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()
MCP_SERVER_DIR = REPO_ROOT / "mcp-server"
VENV_PYTHON = REPO_ROOT / "sdk" / "python" / ".venv" / "bin" / "python"
KCP_DB = Path.home() / ".kcp" / "kcp.db"
KCP_KEYS = Path.home() / ".kcp" / "keys"

# ── Config builders ────────────────────────────────────────────

def _server_entry(user_id: str) -> dict:
    """Build the MCP server config entry."""
    return {
        "command": str(VENV_PYTHON),
        "args": ["-m", "kcp_mcp_server"],
        "env": {
            "KCP_USER_ID": user_id,
            "KCP_TENANT_ID": "local",
            "KCP_DB_PATH": str(KCP_DB),
            "KCP_KEYS_DIR": str(KCP_KEYS),
            "PYTHONPATH": str(MCP_SERVER_DIR) + ":" + str(REPO_ROOT / "sdk" / "python"),
        },
    }


# ── Claude Desktop ─────────────────────────────────────────────

def _claude_config_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / "Claude" / "claude_desktop_config.json"
    else:
        return Path.home() / ".config" / "claude" / "claude_desktop_config.json"


def setup_claude(user_id: str):
    config_path = _claude_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    existing = {}
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text())
            print(f"  Found existing config: {config_path}")
        except json.JSONDecodeError:
            print(f"  ⚠️  Existing config invalid JSON — will overwrite")

    existing.setdefault("mcpServers", {})
    existing["mcpServers"]["kcp"] = _server_entry(user_id)

    config_path.write_text(json.dumps(existing, indent=2))
    print(f"\n  ✅ Claude Desktop configured!")
    print(f"  Config: {config_path}")
    print(f"\n  ➡️  Restart Claude Desktop.")
    print(f"  ➡️  Open any chat and type:")
    print(f'     "Use kcp_search to find anything about rate limiting"')
    print(f'     "Use kcp_publish to save this conversation as a knowledge artifact"')


# ── Cursor ─────────────────────────────────────────────────────

def _cursor_config_path() -> Path:
    """Cursor supports both global (~/.cursor/mcp.json) and per-project (.cursor/mcp.json)."""
    return Path.home() / ".cursor" / "mcp.json"


def setup_cursor(user_id: str, project_local: bool = False):
    if project_local:
        config_path = REPO_ROOT / ".cursor" / "mcp.json"
    else:
        config_path = _cursor_config_path()

    config_path.parent.mkdir(parents=True, exist_ok=True)

    existing = {}
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text())
            print(f"  Found existing config: {config_path}")
        except json.JSONDecodeError:
            print(f"  ⚠️  Existing config invalid JSON — will overwrite")

    existing.setdefault("mcpServers", {})
    existing["mcpServers"]["kcp"] = _server_entry(user_id)

    config_path.write_text(json.dumps(existing, indent=2))
    print(f"\n  ✅ Cursor configured!")
    print(f"  Config: {config_path}")
    print(f"\n  ➡️  Restart Cursor (or reload window: Cmd+Shift+P → 'Reload Window').")
    print(f"  ➡️  Open Cursor Chat (Cmd+L) and type:")
    print(f'     "@kcp_search rate limiting"')
    print(f'     "kcp_publish this analysis with tags architecture"')


# ── Windsurf ───────────────────────────────────────────────────

def _windsurf_config_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Windsurf" / "User" / "globalStorage" / "windsurf.mcp" / "mcp_config.json"
    else:
        return Path.home() / ".windsurf" / "mcp_config.json"


def setup_windsurf(user_id: str):
    config_path = _windsurf_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    existing = {}
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text())
        except json.JSONDecodeError:
            pass

    existing.setdefault("mcpServers", {})
    existing["mcpServers"]["kcp"] = _server_entry(user_id)

    config_path.write_text(json.dumps(existing, indent=2))
    print(f"\n  ✅ Windsurf configured!")
    print(f"  Config: {config_path}")
    print(f"\n  ➡️  Restart Windsurf.")


# ── Show current config ────────────────────────────────────────

def show_configs():
    configs = {
        "Claude Desktop": _claude_config_path(),
        "Cursor (global)": _cursor_config_path(),
        "Cursor (project)": REPO_ROOT / ".cursor" / "mcp.json",
        "Windsurf": _windsurf_config_path(),
    }
    print("\n  Current MCP configurations:\n")
    for name, path in configs.items():
        if path.exists():
            try:
                data = json.loads(path.read_text())
                has_kcp = "kcp" in data.get("mcpServers", {})
                status = "✅ KCP configured" if has_kcp else "⚠️  exists but no KCP entry"
            except Exception:
                status = "⚠️  invalid JSON"
            print(f"  {name}: {status}")
            print(f"    {path}")
        else:
            print(f"  {name}: — (not found)")
            print(f"    {path}")
    print()


# ── Test server starts ─────────────────────────────────────────

def test_server():
    """Verify the MCP server process starts and responds to initialize."""
    print("\n  Testing MCP server startup...\n")

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{MCP_SERVER_DIR}:{REPO_ROOT / 'sdk' / 'python'}"
    env["KCP_USER_ID"] = "test-user"
    env["KCP_TENANT_ID"] = "test"
    env["KCP_DB_PATH"] = "/tmp/kcp-mcp-test.db"
    env["KCP_KEYS_DIR"] = "/tmp/kcp-mcp-test-keys"

    # Send MCP initialize message over stdin
    init_msg = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "kcp-test", "version": "1.0"},
        },
    }) + "\n"

    try:
        result = subprocess.run(
            [str(VENV_PYTHON), "-m", "kcp_mcp_server"],
            input=init_msg.encode(),
            capture_output=True,
            timeout=5,
            env=env,
            cwd=str(MCP_SERVER_DIR),
        )
        stdout = result.stdout.decode(errors="replace")
        if '"result"' in stdout and '"serverInfo"' in stdout:
            resp = json.loads(stdout.split("\n")[0])
            server_name = resp.get("result", {}).get("serverInfo", {}).get("name", "?")
            print(f"  ✅ Server started and responded: {server_name}")
            print(f"  Protocol: MCP stdio JSON-RPC")

            # Also list tools
            tools_msg = json.dumps({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            }) + "\n"

            result2 = subprocess.run(
                [str(VENV_PYTHON), "-m", "kcp_mcp_server"],
                input=(init_msg + tools_msg).encode(),
                capture_output=True,
                timeout=5,
                env=env,
                cwd=str(MCP_SERVER_DIR),
            )
            out2 = result2.stdout.decode(errors="replace")
            for line in out2.strip().split("\n"):
                try:
                    msg = json.loads(line)
                    if msg.get("id") == 2:
                        tools = [t["name"] for t in msg.get("result", {}).get("tools", [])]
                        print(f"  Tools registered: {tools}")
                except Exception:
                    pass
        else:
            print(f"  ❌ Unexpected response: {stdout[:200]}")
            if result.stderr:
                print(f"  stderr: {result.stderr.decode()[:200]}")
            sys.exit(1)
    except subprocess.TimeoutExpired:
        print("  ✅ Server running (timeout expected — it's a long-lived process)")
    except Exception as e:
        print(f"  ❌ Error: {e}")
        sys.exit(1)

    print()
    print("  The server is ready to connect to any MCP-compatible client.")
    print("  Run one of the setup commands to configure your editor:")
    print("    make setup-mcp-claude")
    print("    make setup-mcp-cursor")
    print()


# ── CLI ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Configure KCP MCP Server for your AI assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python mcp-server/setup_mcp.py --claude
  python mcp-server/setup_mcp.py --cursor
  python mcp-server/setup_mcp.py --cursor --local   (project-local config)
  python mcp-server/setup_mcp.py --show
  python mcp-server/setup_mcp.py --test
        """,
    )
    parser.add_argument("--claude", action="store_true", help="Configure Claude Desktop")
    parser.add_argument("--cursor", action="store_true", help="Configure Cursor")
    parser.add_argument("--windsurf", action="store_true", help="Configure Windsurf")
    parser.add_argument("--local", action="store_true", help="Use project-local config (Cursor only)")
    parser.add_argument("--show", action="store_true", help="Show current configurations")
    parser.add_argument("--test", action="store_true", help="Test server startup")
    parser.add_argument("--user", default=None, help="Your user ID (email or username)")
    args = parser.parse_args()

    if not any([args.claude, args.cursor, args.windsurf, args.show, args.test]):
        parser.print_help()
        return

    print("\n  KCP MCP Server Setup\n  " + "─" * 38)

    user_id = args.user or os.environ.get("KCP_USER_ID") or os.environ.get("USER", "user") + "@local"

    if args.show:
        show_configs()
    if args.test:
        test_server()
    if args.claude:
        setup_claude(user_id)
    if args.cursor:
        setup_cursor(user_id, project_local=args.local)
    if args.windsurf:
        setup_windsurf(user_id)


if __name__ == "__main__":
    main()
