// Package models defines the core data structures for KCP.
package models

import (
	"encoding/json"
	"sort"
	"time"

	"github.com/google/uuid"
)

// KnowledgeArtifact represents a signed unit of AI-generated knowledge.
type KnowledgeArtifact struct {
	ID          string   `json:"id"`
	Version     string   `json:"version"`
	UserID      string   `json:"user_id"`
	TenantID    string   `json:"tenant_id"`
	Team        string   `json:"team,omitempty"`
	Tags        []string `json:"tags,omitempty"`
	Source      string   `json:"source,omitempty"`
	Timestamp   string   `json:"timestamp"`
	Format      string   `json:"format"`
	Visibility  string   `json:"visibility"`
	Title       string   `json:"title"`
	Summary     string   `json:"summary,omitempty"`
	Lineage     *Lineage `json:"lineage,omitempty"`
	ContentHash string   `json:"content_hash"`
	ContentURL  string   `json:"content_url,omitempty"`
	Signature   string   `json:"signature,omitempty"`
	ACL         *ACL     `json:"acl,omitempty"`
	DerivedFrom string   `json:"derived_from,omitempty"`
}

// Lineage tracks the provenance of an artifact.
type Lineage struct {
	Query         string   `json:"query"`
	DataSources   []string `json:"data_sources,omitempty"`
	Agent         string   `json:"agent,omitempty"`
	ParentReports []string `json:"parent_reports,omitempty"`
}

// ACL defines access control for an artifact.
type ACL struct {
	AllowedTenants []string `json:"allowed_tenants,omitempty"`
	AllowedUsers   []string `json:"allowed_users,omitempty"`
	AllowedTeams   []string `json:"allowed_teams,omitempty"`
}

// SearchResult is a single result from a search query.
type SearchResult struct {
	ID        string  `json:"id"`
	Title     string  `json:"title"`
	Summary   string  `json:"summary"`
	CreatedAt string  `json:"created_at"`
	Relevance float64 `json:"relevance"`
	Format    string  `json:"format"`
}

// SearchResponse contains search results.
type SearchResponse struct {
	Results     []SearchResult `json:"results"`
	Total       int            `json:"total"`
	QueryTimeMs int            `json:"query_time_ms"`
}

// LineageEntry represents one step in a lineage chain.
type LineageEntry struct {
	ID          string `json:"id"`
	Title       string `json:"title"`
	Author      string `json:"author"`
	CreatedAt   string `json:"created_at"`
	DerivedFrom string `json:"derived_from,omitempty"`
}

// PeerInfo holds information about a connected peer.
type PeerInfo struct {
	ID        string `json:"id"`
	URL       string `json:"url"`
	Name      string `json:"name,omitempty"`
	PublicKey string `json:"public_key,omitempty"`
	LastSeen  string `json:"last_seen,omitempty"`
	AddedAt   string `json:"added_at"`
}

// NodeStats contains node statistics.
type NodeStats struct {
	NodeID           string `json:"node_id"`
	UserID           string `json:"user_id"`
	TenantID         string `json:"tenant_id"`
	Artifacts        int    `json:"artifacts"`
	ContentSizeBytes int64  `json:"content_size_bytes"`
	ContentSizeHuman string `json:"content_size_human"`
	Peers            int    `json:"peers"`
	DBSizeBytes      int64  `json:"db_size_bytes"`
	DBSizeHuman      string `json:"db_size_human"`
	DBPath           string `json:"db_path"`
}

// NewArtifact creates a new KnowledgeArtifact with defaults.
func NewArtifact(title, userID, tenantID, format string) *KnowledgeArtifact {
	return &KnowledgeArtifact{
		ID:         uuid.New().String(),
		Version:    "1",
		UserID:     userID,
		TenantID:   tenantID,
		Timestamp:  time.Now().UTC().Format(time.RFC3339),
		Format:     format,
		Visibility: "public",
		Title:      title,
	}
}

// CanonicalJSON returns the artifact as canonical JSON (sorted keys, no signature)
// for signing/verification.
func (a *KnowledgeArtifact) CanonicalJSON() ([]byte, error) {
	// Marshal to map, remove signature, sort keys
	data, err := json.Marshal(a)
	if err != nil {
		return nil, err
	}

	var m map[string]interface{}
	if err := json.Unmarshal(data, &m); err != nil {
		return nil, err
	}

	delete(m, "signature")

	// Remove empty/zero fields for consistency with Python SDK
	for k, v := range m {
		if v == nil || v == "" {
			delete(m, k)
		}
		if arr, ok := v.([]interface{}); ok && len(arr) == 0 {
			delete(m, k)
		}
	}

	// Sort keys manually for canonical output
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	// Build canonical JSON manually
	buf := []byte("{")
	for i, k := range keys {
		if i > 0 {
			buf = append(buf, ',')
		}
		keyBytes, _ := json.Marshal(k)
		valBytes, _ := json.Marshal(m[k])
		buf = append(buf, keyBytes...)
		buf = append(buf, ':')
		buf = append(buf, valBytes...)
	}
	buf = append(buf, '}')

	return buf, nil
}
