//! Cross-language compatibility tests.
//!
//! Every expectation in `fixtures/vectors.json` was produced by the **Python
//! reference SDK** (`sdk/python/kcp/models.py` + `crypto.py`) through
//! `tests/fixtures/gen_vectors.py`. If the Rust SDK drifts from the reference
//! by a single byte, these tests fail — that is the whole point.

use kcp::{
    canonical_json, decrypt_content, derive_content_key, derive_public_key, encrypt_content,
    hash_content, is_encrypted, sign, verify, KnowledgeArtifact, ENCRYPTION_MAGIC,
};
use serde_json::Value;

const VECTORS: &str = include_str!("fixtures/vectors.json");

fn vectors() -> Value {
    serde_json::from_str(VECTORS).expect("vectors.json must be valid JSON")
}

fn seed() -> [u8; 32] {
    let hex_seed = vectors()["seed_hex"].as_str().unwrap().to_string();
    let bytes = hex::decode(hex_seed).unwrap();
    let mut seed = [0u8; 32];
    seed.copy_from_slice(&bytes);
    seed
}

fn public_key() -> Vec<u8> {
    hex::decode(vectors()["public_key_hex"].as_str().unwrap()).unwrap()
}

#[test]
fn reference_public_key_derivation_matches() {
    let v = vectors();
    assert_eq!(hex::encode(derive_public_key(&seed())), v["public_key_hex"].as_str().unwrap());
}

#[test]
fn reference_private_key_vector_is_loaded() {
    let v = vectors();
    assert_eq!(hex::encode(seed()), v["private_key_hex"].as_str().unwrap());
    assert!(v["generator"].as_str().unwrap().contains("python"));
}

#[test]
fn canonical_json_matches_python_for_every_artifact_vector() {
    let v = vectors();
    let artifacts = v["artifacts"].as_array().unwrap();
    assert!(artifacts.len() >= 5, "expected a representative vector set");

    for case in artifacts {
        let name = case["name"].as_str().unwrap();
        let mut artifact = KnowledgeArtifact::from_dict(&case["input"])
            .unwrap_or_else(|e| panic!("{name}: from_dict failed: {e}"));
        artifact.signature = case["signature"].as_str().unwrap().to_string();

        assert_eq!(
            artifact.canonical_json(),
            case["canonical"].as_str().unwrap(),
            "{name}: canonical payload diverged from the Python reference"
        );
    }
}

#[test]
fn signatures_match_python_for_every_artifact_vector() {
    let v = vectors();
    for case in v["artifacts"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let artifact = KnowledgeArtifact::from_dict(&case["input"]).unwrap();
        assert_eq!(
            sign(&artifact.canonical_bytes(), &seed()),
            case["signature"].as_str().unwrap(),
            "{name}: Ed25519 signature diverged from the Python reference"
        );
    }
}

#[test]
fn python_signatures_verify_in_rust() {
    let v = vectors();
    for case in v["artifacts"].as_array().unwrap() {
        let artifact = KnowledgeArtifact::from_dict(&case["input"]).unwrap();
        assert!(verify(
            &artifact.canonical_bytes(),
            case["signature"].as_str().unwrap(),
            &public_key()
        ));
    }
}

#[test]
fn rust_signatures_verify_for_python_style_raw_payloads() {
    let v = vectors();
    for case in v["raw_sign"].as_array().unwrap() {
        let canonical = case["canonical"].as_str().unwrap();
        assert_eq!(
            canonical,
            canonical_json(&case["payload"]),
            "canonical encoding of a raw payload diverged"
        );
        assert_eq!(sign(canonical.as_bytes(), &seed()), case["signature"].as_str().unwrap());
        assert!(verify(
            canonical.as_bytes(),
            case["signature"].as_str().unwrap(),
            &public_key()
        ));
    }
}

#[test]
fn tampering_with_a_reference_artifact_breaks_verification() {
    let v = vectors();
    let case = &v["artifacts"][0];
    let mut artifact = KnowledgeArtifact::from_dict(&case["input"]).unwrap();
    artifact.title = format!("{} (tampered)", artifact.title);
    assert!(!verify(
        &artifact.canonical_bytes(),
        case["signature"].as_str().unwrap(),
        &public_key()
    ));
}

#[test]
fn hash_vectors_match_python() {
    let v = vectors();
    let hashes = v["hashes"].as_array().unwrap();
    assert!(hashes.len() >= 4);
    for case in hashes {
        let input = hex::decode(case["input_hex"].as_str().unwrap()).unwrap();
        assert_eq!(
            hash_content(&input),
            case["sha256"].as_str().unwrap(),
            "sha256 of {} diverged",
            case["input_utf8"]
        );
    }
}

#[test]
fn hkdf_content_key_vectors_match_python() {
    let v = vectors();
    for case in v["content_keys"].as_array().unwrap() {
        let id = case["artifact_id"].as_str().unwrap();
        assert_eq!(
            hex::encode(derive_content_key(&seed(), id)),
            case["key_hex"].as_str().unwrap(),
            "HKDF-SHA256 key for {id} diverged"
        );
    }
}

#[test]
fn decrypts_python_encrypted_blobs() {
    let v = vectors();
    let cases = v["aes_gcm"].as_array().unwrap();
    assert!(cases.len() >= 3);
    for case in cases {
        let blob = hex::decode(case["blob_hex"].as_str().unwrap()).unwrap();
        let key_hex = case["key_hex"].as_str().unwrap();
        let mut key = [0u8; 32];
        key.copy_from_slice(&hex::decode(key_hex).unwrap());
        let plaintext = hex::decode(case["plaintext_hex"].as_str().unwrap()).unwrap();

        assert!(is_encrypted(&blob));
        assert_eq!(&blob[..7], ENCRYPTION_MAGIC);
        assert_eq!(
            decrypt_content(&blob, &key).unwrap(),
            plaintext,
            "{}: Python blob did not decrypt in Rust",
            case["name"]
        );
    }
}

#[test]
fn rust_encryption_roundtrips_with_reference_key() {
    let v = vectors();
    let case = &v["aes_gcm"][1];
    let id = case["artifact_id"].as_str().unwrap();
    let key = derive_content_key(&seed(), id);
    let plaintext = hex::decode(case["plaintext_hex"].as_str().unwrap()).unwrap();

    let blob = encrypt_content(&plaintext, &key).unwrap();
    assert!(is_encrypted(&blob));
    assert_eq!(decrypt_content(&blob, &key).unwrap(), plaintext);
    // The nonce is random, so the ciphertext must differ from Python's blob...
    assert_ne!(blob, hex::decode(case["blob_hex"].as_str().unwrap()).unwrap());
}

#[test]
fn wrong_reference_key_does_not_decrypt() {
    let v = vectors();
    let case = &v["aes_gcm"][0];
    let blob = hex::decode(case["blob_hex"].as_str().unwrap()).unwrap();
    let other_key = derive_content_key(&seed(), "some-other-artifact");
    assert!(decrypt_content(&blob, &other_key).is_err());
}

#[test]
fn plaintext_vectors_are_not_reported_as_encrypted() {
    let v = vectors();
    for case in v["is_encrypted_false"].as_array().unwrap() {
        assert!(!is_encrypted(case.as_str().unwrap().as_bytes()));
    }
}

#[test]
fn to_dict_of_reference_vectors_matches_recorded_python_to_dict() {
    let v = vectors();
    for case in v["artifacts"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let mut artifact = KnowledgeArtifact::from_dict(&case["input"]).unwrap();
        let expected = &case["to_dict"];
        // Compare every recorded Python field with the Rust field.
        assert_eq!(
            artifact.id,
            expected["id"].as_str().unwrap(),
            "{name}: id mismatch"
        );
        assert_eq!(artifact.signature, "", "{name}: from_dict must not invent a signature");
        artifact.signature = expected["signature"].as_str().unwrap().to_string();
        assert_eq!(
            canonical_json(&artifact.to_dict()),
            canonical_json(expected),
            "{name}: serialized dict diverged from Python's to_dict()"
        );
    }
}

#[test]
fn unicode_payload_uses_python_escaping() {
    let v = vectors();
    let case = v["artifacts"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["name"] == "unicode_and_escaping")
        .expect("unicode vector present");
    let canonical = case["canonical"].as_str().unwrap();
    assert!(canonical.contains(r"\u00e7"), "expected escaped cedilla");
    assert!(canonical.contains(r"\ud83d\ude80"), "expected emoji surrogate pair");
    assert!(canonical.contains(r"\t"), "expected escaped tab");
    assert!(!canonical.contains('ç'), "raw non-ASCII must never appear");
}
