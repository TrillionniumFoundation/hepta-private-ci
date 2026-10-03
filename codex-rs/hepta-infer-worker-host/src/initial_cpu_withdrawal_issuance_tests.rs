//! Retention tests exercise physical original records, not parameter tables.
#![allow(clippy::unwrap_used, clippy::expect_used)]
use super::*;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;

#[test]
fn ordinary_unprotected_parent_cannot_read_or_create_an_issuance() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("withdrawal-issuance.json");
    assert!(read(&path, Digest32::of_bytes(b"request")).is_err());
    assert!(!path.exists());
}
#[test]
#[ignore = "Run exact original native ELF as Root in isolated protected custody"]
fn root_retains_exact_original_signature_without_overwriting_or_rebinding() {
    let parent = PathBuf::from(format!(
        "/var/lib/hepta/native-withdrawal-issuance-tests/{}-{}",
        std::process::id(),
        now_ms().unwrap()
    ));
    std::fs::create_dir_all(&parent).unwrap();
    std::fs::set_permissions(&parent, std::fs::Permissions::from_mode(0o700)).unwrap();
    let path = parent.join("withdrawal-issuance.json");
    let request = Digest32::of_bytes(b"original Root request");
    let digest = Digest32::of_bytes(b"retained original digest").to_string();
    let original: Issuance = serde_json::from_value(serde_json::json!({
        "request_digest":request.to_string(),
        "evidence":{"evidence_id":"same-evidence","principal_id":"dedicated-unlearner","role":"unlearning_authority",
            "trust_digest":digest,"scope_digest":digest,"objective_digest":digest,"authority_epoch":1,
            "issued_at":100,"expires_at":200,"payload_digest":digest,"signature_hex":"07".repeat(64)},
        "source_event":digest,"event":digest,"admitted_at":100,
        "head":{"time":{"profile_digest":digest,"evidence_digest":digest,"issued_at":100,"expires_at":200,"signature_hex":"08".repeat(64)},
            "generation":4,"predecessor":digest,"head":digest},
        "suffix":[{"event_id":"original-revoke","artifact_id":"source","evaluator_id":"dedicated-unlearner","reason_digest":digest}],
        "before":{"binding":digest,"head":digest,"file":digest,"records":3,"bytes":300},
        "delivery_targets":["source","descendant"]
    })).unwrap();
    retain(&path, &original).unwrap();
    let bytes = std::fs::read(&path).unwrap();
    let metadata = std::fs::symlink_metadata(&path).unwrap();
    let reopened = read(&path, request).unwrap().unwrap();
    assert_eq!(serde_json::to_vec(&reopened).unwrap(), bytes);
    assert_eq!(
        reopened.suffix[0].native().unwrap(),
        original.suffix[0].native().unwrap()
    );
    assert!(retain(&path, &original).is_err());
    assert!(read(&path, Digest32::of_bytes(b"another Root request")).is_err());
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
    let after = std::fs::symlink_metadata(&path).unwrap();
    assert_eq!((metadata.dev(), metadata.ino()), (after.dev(), after.ino()));
    let alias = parent.join("alias.json");
    std::fs::hard_link(&path, &alias).unwrap();
    assert!(read(&path, request).is_err());
    std::fs::remove_file(alias).unwrap();
    assert_eq!(
        serde_json::to_vec(&read(&path, request).unwrap().unwrap()).unwrap(),
        bytes
    );
    std::fs::remove_dir_all(parent).unwrap();
}
