#![cfg(target_os = "linux")]
use super::*;
use pretty_assertions::assert_eq;
use serde_json::json;
use std::os::unix::fs::{PermissionsExt, symlink};
fn scope() -> RecoveryScope {
    RecoveryScope {
        endpoint: "https://console.test/api/ui-control/v1/".into(),
        protocol_version: "hepta.ui-control.v1".into(),
        identity_id: "operator.1".into(),
    }
}
fn private_root() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    std::fs::set_permissions(dir.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    dir
}
fn record(id: &str) -> Value {
    let intent = crate::contract::OperationIntent {
        action: crate::contract::Action::RequestStop,
        target_id: "runtime.agentd".into(),
        generation: 1,
        displayed_revision: 1,
        reason: "Qualification".into(),
    };
    json!({"protocolVersion":"hepta.ui-control.v1","method":"runtime/stop",
        "operationId":id,"semanticDigest":crate::contract::digest_operation_intent(&intent).unwrap(),
        "action":"request_stop","targetId":"runtime.agentd","reason":"Qualification",
        "sessionId":"session.1","connectionGeneration":1,"generation":1,"displayedRevision":1,
        "snapshotDigest":"a".repeat(64),"state":"submitting","auditTraceId":null,"createdAt":1,"updatedAt":1})
}

#[test]
fn restart_retains_exact_identity_and_never_readmits() {
    let root = private_root();
    let mut store = FileRecoveryStore::open(root.path(), scope(), 1024).unwrap();
    assert_eq!(
        store.prepare("op.1", &record("op.1")).unwrap(),
        Preparation::New
    );
    drop(store);
    let mut store = FileRecoveryStore::open(root.path(), scope(), 1024).unwrap();
    assert_eq!(
        store.prepare("op.1", &record("op.1")).unwrap(),
        Preparation::ExistingNeedsRecovery
    );
    assert_eq!(
        store.load().unwrap(),
        BTreeMap::from([("op.1".into(), record("op.1"))])
    );
    store.complete("op.1", &record("op.1")).unwrap();
    assert!(store.load().unwrap().is_empty());
}
#[test]
fn scope_conflict_and_payload_drift_preserve_original() {
    let root = private_root();
    let mut store = FileRecoveryStore::open(root.path(), scope(), 2).unwrap();
    store.prepare("op.1", &record("op.1")).unwrap();
    let mut foreign = scope();
    foreign.identity_id = "operator.2".into();
    assert!(FileRecoveryStore::open(root.path(), foreign, 2).is_err());
    let mut changed = record("op.1");
    changed["state"] = json!("changed");
    assert!(store.prepare("op.1", &changed).is_err());
    assert!(store.complete("op.1", &changed).is_err());
    assert_eq!(store.load().unwrap().len(), 1);
}
#[test]
fn corruption_crash_temporary_and_oversize_fail_closed() {
    let root = private_root();
    let mut store = FileRecoveryStore::open(root.path(), scope(), 2).unwrap();
    let mut large = record("op.1");
    large["payload"] = json!("a".repeat(MAX_RECORD_BYTES));
    assert!(store.prepare("op.1", &large).is_err());
    store.prepare("op.1", &record("op.1")).unwrap();
    std::fs::write(root.path().join("state.pending"), b"uncertain").unwrap();
    assert!(store.load().is_err());
    std::fs::remove_file(root.path().join("state.pending")).unwrap();
    std::fs::write(root.path().join("state.json"), b"{}").unwrap();
    assert!(store.load().is_err());
}
#[test]
fn symlink_nonprivate_hardlink_and_replaced_root_are_rejected() {
    let root = private_root();
    let holder = private_root();
    let link = holder.path().join("redirect");
    symlink(root.path(), &link).unwrap();
    assert!(FileRecoveryStore::open(&link, scope(), 2).is_err());
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o755)).unwrap();
    assert!(FileRecoveryStore::open(root.path(), scope(), 2).is_err());
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let mut store = FileRecoveryStore::open(root.path(), scope(), 2).unwrap();
    store.prepare("op.1", &record("op.1")).unwrap();
    std::fs::hard_link(root.path().join("state.json"), holder.path().join("copy")).unwrap();
    assert!(store.load().is_err());
}
#[test]
fn capacity_is_shared_across_independent_handles() {
    let root = private_root();
    let mut first = FileRecoveryStore::open(root.path(), scope(), 1).unwrap();
    let mut second = FileRecoveryStore::open(root.path(), scope(), 1).unwrap();
    first.prepare("op.1", &record("op.1")).unwrap();
    assert_eq!(
        second.prepare("op.2", &record("op.2")).unwrap_err().code,
        ErrorCode::PendingLimit
    );
    assert_eq!(second.load().unwrap().len(), 1);
}
#[test]
fn live_process_lock_conflict_fails_without_releasing_owner() {
    let root = private_root();
    let mut first = FileRecoveryStore::open(root.path(), scope(), 1).unwrap();
    let lock = first.locked().unwrap();
    assert!(FileRecoveryStore::open(root.path(), scope(), 1).is_err());
    assert!(FileRecoveryStore::open(root.path(), scope(), 1).is_err());
    drop(lock);
    assert!(first.load().is_ok());
}

#[test]
fn replaced_lock_inode_fails_before_any_new_publication() {
    let root = private_root();
    let store = FileRecoveryStore::open(root.path(), scope(), 2).unwrap();
    let lock = store.locked().unwrap();
    std::fs::rename(
        root.path().join(".owner-lock"),
        root.path().join(".retired-lock"),
    )
    .unwrap();
    std::fs::write(root.path().join(".owner-lock"), b"").unwrap();
    std::fs::set_permissions(
        root.path().join(".owner-lock"),
        std::fs::Permissions::from_mode(0o600),
    )
    .unwrap();
    assert!(lock.verify().is_err());
    assert!(!root.path().join("state.json").exists());
}
#[test]
fn completing_one_operation_preserves_every_sibling() {
    let root = private_root();
    let mut store = FileRecoveryStore::open(root.path(), scope(), 3).unwrap();
    for id in ["op.1", "op.2", "op.3"] {
        store.prepare(id, &record(id)).unwrap();
    }
    store.complete("op.2", &record("op.2")).unwrap();
    assert_eq!(
        store.load().unwrap(),
        BTreeMap::from([
            ("op.1".into(), record("op.1")),
            ("op.3".into(), record("op.3"))
        ])
    );
}
#[test]
fn retained_pending_descriptor_must_match_its_publication_name() {
    let root = private_root();
    let store = FileRecoveryStore::open(root.path(), scope(), 2).unwrap();
    let held = unix::open_file(&store.directory, "state.pending", true).unwrap();
    std::fs::rename(
        root.path().join("state.pending"),
        root.path().join("foreign"),
    )
    .unwrap();
    let replacement = unix::open_file(&store.directory, "state.pending", true).unwrap();
    assert!(unix::verify_named_file(&store.directory, "state.pending", &held).is_err());
    assert!(unix::verify_named_file(&store.directory, "state.pending", &replacement).is_ok());
}
#[test]
fn root_replacement_cannot_redirect_an_existing_store() {
    let holder = private_root();
    let original = holder.path().join("state");
    std::fs::create_dir(&original).unwrap();
    std::fs::set_permissions(&original, std::fs::Permissions::from_mode(0o700)).unwrap();
    let mut store = FileRecoveryStore::open(&original, scope(), 2).unwrap();
    store.prepare("op.1", &record("op.1")).unwrap();
    let retained = holder.path().join("retained");
    std::fs::rename(&original, &retained).unwrap();
    std::fs::create_dir(&original).unwrap();
    std::fs::set_permissions(&original, std::fs::Permissions::from_mode(0o700)).unwrap();
    assert!(store.prepare("op.2", &record("op.2")).is_err());
    assert!(!original.join("state.json").exists());
    assert!(retained.join("state.json").exists());
}

#[test]
fn direct_storage_boundary_rejects_unknown_fields_and_invalid_admission_semantics() {
    let root = private_root();
    let mut store = FileRecoveryStore::open(root.path(), scope(), 2).unwrap();
    let mut unknown = record("op.1");
    unknown["credential"] = json!("untrusted secret material");
    assert!(store.prepare("op.1", &unknown).is_err());
    for (field, value) in [
        ("auditTraceId", json!(true)),
        ("state", json!("terminal")),
        ("semanticDigest", json!("c".repeat(64))),
        ("createdAt", json!(0)),
    ] {
        let mut invalid = record("op.1");
        invalid[field] = value;
        assert!(store.prepare("op.1", &invalid).is_err());
    }
    assert!(store.load().unwrap().is_empty());
}
