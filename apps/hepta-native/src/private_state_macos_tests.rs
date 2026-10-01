use super::PrivateStateRoot;
use crate::private_state_test_support::add_macos_acl;
use crate::private_state_test_support::macos_acl;
use crate::private_state_test_support::private_tempdir;
use std::os::unix::fs::PermissionsExt as _;

#[test]
fn mode_private_root_with_named_acl_is_rejected_without_changing_acl() {
    let directory = private_tempdir();
    assert_eq!(
        directory.path().metadata().unwrap().permissions().mode() & 0o777,
        0o700
    );
    let acl = add_macos_acl(directory.path(), "list,search");
    assert!(PrivateStateRoot::open_existing(directory.path()).is_err());
    assert!(PrivateStateRoot::open(directory.path()).is_err());
    assert_eq!(macos_acl(directory.path()), acl);
}

#[test]
fn held_root_rejects_acl_drift_before_creating_an_inheriting_child() {
    let directory = private_tempdir();
    let root = PrivateStateRoot::open_existing(directory.path()).unwrap();
    let acl = add_macos_acl(
        directory.path(),
        "list,search,file_inherit,directory_inherit",
    );
    assert_eq!(
        directory.path().metadata().unwrap().permissions().mode() & 0o777,
        0o700
    );
    assert!(root.verify().is_err());
    assert!(root.child_create("staged").is_err());
    assert!(!directory.path().join("staged").exists());
    assert_eq!(macos_acl(directory.path()), acl);
}

#[test]
fn owned_child_acl_is_rejected_before_permission_migration() {
    for mode in [0o700, 0o755] {
        let directory = private_tempdir();
        let root = PrivateStateRoot::open_existing(directory.path()).unwrap();
        let child = root.child_create("staged").unwrap();
        std::fs::write(child.path().join("operator-file"), b"preserved").unwrap();
        std::fs::set_permissions(child.path(), std::fs::Permissions::from_mode(mode)).unwrap();
        let acl = add_macos_acl(child.path(), "list,search");
        assert!(root.child_open("staged").is_err());
        assert!(root.child_create("staged").is_err());
        assert_eq!(
            child.path().metadata().unwrap().permissions().mode() & 0o777,
            mode
        );
        assert_eq!(
            std::fs::read(child.path().join("operator-file")).unwrap(),
            b"preserved"
        );
        assert_eq!(macos_acl(child.path()), acl);
    }
}
