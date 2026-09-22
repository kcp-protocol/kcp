//! KCP error type shared across the SDK.

use thiserror::Error;

/// Errors produced by the KCP Rust SDK.
#[derive(Debug, Error)]
pub enum KcpError {
    #[error("database error: {0}")]
    Database(#[from] rusqlite::Error),

    #[error("serialization error: {0}")]
    Serialization(#[from] serde_json::Error),

    #[error("io error: {0}")]
    Io(#[from] std::io::Error),

    #[error("invalid key: {0}")]
    InvalidKey(String),

    #[error("invalid signature: {0}")]
    InvalidSignature(String),

    #[error("decryption failed: {0}")]
    DecryptionFailed(String),

    #[error("not a KCP encrypted blob (missing KCPENC1 magic)")]
    NotEncrypted,

    #[error("missing required field: {0}")]
    MissingField(String),

    #[error("invalid uuid: {0}")]
    InvalidUuid(String),

    #[error("{0}")]
    Other(String),
}

/// Convenience alias used throughout the SDK.
pub type Result<T> = std::result::Result<T, KcpError>;
