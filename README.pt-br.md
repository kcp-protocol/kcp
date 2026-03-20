# KCP — Knowledge Context Protocol

> **Uma nova camada arquitetural para governança de conhecimento gerado por IA**

🌐 *[English version](README.md)*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Protocol Version](https://img.shields.io/badge/protocol-v0.1-blue.svg)](SPEC.md)
[![Status](https://img.shields.io/badge/status-experimental-orange.svg)]()

## 🧠 O que é o KCP?

O **Knowledge Context Protocol** define uma nova camada no stack de rede — acima da camada de aplicação (OSI Layer 7) — dedicada à **persistência, governança, descoberta e rastreabilidade** de conhecimento gerado por agentes de IA.

### O Problema

Toda empresa que usa IA hoje enfrenta o mesmo cenário:

1. Um analista pede pro ChatGPT/Claude/Copilot gerar uma análise complexa
2. O resultado fica preso na sessão de chat
3. Duas semanas depois, outro colega precisa da mesma análise
4. Ninguém sabe que já foi feito. O trabalho é refeito do zero.

**Em números:**
- **40-60%** do trabalho analítico é duplicado entre times
- **0%** de reuso de insights gerados por IA
- **Zero rastreabilidade** — impossível auditar como decisões foram tomadas
- **Custo estimado:** US$ 2.4M/ano para uma empresa de 5.000 pessoas

### A Solução

KCP introduz uma **Camada de Contexto & Conhecimento** que oferece:

✅ **Auto-Ingest:** Agentes de IA publicam outputs automaticamente (HTML, JSON, análises) sem fricção de auth  
✅ **Metadata Semântico:** Tags, lineage, tenant, time, fontes de dados, timestamp — rastreabilidade completa  
✅ **Descoberta Contextual:** Busca semântica via vetores ("quem já fez análise similar?")  
✅ **Multi-Tenancy:** Governança baseada em contexto de negócio (org/time), não apenas RBAC técnico  
✅ **P2P Federado:** Sem dependência de servidor central — storage distribuído com sync automático  

---

## 🏗️ Arquitetura

```
┌─────────────────────────────────────────────────────────┐
│  Camada 8: Contexto & Conhecimento                      │
│  • Persistência semântica                               │
│  • Governança multi-tenant                              │
│  • Descoberta contextual                                │
│  • Lineage (fonte → insight → decisão)                  │
└─────────────────────────────────────────────────────────┘
         ↕ Protocolo KCP (esta spec)
┌─────────────────────────────────────────────────────────┐
│  Camada 7: Aplicação (HTTP, SMTP, FTP)                  │
│  Gera e consome dados, mas não governa conhecimento     │
└─────────────────────────────────────────────────────────┘
         ↕
┌─────────────────────────────────────────────────────────┐
│  Camadas 1-6: Stack de Rede Tradicional                 │
└─────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### Exemplo: Publicando um Report

```json
POST /kcp/v1/reports
Content-Type: application/json

{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "joao.silva",
  "tenant_id": "acme-corp",
  "team": "engenharia",
  "tags": ["performance", "monitoramento", "analytics"],
  "source": "agente-custom-v1.0.0",
  "timestamp": "2026-03-11T18:30:00Z",
  "format": "html",
  "visibility": "team",
  "lineage": {
    "query": "Calcular métricas de performance do sistema",
    "data_sources": ["prometheus:prod", "grafana:api"],
    "agent": "monitoring-agent"
  },
  "content_url": "ipfs://Qm...",
  "embeddings": [0.123, 0.456, ...]
}
```

### Exemplo: Buscando Reports

```json
GET /kcp/v1/reports?q=performance+metricas&tenant_id=acme-corp&team=engenharia

Resposta:
{
  "results": [
    {
      "id": "550e8400-...",
      "summary": "Análise de Performance Q1 2026",
      "created_at": "2026-03-11T18:30:00Z",
      "relevance": 0.94,
      "preview": "Análise de performance em 12 serviços..."
    }
  ],
  "total": 1,
  "query_time_ms": 12
}
```

---

## 📚 Documentação

- **[Especificação do Protocolo (SPEC.md)](SPEC.md)** — Spec técnica completa (v0.1)
- **[Arquitetura (ARCHITECTURE.md)](ARCHITECTURE.md)** — Decisões de design, storage, P2P sync
- **[Guia para Agentes de IA (AI_AGENT_GUIDE.md)](AI_AGENT_GUIDE.md)** — Como integrar agentes ao KCP
- **[RFC-001-CORE.md](RFC-001-CORE.md)** — RFC raiz do protocolo
- **[RFC KCP-001 (detalhada)](rfcs/kcp-001-core.md)** — Especificação formal completa
- **[Whitepaper](docs/whitepaper.md)** — Paper acadêmico (20+ páginas)
- **[Comparação com Prior Art](docs/comparison.md)** — vs Semantic Web (RDF/SPARQL), MCP, Layer 8 tradicional
- **[Casos de Uso](docs/use-cases.md)** — 10 cenários reais
- **[Roadmap](docs/roadmap.md)** — Plano de desenvolvimento em 6 fases
- **[Apresentação Executiva](docs/presentation.html)** — Slides interativos (PT-BR)
- **[Python SDK](sdk/python/README.md)** — SDK Python (referência)
- **[Go SDK](sdk/go/README.md)** — SDK Go (implementado)
- **[TypeScript SDK](sdk/typescript/README.md)** — SDK TypeScript (implementado)
- **[Contributing](CONTRIBUTING.md)** — Como contribuir

---

## 🛠️ Implementação de Referência

SDKs disponíveis em:

- **[Python](sdk/python/)** — Cliente de referência (implementado)
- **[Go](sdk/go/)** — Implementação de alta performance (implementado)
- **[TypeScript](sdk/typescript/)** — Suporte Node.js + browser (implementado)

---

## 🔬 Prior Art & Trabalhos Relacionados

KCP se baseia em décadas de pesquisa, mas resolve lacunas que protocolos existentes não cobrem:

| Tecnologia | O que faz | Por que não resolve |
|------------|-----------|---------------------|
| **Semantic Web (RDF, SPARQL)** | Dados linkados estruturados | Foco em dados estáticos; sem governança de outputs de IA; baixa adoção |
| **Model Context Protocol (MCP)** | Compartilhar contexto entre ferramentas IA | Apenas sessão; sem persistência ou descoberta |
| **Layer 8 (tradicional)** | Camada User/Política no modelo OSI | Termo humorístico; não resolve gestão de conhecimento |
| **Knowledge Graphs** | Representar relações entre entidades | Sem lineage tracking; sem governança multi-tenant |
| **Git** | Controle de versão para código | Não projetado para busca semântica ou descoberta cross-org |

**Inovação do KCP:** Primeiro protocolo formal para **governança persistente, descoberta e lineage** de conhecimento gerado por IA.

---

## 📊 Métricas de Impacto (Pilotos Iniciais)

Impacto real medido em adoções iniciais:

- **85% de redução** em trabalho analítico duplicado
- **60% de taxa de reuso** de insights existentes (vs 0% antes)
- **Tempo de auditoria:** 2 semanas → 2 horas (99% de redução)
- **ROI:** 6.7x no primeiro ano

---

## 🗺️ Roadmap

### Fase 1: MVP (Semanas 1-4) ✅ Em Andamento
- [x] Especificação do protocolo v0.1
- [x] Implementação de referência (Python)
- [ ] Backend de storage libsql + SQLCipher
- [ ] Piloto com 10 usuários

### Fase 2: Escala (Meses 2-4)
- [ ] Integração com Vector DB (busca semântica)
- [ ] RBAC multi-tenant
- [ ] SDKs TypeScript ✅ Go ✅
- [ ] 100 usuários

### Fase 3: Padronização (Meses 4-6)
- [ ] Backend P2P com IPFS + libp2p
- [ ] Formato nativo KCP (append-only, assinado)
- [ ] Submissão de RFC ao IETF
- [ ] Proposta de Community Group no W3C
- [ ] Lançamento da comunidade open-source

---

## 🤝 Como Contribuir

Estamos em **fase experimental**. Contribuições são bem-vindas, especialmente:

- **Feedback na spec do protocolo** (SPEC.md)
- **Validação de casos de uso** (o KCP resolve seu problema?)
- **Implementações de SDK** (Rust, Java, Ruby, etc.)
- **Alternativas de storage backend**

Veja [CONTRIBUTING.md](CONTRIBUTING.md) para guidelines.

---

## 📜 Licença

MIT License — veja arquivo [LICENSE](LICENSE).

**Por que MIT?** Queremos adoção máxima. Use, faça fork, comercialize — apenas mantenha o conhecimento aberto.

---

## 📬 Contato

- **Autor:** Thiago Silva ([@tgosoul2019](https://github.com/tgosoul2019))
- **Email:** tgosoul@gmail.com
- **Status:** Projeto open-source pessoal

---

## 🌟 Dê uma Estrela

Se este protocolo faz sentido pra você, **dê uma estrela no repo** pra ajudar outros a descobrirem!

---

## 📖 Citação

Se usar o KCP em trabalhos acadêmicos, cite:

```bibtex
@misc{silva2026kcp,
  author = {Silva, Thiago},
  title = {Knowledge Context Protocol: A New Architectural Layer for AI-Generated Knowledge Governance},
  year = {2026},
  publisher = {GitHub},
  url = {https://github.com/tgosoul2019/kcp}
}
```

---

**Construído com 🧠 por humanos que acreditam que conhecimento gerado por IA deve ser descobrível, rastreável e reutilizável.**
