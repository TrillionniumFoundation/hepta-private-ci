use std::fs;
use std::os::unix::fs::PermissionsExt;

use super::run_start_owner_fixture;

fn write_private_json(path: &std::path::Path, value: serde_json::Value) {
    fs::write(path, serde_json::to_vec(&value).expect("owner json")).expect("owner file");
    fs::set_permissions(path, fs::Permissions::from_mode(0o600)).expect("private owner file");
}

#[test]
fn authbus_owner_trust_rejects_unsafe_ancestor_and_accepts_trusted_sticky() {
    let (temp, identity) = run_start_owner_fixture();
    let path = identity.home_root.join("text-trust.json");
    let key = ed25519_dalek::SigningKey::from_bytes(&[19; 32]);
    let public_key_hex = key
        .verifying_key()
        .as_bytes()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    write_private_json(
        &path,
        serde_json::json!({
            "schema_version": 1, "agent_id": identity.agent_id.as_str(),
            "issuer_id": "issuer.owner", "key_epoch": 1,
            "public_key_hex": public_key_hex, "revoked": false,
            "thread_ids": ["thread.owner"]
        }),
    );
    assert!(crate::authbus_trust::TextTrust::load(&path, &identity).is_ok());
    fs::set_permissions(temp.path(), fs::Permissions::from_mode(0o777)).expect("unsafe ancestor");
    assert!(crate::authbus_trust::TextTrust::load(&path, &identity).is_err());
    fs::set_permissions(temp.path(), fs::Permissions::from_mode(0o1777)).expect("sticky ancestor");
    assert!(crate::authbus_trust::TextTrust::load(&path, &identity).is_ok());
}

#[test]
fn evidence_owner_trust_rejects_unsafe_ancestor_and_accepts_trusted_sticky() {
    let (temp, identity) = run_start_owner_fixture();
    let path = identity.home_root.join("evidence-trust.json");
    let key = ed25519_dalek::SigningKey::from_bytes(&[23; 32]);
    let public_key_hex = key
        .verifying_key()
        .as_bytes()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    write_private_json(
        &path,
        serde_json::json!({
            "schema_version": 1, "agent_id": identity.agent_id.as_str(),
            "issuers": [{"issuer_id": "issuer.owner", "key_epoch": 1,
                "public_key_hex": public_key_hex, "revoked": false, "roles": ["security"]}]
        }),
    );
    assert!(crate::evidence_trust::EvidenceTrust::load(&path, &identity).is_ok());
    fs::set_permissions(temp.path(), fs::Permissions::from_mode(0o777)).expect("unsafe ancestor");
    assert!(crate::evidence_trust::EvidenceTrust::load(&path, &identity).is_err());
    fs::set_permissions(temp.path(), fs::Permissions::from_mode(0o1777)).expect("sticky ancestor");
    assert!(crate::evidence_trust::EvidenceTrust::load(&path, &identity).is_ok());
}

#[test]
fn objective_journal_rejects_unsafe_ancestor_without_creating_a_file() {
    let (temp, identity) = run_start_owner_fixture();
    let path = identity
        .home_root
        .join(super::super::RUN_START_DIRECTORY)
        .join(super::super::RUN_START_FILE);
    fs::set_permissions(temp.path(), fs::Permissions::from_mode(0o777)).expect("unsafe ancestor");
    assert!(super::super::open_run_start_journal(&identity, super::digest("profile")).is_err());
    assert!(!path.exists());
    fs::set_permissions(temp.path(), fs::Permissions::from_mode(0o1777)).expect("sticky ancestor");
    let journal = super::super::open_run_start_journal(&identity, super::digest("profile"))
        .expect("trusted sticky namespace");
    let expected_head = journal.head_digest();
    drop(journal);
    assert_eq!(
        super::super::open_run_start_journal(&identity, super::digest("profile"))
            .expect("recover private journal")
            .head_digest(),
        expected_head
    );
}
