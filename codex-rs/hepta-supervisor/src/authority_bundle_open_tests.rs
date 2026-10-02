//! Real substitution at the same descriptor-open boundary used by startup.

use std::io;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::sync::mpsc;
use std::time::Duration;

use anyhow::Result;

use super::ProductionAuthorityBundleError;
use super::open_secure_file;

#[test]
fn fifo_swap_after_regular_metadata_is_rejected_before_watchdog_release() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("authority.json");
    std::fs::write(&path, b"public verifier bundle")?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
    let before = std::fs::symlink_metadata(&path)?;
    assert!(before.file_type().is_file());
    super::validate_unix_metadata(&before)?;

    // Create the FIFO while the original inode still exists, then replace its
    // name after the production pre-open checks have genuinely succeeded.
    let fifo_path = directory.path().join("replacement.fifo");
    let name = std::ffi::CString::new(fifo_path.as_os_str().as_bytes())?;
    // SAFETY: name is NUL-terminated and alive; mode is owner-only permissions.
    if unsafe {
        libc::mkfifo(name.as_ptr(), /*mode*/ 0o600)
    } != 0
    {
        return Err(io::Error::last_os_error().into());
    }
    std::fs::rename(&fifo_path, &path)?;
    assert!(!std::fs::symlink_metadata(&path)?.file_type().is_file());

    let (done, completed) = mpsc::channel();
    let watchdog_path = path.clone();
    let watchdog = std::thread::spawn(move || -> io::Result<bool> {
        match completed.recv_timeout(Duration::from_secs(1)) {
            Ok(()) | Err(mpsc::RecvTimeoutError::Disconnected) => Ok(false),
            Err(mpsc::RecvTimeoutError::Timeout) => {
                // Keep a writer alive until the attempted open has returned.
                // This releases the old blocking implementation for a bounded
                // failing regression, rather than leaving a hung reader behind.
                let writer = std::fs::OpenOptions::new()
                    .read(true)
                    .write(true)
                    .custom_flags(libc::O_NONBLOCK | libc::O_CLOEXEC | libc::O_NOFOLLOW)
                    .open(watchdog_path)?;
                let result = completed.recv_timeout(Duration::from_secs(5));
                drop(writer);
                result.map_err(io::Error::other)?;
                Ok(true)
            }
        }
    });
    let result = open_secure_file(&path, &before);
    let _ = done.send(());
    let released = watchdog
        .join()
        .map_err(|_| io::Error::other("bundle open watchdog panicked"))??;
    assert!(!released, "special-file open required a watchdog writer");
    assert!(matches!(
        result,
        Err(ProductionAuthorityBundleError::Invalid(message))
            if message == "opened bundle must be a bounded regular file"
    ));
    assert!(!std::fs::symlink_metadata(&path)?.file_type().is_file());
    Ok(())
}
