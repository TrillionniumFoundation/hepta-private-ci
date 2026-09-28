use std::fs::Permissions;
use std::os::unix::fs::PermissionsExt;

use super::*;

fn private_home() -> tempfile::TempDir {
    let home = tempfile::TempDir::new().expect("home");
    std::fs::set_permissions(home.path(), Permissions::from_mode(0o700)).expect("private home");
    home
}

#[test]
fn separate_opens_cannot_share_a_publisher_even_with_the_same_logical_owner() {
    let home = private_home();
    let first = PublicationProcessGuard::acquire(home.path()).expect("first publisher");
    let error = PublicationProcessGuard::acquire(home.path())
        .err()
        .expect("competing publisher must fail");
    assert_eq!(error.kind(), io::ErrorKind::WouldBlock);
    first.validate().expect("owner remains valid");
    drop(first);
    PublicationProcessGuard::acquire(home.path()).expect("successor after release");
}

#[test]
fn replacement_and_symlink_homes_do_not_preserve_the_fence() {
    let parent = private_home();
    let home = parent.path().join("home");
    std::fs::create_dir(&home).expect("home directory");
    std::fs::set_permissions(&home, Permissions::from_mode(0o700)).expect("private home");
    let guard = PublicationProcessGuard::acquire(&home).expect("publisher");
    let moved = parent.path().join("moved");
    std::fs::rename(&home, &moved).expect("replace home");
    std::os::unix::fs::symlink(&moved, &home).expect("symlink replacement");
    assert!(guard.validate().is_err());
    assert!(PublicationProcessGuard::acquire(&home).is_err());
}

#[test]
fn private_mode_is_rechecked_while_owned() {
    let home = private_home();
    let guard = PublicationProcessGuard::acquire(home.path()).expect("publisher");
    std::fs::set_permissions(home.path(), Permissions::from_mode(0o755)).expect("mode drift");
    assert!(guard.validate().is_err());
    assert!(PublicationProcessGuard::acquire(home.path()).is_err());
}
