// Package store provides SQLite-based local storage for KCP artifacts.
package store

import (
	"database/sql"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/tgosoul2019/kcp/sdk/go/pkg/models"

	_ "github.com/mattn/go-sqlite3"
)

const schemaDDL = `
CREATE TABLE IF NOT EXISTS kcp_artifacts (
    id TEXT PRIMARY KEY,
    version TEXT NOT NULL DEFAULT '1',
    user_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    team TEXT,
    tags TEXT,
    source TEXT,
    created_at TEXT NOT NULL,
    format TEXT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'private',
    title TEXT NOT NULL,
    summary TEXT,
    lineage TEXT,
    content_hash TEXT NOT NULL,
    content_url TEXT,
    signature TEXT,
    acl TEXT,
    derived_from TEXT,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS kcp_content (
    content_hash TEXT PRIMARY KEY,
    content BLOB NOT NULL,
    size_bytes INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS kcp_peers (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    name TEXT,
    public_key TEXT,
    last_seen TEXT,
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kcp_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    user_id TEXT,
    action TEXT NOT NULL,
    artifact_id TEXT,
    details TEXT
);

CREATE TABLE IF NOT EXISTS kcp_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_artifacts_tenant ON kcp_artifacts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_user ON kcp_artifacts(user_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_hash ON kcp_artifacts(content_hash);
CREATE INDEX IF NOT EXISTS idx_artifacts_created ON kcp_artifacts(created_at);
CREATE INDEX IF NOT EXISTS idx_artifacts_derived ON kcp_artifacts(derived_from);
`

// LocalStore is a SQLite-based KCP storage backend.
type LocalStore struct {
	db     *sql.DB
	dbPath string
}

// NewLocalStore creates and initializes a local SQLite store.
func NewLocalStore(dbPath string) (*LocalStore, error) {
	// Expand ~ to home dir
	if strings.HasPrefix(dbPath, "~/") {
		home, _ := os.UserHomeDir()
		dbPath = filepath.Join(home, dbPath[2:])
	}

	dir := filepath.Dir(dbPath)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return nil, fmt.Errorf("create db dir: %w", err)
	}

	db, err := sql.Open("sqlite3", dbPath+"?_journal_mode=WAL&_foreign_keys=ON")
	if err != nil {
		return nil, fmt.Errorf("open db: %w", err)
	}

	if _, err := db.Exec(schemaDDL); err != nil {
		return nil, fmt.Errorf("init schema: %w", err)
	}

	return &LocalStore{db: db, dbPath: dbPath}, nil
}

// Close closes the database connection.
func (s *LocalStore) Close() error {
	return s.db.Close()
}

// Publish stores a knowledge artifact with its content.
func (s *LocalStore) Publish(artifact *models.KnowledgeArtifact, content []byte, derivedFrom string) error {
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	// Store content
	if len(content) > 0 {
		_, err = tx.Exec(
			"INSERT OR IGNORE INTO kcp_content (content_hash, content, size_bytes) VALUES (?, ?, ?)",
			artifact.ContentHash, content, len(content),
		)
		if err != nil {
			return fmt.Errorf("store content: %w", err)
		}
	}

	tagsJSON, _ := json.Marshal(artifact.Tags)
	var lineageJSON, aclJSON *string
	if artifact.Lineage != nil {
		b, _ := json.Marshal(artifact.Lineage)
		s := string(b)
		lineageJSON = &s
	}
	if artifact.ACL != nil {
		b, _ := json.Marshal(artifact.ACL)
		s := string(b)
		aclJSON = &s
	}

	df := sql.NullString{String: derivedFrom, Valid: derivedFrom != ""}

	_, err = tx.Exec(`
		INSERT OR REPLACE INTO kcp_artifacts
		(id, version, user_id, tenant_id, team, tags, source, created_at,
		 format, visibility, title, summary, lineage, content_hash,
		 content_url, signature, acl, derived_from)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		artifact.ID, artifact.Version, artifact.UserID, artifact.TenantID,
		artifact.Team, string(tagsJSON), artifact.Source, artifact.Timestamp,
		artifact.Format, artifact.Visibility, artifact.Title, artifact.Summary,
		lineageJSON, artifact.ContentHash, artifact.ContentURL,
		artifact.Signature, aclJSON, df,
	)
	if err != nil {
		return fmt.Errorf("store artifact: %w", err)
	}

	// Audit
	now := time.Now().UTC().Format(time.RFC3339)
	tx.Exec("INSERT INTO kcp_audit (timestamp, user_id, action, artifact_id) VALUES (?, ?, 'publish', ?)",
		now, artifact.UserID, artifact.ID)

	return tx.Commit()
}

// Get retrieves an artifact by ID.
func (s *LocalStore) Get(id string) (*models.KnowledgeArtifact, error) {
	row := s.db.QueryRow(
		"SELECT id, version, user_id, tenant_id, team, tags, source, created_at, format, visibility, title, summary, lineage, content_hash, content_url, signature, acl, derived_from FROM kcp_artifacts WHERE id = ? AND deleted_at IS NULL",
		id,
	)
	return scanArtifact(row)
}

// GetContent retrieves raw content by hash.
func (s *LocalStore) GetContent(contentHash string) ([]byte, error) {
	var content []byte
	err := s.db.QueryRow("SELECT content FROM kcp_content WHERE content_hash = ?", contentHash).Scan(&content)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	return content, err
}

// Delete soft-deletes an artifact.
func (s *LocalStore) Delete(id, userID string) (bool, error) {
	now := time.Now().UTC().Format(time.RFC3339)
	res, err := s.db.Exec("UPDATE kcp_artifacts SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL", now, id)
	if err != nil {
		return false, err
	}
	n, _ := res.RowsAffected()
	return n > 0, nil
}

// List returns recent artifacts with optional filters.
func (s *LocalStore) List(limit int, tags []string) ([]*models.KnowledgeArtifact, error) {
	query := "SELECT id, version, user_id, tenant_id, team, tags, source, created_at, format, visibility, title, summary, lineage, content_hash, content_url, signature, acl, derived_from FROM kcp_artifacts WHERE deleted_at IS NULL"
	args := []interface{}{}

	for _, tag := range tags {
		query += " AND tags LIKE ?"
		args = append(args, "%"+tag+"%")
	}

	query += " ORDER BY created_at DESC LIMIT ?"
	args = append(args, limit)

	rows, err := s.db.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var results []*models.KnowledgeArtifact
	for rows.Next() {
		a, err := scanArtifactRows(rows)
		if err != nil {
			continue
		}
		results = append(results, a)
	}
	return results, nil
}

// Search performs full-text search using LIKE (FTS5 optional).
func (s *LocalStore) Search(query string, limit int) (*models.SearchResponse, error) {
	start := time.Now()
	like := "%" + query + "%"

	rows, err := s.db.Query(
		"SELECT id, title, summary, created_at, format FROM kcp_artifacts WHERE deleted_at IS NULL AND (title LIKE ? OR summary LIKE ? OR tags LIKE ?) ORDER BY created_at DESC LIMIT ?",
		like, like, like, limit,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var results []models.SearchResult
	for rows.Next() {
		var r models.SearchResult
		if err := rows.Scan(&r.ID, &r.Title, &r.Summary, &r.CreatedAt, &r.Format); err != nil {
			continue
		}
		r.Relevance = 1.0
		results = append(results, r)
	}

	elapsed := time.Since(start).Milliseconds()

	// Total count
	var total int
	s.db.QueryRow("SELECT COUNT(*) FROM kcp_artifacts WHERE deleted_at IS NULL").Scan(&total)

	return &models.SearchResponse{
		Results:     results,
		Total:       total,
		QueryTimeMs: int(elapsed),
	}, nil
}

// GetLineage returns the lineage chain from root to the given artifact.
func (s *LocalStore) GetLineage(artifactID string) ([]models.LineageEntry, error) {
	var chain []models.LineageEntry
	visited := map[string]bool{}
	currentID := artifactID

	for currentID != "" && !visited[currentID] {
		visited[currentID] = true
		var e models.LineageEntry
		var derivedFrom sql.NullString
		err := s.db.QueryRow(
			"SELECT id, title, user_id, created_at, derived_from FROM kcp_artifacts WHERE id = ?",
			currentID,
		).Scan(&e.ID, &e.Title, &e.Author, &e.CreatedAt, &derivedFrom)
		if err != nil {
			break
		}
		if derivedFrom.Valid {
			e.DerivedFrom = derivedFrom.String
		}
		chain = append(chain, e)
		currentID = derivedFrom.String
	}

	// Reverse: root first
	for i, j := 0, len(chain)-1; i < j; i, j = i+1, j-1 {
		chain[i], chain[j] = chain[j], chain[i]
	}
	return chain, nil
}

// AddPeer registers a peer node.
func (s *LocalStore) AddPeer(id, url, name, publicKey string) error {
	now := time.Now().UTC().Format(time.RFC3339)
	_, err := s.db.Exec(
		"INSERT OR REPLACE INTO kcp_peers (id, url, name, public_key, last_seen, added_at) VALUES (?, ?, ?, ?, ?, ?)",
		id, url, name, publicKey, now, now,
	)
	return err
}

// GetPeers returns all known peers.
func (s *LocalStore) GetPeers() ([]models.PeerInfo, error) {
	rows, err := s.db.Query("SELECT id, url, name, public_key, last_seen, added_at FROM kcp_peers ORDER BY last_seen DESC")
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var peers []models.PeerInfo
	for rows.Next() {
		var p models.PeerInfo
		var pk, ls sql.NullString
		if err := rows.Scan(&p.ID, &p.URL, &p.Name, &pk, &ls, &p.AddedAt); err != nil {
			continue
		}
		p.PublicKey = pk.String
		p.LastSeen = ls.String
		peers = append(peers, p)
	}
	return peers, nil
}

// GetArtifactIDsSince returns artifact IDs created after a timestamp.
func (s *LocalStore) GetArtifactIDsSince(since string) ([]string, error) {
	var rows *sql.Rows
	var err error
	if since != "" {
		rows, err = s.db.Query("SELECT id FROM kcp_artifacts WHERE created_at > ? AND deleted_at IS NULL ORDER BY created_at", since)
	} else {
		rows, err = s.db.Query("SELECT id FROM kcp_artifacts WHERE deleted_at IS NULL ORDER BY created_at")
	}
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var ids []string
	for rows.Next() {
		var id string
		rows.Scan(&id)
		ids = append(ids, id)
	}
	return ids, nil
}

// GetArtifactWithContent returns artifact data + base64 content for sync.
func (s *LocalStore) GetArtifactWithContent(id string) (map[string]interface{}, error) {
	a, err := s.Get(id)
	if err != nil || a == nil {
		return nil, err
	}

	data, _ := json.Marshal(a)
	var m map[string]interface{}
	json.Unmarshal(data, &m)

	content, _ := s.GetContent(a.ContentHash)
	if len(content) > 0 {
		m["_content_b64"] = base64.StdEncoding.EncodeToString(content)
	}
	return m, nil
}

// ImportArtifact imports an artifact from sync. Returns true if new.
func (s *LocalStore) ImportArtifact(data map[string]interface{}) (bool, error) {
	id, _ := data["id"].(string)
	if id == "" {
		return false, fmt.Errorf("missing id")
	}

	existing, _ := s.Get(id)
	if existing != nil {
		return false, nil
	}

	jsonData, _ := json.Marshal(data)
	var artifact models.KnowledgeArtifact
	if err := json.Unmarshal(jsonData, &artifact); err != nil {
		return false, err
	}

	var content []byte
	if b64, ok := data["_content_b64"].(string); ok {
		content, _ = base64.StdEncoding.DecodeString(b64)
	}

	derivedFrom, _ := data["derived_from"].(string)
	if err := s.Publish(&artifact, content, derivedFrom); err != nil {
		return false, err
	}
	return true, nil
}

// SetConfig stores a config value.
func (s *LocalStore) SetConfig(key, value string) error {
	_, err := s.db.Exec("INSERT OR REPLACE INTO kcp_config (key, value) VALUES (?, ?)", key, value)
	return err
}

// GetConfig retrieves a config value.
func (s *LocalStore) GetConfig(key, defaultVal string) string {
	var val string
	err := s.db.QueryRow("SELECT value FROM kcp_config WHERE key = ?", key).Scan(&val)
	if err != nil {
		return defaultVal
	}
	return val
}

// Stats returns storage statistics.
func (s *LocalStore) Stats() models.NodeStats {
	var stats models.NodeStats
	stats.DBPath = s.dbPath

	s.db.QueryRow("SELECT COUNT(*) FROM kcp_artifacts WHERE deleted_at IS NULL").Scan(&stats.Artifacts)
	s.db.QueryRow("SELECT COALESCE(SUM(size_bytes),0) FROM kcp_content").Scan(&stats.ContentSizeBytes)
	s.db.QueryRow("SELECT COUNT(*) FROM kcp_peers").Scan(&stats.Peers)

	stats.ContentSizeHuman = humanSize(stats.ContentSizeBytes)

	if info, err := os.Stat(s.dbPath); err == nil {
		stats.DBSizeBytes = info.Size()
	}
	stats.DBSizeHuman = humanSize(stats.DBSizeBytes)

	return stats
}

// ─── Internal helpers ─────────────────────────────────────────

type scannable interface {
	Scan(dest ...interface{}) error
}

func scanArtifact(row *sql.Row) (*models.KnowledgeArtifact, error) {
	a := &models.KnowledgeArtifact{}
	var team, tags, source, summary, lineage, contentURL, signature, acl sql.NullString
	var derivedFrom sql.NullString

	err := row.Scan(
		&a.ID, &a.Version, &a.UserID, &a.TenantID,
		&team, &tags, &source, &a.Timestamp,
		&a.Format, &a.Visibility, &a.Title,
		&summary, &lineage, &a.ContentHash,
		&contentURL, &signature, &acl, &derivedFrom,
	)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}

	a.Team = team.String
	a.Source = source.String
	a.Summary = summary.String
	a.ContentURL = contentURL.String
	a.Signature = signature.String
	a.DerivedFrom = derivedFrom.String

	if tags.Valid {
		json.Unmarshal([]byte(tags.String), &a.Tags)
	}
	if lineage.Valid {
		var l models.Lineage
		json.Unmarshal([]byte(lineage.String), &l)
		a.Lineage = &l
	}
	if acl.Valid {
		var ac models.ACL
		json.Unmarshal([]byte(acl.String), &ac)
		a.ACL = &ac
	}

	return a, nil
}

func scanArtifactRows(rows *sql.Rows) (*models.KnowledgeArtifact, error) {
	a := &models.KnowledgeArtifact{}
	var team, tags, source, summary, lineage, contentURL, signature, acl sql.NullString
	var derivedFrom sql.NullString

	err := rows.Scan(
		&a.ID, &a.Version, &a.UserID, &a.TenantID,
		&team, &tags, &source, &a.Timestamp,
		&a.Format, &a.Visibility, &a.Title,
		&summary, &lineage, &a.ContentHash,
		&contentURL, &signature, &acl, &derivedFrom,
	)
	if err != nil {
		return nil, err
	}

	a.Team = team.String
	a.Source = source.String
	a.Summary = summary.String
	a.ContentURL = contentURL.String
	a.Signature = signature.String
	a.DerivedFrom = derivedFrom.String

	if tags.Valid {
		json.Unmarshal([]byte(tags.String), &a.Tags)
	}
	if lineage.Valid {
		var l models.Lineage
		json.Unmarshal([]byte(lineage.String), &l)
		a.Lineage = &l
	}
	if acl.Valid {
		var ac models.ACL
		json.Unmarshal([]byte(acl.String), &ac)
		a.ACL = &ac
	}

	return a, nil
}

func humanSize(bytes int64) string {
	units := []string{"B", "KB", "MB", "GB", "TB"}
	size := float64(bytes)
	for _, unit := range units {
		if size < 1024 {
			return fmt.Sprintf("%.1f %s", size, unit)
		}
		size /= 1024
	}
	return fmt.Sprintf("%.1f PB", size)
}
