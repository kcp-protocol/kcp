# KCP Network Report — 21 de março de 2026

> Snapshot gerado ao final da sessão de provisionamento completo da rede.  
> Todos os 7 peers públicos foram colocados em produção nesta data.

---

## Estado da rede

| Peer | URL | Node ID | Status |
|------|-----|---------|--------|
| peer01 | https://peer01.kcp-protocol.org | `c5c9de87-bc07-4235` | ✅ Live |
| peer02 | https://peer02.kcp-protocol.org | `8fb635b9-2426-4fe6` | ✅ Live |
| peer03 | https://peer03.kcp-protocol.org | `ed536e8d-80db-4536` | ✅ Live |
| peer04 | https://peer04.kcp-protocol.org | `133aec3e-5bc0-41b7` | ✅ Live |
| peer05 | https://peer05.kcp-protocol.org | `ea634ee9-fc64-420c` | ✅ Live |
| peer06 | https://peer06.kcp-protocol.org | `8275f9c7-047f-4965` | ✅ Live |
| peer07 | https://peer07.kcp-protocol.org | `9aa41716-1761-4f52` | ✅ Live |

**Summary:** `operational — 7/7 online`  
**Latência interna (peer-to-peer, mesma VPS):** 8–10ms  
**Certificados TLS:** Let's Encrypt, válidos até junho 2026

---

## Acesso ao site — logs nginx (20–21/03/2026)

### Total de requests por peer

| Peer | Requests | Período (UTC) |
|------|----------|---------------|
| peer01 | 721 | 21/03 14:43 → 14:49 *(recém provisionado)* |
| peer02 | 481 | 21/03 14:43 → 14:49 *(recém provisionado)* |
| peer03 | 721 | 21/03 14:43 → 14:49 *(recém provisionado)* |
| peer04 | 275 | 21/03 10:44 → 14:54 *(~4h)* |
| peer05 | 271 | 21/03 10:44 → 14:54 *(~4h)* |
| peer06 | 723 | 21/03 14:43 → 14:49 *(recém provisionado)* |
| peer07 | 319 | 21/03 10:43 → 14:54 *(~4h)* |
| *legado* | 1.252 | 20/03 22:48 → 21/03 10:16 *(config anterior)* |
| **TOTAL** | **4.762** | **20–21/03/2026** |

> Os peers 01/02/03/06 têm volume alto nos primeiros minutos por causa do cross-announce entre os 7 nós (42 chamadas `/kcp/v1/peers/announce` + health checks internos).

---

### Top endpoints (peer04 — representativo)

| Requests | Endpoint | Tipo |
|----------|----------|------|
| 225 | `/kcp/v1/health` | Health check (bots + network-status) |
| 13 | `/` | Home / redirecionamento |
| 7 | `/favicon.ico` | Browser |
| 6 | `/robots.txt` | Crawlers |
| 3 | `/kcp/v1/peers` | Gossip / peer discovery |
| 2 | `/kcp/v1/peers/announce` | Bootstrap de novos peers |
| 2 | `/pricing`, `/checkout`, `/cart`... | Scanners automáticos |

---

### HTTP Status codes (peer04)

| Código | Quantidade | Descrição |
|--------|------------|-----------|
| `200` | 230 | OK |
| `404` | 44 | Scanners explorando rotas inexistentes |

---

### IPs únicos (peer04)

**21 IPs distintos** no período. Distribuição por tipo:

| Tipo | Requests | Origem |
|------|----------|--------|
| Dev/Monitor (VS Code + curl) | 199 | Desenvolvedor principal |
| Visitante humano — Brasil | 15 | Visitante orgânico |
| Visitante humano — Brasil | 10 | Visitante orgânico |
| Visitante humano — Europa | 9 | Visitante orgânico |
| VPS interno | 8 | O próprio peer (cross-announce) |

> IPs de origem removidos por privacidade. Dados agregados por perfil de acesso.

---

### Clientes identificados (User-Agent)

| Requests | Cliente |
|----------|---------|
| ~166 | **VS Code 1.105** (Electron/Chrome) — desenvolvedor principal |
| ~30 | **Safari macOS** — acesso manual ao site |
| ~18 | **Chrome Mobile** (Android) |
| 9 | **Python aiohttp/3.13** — SDK ou automação |
| 7 | **curl** — testes manuais via terminal |
| 4 | **Applebot** — indexador da Apple |
| 3 | **OAI-SearchBot/1.3** — indexador OpenAI |

---

### Bots e crawlers

O site foi descoberto e indexado por:

- **OpenAI SearchBot** (`OAI-SearchBot/1.3`) — consultou `/robots.txt`
- **Applebot** (`Applebot/0.1`) — indexador da Apple / Spotlight

Ambos respeitaram o `robots.txt`. Nenhum bot malicioso bloqueado por rate limit ou blackhole neste período.

> **Nota:** Scanners automáticos testaram rotas como `/.env`, `/.git/config`, `/src/.env`, `/admin`. Todas retornaram `404` — nenhuma informação sensível exposta.

---

## Infraestrutura provisionada nesta sessão

### Commits

| Hash | Descrição |
|------|-----------|
| `0dd23ff` | feat(status): server-side `/kcp/v1/network-status` endpoint |
| `b387169` | fix(network-status): probe self via `localhost:{port}` |
| `0691cf6` | infra: `KCP_SELF_URL` nos systemd units |
| `f615efe` | fix(store): `upsert_peer` atualiza `node_id` corretamente |
| `715f1e1` | fix(peers.json): node_ids reais + remove campo `provider` |
| `990ca52` | infra: provisão completa dos 7 peers |
| `71fc61c` | fix(nginx): caminhos corretos dos certificados SSL |
| `1178b8a` | fix(nginx): peer05/peer07 usando cert de peer04 |
| `f1bd17d` | feat(peers.json): todos os 7 peers com node_ids reais |

### Arquivos criados/modificados

```
infra/
  kcp-peer01.service   ← NOVO
  kcp-peer02.service   ← NOVO
  kcp-peer03.service   ← NOVO
  kcp-peer06.service   ← NOVO
  nginx-kcp-peers.conf ← 7 server blocks + certs corretos
  deploy-new-peers.sh  ← NOVO (script one-shot de provisão)

docs/
  peers.json           ← 7 peers, node_ids reais, sem campo provider
  status.html          ← server-side health (não mais client-side)

sdk/python/kcp/
  node.py              ← GET /kcp/v1/network-status + self._port
  store.py             ← upsert_peer corrige node_id em updates
```

### Certificados TLS

| Cert | Cobre | Validade |
|------|-------|---------|
| `peer04.kcp-protocol.org` | peer04, peer05, peer07 | 18/06/2026 |
| `peer01.kcp-protocol.org` | peer01, peer02, peer03, peer06 | 19/06/2026 |

---

## Observações técnicas

### Bug corrigido: node_id placeholder no gossip
O `upsert_peer()` no `store.py` nunca atualizava o campo `id` em updates — IDs placeholder (`000000000004`) persistiam para sempre. Corrigido com `COALESCE(NULLIF(?, ''), id)` no UPDATE.

### Melhoria: status page server-side
A `status.html` agora consulta `GET /kcp/v1/network-status` (endpoint Python no peer04) em vez de fazer `fetch()` direto a cada peer. Elimina falsos negativos causados por VPN/firewall corporativo no browser do visitante.

### Próximos passos sugeridos
- Adicionar `kcp-peers.target` systemd para gerenciar os 7 como grupo
- Configurar `logrotate` para os logs nginx dos novos peers
- Monitoramento de uptime externo (UptimeRobot ou similar)
- Documentar o processo de "como adicionar um peer comunitário" (RFC KCP-004 → guia prático)
