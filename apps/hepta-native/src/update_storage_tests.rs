use super::*;
use crate::model::sha256_hex;

#[test]
fn source_replacement_after_digest_check_cannot_replace_destination() {
    let root = tempfile::tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("installed");
    std::fs::write(&source, b"admitted predecessor").unwrap();
    std::fs::write(&destination, b"installed candidate").unwrap();
    let admitted = digest_file(&source).unwrap();
    std::fs::write(&source, b"substituted backup").unwrap();

    let error = copy_and_sync(&source, &destination, &admitted).unwrap_err();
    assert!(error.to_string().contains("before atomic replacement"));
    assert_eq!(std::fs::read(&destination).unwrap(), b"installed candidate");
}

#[test]
fn failed_copy_does_not_publish_a_new_backup() {
    let root = tempfile::tempdir().unwrap();
    let source = root.path().join("source");
    let backup = root.path().join("backup");
    std::fs::write(&source, b"substituted predecessor").unwrap();
    assert!(copy_and_sync(&source, &backup, &sha256_hex(b"admitted predecessor")).is_err());
    assert!(!backup.exists());
}

#[test]
fn verified_copy_preserves_installed_executable_mode() {
    let root = tempfile::tempdir().unwrap();
    let source = root.path().join("source");
    let destination = root.path().join("installed");
    std::fs::write(&source, b"admitted candidate").unwrap();
    std::fs::write(&destination, b"predecessor").unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt as _;
        std::fs::set_permissions(&destination, std::fs::Permissions::from_mode(0o751)).unwrap();
    }
    copy_and_sync(&source, &destination, &sha256_hex(b"admitted candidate")).unwrap();
    assert_eq!(std::fs::read(&destination).unwrap(), b"admitted candidate");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt as _;
        assert_eq!(
            std::fs::metadata(&destination)
                .unwrap()
                .permissions()
                .mode()
                & 0o777,
            0o751
        );
    }
}

#[cfg(unix)]
#[test]
fn owner_locks_reject_links_and_special_files_without_mutating_targets() {
    let root = tempfile::tempdir().unwrap();
    let target = root.path().join("operator-data");
    std::fs::write(&target, b"preserve").unwrap();
    let owner = root.path().join("update-owner.lock");
    std::os::unix::fs::symlink(&target, &owner).unwrap();
    assert!(lock_update_root(root.path()).is_err());
    assert_eq!(std::fs::read(&target).unwrap(), b"preserve");
    std::fs::remove_file(&owner).unwrap();
    let absent = root.path().join("absent");
    std::os::unix::fs::symlink(&absent, &owner).unwrap();
    assert!(lock_update_root(root.path()).is_err());
    assert!(!absent.exists());
    std::fs::remove_file(&owner).unwrap();
    rustix::fs::mkfifoat(
        rustix::fs::CWD,
        &owner,
        rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR,
    )
    .unwrap();
    assert!(lock_update_root(root.path()).is_err());
}

#[test]
fn handoff_lock_waits_for_readiness_publication_to_release_ownership() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("locks");
    let _private = PrivateStateRoot::open(path.clone()).unwrap();
    let owner = lock_update_root(&path).unwrap();
    let (started, waiting) = std::sync::mpsc::sync_channel(1);
    let waiter = std::thread::spawn(move || {
        started.send(()).unwrap();
        lock_update_handoff(&path)
    });
    waiting.recv().unwrap();
    std::thread::sleep(std::time::Duration::from_millis(20));
    drop(owner);
    let acquired = waiter.join().unwrap().unwrap();
    drop(acquired);
}
