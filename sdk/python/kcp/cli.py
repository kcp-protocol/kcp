"""
KCP CLI

Command-line interface for operating a KCP node.

Usage:
    kcp init                          # Initialize node (generate keys, create DB)
    kcp identity create               # Create new identity with recovery phrase
    kcp identity recover              # Recover identity from recovery phrase
    kcp identity show                 # Show current identity
    kcp identity export               # Export identity backup
    kcp identity import               # Import identity from backup
    kcp publish --title "..." FILE    # Publish a file as knowledge artifact
    kcp publish --ttl 3600 FILE       # Publish with a 1h TTL
    kcp versions CANONICAL_ID         # List all versions of an artifact
    kcp search "query"                # Search artifacts (keyword by default, active only)
    kcp search "query" --mode semantic|hybrid [--alpha 0.5]
    kcp search "query" --include-superseded --include-expired
    kcp reindex                       # (Re)build the semantic vector index
    kcp list                          # List recent artifacts
    kcp get ARTIFACT_ID               # Show artifact details
    kcp lineage ARTIFACT_ID           # Show lineage chain
    kcp serve                         # Start HTTP server for P2P
    kcp peer add URL                  # Add a peer
    kcp peer list                     # List peers
    kcp sync URL                      # Sync with a peer
    kcp stats                         # Show node stats
    kcp keygen                        # Generate new keypair (legacy)
"""

from __future__ import annotations

import json
import os
import sys
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
    elif cmd == "identity":
        cmd_identity(rest)
    elif cmd == "publish":
        cmd_publish(rest)
    elif cmd == "search":
        cmd_search(rest)
    elif cmd == "reindex":
        cmd_reindex(rest)
    elif cmd == "list":
        cmd_list(rest)
    elif cmd == "get":
        cmd_get(rest)
    elif cmd == "lineage":
        cmd_lineage(rest)
    elif cmd == "versions":
        cmd_versions(rest)
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

    # Semantic search is opt-in: only forward the kwargs when the env asks for them,
    # so a plain `KCPNode(...)` stays FTS5-only (zero dependencies).
    search_backend = os.environ.get("KCP_SEARCH_BACKEND")
    embedding_model = os.environ.get("KCP_EMBEDDING_MODEL")
    if search_backend:
        kwargs.setdefault("search_backend", search_backend)
    if embedding_model:
        kwargs.setdefault("embedding_model", embedding_model)

    return KCPNode(user_id=user_id, tenant_id=tenant_id, db_path=db_path, **kwargs)


def _detect_language() -> str:
    """Detect user's preferred language."""
    lang = os.environ.get("LANG", "en_US").lower()
    return "pt" if "pt" in lang else "en"


def cmd_identity(args):
    """Manage KCP identity (create, recover, show, export, import)."""
    from .identity_cli import (
        export_backup,
        import_backup,
        show_identity,
        wizard_create_identity,
        wizard_recover_identity,
    )

    lang = _detect_language()

    if not args or args[0] in ("-h", "--help"):
        print("""
🔐 KCP Identity Management

Commands:
    kcp identity create     Create new identity with recovery phrase
    kcp identity recover    Recover identity from recovery phrase
    kcp identity show       Show current identity
    kcp identity export     Export identity to backup file
    kcp identity import     Import identity from backup file

Your identity is your cryptographic signature. Back it up!
""")
        return

    subcmd = args[0]

    if subcmd == "create":
        wizard_create_identity(lang)
    elif subcmd == "recover":
        wizard_recover_identity(lang)
    elif subcmd == "show":
        show_identity(lang)
    elif subcmd == "export":
        output = args[1] if len(args) > 1 else None
        export_backup(output, lang)
    elif subcmd == "import":
        input_file = args[1] if len(args) > 1 else None
        import_backup(input_file, lang)
    else:
        print(f"Unknown identity command: {subcmd}")
        print("Use: kcp identity --help")


def cmd_init(args):
    """Initialize a KCP node."""
    node = _get_node()
    stats = node.stats()
    print("✅ KCP node initialized")
    print(f"   Node ID:  {stats['node_id']}")
    print(f"   User:     {stats['user_id']}")
    print(f"   Tenant:   {stats['tenant_id']}")
    print(f"   Database: {stats['db_path']}")
    print("   Keys:     ~/.kcp/keys/")


def cmd_publish(args):
    """Publish a file as a knowledge artifact (or a new version of one)."""
    title = ""
    tags = []
    summary = ""
    derived_from = None
    file_path = None
    fmt = None
    ttl_seconds = None
    expires_at = None
    version_of = None
    explicit_title = None
    explicit_fmt = None

    i = 0
    while i < len(args):
        if args[i] == "--title" and i + 1 < len(args):
            title = args[i + 1]
            explicit_title = title
            i += 2
        elif args[i] == "--tags" and i + 1 < len(args):
            tags = [t.strip() for t in args[i + 1].split(",")]
            i += 2
        elif args[i] == "--summary" and i + 1 < len(args):
            summary = args[i + 1]
            i += 2
        elif args[i] == "--format" and i + 1 < len(args):
            fmt = args[i + 1]
            explicit_fmt = fmt
            i += 2
        elif args[i] == "--derived-from" and i + 1 < len(args):
            derived_from = args[i + 1]
            i += 2
        elif args[i] == "--ttl" and i + 1 < len(args):
            ttl_seconds = float(args[i + 1])
            i += 2
        elif args[i] == "--expires-at" and i + 1 < len(args):
            expires_at = args[i + 1]
            i += 2
        elif args[i] == "--version-of" and i + 1 < len(args):
            version_of = args[i + 1]
            i += 2
        elif args[i] == "-":
            file_path = "-"
            i += 1
        else:
            file_path = args[i]
            i += 1

    if not file_path and not version_of:
        print("Usage: kcp publish [--title TITLE] [--tags a,b] [--format md]")
        print("                   [--ttl SECONDS] [--expires-at ISO8601] FILE")
        print("       kcp publish --version-of ARTIFACT_ID [--title TITLE] [--ttl SECONDS] [FILE]")
        print("       echo 'content' | kcp publish --title 'My Note' -")
        sys.exit(1)

    # Read content
    content = None
    if file_path == "-":
        content = sys.stdin.buffer.read()
    elif file_path:
        p = Path(file_path)
        if not p.exists():
            print(f"File not found: {file_path}")
            sys.exit(1)
        content = p.read_bytes()
        if not title:
            title = p.stem.replace("-", " ").replace("_", " ").title()
        if not fmt:
            ext_map = {
                ".md": "markdown",
                ".html": "html",
                ".json": "json",
                ".csv": "csv",
                ".txt": "text",
                ".pdf": "pdf",
                ".py": "text",
            }
            fmt = ext_map.get(p.suffix.lower(), "text")

    if not title:
        title = "Untitled"
    if not fmt:
        fmt = "text"

    node = _get_node()

    if version_of:
        try:
            artifact = node.publish_version(
                artifact_id=version_of,
                title=explicit_title,
                content=content,
                format=explicit_fmt,
                tags=tags or None,
                summary=summary or None,
                derived_from=derived_from,
                ttl_seconds=ttl_seconds,
                expires_at=expires_at,
            )
        except ValueError as exc:
            print(f"❌ {exc}")
            sys.exit(1)
        print(f"✅ Published version {artifact.version}: {artifact.id}")
        print(f"   Canonical: {artifact.canonical_id}")
        print(f"   Derived from: {derived_from or '(previous version)'}")
        return

    artifact = node.publish(
        title=title,
        content=content,
        format=fmt,
        tags=tags,
        summary=summary,
        derived_from=derived_from,
        ttl_seconds=ttl_seconds,
        expires_at=expires_at,
    )

    print(f"✅ Published: {artifact.id}")
    print(f"   Title:   {artifact.title}")
    print(f"   Format:  {artifact.format}")
    print(f"   Hash:    {artifact.content_hash[:16]}...")
    print(f"   Tags:    {', '.join(artifact.tags) if artifact.tags else '(none)'}")
    if derived_from:
        print(f"   Derived: {derived_from}")
    if artifact.expires_at:
        print(f"   Expires: {artifact.expires_at}")


def cmd_search(args):
    """Search for artifacts — keyword (default), semantic or hybrid."""
    query, options = _parse_search_options(args)
    if not query:
        print(
            "Usage: kcp search QUERY [--mode keyword|semantic|hybrid] [--alpha 0.5] [--limit N] "
            "[--include-superseded] [--include-expired]"
        )
        sys.exit(1)

    from .embeddings import EmbeddingError, SemanticSearchUnavailableError

    mode = options["mode"].lower()
    node = _get_node()
    try:
        results = node.search(
            query,
            limit=options["limit"],
            mode=mode,
            alpha=options["alpha"],
            include_superseded=options["include_superseded"],
            include_expired=options["include_expired"],
        )
    except SemanticSearchUnavailableError as exc:
        print(f"⚠️  Semantic search unavailable: {exc}")
        print(
            "   Enable it with: KCP_SEARCH_BACKEND=sqlite-vss "
            "[KCP_EMBEDDING_MODEL=ollama:nomic-embed-text] kcp search …"
        )
        sys.exit(2)
    except (EmbeddingError, ValueError) as exc:
        print(f"❌ Search failed (mode={mode}): {exc}")
        sys.exit(2)

    if not results.results:
        print(f"No results for: {query} (mode={mode})")
        return

    scope = (
        "all statuses"
        if (options["include_superseded"] and options["include_expired"])
        else (
            "active + superseded"
            if options["include_superseded"]
            else ("active + expired" if options["include_expired"] else "active only")
        )
    )
    print(f"Found {results.total} artifacts ({results.query_time_ms}ms, mode={mode} — {scope}):\n")
    for r in results.results:
        print(f"  📄 {r.title}")
        print(f"     ID: {r.id}")
        print(f"     {r.summary[:100]}" if r.summary else "")
        detail = f"     Format: {r.format} | Created: {r.created_at[:10]} | Status: {r.status} | Score: {r.relevance}"
        if r.scores:
            detail += "  (" + ", ".join(f"{k}={v:.3f}" for k, v in r.scores.items()) + ")"
        print(detail)
        print()


def cmd_versions(args):
    """List all versions of a canonical artifact."""
    if not args:
        print("Usage: kcp versions CANONICAL_ID")
        sys.exit(1)

    node = _get_node()
    canonical_id = node.store.resolve_canonical_id(args[0]) or args[0]
    versions = node.versions(canonical_id)

    if not versions:
        print(f"No versions found for: {canonical_id}")
        return

    print(f"Versions of {canonical_id} ({len(versions)}):\n")
    for v in versions:
        current = " ← current" if v.status == "active" else ""
        print(f"  v{v.version}  [{v.status}]{current}")
        print(f"     ID: {v.id}")
        print(f"     Title: {v.title} | {v.format} | {v.timestamp[:10]}")
        if v.expires_at:
            print(f"     Expires: {v.expires_at}")
        if v.superseded_by:
            print(f"     Superseded by: {v.superseded_by}")
        print()
    current_artifact = node.get_current(canonical_id)
    if current_artifact:
        print(f"Current: v{current_artifact.version} ({current_artifact.id})")
    else:
        print("Current: (none — no active version)")


def _parse_search_options(args):
    """Split `kcp search` arguments into (query, options) — flags may come first."""
    options = {
        "mode": os.environ.get("KCP_SEARCH_MODE", "keyword"),
        "alpha": float(os.environ.get("KCP_SEARCH_ALPHA", "0.5")),
        "limit": 20,
        "include_superseded": False,
        "include_expired": False,
    }
    terms: list = []
    index = 0
    try:
        while index < len(args):
            arg = args[index]
            if arg in ("--mode", "-m") and index + 1 < len(args):
                options["mode"] = args[index + 1]
                index += 2
            elif arg.startswith("--mode="):
                options["mode"] = arg.split("=", 1)[1]
                index += 1
            elif arg == "--alpha" and index + 1 < len(args):
                options["alpha"] = float(args[index + 1])
                index += 2
            elif arg.startswith("--alpha="):
                options["alpha"] = float(arg.split("=", 1)[1])
                index += 1
            elif arg in ("--limit", "-n") and index + 1 < len(args):
                options["limit"] = int(args[index + 1])
                index += 2
            elif arg.startswith("--limit="):
                options["limit"] = int(arg.split("=", 1)[1])
                index += 1
            elif arg in ("--include-superseded", "--include-expired"):
                options[arg[2:].replace("-", "_")] = True
                index += 1
            else:
                terms.append(arg)
                index += 1
    except ValueError:
        print("Usage: kcp search QUERY [--mode keyword|semantic|hybrid] [--alpha 0.5] [--limit N]")
        print("       [--include-superseded] [--include-expired]")
        print("       --alpha must be a number in [0, 1]; --limit must be an integer")
        sys.exit(1)
    return " ".join(terms), options


def cmd_reindex(args):
    """(Re)build embeddings for stored artifacts (semantic search)."""
    force = "--force" in args or "-f" in args
    node = _get_node()
    if not node.semantic_available:
        print("Vector backend is disabled for this node.")
        print(
            "Set KCP_SEARCH_BACKEND=sqlite-vss (optionally KCP_EMBEDDING_MODEL=ollama:nomic-embed-text) "
            "before running `kcp reindex`."
        )
        sys.exit(2)

    stats = node.reindex(force=force)
    print(f"Indexed {stats['indexed']} artifact(s), skipped {stats['skipped']}, errors {stats['errors']}")
    print(f"  model:   {stats['model']}")
    print(f"  backend: {stats['backend']}")
    if stats.get("fallback_reason"):
        print(f"  fallback: {stats['fallback_reason']}")
    print(f"  vectors: {stats['indexed_total']}")


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
        print("\n--- Content ---\n")
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
    # noqa: S104 / nosec B104 — nó P2P precisa escutar em todas as interfaces
    host = "0.0.0.0"  # noqa: S104  # nosec B104
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

    print("✅ Keypair generated")
    print(f"   Private: {out_dir}/private.key")
    print(f"   Public:  {out_dir}/public.key")
    print(f"   Public (hex): {pub.hex()}")


def cmd_export(args):
    """Export all artifacts as JSON (for backup/migration)."""
    node = _get_node()
    artifacts = node.list(limit=10000, include_superseded=True, include_expired=True)
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
  publish --ttl 3600 FILE       Publish with a TTL (seconds) / --expires-at ISO8601
  publish --version-of ID FILE  Publish a new version of an existing artifact
  search QUERY                  Search artifacts (keyword by default, active only)
  search QUERY --mode semantic|hybrid [--alpha 0.5]
  search QUERY --include-superseded --include-expired
  reindex [--force]             (Re)build the semantic vector index
  list [N]                      List recent artifacts (default: 20)
  get ID                        Show artifact details + content
  lineage ID                    Show lineage chain (root → current)
  versions CANONICAL_ID         List all versions + lifecycle status
  serve [--port 8800]           Start HTTP server for P2P + Web UI
  peer add URL [NAME]           Add a peer node
  peer list                     List known peers
  sync URL [--pull|--push]      Sync with a peer (default: both)
  stats                         Show node statistics
  keygen [DIR]                  Generate Ed25519 keypair
  export [FILE]                 Export all artifacts as JSON

Environment:
  KCP_USER            Your user ID (default: anonymous)
  KCP_TENANT          Your tenant/org (default: local)
  KCP_DB              Database path (default: ~/.kcp/kcp.db)
  KCP_SEARCH_BACKEND  'fts5' (default) or 'sqlite-vss' (local vector index)
  KCP_EMBEDDING_MODEL 'hash' (offline), 'ollama:nomic-embed-text', 'openai:text-embedding-3-small'
  KCP_SEARCH_MODE     Default mode for `kcp search`: keyword | semantic | hybrid

Examples:
  kcp init
  kcp publish --title "Auth Guide" --tags "jwt,security" guide.md
  echo "quick note" | kcp publish --title "Note" --format text -
  kcp publish --ttl 86400 --title "Daily snapshot" report.md
  kcp publish --version-of $ID --title "Report v2" report-v2.md
  kcp versions $ID
  kcp search "authentication"
  kcp search "rate limiting" --mode hybrid --alpha 0.5
  KCP_SEARCH_BACKEND=sqlite-vss KCP_EMBEDDING_MODEL=ollama:nomic-embed-text kcp reindex
  kcp serve --port 8800
  kcp peer add https://colleague-node.trycloudflare.com
  kcp sync https://colleague-node.trycloudflare.com
""")


if __name__ == "__main__":
    main()
