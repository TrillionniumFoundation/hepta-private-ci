use std::io;
#[cfg(unix)]
use std::path::Path;

use super::open_regular_file;
use super::read_bounded;

#[cfg(unix)]
pub(crate) fn make_fifo(path: &Path) -> io::Result<()> {
    use std::os::unix::ffi::OsStrExt;

    let name = std::ffi::CString::new(path.as_os_str().as_bytes())?;
    // SAFETY: the NUL-terminated path is live; mode grants only owner access.
    if unsafe {
        libc::mkfifo(name.as_ptr(), /*mode*/ 0o600)
    } != 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

#[cfg(unix)]
pub(crate) fn with_fifo_watchdog<T>(path: &Path, operation: impl FnOnce() -> T) -> io::Result<T> {
    use std::os::unix::fs::OpenOptionsExt;
    use std::sync::mpsc;
    use std::time::Duration;

    let (done, completed) = mpsc::channel();
    let path = path.to_path_buf();
    let watchdog = std::thread::spawn(move || -> io::Result<bool> {
        match completed.recv_timeout(Duration::from_secs(1)) {
            Ok(()) | Err(mpsc::RecvTimeoutError::Disconnected) => Ok(false),
            Err(mpsc::RecvTimeoutError::Timeout) => {
                let writer = std::fs::OpenOptions::new()
                    .read(true)
                    .write(true)
                    .custom_flags(libc::O_NONBLOCK | libc::O_NOFOLLOW | libc::O_CLOEXEC)
                    .open(path)?;
                let result = completed.recv_timeout(Duration::from_secs(5));
                drop(writer);
                result.map_err(io::Error::other)?;
                Ok(true)
            }
        }
    });
    let result = operation();
    let _ = done.send(());
    let released = watchdog
        .join()
        .map_err(|_| io::Error::other("regular input watchdog panicked"))??;
    assert!(!released, "regular-file open needed a watchdog FIFO writer");
    Ok(result)
}

#[cfg(unix)]
#[test]
fn fifo_key_and_request_paths_are_rejected_before_watchdog_release() -> io::Result<()> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("regular-input");
    make_fifo(&path)?;
    for maximum in [32, 8 * 1024 * 1024] {
        let result = with_fifo_watchdog(&path, || open_regular_file(&path, maximum))?;
        assert_eq!(
            result.expect_err("regular input").kind(),
            io::ErrorKind::InvalidData
        );
    }
    Ok(())
}

#[test]
fn read_bound_is_enforced_after_opened_file_grows() -> io::Result<()> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("regular-input");
    std::fs::write(&path, b"ok")?;
    let mut file = open_regular_file(&path, /*maximum*/ 4)?;
    std::fs::write(&path, b"oversized after open")?;
    let mut bytes = Vec::new();
    let error = read_bounded(&mut file, &mut bytes, /*maximum*/ 4)
        .expect_err("read itself must enforce the byte bound");
    assert_eq!(error.kind(), io::ErrorKind::InvalidData);
    assert_eq!(bytes, b"overs");
    Ok(())
}
