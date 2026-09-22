//! KCP cryptographic operations.
//!
//! Mirrors `sdk/python/kcp/crypto.py`:
//!
//! * Ed25519 signing/verification (raw 32-byte seed keys, hex signatures),
//! * SHA-256 content hashing (lowercase hex),
//! * AES-256-GCM content encryption with an HKDF-SHA256 derived key and the
//!   `KCPENC1` wire magic.
//!
//! Wire format of an encrypted blob:
//!
//! ```text
//! KCPENC1 (7 bytes) | nonce (12 bytes) | ciphertext + GCM tag (N + 16 bytes)
//! ```

use std::path::{Path, PathBuf};

use aes_gcm::aead::{Aead, KeyInit};
use aes_gcm::{Aes256Gcm, Nonce};
use ed25519_dalek::{Signature, Signer, SigningKey, Verifier, VerifyingKey};
use hkdf::Hkdf;
use rand::RngCore;
use sha2::{Digest, Sha256};

use crate::error::{KcpError, Result};

/// 7-byte magic prefix marking an encrypted (private) content blob.
pub const ENCRYPTION_MAGIC: &[u8] = b"KCPENC1";

/// Length of the AES-GCM nonce used by KCP.
pub const NONCE_LEN: usize = 12;

/// An Ed25519 keypair in KCP's raw-bytes representation (32-byte seed/public).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct KeyPair {
    pub private_key: [u8; 32],
    pub public_key: [u8; 32],
}

/// Generate a fresh random Ed25519 keypair (`cryptography`'s `generate()`).
pub fn generate_keypair() -> KeyPair {
    let mut seed = [0u8; 32];
    rand::rngs::OsRng.fill_bytes(&mut seed);
    keypair_from_seed(&seed)
}

/// Build a keypair from a raw 32-byte Ed25519 seed.
pub fn keypair_from_seed(seed: &[u8; 32]) -> KeyPair {
    let signing = SigningKey::from_bytes(seed);
    KeyPair {
        private_key: *seed,
        public_key: signing.verifying_key().to_bytes(),
    }
}

/// Derive the 32-byte public key from a raw 32-byte private seed.
pub fn derive_public_key(private_key: &[u8; 32]) -> [u8; 32] {
    SigningKey::from_bytes(private_key).verifying_key().to_bytes()
}

/// Sign raw bytes with Ed25519, returning a lowercase hex signature.
pub fn sign(payload: &[u8], private_key: &[u8; 32]) -> String {
    let signing = SigningKey::from_bytes(private_key);
    signing.sign(payload).to_bytes().iter().map(|b| format!("{:02x}", b)).collect()
}

/// Verify an Ed25519 signature (hex) over `payload`.
///
/// Returns `false` — never an error — for malformed input, mirroring the
/// Python reference (`verify_artifact`).
pub fn verify(payload: &[u8], signature_hex: &str, public_key: &[u8]) -> bool {
    if signature_hex.is_empty() {
        return false;
    }
    let sig_bytes = match hex::decode(signature_hex) {
        Ok(b) => b,
        Err(_) => return false,
    };
    let signature = match Signature::from_slice(&sig_bytes) {
        Ok(s) => s,
        Err(_) => return false,
    };
    if public_key.len() != 32 {
        return false;
    }
    let mut pk = [0u8; 32];
    pk.copy_from_slice(public_key);
    let verifying = match VerifyingKey::from_bytes(&pk) {
        Ok(v) => v,
        Err(_) => return false,
    };
    verifying.verify(payload, &signature).is_ok()
}

/// Verify a signature given as raw 64 bytes.
pub fn verify_bytes(payload: &[u8], signature: &[u8], public_key: &[u8]) -> bool {
    verify(payload, &hex::encode(signature), public_key)
}

/// SHA-256 of `content` as lowercase hex (64 chars).
pub fn hash_content(content: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(content);
    hex::encode(hasher.finalize())
}

/// Derive the 256-bit AES key for an artifact from the node's private seed.
///
/// HKDF-SHA256 with a `None` salt (RFC 5869 all-zero salt, exactly what
/// `cryptography`'s `HKDF(salt=None)` does) and
/// `info = "kcp-content-key:{artifact_id}"`.
pub fn derive_content_key(private_key: &[u8; 32], artifact_id: &str) -> [u8; 32] {
    let hkdf = Hkdf::<Sha256>::new(None, private_key);
    let info = format!("kcp-content-key:{}", artifact_id);
    let mut okm = [0u8; 32];
    hkdf.expand(info.as_bytes(), &mut okm)
        .expect("32 bytes is a valid HKDF-SHA256 output length");
    okm
}

/// Encrypt content with AES-256-GCM using a random 12-byte nonce.
pub fn encrypt_content(content: &[u8], key: &[u8; 32]) -> Result<Vec<u8>> {
    encrypt_content_with_nonce(content, key, &random_nonce())
}

/// Encrypt with an explicit nonce (used by tests and deterministic tooling).
pub fn encrypt_content_with_nonce(
    content: &[u8],
    key: &[u8; 32],
    nonce: &[u8; NONCE_LEN],
) -> Result<Vec<u8>> {
    let cipher = Aes256Gcm::new_from_slice(key)
        .map_err(|e| KcpError::InvalidKey(format!("aes key: {}", e)))?;
    let ciphertext = cipher
        .encrypt(Nonce::from_slice(nonce), content)
        .map_err(|e| KcpError::DecryptionFailed(format!("encrypt: {}", e)))?;
    let mut blob = Vec::with_capacity(ENCRYPTION_MAGIC.len() + NONCE_LEN + ciphertext.len());
    blob.extend_from_slice(ENCRYPTION_MAGIC);
    blob.extend_from_slice(nonce);
    blob.extend_from_slice(&ciphertext);
    Ok(blob)
}

/// Decrypt a `KCPENC1` blob produced by the Python, Go, TypeScript or Rust SDK.
pub fn decrypt_content(blob: &[u8], key: &[u8; 32]) -> Result<Vec<u8>> {
    if !is_encrypted(blob) {
        return Err(KcpError::NotEncrypted);
    }
    let nonce = &blob[ENCRYPTION_MAGIC.len()..ENCRYPTION_MAGIC.len() + NONCE_LEN];
    let ciphertext = &blob[ENCRYPTION_MAGIC.len() + NONCE_LEN..];
    let cipher = Aes256Gcm::new_from_slice(key)
        .map_err(|e| KcpError::InvalidKey(format!("aes key: {}", e)))?;
    cipher
        .decrypt(Nonce::from_slice(nonce), ciphertext)
        .map_err(|e| KcpError::DecryptionFailed(format!("invalid tag: {}", e)))
}

/// True when the blob carries the KCP encryption magic prefix.
pub fn is_encrypted(blob: &[u8]) -> bool {
    blob.len() >= ENCRYPTION_MAGIC.len()
        && &blob[..ENCRYPTION_MAGIC.len()] == ENCRYPTION_MAGIC
}

fn random_nonce() -> [u8; NONCE_LEN] {
    let mut nonce = [0u8; NONCE_LEN];
    rand::rngs::OsRng.fill_bytes(&mut nonce);
    nonce
}

// ─── Key persistence (same layout as the Python/Go SDKs) ──────

fn private_key_path(dir: &Path) -> PathBuf {
    dir.join("private.key")
}

fn public_key_path(dir: &Path) -> PathBuf {
    dir.join("public.key")
}

/// Write `private.key` / `public.key` (raw bytes) into `dir`.
pub fn save_keys(dir: &Path, keys: &KeyPair) -> Result<()> {
    std::fs::create_dir_all(dir)?;
    let priv_path = private_key_path(dir);
    std::fs::write(&priv_path, keys.private_key)?;
    restrict_permissions(&priv_path)?;
    std::fs::write(public_key_path(dir), keys.public_key)?;
    Ok(())
}

/// Load a keypair previously written by [`save_keys`] (or the Python SDK).
pub fn load_keys(dir: &Path) -> Result<KeyPair> {
    let priv_bytes = std::fs::read(private_key_path(dir))?;
    let pub_bytes = std::fs::read(public_key_path(dir))?;
    if priv_bytes.len() != 32 {
        return Err(KcpError::InvalidKey(format!(
            "private.key must be 32 bytes, got {}",
            priv_bytes.len()
        )));
    }
    if pub_bytes.len() != 32 {
        return Err(KcpError::InvalidKey(format!(
            "public.key must be 32 bytes, got {}",
            pub_bytes.len()
        )));
    }
    let mut seed = [0u8; 32];
    seed.copy_from_slice(&priv_bytes);
    let mut public_key = [0u8; 32];
    public_key.copy_from_slice(&pub_bytes);
    Ok(KeyPair {
        private_key: seed,
        public_key,
    })
}

/// Load the keypair from `dir`, generating and persisting one if missing.
pub fn load_or_generate_keys(dir: &Path) -> Result<KeyPair> {
    if private_key_path(dir).exists() && public_key_path(dir).exists() {
        return load_keys(dir);
    }
    let keys = generate_keypair();
    save_keys(dir, &keys)?;
    Ok(keys)
}

#[cfg(unix)]
fn restrict_permissions(path: &Path) -> Result<()> {
    use std::os::unix::fs::PermissionsExt;
    let perms = std::fs::Permissions::from_mode(0o600);
    std::fs::set_permissions(path, perms)?;
    Ok(())
}

#[cfg(not(unix))]
fn restrict_permissions(_path: &Path) -> Result<()> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    const SEED: [u8; 32] = [
        0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24,
        25, 26, 27, 28, 29, 30, 31,
    ];

    #[test]
    fn generate_keypair_returns_32_byte_keys() {
        let kp = generate_keypair();
        assert_eq!(kp.private_key.len(), 32);
        assert_eq!(kp.public_key.len(), 32);
    }

    #[test]
    fn generate_keypair_is_unique() {
        assert_ne!(generate_keypair().public_key, generate_keypair().public_key);
    }

    #[test]
    fn derive_public_key_matches_keypair() {
        let kp = keypair_from_seed(&SEED);
        assert_eq!(derive_public_key(&SEED), kp.public_key);
    }

    #[test]
    fn sign_and_verify_roundtrip() {
        let kp = generate_keypair();
        let sig = sign(b"hello kcp", &kp.private_key);
        assert_eq!(sig.len(), 128);
        assert!(verify(b"hello kcp", &sig, &kp.public_key));
    }

    #[test]
    fn verify_rejects_tampered_payload() {
        let kp = generate_keypair();
        let sig = sign(b"original", &kp.private_key);
        assert!(!verify(b"tampered", &sig, &kp.public_key));
    }

    #[test]
    fn verify_rejects_wrong_key() {
        let kp = generate_keypair();
        let other = generate_keypair();
        let sig = sign(b"data", &kp.private_key);
        assert!(!verify(b"data", &sig, &other.public_key));
    }

    #[test]
    fn verify_rejects_malformed_signature() {
        let kp = generate_keypair();
        assert!(!verify(b"data", "", &kp.public_key));
        assert!(!verify(b"data", "zz-not-hex", &kp.public_key));
        assert!(!verify(b"data", "abcd", &kp.public_key));
    }

    #[test]
    fn verify_rejects_bad_public_key_length() {
        let kp = generate_keypair();
        let sig = sign(b"data", &kp.private_key);
        assert!(!verify(b"data", &sig, &[0u8; 16]));
    }

    #[test]
    fn sign_is_deterministic() {
        let kp = generate_keypair();
        assert_eq!(sign(b"same", &kp.private_key), sign(b"same", &kp.private_key));
    }

    #[test]
    fn signature_is_lowercase_hex() {
        let kp = generate_keypair();
        let sig = sign(b"x", &kp.private_key);
        assert!(sig
            .chars()
            .all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase()));
    }

    #[test]
    fn hash_content_known_values() {
        assert_eq!(
            hash_content(b""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        assert_eq!(hash_content(b"").len(), 64);
    }

    #[test]
    fn hash_content_is_deterministic_and_sensitive() {
        assert_eq!(hash_content(b"a"), hash_content(b"a"));
        assert_ne!(hash_content(b"a"), hash_content(b"b"));
    }

    #[test]
    fn derive_content_key_is_32_bytes_and_id_dependent() {
        let k1 = derive_content_key(&SEED, "id-1");
        let k2 = derive_content_key(&SEED, "id-2");
        assert_eq!(k1.len(), 32);
        assert_ne!(k1, k2);
        assert_eq!(k1, derive_content_key(&SEED, "id-1"));
    }

    #[test]
    fn encrypt_blob_layout() {
        let key = derive_content_key(&SEED, "a");
        let blob = encrypt_content(b"hello", &key).unwrap();
        assert!(is_encrypted(&blob));
        assert_eq!(blob.len(), 7 + 12 + 5 + 16);
    }

    #[test]
    fn encrypt_decrypt_roundtrip() {
        let key = derive_content_key(&SEED, "a");
        let plaintext = "Conteúdo secreto ção 🚀".as_bytes();
        let blob = encrypt_content(plaintext, &key).unwrap();
        assert_eq!(decrypt_content(&blob, &key).unwrap(), plaintext);
    }

    #[test]
    fn encrypt_empty_payload() {
        let key = derive_content_key(&SEED, "a");
        let blob = encrypt_content(b"", &key).unwrap();
        assert_eq!(decrypt_content(&blob, &key).unwrap(), b"");
    }

    #[test]
    fn encrypt_uses_random_nonce() {
        let key = derive_content_key(&SEED, "a");
        assert_ne!(
            encrypt_content(b"same", &key).unwrap(),
            encrypt_content(b"same", &key).unwrap()
        );
    }

    #[test]
    fn decrypt_with_wrong_key_fails() {
        let blob = encrypt_content(b"secret", &derive_content_key(&SEED, "a")).unwrap();
        let wrong = derive_content_key(&SEED, "b");
        assert!(decrypt_content(&blob, &wrong).is_err());
    }

    #[test]
    fn decrypt_rejects_plaintext() {
        let key = derive_content_key(&SEED, "a");
        assert!(matches!(
            decrypt_content(b"not encrypted", &key),
            Err(KcpError::NotEncrypted)
        ));
    }

    #[test]
    fn is_encrypted_false_for_plaintext() {
        assert!(!is_encrypted(b""));
        assert!(!is_encrypted(b"plain text"));
        assert!(!is_encrypted(b"KCPEN"));
        assert!(!is_encrypted(b"KCPENC"));
        // Matches Python: `blob[:7] == b"KCPENC1"` is true even for the bare magic.
        assert!(is_encrypted(ENCRYPTION_MAGIC));
    }

    #[test]
    fn save_and_load_keys_roundtrip() {
        let dir = tempfile::tempdir().unwrap();
        let kp = generate_keypair();
        save_keys(dir.path(), &kp).unwrap();
        assert_eq!(load_keys(dir.path()).unwrap(), kp);
    }

    #[test]
    fn load_or_generate_keys_is_idempotent() {
        let dir = tempfile::tempdir().unwrap();
        let a = load_or_generate_keys(dir.path()).unwrap();
        let b = load_or_generate_keys(dir.path()).unwrap();
        assert_eq!(a.public_key, b.public_key);
    }

    #[test]
    fn load_keys_rejects_wrong_size() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("private.key"), b"short").unwrap();
        std::fs::write(dir.path().join("public.key"), [0u8; 32]).unwrap();
        assert!(load_keys(dir.path()).is_err());
    }
}
