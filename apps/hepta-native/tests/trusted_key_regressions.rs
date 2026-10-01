use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;
use hepta_native::security::TrustedKeySet;
use tempfile::TempDir;

fn write_keys(root: &TempDir, keys: serde_json::Value) -> std::path::PathBuf {
    let path = root.path().join("trusted-keys.json");
    std::fs::write(&path, serde_json::to_vec(&keys).unwrap()).unwrap();
    path
}

#[test]
fn weak_identity_key_is_rejected_at_import() {
    let root = TempDir::new().unwrap();
    let mut identity = [0_u8; 32];
    identity[0] = 1;
    let path = write_keys(
        &root,
        serde_json::json!({
            "schema": "hepta.native-trusted-keys.v1",
            "keys": {"weak.key": STANDARD.encode(identity)}
        }),
    );
    assert!(TrustedKeySet::from_path(&path).is_err());
}

#[test]
fn revoked_key_cannot_be_reintroduced_under_an_alias() {
    let root = TempDir::new().unwrap();
    let key = SigningKey::from_bytes(&[23_u8; 32]);
    let encoded = STANDARD.encode(key.verifying_key().to_bytes());
    let path = write_keys(
        &root,
        serde_json::json!({
            "schema": "hepta.native-trusted-keys.v1",
            "keys": {"revoked.key": encoded, "alias.key": encoded},
            "revoked_key_ids": ["revoked.key"]
        }),
    );
    assert!(TrustedKeySet::from_path(&path).is_err());
}

#[test]
fn duplicate_json_key_identity_is_not_last_writer_wins() {
    let root = TempDir::new().unwrap();
    let key = SigningKey::from_bytes(&[24_u8; 32]);
    let encoded = STANDARD.encode(key.verifying_key().to_bytes());
    let path = root.path().join("duplicate.json");
    std::fs::write(
        &path,
        format!(
            r#"{{"schema":"hepta.native-trusted-keys.v1","keys":{{"same.key":"{encoded}","same.key":"{encoded}"}}}}"#
        ),
    )
    .unwrap();
    assert!(TrustedKeySet::from_path(&path).is_err());
}

#[test]
fn strict_verification_accepts_valid_signatures_and_rejects_tampering() {
    let root = TempDir::new().unwrap();
    let key = SigningKey::from_bytes(&[25_u8; 32]);
    let path = write_keys(
        &root,
        serde_json::json!({
            "schema": "hepta.native-trusted-keys.v1",
            "keys": {"release.key": STANDARD.encode(key.verifying_key().to_bytes())}
        }),
    );
    let keys = TrustedKeySet::from_path(&path).unwrap();
    let signature = STANDARD.encode(key.sign(b"bound payload").to_bytes());
    assert!(
        keys.verify_message("release.key", &signature, b"bound payload")
            .is_ok()
    );
    assert!(
        keys.verify_message("release.key", &signature, b"changed payload")
            .is_err()
    );
}

#[test]
fn revoked_key_is_refused_even_with_a_valid_signature() {
    let root = TempDir::new().unwrap();
    let key = SigningKey::from_bytes(&[26_u8; 32]);
    let path = write_keys(
        &root,
        serde_json::json!({
            "schema": "hepta.native-trusted-keys.v1",
            "keys": {"release.key": STANDARD.encode(key.verifying_key().to_bytes())},
            "revoked_key_ids": ["release.key"]
        }),
    );
    let keys = TrustedKeySet::from_path(&path).unwrap();
    let signature = STANDARD.encode(key.sign(b"bound payload").to_bytes());
    assert!(
        keys.verify_message("release.key", &signature, b"bound payload")
            .is_err()
    );
}
