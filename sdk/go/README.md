# KCP Go SDK

Go implementation of the Knowledge Context Protocol.

## Install

```bash
go install github.com/tgosoul2019/kcp/sdk/go/cmd/kcp@latest
```

## Build from source

```bash
cd sdk/go
go build -o kcp ./cmd/kcp
```

## CLI Usage

```bash
# Initialize node
kcp init

# Publish a file
kcp publish --title "Rate Limiting Guide" --tags "architecture,scaling" guide.md

# Search
kcp search "rate limiting"

# List artifacts
kcp list

# Show details
kcp get <artifact-id>

# Lineage chain
kcp lineage <artifact-id>

# Stats
kcp stats

# Generate keys
kcp keygen

# Export all artifacts
kcp export backup.json
```

## Library Usage

```go
package main

import (
    "fmt"
    "github.com/tgosoul2019/kcp/sdk/go/pkg/node"
)

func main() {
    cfg := node.DefaultConfig()
    cfg.UserID = "alice@acme.com"
    cfg.TenantID = "acme-corp"

    n, err := node.New(cfg)
    if err != nil {
        panic(err)
    }
    defer n.Close()

    // Publish
    artifact, err := n.Publish(
        "JWT Auth Best Practices",
        []byte("## JWT Auth\n\nAlways validate exp claim..."),
        "markdown",
        node.WithTags("security", "jwt"),
        node.WithSummary("Guide for secure JWT implementation"),
    )
    if err != nil {
        panic(err)
    }
    fmt.Printf("Published: %s\n", artifact.ID)

    // Search
    results, _ := n.Search("JWT", 10)
    for _, r := range results.Results {
        fmt.Printf("  %s (%s)\n", r.Title, r.Format)
    }

    // Lineage
    derived, _ := n.Publish(
        "OAuth2 + JWT Integration",
        []byte("Building on JWT best practices..."),
        "markdown",
        node.WithDerivedFrom(artifact.ID),
    )

    chain, _ := n.Lineage(derived.ID)
    for _, step := range chain {
        fmt.Printf("  → %s by %s\n", step.Title, step.Author)
    }
}
```

## Packages

| Package | Description |
|---------|-------------|
| `pkg/node` | Embedded KCP node (main entry point) |
| `pkg/store` | SQLite storage backend |
| `pkg/crypto` | Ed25519 signing + SHA-256 hashing |
| `pkg/models` | Data models |
| `cmd/kcp` | CLI binary |

## Cross-platform Build

```bash
# Linux
GOOS=linux GOARCH=amd64 go build -o kcp-linux ./cmd/kcp

# macOS (Intel)
GOOS=darwin GOARCH=amd64 go build -o kcp-darwin ./cmd/kcp

# macOS (Apple Silicon)
GOOS=darwin GOARCH=arm64 go build -o kcp-darwin-arm64 ./cmd/kcp

# Windows
GOOS=windows GOARCH=amd64 go build -o kcp.exe ./cmd/kcp
```

## License

MIT — see [LICENSE](../../LICENSE)
