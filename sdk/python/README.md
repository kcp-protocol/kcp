# KCP Python SDK

Reference implementation of the Knowledge Context Protocol client.

## Status: In Development

Coming soon. Track progress in [Phase 1 Roadmap](../../docs/roadmap.md).

## Planned API

```python
from kcp import KCPClient

# Initialize client
client = KCPClient(
    node_url="http://localhost:8080",
    tenant_id="acme-corp",
    user_id="alice@example.com",
    private_key_path="~/.kcp/keys/private.pem"
)

# Publish a report
report = client.publish(
    title="Q1 Customer Churn Analysis",
    content=open("report.html").read(),
    format="html",
    tags=["churn", "analytics", "ml"],
    team="data-science",
    visibility="team",
    lineage={
        "query": "Predict customer churn using 12 months of history",
        "data_sources": ["postgres://analytics/customers"],
        "agent": "jupyter-agent-v1.2.3"
    }
)

# Search for reports
results = client.search(
    query="customer retention",
    tags=["analytics"],
    limit=10
)

# Get report content
content = client.get_content(report_id="550e8400-...")
```

## Installation (Future)

```bash
pip install kcp
```
