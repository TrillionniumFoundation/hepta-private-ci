//! Existing protected-record reads with real temporary files and fsync.
use super::*;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;

fn directory(path: &Path) -> Arc<RootAuthorityDirectory> {
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700)).unwrap();
    let directory = open_directory(None, path).unwrap();
    let owner_uid = rustix::process::geteuid().as_raw();
    check_directory(&directory, owner_uid, DirectoryAccess::Private).unwrap();
    Arc::new(RootAuthorityDirectory {
        directory,
        owner_uid,
        before_directory_sync: std::sync::Mutex::new(None),
    })
}

#[test]
fn original_observation_open_preserves_the_saved_inode_and_complete_payload() {
    let temp = tempfile::tempdir().unwrap();
    let root = directory(temp.path());
    let saved = root
        .save_observation("boot-cut.1", b"original complete bytes")
        .unwrap();
    let name = observation_name(saved.observation_id()).unwrap();
    let original = std::fs::metadata(temp.path().join(&name)).unwrap();
    drop(saved);
    drop(root);
    let reopened = directory(temp.path())
        .open_observation("boot-cut.1")
        .unwrap();
    let current = std::fs::metadata(temp.path().join(name)).unwrap();
    assert_eq!(
        (original.dev(), original.ino()),
        (current.dev(), current.ino())
    );
    assert_eq!(reopened.payload(), b"original complete bytes");
    assert_eq!(reopened.verify_durable(), Ok(()));
}

#[test]
fn original_observation_open_never_creates_repairs_or_acknowledges_failed_sync() {
    let temp = tempfile::tempdir().unwrap();
    let root = directory(temp.path());
    let missing = observation_name("missing").unwrap();
    assert!(root.open_observation("missing").is_err());
    assert!(!temp.path().join(missing).exists());
    let saved = root.save_observation("boot-cut.1", b"original").unwrap();
    let path = temp
        .path()
        .join(observation_name(saved.observation_id()).unwrap());
    *root.before_directory_sync.lock().unwrap() = Some(Arc::new(|| {
        Err(std::io::Error::other("actual acknowledgement sync refused"))
    }));
    assert!(root.open_observation("boot-cut.1").is_err());
    *root.before_directory_sync.lock().unwrap() = None;
    std::fs::write(&path, b"truncated").unwrap();
    assert!(root.open_observation("boot-cut.1").is_err());
    assert_eq!(std::fs::read(path).unwrap(), b"truncated");
}
