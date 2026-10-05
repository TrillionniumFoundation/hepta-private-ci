use super::PrivateStateRoot;
use crate::private_state_test_support::private_tempdir;

#[test]
fn private_children_require_one_normal_component_and_existing_state() {
    let directory = private_tempdir();
    let root = PrivateStateRoot::open_existing(directory.path()).unwrap();
    for name in [
        "",
        ".",
        "..",
        "../staged",
        "one/two",
        "one\\two",
        "bad\0name",
    ] {
        assert!(root.child_create(name).is_err());
        assert!(root.child_open(name).is_err());
    }
    assert!(root.child_open("missing").is_err());
    let child = root.child_create("staged").unwrap();
    assert_eq!(child.path(), directory.path().join("staged"));
    root.child_open("staged").unwrap().verify().unwrap();
}

#[cfg(unix)]
#[test]
fn child_create_tightens_owned_legacy_permissions_without_following_links() {
    use std::os::unix::fs::PermissionsExt as _;

    let directory = private_tempdir();
    let root = PrivateStateRoot::open_existing(directory.path()).unwrap();
    let legacy = directory.path().join("staged");
    std::fs::create_dir(&legacy).unwrap();
    std::fs::set_permissions(&legacy, std::fs::Permissions::from_mode(0o755)).unwrap();
    std::fs::write(legacy.join("operator-file"), b"preserved").unwrap();
    assert!(root.child_open("staged").is_err());
    let child = root.child_create("staged").unwrap();
    assert_eq!(
        std::fs::metadata(child.path())
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o700
    );
    assert_eq!(
        std::fs::read(legacy.join("operator-file")).unwrap(),
        b"preserved"
    );

    let target = directory.path().join("external");
    std::fs::create_dir(&target).unwrap();
    std::fs::set_permissions(&target, std::fs::Permissions::from_mode(0o755)).unwrap();
    std::os::unix::fs::symlink(&target, directory.path().join("redirected")).unwrap();
    assert!(root.child_create("redirected").is_err());
    assert_eq!(
        std::fs::metadata(&target).unwrap().permissions().mode() & 0o777,
        0o755
    );
}

#[cfg(unix)]
#[test]
fn child_capability_rejects_parent_or_child_replacement() {
    let directory = private_tempdir();
    let path = directory.path().join("state");
    let root = PrivateStateRoot::open(&path).unwrap();
    let child = root.child_create("staged").unwrap();
    std::fs::rename(child.path(), path.join("original-staged")).unwrap();
    root.child_create("staged").unwrap();
    assert!(child.verify().is_err());

    std::fs::rename(&path, directory.path().join("original-state")).unwrap();
    PrivateStateRoot::open(&path).unwrap();
    assert!(root.child_create("new-child").is_err());
    assert!(!path.join("new-child").exists());
    assert!(!directory.path().join("original-state/new-child").exists());
}
