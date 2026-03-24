#!/bin/sh
# KCP Peer Node — Docker entrypoint
# Derives sane defaults from env, then starts the peer via Python SDK

set -e

# NODE_ID: use env or derive from hostname
NODE_ID="${KCP_NODE_ID:-$(hostname)}"

# USER_ID: use env or derive from NODE_ID
USER_ID="${KCP_USER_ID:-${NODE_ID}@kcp-protocol.org}"

# Tenant
TENANT="${KCP_TENANT_ID:-community}"

# Data path
DB_PATH="${KCP_DATA_DIR:-/data}/kcp.db"

# Port
PORT="${KCP_PORT:-8800}"
HOST="${KCP_HOST:-0.0.0.0}"

echo "========================================"
echo "  KCP Peer Node v0.2.0"
echo "========================================"
echo "  node_id   : ${NODE_ID}"
echo "  user_id   : ${USER_ID}"
echo "  tenant    : ${TENANT}"
echo "  db        : ${DB_PATH}"
echo "  listen    : ${HOST}:${PORT}"
echo "  peers_url : ${KCP_PEERS_URL:-https://kcp-protocol.org/peers.json}"
echo "========================================"

# Create data dir if needed
mkdir -p "$(dirname "${DB_PATH}")"

# Export all KCP_* env vars so Python subprocess inherits them
export KCP_PEERS
export KCP_PEERS_URL
export KCP_USER_ID
export KCP_TENANT_ID
export KCP_DATA_DIR
export KCP_PORT
export KCP_HOST
export KCP_NODE_ID

exec python - <<PYEOF
import sys
import os
sys.path.insert(0, '/app')
from kcp.node import KCPNode

# Verify env vars are available
peers = os.environ.get("KCP_PEERS", "")
print(f"  peers     : {len([p for p in peers.split(',') if p.strip()])} configured")

node = KCPNode(
    user_id="${USER_ID}",
    tenant_id="${TENANT}",
    db_path="${DB_PATH}",
)
print(f"  node started — {node.node_id}")
node.serve(host="${HOST}", port=${PORT})
PYEOF
