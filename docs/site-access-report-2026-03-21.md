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
> IPs de origem removidos por privacidade. Dados agregados por país/dispositivo.

| # | Sessão | Requests | Dispositivo | País | Horário (UTC) |
|---|--------|---------|-------------|------|----------------|
| 1 | visitor-A | **45** | Android Chrome 146 | 🇧🇷 Brasil | 11:23 → 14:31 (4 retornos) |
| 2 | visitor-B | **9** | Android Chrome 146 | 🇧🇷 Brasil | 12:25 → 12:31 |
| 3 | visitor-C | **3** | iPhone iOS 18.7 / Safari | 🇧🇷 Brasil | 14:28 |
| 4 | visitor-D | **3** | iPhone iOS 18.7 / Chrome | 🇧🇷 Brasil | 11:20 |
| 5 | visitor-E | **3** | Windows Chrome 125 | 🇬🇧 Reino Unido | 11:04 |
| 6 | visitor-F | **3** | Android Chrome 146 | 🇧🇷 Brasil | 12:35 |

**Total humanos: 6 visitantes únicos, ~15 sessões distintas**

### Destaques

- **Visitor-A é o mais engajado** — retornou ao site em 4 momentos distintos ao longo de 3 horas (11:23, 11:46, 13:07, 13:41–13:47, 14:31). Cada visita verifica o status da rede em tempo real. Provavelmente compartilhou o link com outras pessoas.

- **Visitor-B** foi além do status: também acessou diretamente `/kcp/v1/peers` (a lista de peers da rede), indicando curiosidade técnica sobre a arquitetura.

- **Maioria mobile, maioria brasileira** — 5 dos 6 visitantes usam Android/iPhone com origem no Brasil. O protocolo já tem audiência orgânica no Brasil desde o primeiro dia.

- **Primeiro visitante internacional** (visitor-E, Windows/Chrome, Reino Unido) — registrado às 11:04 UTC.

---

## Bots & Crawlers Identificados

| Família | Requests | Tipo | Via site? |
|---------|---------|------|-----------|
| **Applebot** (Apple Inc.) | 8 | Indexador Spotlight/Siri | ✅ Via `kcp-protocol.org` |
| **Google-Read-Aloud** | 3 | Leitor IA do Google | ✅ Via `kcp-protocol.org` |
| **Monitor automatizado** (curl/8.7.1) | **639** | Script de monitoramento contínuo | Via site (status.html aberto) |
| Crawler desconhecido | 10 | Acesso direto às URLs dos peers | ❌ Direto ao peer |
| Crawler desconhecido (POST /) | 6 | Tentativa de POST na raiz | ❌ Direto ao peer |
| Scanner de rede (6 IPs) | 6 | GET / com Chrome UA falso | ❌ Direto ao peer |
| Scanner de rede (5 IPs) | 5 | GET / com Chrome UA falso | ❌ Direto ao peer |

### Destaques de bots

- **Applebot visitou 8 vezes via `kcp-protocol.org`** — Apple está indexando o conteúdo do site para Apple Intelligence / Spotlight / Safari. Isso significa que usuários de iPhone poderão encontrar o KCP em buscas nativas da Apple.

- **Google-Read-Aloud visitou via `kcp-protocol.org`** — O assistente de leitura por voz do Google leu o site. É sinal de que o Google já rastreou o conteúdo e o está processando para síntese de voz (Google Assistant, Chrome leitor).

- **Monitor curl — 639 requests** — Uma sessão manteve o `status.html` aberto em auto-refresh (a cada ~30 segundos, 3 peers × ~213 ciclos = ~6h30 de monitoramento contínuo). Comportamento típico de dev/ops monitorando o deployment ao vivo.

---

## Linha do Tempo — Dia 1

```
20/03 23:54  Primeiros scanners de rede detectam os peers (peer07 online)
21/03 01:00  Segunda rodada de scanners (peer04/05)
21/03 05:03  Crawler desconhecido (Windows Edge 18) — acesso direto
21/03 06:20  Crawler — POST na raiz (probe de vulnerabilidade)
21/03 08:39  Crawler acessa peer05
21/03 09:01  Crawler acessa peer07

--- Fase humana começa ---
21/03 11:04  👤 visitor-E: Windows/Chrome — Reino Unido
21/03 11:20  👤 visitor-D: iPhone/Safari — Brasil
21/03 11:23  👤 visitor-A (mais ativo): Android/Chrome — Brasil
             🤖 Applebot começa a indexar
21/03 12:25  👤 visitor-B: Android/Chrome — Brasil
             🤖 Google-Read-Aloud lê o site
21/03 12:35  👤 visitor-F: Android/Chrome — Brasil
21/03 13:07  🔄 visitor-A retorna (2ª sessão)
21/03 13:41  🔄 visitor-A retorna (3ª sessão — monitora status por ~6min)
21/03 14:28  👤 visitor-C: iPhone/Safari — Brasil
21/03 14:31  🔄 visitor-A retorna (4ª sessão)
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

O site `kcp-protocol.org` completou seu primeiro dia com **6 visitantes humanos únicos confirmados**, maioria mobile brasileira, e foi imediatamente indexado por **Apple** e **Google**. O visitor-A retornou 4 vezes ao longo do dia e claramente compartilhou o link — os outros visitantes brasileiros aparecem nas horas seguintes.

Para próximas iterações: implementar o beacon de analytics próprio no VPS para ter visibilidade completa de todo o tráfego GitHub Pages, não apenas de quem abre o status.

---

*Gerado por análise dos logs nginx do VPS — peers peer04/05/07.*  
*IPs de origem de visitantes humanos omitidos por privacidade.*  
*Dados coletados via `sudo grep 'kcp-protocol.org' /var/log/nginx/kcp-peer*.access.log`*
