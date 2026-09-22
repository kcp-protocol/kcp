//! KCP data models.
//!
//! Field-for-field mirror of `sdk/python/kcp/models.py`, including the
//! `to_dict()` / `from_dict()` rules that decide which fields take part in the
//! signed payload (optional fields are only emitted when set).

use chrono::{SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use uuid::Uuid;

use crate::canon::{canonical_bytes, canonical_json};
use crate::error::{KcpError, Result};

/// Current UTC timestamp in the reference format
/// (`datetime.now(timezone.utc).isoformat()`).
pub fn now_iso() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Micros, false)
}

/// Provenance information for a knowledge artifact.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct Lineage {
    pub query: String,
    #[serde(default)]
    pub data_sources: Vec<String>,
    #[serde(default)]
    pub agent: String,
    #[serde(default)]
    pub parent_reports: Vec<String>,
}

impl Lineage {
    pub fn new(query: impl Into<String>) -> Self {
        Self {
            query: query.into(),
            data_sources: Vec::new(),
            agent: String::new(),
            parent_reports: Vec::new(),
        }
    }

    pub fn with_sources(mut self, sources: Vec<String>) -> Self {
        self.data_sources = sources;
        self
    }

    pub fn with_agent(mut self, agent: impl Into<String>) -> Self {
        self.agent = agent.into();
        self
    }

    pub fn with_parents(mut self, parents: Vec<String>) -> Self {
        self.parent_reports = parents;
        self
    }

    /// Python `Lineage.to_dict()` — always emits all four keys.
    pub fn to_dict(&self) -> Value {
        let mut m = Map::new();
        m.insert("query".into(), Value::String(self.query.clone()));
        m.insert(
            "data_sources".into(),
            Value::Array(self.data_sources.iter().cloned().map(Value::String).collect()),
        );
        m.insert("agent".into(), Value::String(self.agent.clone()));
        m.insert(
            "parent_reports".into(),
            Value::Array(self.parent_reports.iter().cloned().map(Value::String).collect()),
        );
        Value::Object(m)
    }
}

/// Fine-grained access control for artifacts.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct ACL {
    #[serde(default)]
    pub allowed_tenants: Vec<String>,
    #[serde(default)]
    pub allowed_users: Vec<String>,
    #[serde(default)]
    pub allowed_teams: Vec<String>,
}

impl ACL {
    /// Python `ACL.to_dict()` — always emits all three keys.
    pub fn to_dict(&self) -> Value {
        let mut m = Map::new();
        m.insert(
            "allowed_tenants".into(),
            Value::Array(self.allowed_tenants.iter().cloned().map(Value::String).collect()),
        );
        m.insert(
            "allowed_users".into(),
            Value::Array(self.allowed_users.iter().cloned().map(Value::String).collect()),
        );
        m.insert(
            "allowed_teams".into(),
            Value::Array(self.allowed_teams.iter().cloned().map(Value::String).collect()),
        );
        Value::Object(m)
    }
}

/// A KCP Knowledge Artifact — the signed unit of AI-generated knowledge.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct KnowledgeArtifact {
    pub id: String,
    pub version: String,
    pub user_id: String,
    pub tenant_id: String,
    pub timestamp: String,
    pub format: String,
    pub visibility: String,
    pub title: String,

    #[serde(default)]
    pub team: Option<String>,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default)]
    pub source: String,
    #[serde(default)]
    pub summary: String,
    #[serde(default)]
    pub lineage: Option<Lineage>,
    #[serde(default)]
    pub content_url: String,
    #[serde(default)]
    pub content_hash: String,
    #[serde(default)]
    pub embeddings: Vec<f64>,
    #[serde(default)]
    pub signature: String,
    #[serde(default)]
    pub acl: Option<ACL>,

    /// Kept in the metadata table only — never part of the signed payload
    /// (the reference SDK drops it from `to_dict()` too).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub derived_from: Option<String>,
}

impl KnowledgeArtifact {
    /// Create an artifact with reference defaults (public visibility, v1).
    pub fn new(
        title: impl Into<String>,
        user_id: impl Into<String>,
        tenant_id: impl Into<String>,
        format: impl Into<String>,
    ) -> Self {
        Self {
            id: Uuid::new_v4().to_string(),
            version: "1".to_string(),
            user_id: user_id.into(),
            tenant_id: tenant_id.into(),
            timestamp: now_iso(),
            format: format.into(),
            visibility: "public".to_string(),
            title: title.into(),
            team: None,
            tags: Vec::new(),
            source: String::new(),
            summary: String::new(),
            lineage: None,
            content_url: String::new(),
            content_hash: String::new(),
            embeddings: Vec::new(),
            signature: String::new(),
            acl: None,
            derived_from: None,
        }
    }

    /// Python `KnowledgeArtifact.to_dict()`.
    ///
    /// Required fields are always present (even when empty); optional fields
    /// appear only when set, exactly like the reference implementation.
    pub fn to_dict(&self) -> Value {
        let mut m = Map::new();
        m.insert("id".into(), Value::String(self.id.clone()));
        m.insert("version".into(), Value::String(self.version.clone()));
        m.insert("user_id".into(), Value::String(self.user_id.clone()));
        m.insert("tenant_id".into(), Value::String(self.tenant_id.clone()));
        m.insert("timestamp".into(), Value::String(self.timestamp.clone()));
        m.insert("format".into(), Value::String(self.format.clone()));
        m.insert("visibility".into(), Value::String(self.visibility.clone()));
        m.insert("title".into(), Value::String(self.title.clone()));
        m.insert("content_hash".into(), Value::String(self.content_hash.clone()));
        m.insert("signature".into(), Value::String(self.signature.clone()));

        if let Some(team) = &self.team {
            if !team.is_empty() {
                m.insert("team".into(), Value::String(team.clone()));
            }
        }
        if !self.tags.is_empty() {
            m.insert(
                "tags".into(),
                Value::Array(self.tags.iter().cloned().map(Value::String).collect()),
            );
        }
        if !self.source.is_empty() {
            m.insert("source".into(), Value::String(self.source.clone()));
        }
        if !self.summary.is_empty() {
            m.insert("summary".into(), Value::String(self.summary.clone()));
        }
        if let Some(lineage) = &self.lineage {
            m.insert("lineage".into(), lineage.to_dict());
        }
        if !self.content_url.is_empty() {
            m.insert("content_url".into(), Value::String(self.content_url.clone()));
        }
        if !self.embeddings.is_empty() {
            m.insert(
                "embeddings".into(),
                Value::Array(
                    self.embeddings
                        .iter()
                        .map(|f| {
                            serde_json::Number::from_f64(*f)
                                .map(Value::Number)
                                .unwrap_or(Value::Null)
                        })
                        .collect(),
                ),
            );
        }
        if let Some(acl) = &self.acl {
            m.insert("acl".into(), acl.to_dict());
        }
        Value::Object(m)
    }

    /// The exact payload that gets signed / verified (dict without signature).
    pub fn signing_payload(&self) -> Value {
        let mut d = self.to_dict();
        if let Value::Object(map) = &mut d {
            map.remove("signature");
        }
        d
    }

    /// Canonical JSON (Python `json.dumps(..., sort_keys=True, separators=(",",":"))`).
    pub fn canonical_json(&self) -> String {
        canonical_json(&self.signing_payload())
    }

    /// Canonical JSON bytes — the message Ed25519 signs.
    pub fn canonical_bytes(&self) -> Vec<u8> {
        canonical_bytes(&self.signing_payload())
    }

    /// Build an artifact from a dict (sync payload / export file).
    ///
    /// Mirrors `KnowledgeArtifact.from_dict`: `user_id`, `tenant_id`, `format`
    /// and `title` are required; everything else falls back to defaults.
    pub fn from_dict(data: &Value) -> Result<Self> {
        let obj = data
            .as_object()
            .ok_or_else(|| KcpError::Other("artifact payload must be a JSON object".into()))?;

        let required = |key: &str| -> Result<String> {
            obj.get(key)
                .and_then(|v| v.as_str())
                .map(|s| s.to_string())
                .ok_or_else(|| KcpError::MissingField(key.to_string()))
        };
        let optional_str = |key: &str| -> String {
            obj.get(key).and_then(|v| v.as_str()).unwrap_or_default().to_string()
        };
        let string_list = |key: &str| -> Vec<String> {
            obj.get(key)
                .and_then(|v| v.as_array())
                .map(|arr| arr.iter().filter_map(|v| v.as_str().map(String::from)).collect())
                .unwrap_or_default()
        };

        let id = match obj.get("id").and_then(|v| v.as_str()) {
            Some(s) if !s.is_empty() => s.to_string(),
            _ => Uuid::new_v4().to_string(),
        };
        let version = match obj.get("version").and_then(|v| v.as_str()) {
            Some(s) if !s.is_empty() => s.to_string(),
            _ => "1".to_string(),
        };
        let timestamp = match obj.get("timestamp").and_then(|v| v.as_str()) {
            Some(s) if !s.is_empty() => s.to_string(),
            _ => now_iso(),
        };
        let visibility = match obj.get("visibility").and_then(|v| v.as_str()) {
            Some(s) if !s.is_empty() => s.to_string(),
            _ => "private".to_string(),
        };
        let team = obj
            .get("team")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .map(String::from);
        let lineage = match obj.get("lineage") {
            Some(Value::Object(_)) => Some(
                serde_json::from_value::<Lineage>(obj.get("lineage").unwrap().clone()).unwrap_or_default(),
            ),
            _ => None,
        };
        let acl = match obj.get("acl") {
            Some(Value::Object(_)) => Some(
                serde_json::from_value::<ACL>(obj.get("acl").unwrap().clone()).unwrap_or_default(),
            ),
            _ => None,
        };
        let embeddings = obj
            .get("embeddings")
            .and_then(|v| v.as_array())
            .map(|arr| arr.iter().filter_map(|v| v.as_f64()).collect())
            .unwrap_or_default();

        Ok(Self {
            id,
            version,
            user_id: required("user_id")?,
            tenant_id: required("tenant_id")?,
            timestamp,
            format: required("format")?,
            visibility,
            title: required("title")?,
            team,
            tags: string_list("tags"),
            source: optional_str("source"),
            summary: optional_str("summary"),
            lineage,
            content_url: optional_str("content_url"),
            content_hash: optional_str("content_hash"),
            embeddings,
            signature: optional_str("signature"),
            acl,
            derived_from: obj
                .get("derived_from")
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
                .map(String::from),
        })
    }
}

/// A single search result from a DISCOVER operation.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SearchResult {
    pub id: String,
    pub title: String,
    #[serde(default)]
    pub summary: String,
    pub created_at: String,
    #[serde(default)]
    pub relevance: f64,
    #[serde(default)]
    pub format: String,
    #[serde(default)]
    pub preview: String,
}

/// Response from a DISCOVER operation.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct SearchResponse {
    pub results: Vec<SearchResult>,
    pub total: usize,
    pub query_time_ms: i64,
}

/// One step of a lineage chain.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct LineageEntry {
    pub id: String,
    pub title: String,
    pub author: String,
    pub created_at: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub derived_from: Option<String>,
}

/// A known peer node.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct PeerInfo {
    pub id: String,
    pub url: String,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub public_key: String,
    #[serde(default)]
    pub last_seen: String,
    #[serde(default)]
    pub added_at: String,
}

/// Full node statistics (internal use).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct NodeStats {
    pub node_id: String,
    pub user_id: String,
    pub tenant_id: String,
    pub artifacts: i64,
    pub content_size_bytes: i64,
    pub content_size_human: String,
    pub peers: i64,
    pub db_size_bytes: i64,
    pub db_size_human: String,
    pub db_path: String,
}

/// Storage-level statistics (before node identity is merged in).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct StoreStats {
    pub artifacts: i64,
    pub content_size_bytes: i64,
    pub content_size_human: String,
    pub peers: i64,
    pub db_size_bytes: i64,
    pub db_size_human: String,
    pub db_path: String,
}

/// Convert a byte count into the reference human-readable string.
pub fn human_size(size_bytes: i64) -> String {
    let units = ["B", "KB", "MB", "GB", "TB"];
    let mut size = size_bytes as f64;
    for unit in units {
        if size < 1024.0 {
            return format!("{:.1} {}", size, unit);
        }
        size /= 1024.0;
    }
    format!("{:.1} PB", size)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn sample() -> KnowledgeArtifact {
        let mut a = KnowledgeArtifact::new("T", "u@x", "t", "markdown");
        a.id = "11111111-1111-4111-8111-111111111111".into();
        a.timestamp = "2026-01-02T03:04:05.123456+00:00".into();
        a.content_hash = "abc".into();
        a
    }

    #[test]
    fn new_sets_defaults() {
        let a = KnowledgeArtifact::new("Title", "u", "t", "text");
        assert_eq!(a.version, "1");
        assert_eq!(a.visibility, "public");
        assert_eq!(a.title, "Title");
        assert!(a.signature.is_empty());
        assert!(a.tags.is_empty());
        assert_eq!(Uuid::parse_str(&a.id).unwrap().to_string(), a.id);
    }

    #[test]
    fn new_generates_unique_ids() {
        assert_ne!(
            KnowledgeArtifact::new("a", "u", "t", "text").id,
            KnowledgeArtifact::new("a", "u", "t", "text").id
        );
    }

    #[test]
    fn new_timestamp_is_rfc3339_utc() {
        let a = KnowledgeArtifact::new("a", "u", "t", "text");
        assert!(a.timestamp.ends_with("+00:00"), "got {}", a.timestamp);
        assert_eq!(a.timestamp.len(), "2026-01-02T03:04:05.123456+00:00".len());
    }

    #[test]
    fn to_dict_minimal_has_required_keys() {
        let d = sample().to_dict();
        let obj = d.as_object().unwrap();
        for key in [
            "id",
            "version",
            "user_id",
            "tenant_id",
            "timestamp",
            "format",
            "visibility",
            "title",
            "content_hash",
            "signature",
        ] {
            assert!(obj.contains_key(key), "missing {key}");
        }
        assert_eq!(obj.len(), 10);
    }

    #[test]
    fn to_dict_omits_empty_optional_fields() {
        let obj = sample().to_dict();
        for key in ["team", "tags", "source", "summary", "lineage", "acl"] {
            assert!(!obj.as_object().unwrap().contains_key(key), "unexpected {key}");
        }
    }

    #[test]
    fn to_dict_includes_set_optional_fields() {
        let mut a = sample();
        a.team = Some("finance".into());
        a.tags = vec!["a".into(), "b".into()];
        a.source = "agent".into();
        a.summary = "sum".into();
        a.content_url = "http://x".into();
        a.lineage = Some(Lineage::new("q"));
        a.acl = Some(ACL {
            allowed_users: vec!["u".into()],
            ..Default::default()
        });
        let d = a.to_dict();
        let obj = d.as_object().unwrap();
        assert_eq!(obj["team"], json!("finance"));
        assert_eq!(obj["tags"], json!(["a", "b"]));
        assert_eq!(obj["source"], json!("agent"));
        assert_eq!(obj["summary"], json!("sum"));
        assert_eq!(obj["content_url"], json!("http://x"));
        assert!(obj["lineage"].is_object());
        assert!(obj["acl"].is_object());
    }

    #[test]
    fn empty_team_is_omitted() {
        let mut a = sample();
        a.team = Some(String::new());
        assert!(!a.to_dict().as_object().unwrap().contains_key("team"));
    }

    #[test]
    fn lineage_to_dict_always_has_four_keys() {
        let v = Lineage::new("q").to_dict();
        assert_eq!(v.as_object().unwrap().len(), 4);
        assert_eq!(v["data_sources"], json!([]));
        assert_eq!(v["agent"], json!(""));
        assert_eq!(v["parent_reports"], json!([]));
    }

    #[test]
    fn acl_to_dict_always_has_three_keys() {
        let v = ACL::default().to_dict();
        assert_eq!(v.as_object().unwrap().len(), 3);
    }

    #[test]
    fn signing_payload_drops_signature() {
        let mut a = sample();
        a.signature = "deadbeef".into();
        assert!(!a.signing_payload().as_object().unwrap().contains_key("signature"));
        assert!(a.to_dict().as_object().unwrap().contains_key("signature"));
    }

    #[test]
    fn canonical_json_is_sorted_and_compact() {
        let c = sample().canonical_json();
        assert!(c.starts_with("{\"content_hash\":\"abc\""));
        assert!(!c.contains(": "));
        assert!(!c.contains("signature"));
    }

    #[test]
    fn canonical_json_is_deterministic() {
        assert_eq!(sample().canonical_json(), sample().canonical_json());
    }

    #[test]
    fn canonical_bytes_match_canonical_json() {
        let a = sample();
        assert_eq!(a.canonical_bytes(), a.canonical_json().into_bytes());
    }

    #[test]
    fn from_dict_roundtrip() {
        let mut a = sample();
        a.tags = vec!["x".into()];
        a.lineage = Some(Lineage::new("q"));
        let back = KnowledgeArtifact::from_dict(&a.to_dict()).unwrap();
        assert_eq!(back.id, a.id);
        assert_eq!(back.tags, a.tags);
        assert_eq!(back.lineage, a.lineage);
        assert_eq!(back.visibility, a.visibility);
    }

    #[test]
    fn from_dict_requires_core_fields() {
        let err = KnowledgeArtifact::from_dict(&json!({"title": "x"})).unwrap_err();
        assert!(matches!(err, KcpError::MissingField(_)));
    }

    #[test]
    fn from_dict_applies_reference_defaults() {
        let a = KnowledgeArtifact::from_dict(&json!({
            "title": "T", "user_id": "u", "tenant_id": "t", "format": "text"
        }))
        .unwrap();
        assert_eq!(a.version, "1");
        assert_eq!(a.visibility, "private");
        assert!(!a.id.is_empty());
        assert!(a.timestamp.ends_with("+00:00"));
    }

    #[test]
    fn from_dict_ignores_unknown_and_private_keys() {
        let a = KnowledgeArtifact::from_dict(&json!({
            "title": "T", "user_id": "u", "tenant_id": "t", "format": "text",
            "_content_b64": "AAAA", "_kcp_export": {"version": "1"},
        }))
        .unwrap();
        assert_eq!(a.title, "T");
    }

    #[test]
    fn from_dict_reads_derived_from() {
        let a = KnowledgeArtifact::from_dict(&json!({
            "title": "T", "user_id": "u", "tenant_id": "t", "format": "text",
            "derived_from": "parent-id",
        }))
        .unwrap();
        assert_eq!(a.derived_from.as_deref(), Some("parent-id"));
        // ...but derived_from never leaks into the signed payload.
        assert!(!a.to_dict().as_object().unwrap().contains_key("derived_from"));
    }

    #[test]
    fn from_dict_rejects_non_object() {
        assert!(KnowledgeArtifact::from_dict(&json!([1, 2])).is_err());
    }

    #[test]
    fn human_size_formatting() {
        assert_eq!(human_size(0), "0.0 B");
        assert_eq!(human_size(1023), "1023.0 B");
        assert_eq!(human_size(1024), "1.0 KB");
        assert_eq!(human_size(1024 * 1024), "1.0 MB");
        assert_eq!(human_size(1024_i64.pow(3)), "1.0 GB");
    }
}
