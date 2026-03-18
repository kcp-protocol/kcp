"""
KCP CLI

Command-line interface for operating a KCP node.

Usage:
    kcp init                          # Initialize node (generate keys, create DB)
    kcp publish --title "..." FILE    # Publish a file as knowledge artifact
    kcp search "query"                # Search artifacts
    kcp list                          # List recent artifacts
    kcp get ARTIFACT_ID               # Show artifact details
    kcp lineage ARTIFACT_ID           # Show lineage chain
    kcp serve                         # Start HTTP server for P2P
    kcp peer add URL                  # Add a peer
    kcp peer list                     # List peers
    kcp sync URL                      # Sync with a peer
    kcp stats                         # Show node stats
    kcp keygen                        # Generate new keypair
"""

import sys
import json
import os
from pathlib import Path


def main():
    """CLI entrypoint."""
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        print_help()
        return

    cmd = args[0]
    rest = args[1:]

    if cmd == "init":
        cmd_init(rest)
    elif cmd == "publish":
        cmd_publish(rest)
    elif cmd == "search":
        cmd_search(rest)
    elif cmd == "list":
        cmd_list(rest)
    elif cmd == "get":
        cmd_get(rest)
    elif cmd == "lineage":
        cmd_lineage(rest)
    elif cmd == "serve":
        cmd_serve(rest)
    elif cmd == "peer":
        cmd_peer(rest)
    elif cmd == "sync":
        cmd_sync(rest)
    elif cmd == "stats":
        cmd_stats(rest)
    elif cmd == "keygen":
        cmd_keygen(rest)
    elif cmd == "export":
        cmd_export(rest)
    else:
        print(f"Unknown command: {cmd}")
        print_help()
        sys.exit(1)


def _get_node(**kwargs):
    """Create a KCPNode with defaults from env/config."""
    from .node import KCPNode

    user_id = os.environ.get("KCP_USER", kwargs.get("user_id", "anonymous"))
    tenant_id = os.environ.get("KCP_TENANT", kwargs.get("tenant_id", "local"))
    db_path = os.environ.get("KCP_DB", kwargs.get("db_path", "~/.kcp/kcp.db"))

    return KCPNode(user_id=user_id, tenant_id=tenant_id, db_path=db_path)


def cmd_init(args):
    """Initialize a KCP node."""
    node = _get_node()
    stats = node.stats()
    print("✅ KCP node initialized")
    print(f"   Node ID:  {stats['node_id']}")
    print(f"   User:     {stats['user_id']}")
    print(f"   Tenant:   {stats['tenant_id']}")
    print(f"   Database: {stats['db_path']}")
    print(f"   Keys:     ~/.kcp/keys/")


def cmd_publish(args):
    """Publish a file as a knowledge artifact."""
    title = ""
    tags = []
    summary = ""
    derived_from = None
    file_path = None
    fmt = None

    i = 0
    while i < len(args):
        if args[i] == "--title" and i + 1 < len(args):
            title = args[i + 1]; i += 2
        elif args[i] == "--tags" and i + 1 < len(args):
            tags = [t.strip() for t in args[i + 1].split(",")]; i += 2
        elif args[i] == "--summary" and i + 1 < len(args):
            summary = args[i + 1]; i += 2
        elif args[i] == "--format" and i + 1 < len(args):
            fmt = args[i + 1]; i += 2
        elif args[i] == "--derived-from" and i + 1 < len(args):
            derived_from = args[i + 1]; i += 2
        elif args[i] == "-":
            file_path = "-"; i += 1
        else:
            file_path = args[i]; i += 1

    if not file_path:
        print("Usage: kcp publish [--title TITLE] [--tags a,b] [--format md] FILE")
        print("       echo 'content' | kcp publish --title 'My Note' -")
        sys.exit(1)

    # Read content
    if file_path == "-":
        content = sys.stdin.buffer.read()
    else:
        p = Path(file_path)
        if not p.exists():
            print(f"File not found: {file_path}")
            sys.exit(1)
        content = p.read_bytes()
        if not title:
            title = p.stem.replace("-", " ").replace("_", " ").title()
        if not fmt:
            ext_map = {".md": "markdown", ".html": "html", ".json": "json",
                       ".csv": "csv", ".txt": "text", ".pdf": "pdf", ".py": "text"}
            fmt = ext_map.get(p.suffix.lower(), "text")

    if not title:
        title = "Untitled"
    if not fmt:
        fmt = "text"

    node = _get_node()
    artifact = node.publish(
        title=title, content=content, format=fmt,
        tags=tags, summary=summary, derived_from=derived_from,
    )

    print(f"✅ Published: {artifact.id}")
    print(f"   Title:   {artifact.title}")
    print(f"   Format:  {artifact.format}")
    print(f"   Hash:    {artifact.content_hash[:16]}...")
    print(f"   Tags:    {', '.join(artifact.tags) if artifact.tags else '(none)'}")
    if derived_from:
        print(f"   Derived: {derived_from}")


def cmd_search(args):
    """Search for artifacts."""
    if not args:
        print("Usage: kcp search QUERY")
        sys.exit(1)

    query = " ".join(args)
    node = _get_node()
    results = node.search(query)

    if not results.results:
        print(f"No results for: {query}")
        return

    print(f"Found {results.total} artifacts ({results.query_time_ms}ms):\n")
    for r in results.results:
        print(f"  📄 {r.title}")
        print(f"     ID: {r.id}")
        print(f"     {r.summary[:100]}" if r.summary else "")
        print(f"     Format: {r.format} | Created: {r.created_at[:10]}")
        print()


def cmd_list(args):
    """List recent artifacts."""
    limit = 20
    if args and args[0].isdigit():
        limit = int(args[0])

    node = _get_node()
    artifacts = node.list(limit=limit)

    if not artifacts:
        print("No artifacts yet. Publish something with: kcp publish FILE")
        return

    print(f"Recent artifacts ({len(artifacts)}):\n")
    for a in artifacts:
        tags = ", ".join(a.tags) if a.tags else ""
        print(f"  📄 {a.title}")
        print(f"     ID: {a.id} | {a.format} | {a.timestamp[:10]}")
        if tags:
            print(f"     Tags: {tags}")
        print()


def cmd_get(args):
    """Show artifact details."""
    if not args:
        print("Usage: kcp get ARTIFACT_ID")
        sys.exit(1)

    node = _get_node()
    artifact = node.get(args[0])

    if not artifact:
        print(f"Artifact not found: {args[0]}")
        sys.exit(1)

    print(json.dumps(artifact.to_dict(), indent=2))

    # Show content preview
    content = node.get_content(args[0])
    if content and len(content) < 2000:
        print(f"\n--- Content ---\n")
        try:
            print(content.decode("utf-8"))
        except UnicodeDecodeError:
            print(f"(binary content, {len(content)} bytes)")


def cmd_lineage(args):
    """Show lineage chain."""
    if not args:
        print("Usage: kcp lineage ARTIFACT_ID")
        sys.exit(1)

    node = _get_node()
    chain = node.lineage(args[0])

    if not chain:
        print(f"No lineage found for: {args[0]}")
        return

    print("Lineage (root → current):\n")
    for i, item in enumerate(chain):
        prefix = "└──" if i == len(chain) - 1 else "├──"
        indent = "   " * i
        print(f"{indent}{prefix} {item['title']}")
        print(f"{indent}    ID: {item['id'][:12]}... | By: {item['author']} | {item['created_at'][:10]}")


def cmd_serve(args):
    """Start HTTP server."""
    port = 8800
    host = "0.0.0.0"
    for i, a in enumerate(args):
        if a == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
        elif a == "--host" and i + 1 < len(args):
            host = args[i + 1]

    node = _get_node()
    node.serve(host=host, port=port)


def cmd_peer(args):
    """Manage peers."""
    if not args:
        print("Usage: kcp peer add URL | kcp peer list")
        sys.exit(1)

    node = _get_node()

    if args[0] == "add" and len(args) > 1:
        name = args[2] if len(args) > 2 else ""
        pid = node.add_peer(args[1], name=name)
        print(f"✅ Peer added: {pid}")
        print(f"   URL: {args[1]}")

    elif args[0] == "list":
        peers = node.get_peers()
        if not peers:
            print("No peers. Add one with: kcp peer add URL")
            return
        print(f"Peers ({len(peers)}):\n")
        for p in peers:
            print(f"  🔗 {p.get('name') or p['url']}")
            print(f"     URL: {p['url']}")
            print(f"     Last seen: {p.get('last_seen', 'never')}")
            print()
    else:
        print("Usage: kcp peer add URL | kcp peer list")


def cmd_sync(args):
    """Sync with a peer."""
    if not args:
        print("Usage: kcp sync URL [--pull|--push|--both]")
        sys.exit(1)

    url = args[0]
    direction = "both"
    if "--pull" in args:
        direction = "pull"
    elif "--push" in args:
        direction = "push"

    node = _get_node()

    if direction in ("push", "both"):
        print(f"📤 Pushing to {url}...")
        result = node.sync_push(url)
        print(f"   Pushed: {result.get('pushed', 0)}/{result.get('total', 0)}")

    if direction in ("pull", "both"):
        print(f"📥 Pulling from {url}...")
        result = node.sync_pull(url)
        print(f"   Pulled: {result.get('pulled', 0)}/{result.get('available', 0)}")


def cmd_stats(args):
    """Show node statistics."""
    node = _get_node()
    s = node.stats()
    print("KCP Node Stats\n")
    print(f"  Node ID:    {s['node_id']}")
    print(f"  User:       {s['user_id']}")
    print(f"  Tenant:     {s['tenant_id']}")
    print(f"  Artifacts:  {s['artifacts']}")
    print(f"  Content:    {s['content_size_human']}")
    print(f"  DB Size:    {s['db_size_human']}")
    print(f"  Peers:      {s['peers']}")
    print(f"  DB Path:    {s['db_path']}")


def cmd_keygen(args):
    """Generate a new Ed25519 keypair."""
    from .crypto import generate_keypair
    priv, pub = generate_keypair()

    out_dir = Path(args[0]) if args else Path("~/.kcp/keys").expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "private.key").write_bytes(priv)
    os.chmod(str(out_dir / "private.key"), 0o600)
    (out_dir / "public.key").write_bytes(pub)

    print(f"✅ Keypair generated")
    print(f"   Private: {out_dir}/private.key")
    print(f"   Public:  {out_dir}/public.key")
    print(f"   Public (hex): {pub.hex()}")


def cmd_export(args):
    """Export all artifacts as JSON (for backup/migration)."""
    node = _get_node()
    artifacts = node.list(limit=10000)
    data = [a.to_dict() for a in artifacts]
    output = json.dumps(data, indent=2)

    if args:
        Path(args[0]).write_text(output)
        print(f"✅ Exported {len(data)} artifacts to {args[0]}")
    else:
        print(output)


def print_help():
    print("""
KCP — Knowledge Context Protocol CLI

Usage: kcp <command> [options]

Commands:
  init                          Initialize node (generate keys, create DB)
  publish [--title T] FILE      Publish a file as knowledge artifact
  search QUERY                  Search artifacts
  list [N]                      List recent artifacts (default: 20)
  get ID                        Show artifact details + content
  lineage ID                    Show lineage chain (root → current)
  serve [--port 8800]           Start HTTP server for P2P + Web UI
  peer add URL [NAME]           Add a peer node
  peer list                     List known peers
  sync URL [--pull|--push]      Sync with a peer (default: both)
  stats                         Show node statistics
  keygen [DIR]                  Generate Ed25519 keypair
  export [FILE]                 Export all artifacts as JSON

Environment:
  KCP_USER      Your user ID (default: anonymous)
  KCP_TENANT    Your tenant/org (default: local)
  KCP_DB        Database path (default: ~/.kcp/kcp.db)

Examples:
  kcp init
  kcp publish --title "Auth Guide" --tags "jwt,security" guide.md
  echo "quick note" | kcp publish --title "Note" --format text -
  kcp search "authentication"
  kcp serve --port 8800
  kcp peer add https://colleague-node.trycloudflare.com
  kcp sync https://colleague-node.trycloudflare.com
""")


if __name__ == "__main__":
    main()
