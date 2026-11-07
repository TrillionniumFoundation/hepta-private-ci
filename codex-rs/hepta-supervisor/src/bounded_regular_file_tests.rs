use crate::bounded_regular_file::read_optional;
use pretty_assertions::assert_eq;

#[test]
fn regular_reader_keeps_exact_limit_and_rejects_overflow_or_directory() {
    let root = tempfile::tempdir().unwrap();
    let file = root.path().join("bounded");
    assert_eq!(read_optional(&file, /*maximum*/ 4).unwrap(), None);
    std::fs::write(&file, b"1234").unwrap();
    assert_eq!(
        read_optional(&file, /*maximum*/ 4).unwrap(),
        Some(b"1234".to_vec())
    );
    std::fs::write(&file, b"12345").unwrap();
    assert!(read_optional(&file, /*maximum*/ 4).is_err());
    assert!(read_optional(root.path(), /*maximum*/ 4).is_err());
}

#[cfg(unix)]
#[test]
fn regular_reader_refuses_symlink_and_fifo_without_waiting_for_a_writer() {
    use std::os::unix::ffi::OsStrExt;
    let root = tempfile::tempdir().unwrap();
    let source = root.path().join("source");
    std::fs::write(&source, b"1234").unwrap();
    let link = root.path().join("link");
    std::os::unix::fs::symlink(&source, &link).unwrap();
    assert!(read_optional(&link, /*maximum*/ 4).is_err());
    let fifo = root.path().join("fifo");
    let path = std::ffi::CString::new(fifo.as_os_str().as_bytes()).unwrap();
    // SAFETY: the owned NUL-terminated path remains live for this syscall.
    assert_eq!(unsafe { libc::mkfifo(path.as_ptr(), 0o600) }, 0);
    let started = std::time::Instant::now();
    assert!(read_optional(&fifo, /*maximum*/ 4).is_err());
    assert!(started.elapsed() < std::time::Duration::from_secs(1));
}
