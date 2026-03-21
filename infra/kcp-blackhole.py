#!/usr/bin/env python3
"""
KCP Blackhole Daemon
====================
Lê o access log do nginx em tempo real via stdin (tail -F | pipe) e aplica
blackhole de roteamento no kernel Linux para IPs que violam as regras.

Como funciona
-------------
O kernel Linux permite dropar todos os pacotes de um IP sem passar pelo nginx:

    ip route add blackhole 1.2.3.4/32

Isso acontece na camada de rede (antes do TCP handshake), consumindo
quase zero CPU/memória comparado ao nginx processar e rejeitar.

Regras de banimento
-------------------
┌──────────────────────────────────────┬──────────┬───────────────────────────┐
│ Violação                             │ Penalidade inicial │ Escalada       │
├──────────────────────────────────────┼──────────┬───────────────────────────┤
│ Sem X-KCP-Client em /sync/ (400)     │ 60s      │ ×5 por reincidência       │
│ Rate limit excedido (429)            │ 60s      │ ×5 por reincidência       │
│ Scan de rotas inválidas (404 repeat) │ 300s     │ ×3 por reincidência       │
│ Acumulou 3+ banimentos               │ permanente → só sai via admin        │
└──────────────────────────────────────┴──────────────────────────────────────┘

Escalada de tempo:
  offense 1 → 60s
  offense 2 → 5min
  offense 3 → 30min
  offense 4 → 3h
  offense 5 → 24h
  offense 6+ → permanente (BLACKLIST permanente)

Uso
---
  # Via systemd (recomendado):
  sudo systemctl start kcp-blackhole

  # Manual (debug):
  tail -F /var/log/nginx/kcp-peer*.access.log | sudo python3 /dados/kcp/infra/kcp-blackhole.py

  # Ver status:
  sudo python3 /dados/kcp/infra/kcp-blackhole.py --status

Persistência
-----------
  /etc/kcp/blacklist.json   — bans ativos (sobrevive restart)
  /var/log/kcp-blackhole.log — audit log de cada ban/unban

Notas de segurança
------------------
- IPs privados (10.x, 172.16.x, 192.168.x, 127.x) NUNCA são banidos
- O próprio IP do servidor NUNCA é banido
- Whitelist configurável em /etc/kcp/whitelist.txt (um IP/CIDR por linha)
- Requer root (para manipular rotas de kernel)
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, Thread
from typing import Optional

# ─── Config ────────────────────────────────────────────────────────────────────

BLACKLIST_PATH = Path("/etc/kcp/blacklist.json")
WHITELIST_PATH = Path("/etc/kcp/whitelist.txt")
AUDIT_LOG      = Path("/var/log/kcp-blackhole.log")
CHECK_INTERVAL = 10   # segundos entre varreduras de expiração

# Janela de tempo para contar violações do mesmo IP (segundos)
VIOLATION_WINDOW = 60

# Mínimo de violações na janela para acionar ban
VIOLATION_THRESHOLD_RATE  = 5   # 5 x 429 em 60s
VIOLATION_THRESHOLD_NOCLI = 3   # 3 x 400 (sem X-KCP-Client) em 60s
VIOLATION_THRESHOLD_SCAN  = 10  # 10 x 404 em 60s

# Duração dos bans por ofensa (segundos). Último item = permanente (0 = forever)
BAN_ESCALATION = [60, 300, 1800, 10800, 86400, 0]

# IPs/redes que NUNCA são banidos
NEVER_BAN_PREFIXES = [
    "127.", "10.", "172.16.", "172.17.", "172.18.", "172.19.",
    "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
    "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.",
    "192.168.",
]

# ─── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(AUDIT_LOG), mode="a"),
    ],
)
log = logging.getLogger("kcp.blackhole")

# ─── Nginx log parser ──────────────────────────────────────────────────────────
# Formato: $remote_addr - $remote_user [$time_local] "$request" $status ...
# Exemplo: 1.2.3.4 - - [21/Mar/2026:10:00:00 +0000] "GET /kcp/v1/health HTTP/1.1" 200 ...

LOG_PATTERN = re.compile(
    r'^(?P<ip>\d+\.\d+\.\d+\.\d+)'   # IP
    r'[^"]*"(?P<method>\w+)\s'        # method
    r'(?P<path>\S+)[^"]*"\s'          # path
    r'(?P<status>\d{3})'              # status code
)


def parse_log_line(line: str) -> Optional[dict]:
    m = LOG_PATTERN.match(line.strip())
    if not m:
        return None
    return {
        "ip":     m.group("ip"),
        "method": m.group("method"),
        "path":   m.group("path"),
        "status": int(m.group("status")),
        "ts":     time.time(),
    }


# ─── State ─────────────────────────────────────────────────────────────────────

class BlackholeState:
    def __init__(self):
        self._lock = Lock()
        # ip → list of (timestamp, violation_type)
        self._violations: dict[str, list[tuple[float, str]]] = defaultdict(list)
        # ip → {"offenses": int, "banned_until": float, "permanent": bool}
        self._bans: dict[str, dict] = {}
        self._whitelist: set[str] = set()
        self._load_persistent()
        self._load_whitelist()

    # ── Persistence ────────────────────────────────────────────

    def _load_persistent(self):
        """Load active bans from disk."""
        BLACKLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        if BLACKLIST_PATH.exists():
            try:
                self._bans = json.loads(BLACKLIST_PATH.read_text())
                # Re-apply kernel routes for still-active bans
                now = time.time()
                for ip, info in self._bans.items():
                    if info.get("permanent") or info.get("banned_until", 0) > now:
                        self._kernel_blackhole(ip, add=True, silent=True)
                log.info(f"Loaded {len(self._bans)} bans from {BLACKLIST_PATH}")
            except Exception as e:
                log.warning(f"Could not load blacklist: {e}")

    def _save_persistent(self):
        """Persist current bans to disk."""
        try:
            BLACKLIST_PATH.write_text(json.dumps(self._bans, indent=2))
        except Exception as e:
            log.error(f"Could not save blacklist: {e}")

    def _load_whitelist(self):
        """Load IP whitelist from file."""
        if WHITELIST_PATH.exists():
            for line in WHITELIST_PATH.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    self._whitelist.add(line)
            log.info(f"Whitelist: {len(self._whitelist)} entries")

    # ── Core logic ─────────────────────────────────────────────

    def is_protected(self, ip: str) -> bool:
        """Return True if this IP must never be banned."""
        if any(ip.startswith(p) for p in NEVER_BAN_PREFIXES):
            return True
        if ip in self._whitelist:
            return True
        # Check CIDR ranges in whitelist
        try:
            addr = ipaddress.ip_address(ip)
            for entry in self._whitelist:
                try:
                    if addr in ipaddress.ip_network(entry, strict=False):
                        return True
                except ValueError:
                    pass
        except ValueError:
            pass
        return False

    def record_violation(self, ip: str, vtype: str):
        """Record a violation and ban if threshold exceeded."""
        if self.is_protected(ip):
            return
        with self._lock:
            now = time.time()
            # Prune old violations outside the window
            self._violations[ip] = [
                (ts, vt) for ts, vt in self._violations[ip]
                if now - ts < VIOLATION_WINDOW
            ]
            self._violations[ip].append((now, vtype))

            counts = defaultdict(int)
            for _, vt in self._violations[ip]:
                counts[vt] += 1

            should_ban = (
                counts["rate_limit"] >= VIOLATION_THRESHOLD_RATE or
                counts["no_client"] >= VIOLATION_THRESHOLD_NOCLI or
                counts["scan"]      >= VIOLATION_THRESHOLD_SCAN
            )

            if should_ban and not self._is_banned(ip):
                self._ban(ip, reason=vtype)

    def _is_banned(self, ip: str) -> bool:
        info = self._bans.get(ip)
        if not info:
            return False
        if info.get("permanent"):
            return True
        return info.get("banned_until", 0) > time.time()

    def _ban(self, ip: str, reason: str):
        """Apply ban with escalating duration."""
        info = self._bans.get(ip, {"offenses": 0})
        offense = info["offenses"] + 1
        info["offenses"] = offense

        idx = min(offense - 1, len(BAN_ESCALATION) - 1)
        duration = BAN_ESCALATION[idx]

        if duration == 0:
            info["permanent"] = True
            info["banned_until"] = 0
            log.warning(f"BLACKHOLE PERMANENT: {ip} (offense #{offense}, reason={reason})")
        else:
            info["banned_until"] = time.time() + duration
            info["permanent"] = False
            log.warning(
                f"BLACKHOLE {ip} for {duration}s "
                f"(offense #{offense}, reason={reason})"
            )

        info["last_reason"] = reason
        info["last_banned_at"] = datetime.now(timezone.utc).isoformat()
        self._bans[ip] = info
        self._kernel_blackhole(ip, add=True)
        self._save_persistent()
        # Clear violation window after ban
        self._violations.pop(ip, None)

    def unban(self, ip: str) -> bool:
        """Manually remove a ban (admin use)."""
        with self._lock:
            if ip in self._bans:
                del self._bans[ip]
                self._kernel_blackhole(ip, add=False)
                self._save_persistent()
                log.info(f"UNBAN: {ip} (manual)")
                return True
            return False

    def expire_bans(self):
        """Remove expired temporary bans (called periodically)."""
        now = time.time()
        with self._lock:
            expired = [
                ip for ip, info in self._bans.items()
                if not info.get("permanent") and info.get("banned_until", 0) < now
            ]
            for ip in expired:
                self._kernel_blackhole(ip, add=False)
                del self._bans[ip]
                log.info(f"BAN EXPIRED: {ip}")
            if expired:
                self._save_persistent()

    def status(self) -> dict:
        """Return current ban state."""
        now = time.time()
        active = []
        for ip, info in self._bans.items():
            if info.get("permanent"):
                remaining = "permanent"
            else:
                remaining = max(0, int(info.get("banned_until", 0) - now))
            active.append({
                "ip": ip,
                "offenses": info["offenses"],
                "remaining": remaining,
                "permanent": info.get("permanent", False),
                "reason": info.get("last_reason", ""),
                "since": info.get("last_banned_at", ""),
            })
        active.sort(key=lambda x: (0 if x["permanent"] else 1, -x["offenses"]))
        return {
            "active_bans": len(active),
            "bans": active,
            "whitelist_size": len(self._whitelist),
        }

    # ── Kernel interface ───────────────────────────────────────

    @staticmethod
    def _kernel_blackhole(ip: str, add: bool, silent: bool = False):
        """Add or remove a kernel-level blackhole route."""
        action = "add" if add else "del"
        cmd = ["ip", "route", action, "blackhole", f"{ip}/32"]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0 and not silent:
                # "RTNETLINK answers: File exists" is fine for add
                # "RTNETLINK answers: No such process" is fine for del
                if "exists" not in result.stderr and "No such" not in result.stderr:
                    log.error(f"ip route {action} failed for {ip}: {result.stderr.strip()}")
        except Exception as e:
            if not silent:
                log.error(f"ip route {action} error for {ip}: {e}")


# ─── Main daemon ───────────────────────────────────────────────────────────────

def expiry_thread(state: BlackholeState):
    """Background thread: expire temporary bans every CHECK_INTERVAL seconds."""
    while True:
        time.sleep(CHECK_INTERVAL)
        try:
            state.expire_bans()
        except Exception as e:
            log.error(f"expire_bans error: {e}")


def run_daemon(state: BlackholeState):
    """Read nginx log lines from stdin and process violations."""
    log.info("KCP Blackhole Daemon started — reading from stdin")

    # Start expiry background thread
    t = Thread(target=expiry_thread, args=(state,), daemon=True)
    t.start()

    for line in sys.stdin:
        try:
            entry = parse_log_line(line)
            if not entry:
                continue

            ip     = entry["ip"]
            status = entry["status"]
            path   = entry["path"]

            # 429 = rate limit exceeded
            if status == 429:
                state.record_violation(ip, "rate_limit")

            # 400 on sync path = missing X-KCP-Client header
            elif status == 400 and "/sync/" in path:
                state.record_violation(ip, "no_client")

            # Repeated 404s = scanning for vulnerabilities
            elif status == 404:
                state.record_violation(ip, "scan")

        except Exception as e:
            log.debug(f"Line parse error: {e}")


def print_status(state: BlackholeState):
    s = state.status()
    print(f"\n{'─'*60}")
    print(f"  KCP Blackhole Status — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'─'*60}")
    print(f"  Active bans : {s['active_bans']}")
    print(f"  Whitelist   : {s['whitelist_size']} entries")
    print(f"{'─'*60}")
    for b in s["bans"]:
        r = "♾  PERMANENT" if b["permanent"] else f"{b['remaining']}s remaining"
        print(f"  {b['ip']:<20} offenses={b['offenses']}  {r}")
        print(f"  {'':20} reason={b['reason']}  since={b['since'][:19]}")
    if not s["bans"]:
        print("  No active bans.")
    print(f"{'─'*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KCP Blackhole Daemon")
    parser.add_argument("--status", action="store_true", help="Show current ban status and exit")
    parser.add_argument("--unban", metavar="IP", help="Manually unban an IP")
    args = parser.parse_args()

    state = BlackholeState()

    if args.status:
        print_status(state)
        sys.exit(0)

    if args.unban:
        if state.unban(args.unban):
            print(f"✅ Unbanned: {args.unban}")
        else:
            print(f"⚠️  IP not in blacklist: {args.unban}")
        sys.exit(0)

    # Must run as root for kernel route manipulation
    if os.geteuid() != 0:
        print("❌ Must run as root (required for 'ip route' kernel operations)")
        sys.exit(1)

    run_daemon(state)
