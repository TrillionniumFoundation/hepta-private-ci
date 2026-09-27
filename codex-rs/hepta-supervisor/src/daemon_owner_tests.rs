use std::os::unix::fs::PermissionsExt;

use pretty_assertions::assert_eq;

use super::SingleInstanceLock;

#[test]
fn contender_does_not_rewrite_or_chmod_live_owner_file() {
    let temp = tempfile::tempdir().expect("temporary directory");
    let path = temp.path().join("owner.lock");
    let owner = SingleInstanceLock::acquire(&path).expect("first owner");
    std::fs::write(&path, b"existing owner receipt").expect("record observation");
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o640)).expect("set mode");
    let before = std::fs::read(&path).expect("read owner receipt");
    let mode = std::fs::metadata(&path)
        .expect("metadata")
        .permissions()
        .mode();
    assert!(SingleInstanceLock::acquire(&path).is_err());
    assert_eq!(std::fs::read(&path).expect("read unchanged receipt"), before);
    assert_eq!(
        std::fs::metadata(&path)
            .expect("metadata")
            .permissions()
            .mode(),
        mode
    );
    drop(owner);
    SingleInstanceLock::acquire(&path).expect("successor after owner release");
}

#[test]
fn symlink_and_hardlink_targets_are_never_truncated() {
    let temp = tempfile::tempdir().expect("temporary directory");
    let target = temp.path().join("unrelated");
    std::fs::write(&target, b"must survive").expect("write target");
    std::fs::set_permissions(&target, std::fs::Permissions::from_mode(0o640)).expect("mode");
    let before = std::fs::read(&target).expect("read target");
    let mode = std::fs::metadata(&target)
        .expect("metadata")
        .permissions()
        .mode();
    let symlink = temp.path().join("symlink.lock");
    let hardlink = temp.path().join("hardlink.lock");
    std::os::unix::fs::symlink(&target, &symlink).expect("symlink");
    std::fs::hard_link(&target, &hardlink).expect("hardlink");
    for path in [&symlink, &hardlink] {
        assert!(SingleInstanceLock::acquire(path).is_err());
        assert_eq!(std::fs::read(&target).expect("unchanged target"), before);
        assert_eq!(
            std::fs::metadata(&target)
                .expect("metadata")
                .permissions()
                .mode(),
            mode
        );
    }
}

#[test]
fn owner_release_keeps_the_same_lock_inode() {
    use std::os::unix::fs::MetadataExt;
    let temp = tempfile::tempdir().expect("temporary directory");
    let path = temp.path().join("owner.lock");
    let first = SingleInstanceLock::acquire(&path).expect("first owner");
    let before = std::fs::metadata(&path).expect("metadata");
    drop(first);
    let successor = SingleInstanceLock::acquire(&path).expect("successor");
    let after = std::fs::metadata(&path).expect("metadata");
    assert_eq!((before.dev(), before.ino()), (after.dev(), after.ino()));
    assert_eq!(after.permissions().mode() & 0o777, 0o600);
    drop(successor);
}

#[test]
fn directory_is_not_a_lock_and_is_not_chmodded() {
    let temp = tempfile::tempdir().expect("temporary directory");
    let mode = std::fs::metadata(temp.path())
        .expect("metadata")
        .permissions()
        .mode();
    assert!(SingleInstanceLock::acquire(temp.path()).is_err());
    assert_eq!(
        std::fs::metadata(temp.path())
            .expect("metadata")
            .permissions()
            .mode(),
        mode
    );
}
