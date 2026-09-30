use std::fs;
use std::os::unix::fs::PermissionsExt;

use super::*;
use crate::objective_runtime::tests::run_start_owner_fixture;

const LIMIT: u64 = 4096;
const LABEL: &str = "independently pinned bootstrap file";

#[test]
fn unsafe_ancestor_rejects_descriptor_reads_rw_open_and_new_registry_creation() {
    let (temp, identity) = run_start_owner_fixture();
    let path = identity.home_root.join("bootstrap.json");
    fs::write(&path, b"pinned bytes").expect("installed bootstrap bytes");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).expect("private bootstrap file");
    assert_eq!(
        read_bounded(&path, LIMIT, LABEL).expect("bounded read"),
        b"pinned bytes"
    );
    drop(open_existing_rw(&path, LABEL).expect("existing owner file"));
    let registry = identity.home_root.join("new-registry");
    fs::set_permissions(temp.path(), fs::Permissions::from_mode(0o777)).expect("unsafe ancestor");
    assert!(read_bounded(&path, LIMIT, LABEL).is_err());
    assert!(open_existing_rw(&path, LABEL).is_err());
    assert!(create_new_rw(&registry, LABEL).is_err());
    assert!(!registry.exists());
    fs::set_permissions(temp.path(), fs::Permissions::from_mode(0o1777)).expect("sticky ancestor");
    assert_eq!(
        read_bounded(&path, LIMIT, LABEL).expect("trusted sticky read"),
        b"pinned bytes"
    );
    drop(open_existing_rw(&path, LABEL).expect("trusted sticky reopen"));
    drop(create_new_rw(&registry, LABEL).expect("trusted sticky new registry"));
    assert_eq!(
        fs::metadata(registry)
            .expect("registry metadata")
            .permissions()
            .mode()
            & 0o777,
        0o600
    );
}

#[test]
fn unsafe_immediate_parent_rejects_descriptor_read_and_existing_journal_open() {
    let (_temp, identity) = run_start_owner_fixture();
    let path = identity.home_root.join("journal");
    fs::write(&path, b"retained owner bytes").expect("existing journal");
    fs::set_permissions(&identity.home_root, fs::Permissions::from_mode(0o777))
        .expect("unsafe parent");
    assert!(read_bounded(&path, LIMIT, LABEL).is_err());
    assert!(open_existing_rw(&path, LABEL).is_err());
    assert_eq!(
        fs::read(path).expect("untouched journal"),
        b"retained owner bytes"
    );
}

#[test]
fn native_snapshot_callback_cannot_accept_same_length_path_substitution() {
    let (_temp, identity) = run_start_owner_fixture();
    let path = identity.home_root.join("snapshot");
    let replacement = identity.home_root.join("replacement");
    fs::write(&path, b"trusted").expect("existing snapshot");
    fs::write(&replacement, b"revoked").expect("substitute snapshot");
    let result = read_existing(&path, LABEL, |mut file| {
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes)?;
        fs::rename(&replacement, &path)?;
        Ok(bytes)
    });
    assert!(result.is_err());
}

#[test]
fn native_snapshot_callback_rechecks_namespace_before_returning_bytes() {
    let (temp, identity) = run_start_owner_fixture();
    let path = identity.home_root.join("snapshot");
    fs::write(&path, b"trusted").expect("existing snapshot");
    let result = read_existing(&path, LABEL, |mut file| {
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes)?;
        fs::set_permissions(temp.path(), fs::Permissions::from_mode(0o777))?;
        Ok(bytes)
    });
    assert!(result.is_err());
}
