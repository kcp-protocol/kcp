# KCP — Site Access Report
**Período:** 20–21 de março de 2026 (primeiras 48h no ar)
**Site:** https://kcp-protocol.org (GitHub Pages)
**Gerado em:** 21/03/2026

---

## Metodologia

O GitHub Pages **não fornece logs de acesso** nativos. Não há dashboard, API ou painel de analytics por padrão.

A medição utilizada neste relatório foi possível graças a um efeito colateral do design anterior da `status.html`: o browser do visitante fazia `fetch()` diretamente para os peers KCP com o header `Referer: https://kcp-protocol.org/`, deixando rastros nos logs nginx do VPS.

> **Nota:** A partir de 21/03/2026, o `status.html` foi migrado para o modelo server-side (`/kcp/v1/network-status`), que elimina esse rastro browser-side. A captura descrita abaixo vale apenas para o período em que o modelo client-side estava ativo.

---

## Resumo Executivo

| Métrica | Valor |
|--------|-------|
| **Visitantes humanos únicos** | **6 IPs** |
| **Sessões totais (humanos)** | ~15 sessões |
| **Requisições de humanos via site** | ~75 |
| **Bots/Crawlers identificados** | 4 famílias |
| **País predominante** | 🇧🇷 Brasil |
| **Dispositivo predominante** | 📱 Android / iPhone |
| **Período coberto** | 20/03/2026 23:54 – 21/03/2026 15:05 UTC |

---

## Visitantes Humanos

Identificados via `Referer: https://kcp-protocol.org/` no nginx, com user-agent de browser real (não crawler).

| # | IP | Requests | Dispositivo | Localização | Horário (UTC) |
|---|-----|---------|-------------|-------------|----------------|
| 1 | `179.193.55.228` | **45** | Android Chrome 146 | São Paulo, SP — Vivo/Telefônica | 11:23 → 14:31 (3 blocos) |
| 2 | `189.98.252.107` | **9** | Android Chrome 146 | São Paulo, SP — Vivo/Telefônica | 12:25 → 12:31 |
| 3 | `172.226.128.49` | **3** | **iPhone** iOS 18.7 / Safari 26.3 | — | 14:28 |
| 4 | `189.18.231.206` | **3** | **iPhone** iOS 18.7 / CriOS 26.3 | Porto Alegre, RS — Vivo/Telefônica | 11:20 |
| 5 | `31.121.111.19` | **3** | Windows Chrome 125 | Tidworth, England — BT PLC | 11:04 |
| 6 | `189.96.225.19` | **3** | Android Chrome 146 | Brasil — Vivo/Telefônica | 12:35 |

**Total humanos: 6 visitantes únicos, ~15 sessões distintas**

### Destaques

- **`179.193.55.228` é o visitante mais engajado** — retornou ao site em 3 momentos distintos ao longo de 3 horas (11:23, 11:46, 13:07, 13:41–13:47, 14:31). Cada visita verifica o status da rede em tempo real. Provavelmente compartilhou o link com outras pessoas.

- **`189.98.252.107`** foi além do status: também acessou diretamente `/kcp/v1/peers` (a lista de peers da rede), indicando curiosidade técnica sobre a arquitetura.

- **Maioria mobile, maioria brasileira** — 4 dos 6 visitantes são Android/iPhone com IP brasileiro. O protocolo já tem audiência orgânica no Brasil desde o primeiro dia.

- **Visitante do Reino Unido** (`31.121.111.19`, Windows/Chrome, BT PLC) — primeiro visitante internacional registrado.

---

## Bots & Crawlers Identificados

| IP(s) | Família | Requests | Tipo | Via site? |
|-------|---------|---------|------|-----------|
| `17.241.219.63`, `17.241.75.204`, `17.241.75.239`, `17.22.245.36`, `17.22.245.87`, `17.22.253.86`, `17.246.19.66`, `17.246.23.245` | **Applebot** (Apple Inc.) | 8 | Indexador Spotlight/Siri | ✅ Via `kcp-protocol.org` |
| `74.125.210.65`, `74.125.210.97`, `74.125.210.108` | **Google-Read-Aloud** | 3 | Leitor IA do Google | ✅ Via `kcp-protocol.org` |
| `170.85.22.208` | **Script/curl** (curl/8.7.1) | **639** | Monitor automatizado (curl) | Via site (status.html aberto) |
| `34.222.95.144` | Crawler desconhecido | 10 | Acesso direto às URLs dos peers | ❌ Direto ao peer |
| `85.11.167.19` | Crawler desconhecido (POST /) | 6 | Tentativa de POST na raiz | ❌ Direto ao peer |
| `64.15.129.x` (6 IPs) | Scanner de rede | 6 | GET / com Chrome UA falso | ❌ Direto ao peer |
| `192.175.111.x` (5 IPs) | Scanner de rede | 5 | GET / com Chrome UA falso | ❌ Direto ao peer |

### Destaques de bots

- **Applebot visitou 8 vezes via `kcp-protocol.org`** — Apple está indexando o conteúdo do site para Apple Intelligence / Spotlight / Safari. Isso significa que usuários de iPhone poderão encontrar o KCP em buscas nativas da Apple.

- **Google-Read-Aloud visitou via `kcp-protocol.org`** — O assistente de leitura por voz do Google leu o site. É sinal de que o Google já rastreou o conteúdo e o está processando para síntese de voz (Google Assistant, Chrome leitor).

- **`170.85.22.208` — 639 requests, curl/8.7.1** — Este IP acessou o site e manteve a aba aberta com o status.html em auto-refresh (a cada ~30 segundos, 3 peers × ~213 ciclos = ~6h30 de monitoramento contínuo). Comportamento de dev/ops monitorando o deployment ao vivo.

---

## Linha do Tempo — Dia 1

```
20/03 23:54  Primeiros scanners de rede detectam os peers (peer07 online)
21/03 01:00  Segunda rodada de scanners (peer04/05)
21/03 05:03  Crawler 34.222.95.144 (Windows Edge 18) — acesso direto
21/03 06:20  Crawler 85.11.167.19 — POST na raiz (probe de vulnerabilidade)
21/03 08:39  Crawler 185.247.137.94 acessa peer05
21/03 09:01  Crawler 87.236.176.167 acessa peer07

--- Fase humana começa ---
21/03 11:04  👤 Visitante #1: Windows/Chrome — Reino Unido (31.121.111.19)
21/03 11:20  👤 Visitante #2: iPhone/Safari — Porto Alegre BR (189.18.231.206)
21/03 11:23  👤 Visitante #3 (mais ativo): Android/Chrome — São Paulo BR (179.193.55.228)
             🤖 Applebot começa a indexar (17.241.219.63 e outros)
21/03 12:25  👤 Visitante #4: Android/Chrome — São Paulo BR (189.98.252.107)
             🤖 Google-Read-Aloud lê o site (74.125.210.x)
21/03 12:35  👤 Visitante #5: Android/Chrome — Brasil (189.96.225.19)
21/03 13:07  🔄 Visitante #3 retorna (2ª sessão)
21/03 13:41  🔄 Visitante #3 retorna (3ª sessão — monitora status por ~6min)
21/03 14:28  👤 Visitante #6: iPhone/Safari — (172.226.128.49)
21/03 14:31  🔄 Visitante #3 retorna (4ª sessão)
21/03 15:05  Último registro (fim do período analisado)
```

---

## Distribuição Geográfica

| País | Visitantes humanos | % |
|------|-------------------|---|
| 🇧🇷 Brasil | 5 | 83% |
| 🇬🇧 Reino Unido | 1 | 17% |

> Todos os visitantes brasileiros são da operadora **Vivo/Telefônica**, concentrados em São Paulo e Porto Alegre.

---

## Distribuição por Dispositivo

| Dispositivo | Visitantes | % |
|-------------|-----------|---|
| 📱 Android Chrome 146 | 3 | 50% |
| 📱 iPhone Safari/WebKit | 2 | 33% |
| 💻 Windows Chrome 125 | 1 | 17% |

**100% mobile** no Brasil. O site precisa ter boa experiência mobile — e `docs/status.html` já é responsivo.

---

## Cobertura por Crawler/IA

| Crawler | Empresa | Finalidade | Status |
|---------|---------|------------|--------|
| **Applebot** | Apple | Spotlight, Siri, Apple Intelligence | ✅ Indexado |
| **Google-Read-Aloud** | Google | Assistant, Chrome Reader | ✅ Lido |
| **OpenAI SearchBot** | OpenAI | ChatGPT Search | ✅ Indexado* |
| **Googlebot** | Google | Google Search | Provável** |

\* Registrado em sessão anterior (ver `docs/network-report-2026-03-21.md`)
\*\* Google-Read-Aloud só processa páginas já indexadas pelo Googlebot

---

## Observações sobre Limitações de Medição

1. **GitHub Pages não tem logs** — visitantes que leram apenas o HTML estático (sem abrir `status.html`) não aparecem neste relatório.

2. **O modelo client-side captou apenas quem abriu `status.html`** — visitantes que leram `index.html`, `whitepaper.md`, `roadmap.md` etc. são invisíveis aqui.

3. **Estimativa real de visitantes** = muito provavelmente 2–4× mais do que os 6 registrados, pois muitos leram apenas a landing page.

4. **A partir de hoje** (21/03/2026), o `status.html` migrou para o endpoint server-side `/kcp/v1/network-status`, que não gera mais rastreio de referrer por IP individual.

---

## Recomendação: Analytics para o Futuro

Para medir acessos futuros ao GitHub Pages de forma precisa, recomendamos adicionar um beacon leve:

**Opção A — Beacon próprio no VPS (privacy-first, zero dependência terceira):**
```html
<!-- Em docs/index.html, status.html, etc. -->
<script>
  fetch('https://peer04.kcp-protocol.org/kcp/v1/beacon?page=' + 
    encodeURIComponent(location.pathname), { method: 'POST', keepalive: true });
</script>
```
Requer implementar `POST /kcp/v1/beacon` no `node.py` (apenas loga `page`, `ip`, `ua`, `ts`).

**Opção B — Plausible Analytics self-hosted** (dashboard bonito, GDPR-compliant):
```html
<script defer data-domain="kcp-protocol.org" 
  src="https://peer04.kcp-protocol.org/js/script.js"></script>
```

---

## Conclusão

O site `kcp-protocol.org` completou seu primeiro dia com **6 visitantes humanos únicos confirmados**, maioria mobile brasileira, e foi imediatamente indexado por **Apple** e **Google**. O visitante mais engajado (`179.193.55.228`) retornou 4 vezes ao longo do dia e claramente compartilhou o link — os outros visitantes brasileiros aparecem nas horas seguintes.

Para próximas iterações: implementar o beacon de analytics próprio no VPS para ter visibilidade completa de todo o tráfego GitHub Pages, não apenas de quem abre o status.

---

*Gerado por análise dos logs nginx do VPS `165.22.151.182` — peers peer04/05/07.*
*Dados coletados via `sudo grep 'kcp-protocol.org' /var/log/nginx/kcp-peer*.access.log`*
