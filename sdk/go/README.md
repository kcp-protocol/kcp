# KCP Go SDK

High-performance server and client implementation for KCP.

## Status: Planned (Phase 2)

Track progress in [Phase 2 Roadmap](../../docs/roadmap.md).

## Planned Architecture

The Go SDK will focus on the **server-side** implementation:

- **KCP Node Server** — Full node with storage, indexing, and federation
- **KCP Client Library** — For Go applications to publish/search artifacts
- **CLI Tool** — `kcp publish`, `kcp search`, `kcp get`, `kcp verify`

## Planned API

```go
package main

import "github.com/tgosoul2019/kcp/sdk/go/kcp"

func main() {
    client := kcp.NewClient(kcp.Config{
        NodeURL:    "http://localhost:8080",
        TenantID:   "acme-corp",
        UserID:     "alice@example.com",
        PrivateKey: privateKeyBytes,
    })

    // Publish
    artifact, err := client.Publish(kcp.PublishRequest{
        Title:      "Q1 Performance Analysis",
        Content:    htmlBytes,
        Format:     "html",
        Tags:       []string{"performance", "analytics"},
        Visibility: kcp.VisibilityTeam,
        Lineage: &kcp.Lineage{
            Query:       "Analyze Q1 API performance",
            DataSources: []string{"prometheus://prod"},
            Agent:       "monitoring-agent-v2",
        },
    })

    // Search
    results, err := client.Search(kcp.SearchRequest{
        Query: "performance metrics",
        Tags:  []string{"analytics"},
        Limit: 10,
    })
}
```

## Installation (Future)

```bash
go get github.com/tgosoul2019/kcp/sdk/go
```
