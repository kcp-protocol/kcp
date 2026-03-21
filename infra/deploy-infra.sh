#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# KCP Infra Deploy Script
# Aplica configurações de multi-instância e blackhole no VPS.
# Execute no VPS como: sudo bash /dados/kcp/infra/deploy-infra.sh
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO=/dados/kcp
VENV=$REPO/sdk/python/.venv

echo "════════════════════════════════════════════════════"
echo "  KCP Infra Deploy"
echo "  $(date)"
echo "════════════════════════════════════════════════════"

# ── 1. Criar diretórios de dados isolados ─────────────────────────────────────
echo "[1/7] Criando diretórios de dados por peer..."
for peer in peer04 peer05 peer07; do
    mkdir -p /dados/kcp/data/$peer/content
    chown -R kcp:kcp /dados/kcp/data/$peer
done

# Migrar dados existentes (peer atual usa /dados/kcp/data/ direto)
if [ -f /dados/kcp/data/kcp.db ] && [ ! -f /dados/kcp/data/peer07/kcp.db ]; then
    echo "  Migrando dados existentes → peer07/..."
    cp /dados/kcp/data/kcp.db     /dados/kcp/data/peer07/kcp.db
    cp -r /dados/kcp/data/content /dados/kcp/data/peer07/ 2>/dev/null || true
    chown -R kcp:kcp /dados/kcp/data/peer07
fi

# ── 2. Instalar serviços systemd ──────────────────────────────────────────────
echo "[2/7] Instalando serviços systemd..."
for peer in peer04 peer05 peer07; do
    cp $REPO/infra/kcp-$peer.service /etc/systemd/system/kcp-$peer.service
done
cp $REPO/infra/kcp-blackhole.service /etc/systemd/system/kcp-blackhole.service

# Parar serviço antigo
systemctl stop kcp-peer 2>/dev/null || true
systemctl disable kcp-peer 2>/dev/null || true

systemctl daemon-reload

# ── 3. Configurar nginx ───────────────────────────────────────────────────────
echo "[3/7] Configurando nginx..."

# Rate limit zones: só adiciona se não existirem em NENHUM arquivo de conf
if ! grep -r "kcp_general" /etc/nginx/ >/dev/null 2>&1; then
    cat > /etc/nginx/conf.d/kcp-ratelimit.conf <<'EOF'
# KCP rate limit zones
limit_req_zone $binary_remote_addr zone=kcp_general:10m rate=20r/s;
limit_req_zone $binary_remote_addr zone=kcp_sync:10m    rate=5r/s;
limit_req_zone $binary_remote_addr zone=kcp_write:10m   rate=10r/s;
EOF
    echo "  Rate limit zones criadas em conf.d/kcp-ratelimit.conf"
else
    echo "  Rate limit zones já existem — skipped"
fi

# Copiar config de locations compartilhado
cp $REPO/infra/nginx-kcp-locations.conf /etc/nginx/kcp-locations.conf

# Copiar config dos peers
cp $REPO/infra/nginx-kcp-peers.conf /etc/nginx/sites-available/kcp-peers

# Ativar nova config, desativar antiga
ln -sf /etc/nginx/sites-available/kcp-peers /etc/nginx/sites-enabled/kcp-peers
rm -f /etc/nginx/sites-enabled/kcp-peer  # config antiga (singular)

# Testar nginx antes de aplicar
nginx -t

# ── 4. Criar diretório de config do blackhole ─────────────────────────────────
echo "[4/7] Configurando blackhole daemon..."
mkdir -p /etc/kcp
touch /etc/kcp/whitelist.txt
chmod 600 /etc/kcp/whitelist.txt

# Whitelist: o próprio servidor e localhost
SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || echo "")
if [ -n "$SERVER_IP" ]; then
    echo "$SERVER_IP" >> /etc/kcp/whitelist.txt
fi
echo "127.0.0.1" >> /etc/kcp/whitelist.txt
sort -u /etc/kcp/whitelist.txt -o /etc/kcp/whitelist.txt

# ── 5. Criar logs do nginx por peer ──────────────────────────────────────────
echo "[5/7] Criando arquivos de log..."
for peer in peer04 peer05 peer07; do
    touch /var/log/nginx/kcp-$peer.access.log
    touch /var/log/nginx/kcp-$peer.error.log
    chown www-data:adm /var/log/nginx/kcp-$peer.access.log
    chown www-data:adm /var/log/nginx/kcp-$peer.error.log
done

# ── 6. Iniciar serviços ───────────────────────────────────────────────────────
echo "[6/7] Iniciando serviços..."
systemctl reload nginx

for peer in peer04 peer05 peer07; do
    systemctl enable kcp-$peer
    systemctl restart kcp-$peer
    echo "  kcp-$peer: $(systemctl is-active kcp-$peer)"
done

sleep 3  # Aguardar uvicorn subir

systemctl enable kcp-blackhole
systemctl restart kcp-blackhole
echo "  kcp-blackhole: $(systemctl is-active kcp-blackhole)"

# ── 7. Health check ───────────────────────────────────────────────────────────
echo "[7/7] Health check..."
for peer in peer04 peer05 peer07; do
    STATUS=$(curl -s --max-time 5 https://$peer.kcp-protocol.org/kcp/v1/health 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null || echo "timeout")
    echo "  https://$peer.kcp-protocol.org → $STATUS"
done

echo ""
echo "════════════════════════════════════════════════════"
echo "  Deploy completo!"
echo "  Blackhole status: python3 /dados/kcp/infra/kcp-blackhole.py --status"
echo "  Unban IP: python3 /dados/kcp/infra/kcp-blackhole.py --unban <ip>"
echo "════════════════════════════════════════════════════"
