use std::fs;
use std::os::unix::fs::PermissionsExt;

use super::*;
use crate::objective_runtime::tests::run_start_owner_fixture;

const TEST_MAXIMUM: u64 = 4096;

#[test]
fn external_frontier_rejects_writable_parent_and_unsafe_ancestor() {
    let (temp, identity) = run_start_owner_fixture();
    let root = temp.path().canonicalize().expect("canonical owner root");
    let parent = root.join("independent-frontier");
    fs::create_dir(&parent).expect("external parent");
    fs::set_permissions(&parent, fs::Permissions::from_mode(0o700)).expect("private parent");
    let path = parent.join("frontier.json");
    let bytes = b"independently provisioned external frontier";
    fs::write(&path, bytes).expect("external frontier");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).expect("not writable by others");
    assert_eq!(
        read_external_file(&path, &identity, TEST_MAXIMUM).expect("external bytes"),
        bytes
    );
    fs::set_permissions(&parent, fs::Permissions::from_mode(0o777)).expect("unsafe parent");
    assert!(read_external_file(&path, &identity, TEST_MAXIMUM).is_err());
    fs::set_permissions(&parent, fs::Permissions::from_mode(0o700)).expect("restore parent");
    fs::set_permissions(&root, fs::Permissions::from_mode(0o777)).expect("unsafe ancestor");
    assert!(read_external_file(&path, &identity, TEST_MAXIMUM).is_err());
    fs::set_permissions(&root, fs::Permissions::from_mode(0o1777))
        .expect("trusted sticky ancestor");
    assert_eq!(
        read_external_file(&path, &identity, TEST_MAXIMUM).expect("external bytes"),
        bytes
    );
}
