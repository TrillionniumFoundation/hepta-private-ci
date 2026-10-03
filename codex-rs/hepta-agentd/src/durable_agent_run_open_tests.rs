use super::*;
use std::os::fd::AsRawFd;
use std::os::unix::fs::PermissionsExt;

#[test]
fn nofollow_open_rejects_a_symlink_swapped_after_prestat() {
    let directory = tempfile::tempdir().unwrap();
    let victim = directory.path().join("victim");
    let foreign = directory.path().join("foreign");
    fs::write(&victim, b"old").unwrap();
    fs::write(&foreign, b"must remain unchanged").unwrap();
    assert!(reject_non_file(&victim).unwrap());
    fs::remove_file(&victim).unwrap();
    std::os::unix::fs::symlink(&foreign, &victim).unwrap();
    assert!(
        private_options()
            .create(true)
            .truncate(false)
            .open(&victim)
            .is_err()
    );
    assert_eq!(fs::read(&foreign).unwrap(), b"must remain unchanged");
}

#[test]
fn native_opens_retain_nonblocking_flag() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("file");
    let file = private_options().create_new(true).open(path).unwrap();
    // SAFETY: F_GETFL queries a live owned file descriptor and takes no pointer.
    let flags = unsafe { libc::fcntl(file.as_raw_fd(), libc::F_GETFL) };
    assert!(flags >= 0);
    assert_ne!(flags & libc::O_NONBLOCK, 0);
}

#[test]
fn writable_shared_parent_is_not_a_protected_store_root() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("runs.json");
    fs::set_permissions(directory.path(), fs::Permissions::from_mode(0o770)).unwrap();
    assert!(RunFile::open(path.clone()).is_err());
    assert!(!path.exists());
}

#[test]
fn stale_absence_hint_does_not_turn_existing_lock_into_bootstrap_permission() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("runs.lock");
    assert!(!reject_non_file(&path).unwrap());
    let (first, origin) = acquire_lock(&path).unwrap();
    assert_eq!(origin, LockOrigin::Created);
    drop(first);
    // Another owner existed after the earlier absence observation. Opening
    // must use the actual exclusive-create result rather than that stale hint.
    let (_second, origin) = acquire_lock(&path).unwrap();
    assert_eq!(origin, LockOrigin::Existing);
}
