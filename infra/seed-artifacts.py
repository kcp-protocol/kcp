#!/usr/bin/env python3
"""
KCP Artifact Seeder
Popula todos os 8 peers com 1000 artefatos cada (mix de formatos e visibilidades).
Roda diretamente no VPS via localhost para máxima velocidade.

Uso:
    python3 /dados/kcp/infra/seed-artifacts.py
    python3 /dados/kcp/infra/seed-artifacts.py --peers 8804,8805  # só alguns
    python3 /dados/kcp/infra/seed-artifacts.py --count 100        # menos artefatos

Endpoint: POST /kcp/v1/artifacts
Campos aceitos: title, content (str), format, tags, summary, visibility, source, derived_from
"""

import sys
import json
import random
import string
import argparse
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PEERS = {
    "peer01": 8801,
    "peer02": 8802,
    "peer03": 8803,
    "peer04": 8804,
    "peer05": 8805,
    "peer06": 8806,
    "peer07": 8807,
    "peer08": 8808,
}

ARTIFACTS_PER_PEER = 1000

# Distribuição de visibilidade
VISIBILITY_WEIGHTS = [
    ("public",  0.30),   # 30% público
    ("org",     0.25),   # 25% organização
    ("team",    0.35),   # 35% time
    ("private", 0.10),   # 10% privado
]

# Tenant/user pools simulados (para contexto do conteúdo gerado)
AGENTS  = ["gpt-4o", "claude-3-5-sonnet", "gemini-2-flash", "kcp-agent/1.0", "copilot-chat"]

# Banco de temas para conteúdo realista
TOPICS = [
    ("Análise de Churn", ["churn", "clientes", "ml", "retenção"],
     "Análise preditiva de churn usando dados dos últimos 12 meses."),
    ("Relatório de Vendas Q1", ["vendas", "q1", "financeiro", "kpi"],
     "Resultados consolidados do primeiro trimestre com comparativo YoY."),
    ("Benchmark de Modelos LLM", ["llm", "benchmark", "ia", "performance"],
     "Comparativo de latência e qualidade entre GPT-4o, Claude 3.5 e Gemini 2.0."),
    ("Plano de Capacidade Cloud", ["infra", "cloud", "aws", "capacidade"],
     "Projeção de uso e custo de infraestrutura para os próximos 6 meses."),
    ("Política de Governança IA", ["governança", "ia", "lgpd", "compliance"],
     "Framework de governança para uso responsável de IA segundo LGPD e EU AI Act."),
    ("Análise de Sentimento", ["nlp", "sentimento", "clientes", "feedback"],
     "Análise de NPS e sentimento em tickets de suporte — março 2026."),
    ("Relatório de Segurança", ["segurança", "auditoria", "pentest", "cvss"],
     "Resumo executivo de pentest e vulnerabilidades identificadas."),
    ("Dashboard de Métricas", ["dashboard", "métricas", "sla", "uptime"],
     "KPIs operacionais: SLA, uptime, MTTR e throughput por serviço."),
    ("Proposta de Arquitetura", ["arquitetura", "microservicos", "evento", "kafka"],
     "Proposta de migração para arquitetura event-driven com Kafka."),
    ("Análise Competitiva", ["competidores", "mercado", "benchmark", "estratégia"],
     "Mapeamento de competidores e análise de gaps de produto."),
    ("Onboarding de Engenharia", ["onboarding", "documentação", "engenharia", "setup"],
     "Guia de onboarding para novos engenheiros — stack, padrões e ferramentas."),
    ("Resultados de A/B Test", ["abtesting", "conversão", "produto", "dados"],
     "Resultados do experimento A/B na página de checkout — uplift +12%."),
    ("Protocolo KCP — RFC", ["kcp", "protocolo", "rfc", "especificação"],
     "Rascunho de RFC para extensão do protocolo KCP com suporte a TTL."),
    ("Previsão de Demanda", ["forecast", "ml", "demanda", "série-temporal"],
     "Modelo de previsão de demanda usando Prophet e dados históricos."),
    ("Auditoria de Custos", ["custos", "finops", "aws", "otimização"],
     "Revisão de custos de nuvem com oportunidades de saving identificadas."),
]

FORMATS = [
    ("html",     0.30),
    ("markdown", 0.25),
    ("json",     0.20),
    ("csv",      0.15),
    ("text",     0.10),
]


# ---------------------------------------------------------------------------
# Content generators
# ---------------------------------------------------------------------------

def rand_date(days_back: int = 90) -> str:
    d = datetime.now(timezone.utc) - timedelta(days=random.randint(0, days_back))
    return d.isoformat()


def pick_weighted(choices):
    r = random.random()
    acc = 0.0
    for item, w in choices:
        acc += w
        if r <= acc:
            return item
    return choices[-1][0]


def gen_html(topic: str, summary: str, tags: list[str]) -> bytes:
    rows = "\n".join(
        f"<tr><td>{random.randint(1,999)}</td><td>{random.choice(tags)}</td>"
        f"<td>{round(random.uniform(10,9999),2)}</td></tr>"
        for _ in range(random.randint(5, 20))
    )
    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>{topic}</title>
<style>body{{font-family:sans-serif;max-width:800px;margin:2rem auto;padding:0 1rem}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:.5rem;border:1px solid #ddd}}th{{background:#f4f4f4}}</style>
</head><body>
<h1>{topic}</h1>
<p>{summary}</p>
<p>Gerado por agente KCP em {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')}</p>
<h2>Dados</h2>
<table><tr><th>#</th><th>Categoria</th><th>Valor</th></tr>
{rows}
</table>
<p>Tags: {', '.join(tags)}</p>
</body></html>""".encode()


def gen_markdown(topic: str, summary: str, tags: list[str]) -> bytes:
    lines = [f"# {topic}", f"", f"> {summary}", f"",
             f"**Data:** {datetime.now(timezone.utc).strftime('%d/%m/%Y')}",
             f"**Tags:** {', '.join(f'`{t}`' for t in tags)}", f"",
             f"## Resumo Executivo", f"",
             f"Este documento foi gerado automaticamente pelo agente KCP como artefato de conhecimento.",
             f"", f"## Dados", f""]
    for i in range(random.randint(3, 8)):
        lines.append(f"- **Item {i+1}:** {random.choice(tags)} — valor {round(random.uniform(1, 100), 2)}")
    lines += ["", "## Conclusão", "",
              f"Análise concluída com {random.randint(90, 99)}% de confiança.",
              f"Próxima revisão recomendada em {random.randint(7, 90)} dias."]
    return "\n".join(lines).encode()


def gen_json(topic: str, summary: str, tags: list[str]) -> bytes:
    data = {
        "title": topic,
        "summary": summary,
        "tags": tags,
        "generated_at": rand_date(0),
        "metrics": {
            tag: round(random.uniform(0, 1000), 2) for tag in tags
        },
        "records": [
            {"id": str(uuid4())[:8], "value": round(random.uniform(0, 9999), 2),
             "category": random.choice(tags), "status": random.choice(["ok", "warn", "error"])}
            for _ in range(random.randint(5, 15))
        ],
        "confidence": round(random.uniform(0.8, 0.99), 3),
    }
    return json.dumps(data, ensure_ascii=False, indent=2).encode()


def gen_csv(topic: str, summary: str, tags: list[str]) -> bytes:
    lines = ["id,categoria,valor,data,status"]
    for i in range(random.randint(20, 50)):
        lines.append(
            f"{i+1},{random.choice(tags)},{round(random.uniform(0,9999),2)},"
            f"{rand_date(90)[:10]},{random.choice(['ok','warn','erro'])}"
        )
    return "\n".join(lines).encode()


def gen_text(topic: str, summary: str, tags: list[str]) -> bytes:
    return f"""{topic.upper()}
{'='*len(topic)}

{summary}

Gerado: {datetime.now(timezone.utc).isoformat()}
Tags: {', '.join(tags)}

DETALHES
--------
{''.join(random.choices(string.ascii_letters + ' \n', k=random.randint(200, 600)))}

FIM DO RELATÓRIO
""".encode()


CONTENT_GENS = {
    "html":     gen_html,
    "markdown": gen_markdown,
    "json":     gen_json,
    "csv":      gen_csv,
    "text":     gen_text,
}


# ---------------------------------------------------------------------------
# HTTP publish (urllib — sem dependências externas)
# POST /kcp/v1/artifacts  →  title, content, format, tags, summary, visibility, source
# ---------------------------------------------------------------------------

def publish_artifact(port: int, body: dict) -> dict:
    url = f"http://127.0.0.1:{port}/kcp/v1/artifacts"
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------------------
# Seed one peer
# ---------------------------------------------------------------------------

def seed_peer(name: str, port: int, count: int) -> int:
    ok = 0
    for i in range(count):
        topic_data       = random.choice(TOPICS)
        topic, tags, summary = topic_data
        fmt              = pick_weighted(FORMATS)
        visibility       = pick_weighted(VISIBILITY_WEIGHTS)
        agent            = random.choice(AGENTS)

        # Vary title slightly so artifacts are distinct
        suffix = (f" #{i+1}" if random.random() < 0.4
                  else f" — {random.choice(['v2', 'v3', 'draft', 'final', '2026'])}")
        title = topic + suffix

        content_bytes = CONTENT_GENS[fmt](title, summary, tags)
        content_str   = content_bytes.decode("utf-8", errors="replace")

        body = {
            "title":      title,
            "content":    content_str,
            "format":     fmt,
            "visibility": visibility,
            "tags":       tags + [name, "seed"],
            "source":     agent,
            "summary":    summary[:200],
        }

        try:
            publish_artifact(port, body)
            ok += 1
            if (i + 1) % 100 == 0:
                print(f"  {name}: {i+1}/{count} artefatos publicados...")
        except Exception as e:
            if ok == 0 and i < 3:   # só mostra erros no início
                print(f"  ⚠ {name} artefato {i+1} erro: {e}")

    return ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="KCP Artifact Seeder")
    parser.add_argument("--count",  type=int, default=ARTIFACTS_PER_PEER,
                        help=f"Artefatos por peer (default: {ARTIFACTS_PER_PEER})")
    parser.add_argument("--peers",  type=str, default="",
                        help="Portas separadas por vírgula, ex: 8804,8805 (default: todos)")
    args = parser.parse_args()

    peers = PEERS
    if args.peers:
        ports = [int(p) for p in args.peers.split(",")]
        peers = {name: port for name, port in PEERS.items() if port in ports}

    print(f"🌱 KCP Artifact Seeder")
    print(f"   Peers: {list(peers.keys())}")
    print(f"   Artefatos por peer: {args.count}")
    print(f"   Total estimado: {len(peers) * args.count}")
    print()

    total_ok = 0
    for name, port in peers.items():
        # Verificar se peer está online
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/kcp/v1/health")
            with urllib.request.urlopen(req, timeout=3) as r:
                health = json.loads(r.read())
            existing = health.get("artifacts", 0)
            print(f"📡 {name} (:{port}) — {existing} artefatos existentes → publicando {args.count}...")
        except Exception as e:
            print(f"❌ {name} (:{port}) offline — pulando ({e})")
            continue

        ok = seed_peer(name, port, args.count)
        total_ok += ok
        print(f"  ✅ {name}: {ok}/{args.count} publicados com sucesso")
        print()

    print(f"🎉 Total: {total_ok} artefatos publicados em {len(peers)} peers")

    # Verificação final
    print()
    print("📊 Contagem final:")
    for name, port in peers.items():
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/kcp/v1/health")
            with urllib.request.urlopen(req, timeout=3) as r:
                h = json.loads(r.read())
            print(f"  {name}: {h.get('artifacts', '?')} artefatos")
        except:
            print(f"  {name}: ??")


if __name__ == "__main__":
    main()
