use super::*;
use pretty_assertions::assert_eq;

#[test]
fn cross_directory_publish_rejects_without_changing_either_file() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let staging = temporary.path().join("staged");
    let other = temporary.path().join("other");
    std::fs::create_dir(&other)?;
    let destination = other.join("intent");
    std::fs::write(&staging, b"new intent")?;
    std::fs::write(&destination, b"old intent")?;
    assert_eq!(
        publish_synced_file(&staging, &destination)
            .err()
            .map(|error| error.kind()),
        Some(io::ErrorKind::InvalidInput)
    );
    assert_eq!(std::fs::read(&staging)?, b"new intent");
    assert_eq!(std::fs::read(&destination)?, b"old intent");
    Ok(())
}

#[cfg(windows)]
#[test]
fn windows_locked_destination_rejects_then_write_through_replacement_succeeds() -> io::Result<()> {
    use std::fs::OpenOptions;
    use std::io::Write;
    use std::os::windows::fs::OpenOptionsExt;

    let temporary = tempfile::tempdir()?;
    let parent = temporary
        .path()
        .join("long-parent-".repeat(/*n*/ 12))
        .join("nested-parent-".repeat(/*n*/ 12));
    std::fs::create_dir_all(&parent)?;
    let staging = parent.join("staged");
    let destination = parent.join("intent");
    let mut writer = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&staging)?;
    writer.write_all(b"new intent")?;
    writer.sync_all()?;
    drop(writer);
    std::fs::write(&destination, b"old intent")?;
    let denied = OpenOptions::new()
        .read(true)
        .share_mode(/*val*/ 0)
        .open(&destination)?;
    assert!(publish_synced_file(&staging, &destination).is_err());
    drop(denied);
    assert_eq!(std::fs::read(&staging)?, b"new intent");
    assert_eq!(std::fs::read(&destination)?, b"old intent");
    publish_synced_file(&staging, &destination)?;
    assert_eq!(std::fs::read(&destination)?, b"new intent");
    assert!(!staging.exists());
    Ok(())
}

#[cfg(windows)]
#[test]
fn windows_rejects_interior_nul_before_calling_the_os() {
    assert_eq!(
        wide_path(Path::new("intent\0suffix"))
            .err()
            .map(|error| error.kind()),
        Some(io::ErrorKind::InvalidInput)
    );
}

#[cfg(any(unix, windows))]
#[test]
fn synchronized_file_is_created_then_replaced() -> io::Result<()> {
    use std::io::Write;

    let temporary = tempfile::tempdir()?;
    let destination = temporary.path().join("session");
    for contents in [
        b"first session".as_slice(),
        b"replacement session".as_slice(),
    ] {
        let staging = temporary.path().join("staged");
        let mut options = std::fs::OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut writer = options.open(&staging)?;
        writer.write_all(contents)?;
        writer.sync_all()?;
        drop(writer);
        publish_synced_file(&staging, &destination)?;
        assert_eq!(std::fs::read(&destination)?, contents);
        assert!(!staging.exists());
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                std::fs::metadata(&destination)?.permissions().mode() & 0o777,
                0o600
            );
        }
    }
    Ok(())
}
