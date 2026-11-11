use std::fs;
use std::io::Write;
use std::process::Command;

use codex_utils_path::PrivateFileAccess;
use pretty_assertions::assert_eq;

use super::super::DurableLeaseRegistryV1;
use super::super::LeaseRegistryErrorV1;

#[test]
fn private_owner_pins_new_ancestry_until_persist_and_drop() {
    let temporary = tempfile::tempdir().expect("temporary directory");
    let ancestor = temporary.path().join("owner");
    let root = ancestor.join("leases");
    let path = root.join("lease-registry.json");
    let moved = temporary.path().join("moved");
    let mut registry = DurableLeaseRegistryV1::open(&path).expect("create private nested owner");

    assert!(fs::rename(&root, ancestor.join("redirected")).is_err());
    assert!(fs::rename(&ancestor, &moved).is_err());
    let prepared = registry
        .prepare_issue("op:issue:1".into(), [3; 32])
        .expect("write, replace and flush through the retained owner");
    drop(registry);

    fs::rename(&ancestor, &moved).expect("dropping the registry releases the directory pins");
    let reopened = DurableLeaseRegistryV1::open(moved.join("leases").join("lease-registry.json"))
        .expect("reopen persisted lease operations after owner release");
    assert_eq!(reopened.operation("op:issue:1"), Some(&prepared));
}

#[test]
fn junction_ancestry_is_rejected_before_creating_registry_state() {
    let temporary = tempfile::tempdir().expect("temporary directory");
    let target = temporary.path().join("target");
    let alias = temporary.path().join("alias");
    fs::create_dir(&target).expect("junction target");
    let output = Command::new("cmd.exe")
        .args(["/D", "/C", "mklink", "/J"])
        .arg(&alias)
        .arg(&target)
        .output()
        .expect("create real junction fixture");
    assert!(output.status.success(), "{output:?}");

    assert!(matches!(
        DurableLeaseRegistryV1::open(alias.join("owner").join("lease-registry.json")),
        Err(LeaseRegistryErrorV1::Unavailable)
    ));
    assert!(!target.join("owner").exists());
    fs::remove_dir(&alias).expect("remove junction without traversing its target");
}

#[test]
fn hardlinked_state_rejects_reopen_and_update_without_advancing_history() {
    let temporary = tempfile::tempdir().expect("temporary directory");
    let root = temporary.path().join("owner");
    let path = root.join("lease-registry.json");
    let alias = root.join("state-alias");
    let mut registry = DurableLeaseRegistryV1::open(&path).expect("private registry");
    let prepared = registry
        .prepare_issue("op:issue:1".into(), [3; 32])
        .expect("initial durable operation");
    let persisted = fs::read(&path).expect("initial bytes");
    fs::hard_link(&path, &alias).expect("real NTFS hardlink fixture");

    assert!(matches!(
        DurableLeaseRegistryV1::open(&path),
        Err(LeaseRegistryErrorV1::Unavailable)
    ));
    assert_eq!(
        registry.prepare_issue("op:issue:2".into(), [4; 32]),
        Err(LeaseRegistryErrorV1::Unavailable)
    );
    assert_eq!(registry.operation("op:issue:1"), Some(&prepared));
    assert_eq!(registry.operation("op:issue:2"), None);
    assert_eq!(fs::read(&path).expect("unchanged state"), persisted);
    assert_eq!(fs::read(&alias).expect("unchanged alias"), persisted);
    assert!(!root.join("lease-registry.json.next").exists());
}

#[test]
fn hardlinked_staging_file_is_rejected_before_truncation() {
    let temporary = tempfile::tempdir().expect("temporary directory");
    let root = temporary.path().join("owner");
    let path = root.join("lease-registry.json");
    let staging_path = root.join("lease-registry.json.next");
    let alias = root.join("staging-alias");
    let mut registry = DurableLeaseRegistryV1::open(&path).expect("private registry");
    let prepared = registry
        .prepare_issue("op:issue:1".into(), [3; 32])
        .expect("initial durable operation");
    let persisted = fs::read(&path).expect("initial bytes");
    let staging_bytes = b"existing uncommitted snapshot";
    let directory = codex_utils_path::open_private_state_directory(&root).expect("retained owner");
    let mut staging = codex_utils_path::open_private_state_child(
        &directory,
        "lease-registry.json.next",
        PrivateFileAccess::Create,
    )
    .expect("private staging fixture");
    staging.write_all(staging_bytes).expect("staging bytes");
    staging.sync_all().expect("durable staging fixture");
    drop(staging);
    fs::hard_link(&staging_path, &alias).expect("real NTFS staging alias");

    assert_eq!(
        registry.prepare_issue("op:issue:2".into(), [4; 32]),
        Err(LeaseRegistryErrorV1::Unavailable)
    );
    assert_eq!(registry.operation("op:issue:1"), Some(&prepared));
    assert_eq!(registry.operation("op:issue:2"), None);
    assert_eq!(fs::read(&path).expect("unchanged state"), persisted);
    assert_eq!(
        fs::read(&staging_path).expect("untruncated staging"),
        staging_bytes
    );
    assert_eq!(fs::read(&alias).expect("untruncated alias"), staging_bytes);
}
