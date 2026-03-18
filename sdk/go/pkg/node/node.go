// Package node provides the embedded KCP node that runs in-process.
package node

import (
	"crypto/ed25519"
	"encoding/hex"
	"os"
	"path/filepath"
	"strings"

	"github.com/google/uuid"
	kcpcrypto "github.com/tgosoul2019/kcp/sdk/go/pkg/crypto"
	"github.com/tgosoul2019/kcp/sdk/go/pkg/models"
	"github.com/tgosoul2019/kcp/sdk/go/pkg/store"
)

// KCPNode is an embedded KCP node. Runs in-process, stores locally.
type KCPNode struct {
	UserID     string
	TenantID   string
	Store      *store.LocalStore
	PrivateKey ed25519.PrivateKey
	PublicKey  ed25519.PublicKey
	keysDir    string
}

// Config holds node configuration.
type Config struct {
	UserID   string // default: "anonymous"
	TenantID string // default: "local"
	DBPath   string // default: "~/.kcp/kcp.db"
	KeysDir  string // default: "~/.kcp/keys"
}

// DefaultConfig returns sensible defaults, overridden by env vars.
func DefaultConfig() Config {
	c := Config{
		UserID:   "anonymous",
		TenantID: "local",
		DBPath:   "~/.kcp/kcp.db",
		KeysDir:  "~/.kcp/keys",
	}
	if v := os.Getenv("KCP_USER"); v != "" {
		c.UserID = v
	}
	if v := os.Getenv("KCP_TENANT"); v != "" {
		c.TenantID = v
	}
	if v := os.Getenv("KCP_DB"); v != "" {
		c.DBPath = v
	}
	return c
}

// New creates a new embedded KCP node.
func New(cfg Config) (*KCPNode, error) {
	// Expand ~
	if strings.HasPrefix(cfg.KeysDir, "~/") {
		home, _ := os.UserHomeDir()
		cfg.KeysDir = filepath.Join(home, cfg.KeysDir[2:])
	}

	// Open store
	s, err := store.NewLocalStore(cfg.DBPath)
	if err != nil {
		return nil, err
	}

	// Load or generate keys
	priv, pub, err := kcpcrypto.LoadOrGenerateKeys(cfg.KeysDir)
	if err != nil {
		return nil, err
	}

	n := &KCPNode{
		UserID:     cfg.UserID,
		TenantID:   cfg.TenantID,
		Store:      s,
		PrivateKey: priv,
		PublicKey:  pub,
		keysDir:    cfg.KeysDir,
	}

	// Store identity
	s.SetConfig("user_id", cfg.UserID)
	s.SetConfig("tenant_id", cfg.TenantID)
	s.SetConfig("public_key", hex.EncodeToString(pub))

	// Ensure node ID
	if s.GetConfig("node_id", "") == "" {
		s.SetConfig("node_id", uuid.New().String())
	}

	return n, nil
}

// NodeID returns the persistent node identifier.
func (n *KCPNode) NodeID() string {
	return n.Store.GetConfig("node_id", "")
}

// Publish creates, signs, and stores a knowledge artifact.
func (n *KCPNode) Publish(title string, content []byte, format string, opts ...PublishOption) (*models.KnowledgeArtifact, error) {
	o := &publishOpts{visibility: "public"}
	for _, fn := range opts {
		fn(o)
	}

	artifact := models.NewArtifact(title, n.UserID, n.TenantID, format)
	artifact.Tags = o.tags
	artifact.Summary = o.summary
	artifact.Visibility = o.visibility
	artifact.Source = o.source
	artifact.ContentHash = kcpcrypto.HashContent(content)

	// Sign
	canonical, err := artifact.CanonicalJSON()
	if err != nil {
		return nil, err
	}
	artifact.Signature = kcpcrypto.Sign(canonical, n.PrivateKey)

	// Store
	if err := n.Store.Publish(artifact, content, o.derivedFrom); err != nil {
		return nil, err
	}

	return artifact, nil
}

// Get retrieves an artifact by ID.
func (n *KCPNode) Get(id string) (*models.KnowledgeArtifact, error) {
	return n.Store.Get(id)
}

// GetContent retrieves raw content for an artifact.
func (n *KCPNode) GetContent(id string) ([]byte, error) {
	a, err := n.Store.Get(id)
	if err != nil || a == nil {
		return nil, err
	}
	return n.Store.GetContent(a.ContentHash)
}

// Search searches artifacts by text.
func (n *KCPNode) Search(query string, limit int) (*models.SearchResponse, error) {
	return n.Store.Search(query, limit)
}

// List returns recent artifacts.
func (n *KCPNode) List(limit int, tags []string) ([]*models.KnowledgeArtifact, error) {
	return n.Store.List(limit, tags)
}

// Delete soft-deletes an artifact.
func (n *KCPNode) Delete(id string) (bool, error) {
	return n.Store.Delete(id, n.UserID)
}

// Lineage returns the lineage chain for an artifact (root → current).
func (n *KCPNode) Lineage(id string) ([]models.LineageEntry, error) {
	return n.Store.GetLineage(id)
}

// Stats returns node statistics.
func (n *KCPNode) Stats() models.NodeStats {
	s := n.Store.Stats()
	s.NodeID = n.NodeID()
	s.UserID = n.UserID
	s.TenantID = n.TenantID
	return s
}

// Close closes the node and its store.
func (n *KCPNode) Close() error {
	return n.Store.Close()
}

// ─── Publish Options (functional options pattern) ────────────

type publishOpts struct {
	tags        []string
	summary     string
	visibility  string
	derivedFrom string
	source      string
}

// PublishOption configures a Publish call.
type PublishOption func(*publishOpts)

// WithTags sets tags for the artifact.
func WithTags(tags ...string) PublishOption {
	return func(o *publishOpts) { o.tags = tags }
}

// WithSummary sets the summary.
func WithSummary(s string) PublishOption {
	return func(o *publishOpts) { o.summary = s }
}

// WithVisibility sets the visibility tier.
func WithVisibility(v string) PublishOption {
	return func(o *publishOpts) { o.visibility = v }
}

// WithDerivedFrom links this artifact to a parent (lineage).
func WithDerivedFrom(parentID string) PublishOption {
	return func(o *publishOpts) { o.derivedFrom = parentID }
}

// WithSource sets the source agent/tool.
func WithSource(s string) PublishOption {
	return func(o *publishOpts) { o.source = s }
}
