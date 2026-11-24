use pretty_assertions::assert_eq;

use super::secure_read;
use super::sync_directory;
use super::write_private_atomic_replace;
use super::write_private_new;
use crate::AcceptanceError;
use crate::test_support::private_tempdir;

#[test]
fn new_and_replaced_artifacts_are_readable_after_directory_sync() -> Result<(), AcceptanceError> {
    let temporary = private_tempdir("directory synchronization");
    let path = temporary.path().join("artifact.json");
    let staging = temporary.path().join("artifact.pending");
    write_private_new(&path, b"original")?;
    assert_eq!(secure_read(&path, 64)?, b"original");
    write_private_atomic_replace(&path, &staging, b"replacement")?;
    assert_eq!(secure_read(&path, 64)?, b"replacement");
    assert!(!staging.exists());
    assert!(write_private_new(&path, b"must not overwrite").is_err());
    assert_eq!(secure_read(&path, 64)?, b"replacement");
    Ok(())
}

#[test]
fn missing_directory_sync_is_an_error_and_creates_nothing() {
    let temporary = private_tempdir("missing directory synchronization");
    let missing = temporary.path().join("absent");
    let error = sync_directory(&missing).expect_err("missing directory must not be acknowledged");
    assert!(
        matches!(error, AcceptanceError::Io(error) if error.kind() == std::io::ErrorKind::NotFound)
    );
    assert!(!missing.exists());
    assert_eq!(std::fs::read_dir(temporary.path()).unwrap().count(), 0);
}

#[cfg(windows)]
#[test]
fn directory_sharing_failure_is_not_reported_as_success() -> Result<(), AcceptanceError> {
    use std::os::windows::fs::OpenOptionsExt;

    let temporary = private_tempdir("exclusive directory handle");
    let blocker = std::fs::OpenOptions::new()
        .read(true)
        .share_mode(0)
        .custom_flags(0x0200_0000)
        .open(temporary.path())?;
    assert!(matches!(
        sync_directory(temporary.path()),
        Err(AcceptanceError::Io(_))
    ));
    drop(blocker);
    sync_directory(temporary.path())?;
    Ok(())
}
