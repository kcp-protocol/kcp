// KCP CLI — Command-line interface for the Knowledge Context Protocol.
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	kcpcrypto "github.com/tgosoul2019/kcp/sdk/go/pkg/crypto"
	"github.com/tgosoul2019/kcp/sdk/go/pkg/node"
)

func main() {
	args := os.Args[1:]
	if len(args) == 0 || args[0] == "help" || args[0] == "-h" || args[0] == "--help" {
		printHelp()
		return
	}

	cmd := args[0]
	rest := args[1:]

	switch cmd {
	case "init":
		cmdInit()
	case "publish":
		cmdPublish(rest)
	case "search":
		cmdSearch(rest)
	case "list":
		cmdList(rest)
	case "get":
		cmdGet(rest)
	case "lineage":
		cmdLineage(rest)
	case "stats":
		cmdStats()
	case "keygen":
		cmdKeygen(rest)
	case "export":
		cmdExport(rest)
	default:
		fmt.Fprintf(os.Stderr, "Unknown command: %s\n", cmd)
		printHelp()
		os.Exit(1)
	}
}

func getNode() *node.KCPNode {
	n, err := node.New(node.DefaultConfig())
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error initializing node: %v\n", err)
		os.Exit(1)
	}
	return n
}

func cmdInit() {
	n := getNode()
	defer n.Close()
	s := n.Stats()
	fmt.Println("✅ KCP node initialized")
	fmt.Printf("   Node ID:  %s\n", s.NodeID)
	fmt.Printf("   User:     %s\n", s.UserID)
	fmt.Printf("   Tenant:   %s\n", s.TenantID)
	fmt.Printf("   Database: %s\n", s.DBPath)
	fmt.Println("   Keys:     ~/.kcp/keys/")
}

func cmdPublish(args []string) {
	var title, format, summary, derivedFrom, filePath string
	var tags []string

	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--title":
			i++; title = args[i]
		case "--format":
			i++; format = args[i]
		case "--tags":
			i++; tags = strings.Split(args[i], ",")
		case "--summary":
			i++; summary = args[i]
		case "--derived-from":
			i++; derivedFrom = args[i]
		case "-":
			filePath = "-"
		default:
			filePath = args[i]
		}
	}

	if filePath == "" {
		fmt.Fprintln(os.Stderr, "Usage: kcp publish [--title T] [--tags a,b] FILE")
		os.Exit(1)
	}

	var content []byte
	var err error
	if filePath == "-" {
		content, err = os.ReadFile("/dev/stdin")
	} else {
		content, err = os.ReadFile(filePath)
		if title == "" {
			base := filepath.Base(filePath)
			title = strings.TrimSuffix(base, filepath.Ext(base))
			title = strings.ReplaceAll(strings.ReplaceAll(title, "-", " "), "_", " ")
		}
		if format == "" {
			extMap := map[string]string{".md": "markdown", ".html": "html", ".json": "json", ".txt": "text", ".csv": "csv", ".go": "text", ".py": "text"}
			format = extMap[strings.ToLower(filepath.Ext(filePath))]
		}
	}
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error reading file: %v\n", err)
		os.Exit(1)
	}
	if title == "" { title = "Untitled" }
	if format == "" { format = "text" }

	var opts []node.PublishOption
	if len(tags) > 0 { opts = append(opts, node.WithTags(tags...)) }
	if summary != "" { opts = append(opts, node.WithSummary(summary)) }
	if derivedFrom != "" { opts = append(opts, node.WithDerivedFrom(derivedFrom)) }

	n := getNode()
	defer n.Close()

	artifact, err := n.Publish(title, content, format, opts...)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error publishing: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("✅ Published: %s\n", artifact.ID)
	fmt.Printf("   Title:   %s\n", artifact.Title)
	fmt.Printf("   Format:  %s\n", artifact.Format)
	fmt.Printf("   Hash:    %s...\n", artifact.ContentHash[:16])
}

func cmdSearch(args []string) {
	if len(args) == 0 {
		fmt.Fprintln(os.Stderr, "Usage: kcp search QUERY")
		os.Exit(1)
	}
	query := strings.Join(args, " ")
	n := getNode()
	defer n.Close()

	results, err := n.Search(query, 20)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
	if len(results.Results) == 0 {
		fmt.Printf("No results for: %s\n", query)
		return
	}

	fmt.Printf("Found %d artifacts (%dms):\n\n", results.Total, results.QueryTimeMs)
	for _, r := range results.Results {
		fmt.Printf("  📄 %s\n", r.Title)
		fmt.Printf("     ID: %s | %s | %s\n\n", r.ID, r.Format, r.CreatedAt[:10])
	}
}

func cmdList(args []string) {
	limit := 20
	if len(args) > 0 {
		if v, err := strconv.Atoi(args[0]); err == nil {
			limit = v
		}
	}

	n := getNode()
	defer n.Close()

	artifacts, err := n.List(limit, nil)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
	if len(artifacts) == 0 {
		fmt.Println("No artifacts yet. Publish with: kcp publish FILE")
		return
	}

	fmt.Printf("Recent artifacts (%d):\n\n", len(artifacts))
	for _, a := range artifacts {
		fmt.Printf("  📄 %s\n", a.Title)
		fmt.Printf("     ID: %s | %s | %s\n", a.ID, a.Format, a.Timestamp[:10])
		if len(a.Tags) > 0 {
			fmt.Printf("     Tags: %s\n", strings.Join(a.Tags, ", "))
		}
		fmt.Println()
	}
}

func cmdGet(args []string) {
	if len(args) == 0 {
		fmt.Fprintln(os.Stderr, "Usage: kcp get ARTIFACT_ID")
		os.Exit(1)
	}

	n := getNode()
	defer n.Close()

	a, err := n.Get(args[0])
	if err != nil || a == nil {
		fmt.Fprintf(os.Stderr, "Artifact not found: %s\n", args[0])
		os.Exit(1)
	}

	data, _ := json.MarshalIndent(a, "", "  ")
	fmt.Println(string(data))

	content, _ := n.GetContent(args[0])
	if len(content) > 0 && len(content) < 2000 {
		fmt.Println("\n--- Content ---\n")
		fmt.Println(string(content))
	}
}

func cmdLineage(args []string) {
	if len(args) == 0 {
		fmt.Fprintln(os.Stderr, "Usage: kcp lineage ARTIFACT_ID")
		os.Exit(1)
	}

	n := getNode()
	defer n.Close()

	chain, err := n.Lineage(args[0])
	if err != nil || len(chain) == 0 {
		fmt.Printf("No lineage found for: %s\n", args[0])
		return
	}

	fmt.Println("Lineage (root → current):\n")
	for i, e := range chain {
		prefix := "├──"
		if i == len(chain)-1 {
			prefix = "└──"
		}
		indent := strings.Repeat("   ", i)
		fmt.Printf("%s%s %s\n", indent, prefix, e.Title)
		fmt.Printf("%s    ID: %s... | By: %s | %s\n", indent, e.ID[:12], e.Author, e.CreatedAt[:10])
	}
}

func cmdStats() {
	n := getNode()
	defer n.Close()
	s := n.Stats()
	fmt.Println("KCP Node Stats\n")
	fmt.Printf("  Node ID:    %s\n", s.NodeID)
	fmt.Printf("  User:       %s\n", s.UserID)
	fmt.Printf("  Tenant:     %s\n", s.TenantID)
	fmt.Printf("  Artifacts:  %d\n", s.Artifacts)
	fmt.Printf("  Content:    %s\n", s.ContentSizeHuman)
	fmt.Printf("  DB Size:    %s\n", s.DBSizeHuman)
	fmt.Printf("  Peers:      %d\n", s.Peers)
	fmt.Printf("  DB Path:    %s\n", s.DBPath)
}

func cmdKeygen(args []string) {
	dir := "~/.kcp/keys"
	if len(args) > 0 {
		dir = args[0]
	}
	if strings.HasPrefix(dir, "~/") {
		home, _ := os.UserHomeDir()
		dir = filepath.Join(home, dir[2:])
	}

	priv, pub, err := kcpcrypto.GenerateKeypair()
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
	if err := kcpcrypto.SaveKeys(dir, priv, pub); err != nil {
		fmt.Fprintf(os.Stderr, "Error saving keys: %v\n", err)
		os.Exit(1)
	}

	fmt.Println("✅ Keypair generated")
	fmt.Printf("   Private: %s/private.key\n", dir)
	fmt.Printf("   Public:  %s/public.key\n", dir)
	fmt.Printf("   Public (hex): %x\n", []byte(pub))
}

func cmdExport(args []string) {
	n := getNode()
	defer n.Close()

	artifacts, _ := n.List(10000, nil)
	data, _ := json.MarshalIndent(artifacts, "", "  ")

	if len(args) > 0 {
		os.WriteFile(args[0], data, 0644)
		fmt.Printf("✅ Exported %d artifacts to %s\n", len(artifacts), args[0])
	} else {
		fmt.Println(string(data))
	}
}

func printHelp() {
	fmt.Print(`
KCP — Knowledge Context Protocol CLI (Go)

Usage: kcp <command> [options]

Commands:
  init                          Initialize node (generate keys, create DB)
  publish [--title T] FILE      Publish a file as knowledge artifact
  search QUERY                  Search artifacts
  list [N]                      List recent artifacts (default: 20)
  get ID                        Show artifact details + content
  lineage ID                    Show lineage chain (root → current)
  stats                         Show node statistics
  keygen [DIR]                  Generate Ed25519 keypair
  export [FILE]                 Export all artifacts as JSON

Environment:
  KCP_USER      Your user ID (default: anonymous)
  KCP_TENANT    Your tenant/org (default: local)
  KCP_DB        Database path (default: ~/.kcp/kcp.db)
`)
}
