use std::ffi::CString;
use std::fs;
use std::fs::OpenOptions;
use std::io::Seek;
use std::io::Write;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::fs::symlink;
use std::sync::mpsc;
use std::thread;
use std::time::Duration;

use super::BrowserServoError;
use super::open_bounded;
use super::snapshot_service;
use super::verify_file_digest;
use crate::browser_servo::sha256_bytes;

#[test]
fn service_snapshot_copies_the_opened_inode_and_owns_private_cleanup() {
    let selected = tempfile::tempdir().expect("selected artifact directory");
    let path = selected.path().join("selected.mjs");
    let approved = b"export default 1;";
    fs::write(&path, approved).expect("approved artifact");
    let mut input = open_bounded(&path, /*maximum*/ 64).expect("opened approved inode");
    let replacement = selected.path().join("replacement.mjs");
    fs::write(&replacement, b"export default 2;").expect("replacement artifact");
    fs::rename(replacement, &path).expect("replace original pathname");

    let snapshot = snapshot_service(&mut input, sha256_bytes(approved), /*maximum*/ 64)
        .expect("snapshot from opened inode");
    let snapshot_path = snapshot.path().to_owned();
    assert_eq!(fs::read(&snapshot_path).expect("snapshot bytes"), approved);
    assert_eq!(
        fs::read(&path).expect("replaced bytes"),
        b"export default 2;"
    );
    assert_eq!(
        (
            fs::metadata(snapshot_path.parent().expect("private parent"))
                .expect("directory metadata")
                .permissions()
                .mode()
                & 0o777,
            fs::metadata(&snapshot_path)
                .expect("snapshot metadata")
                .permissions()
                .mode()
                & 0o777,
        ),
        (0o700, 0o400)
    );
    drop(snapshot);
    assert!(!snapshot_path.exists());
}

#[test]
fn opened_artifacts_reject_symlinks_directories_and_wrong_digests() {
    let selected = tempfile::tempdir().expect("artifact directory");
    let path = selected.path().join("selected.mjs");
    fs::write(&path, b"approved").expect("artifact");
    let link = selected.path().join("link.mjs");
    symlink(&path, &link).expect("artifact symlink");
    assert!(matches!(
        open_bounded(&link, /*maximum*/ 64),
        Err(BrowserServoError::Invalid(_))
    ));
    assert!(matches!(
        open_bounded(selected.path(), /*maximum*/ 64),
        Err(BrowserServoError::Invalid(_))
    ));
    assert!(matches!(
        verify_file_digest(&path, [0; 32], /*maximum*/ 64),
        Err(BrowserServoError::BindingMismatch(_))
    ));
    let mut input = open_bounded(&path, /*maximum*/ 64).expect("opened artifact");
    assert!(matches!(
        snapshot_service(&mut input, [0; 32], /*maximum*/ 64),
        Err(BrowserServoError::BindingMismatch(_))
    ));
}

#[test]
fn opening_a_fifo_returns_without_waiting_for_a_writer() {
    let selected = tempfile::tempdir().expect("fifo directory");
    let path = selected.path().join("selected.mjs");
    let terminated_path = CString::new(path.as_os_str().as_bytes()).expect("fifo pathname");
    // SAFETY: the temporary pathname is a valid NUL-terminated string.
    assert_eq!(
        unsafe {
            libc::mkfifo(terminated_path.as_ptr(), /*mode*/ 0o600)
        },
        0
    );
    let (result, completed) = mpsc::channel();
    thread::spawn(move || {
        result
            .send(open_bounded(&path, /*maximum*/ 64).map(|_| ()))
            .expect("fifo result receiver");
    });
    assert!(matches!(
        completed
            .recv_timeout(Duration::from_secs(1))
            .expect("nonblocking FIFO open"),
        Err(BrowserServoError::Invalid(_))
    ));
}

#[test]
fn service_growth_after_fstat_is_bounded_on_the_same_handle() {
    let selected = tempfile::tempdir().expect("artifact directory");
    let path = selected.path().join("selected.mjs");
    fs::write(&path, b"approved").expect("artifact");
    let mut input = open_bounded(&path, /*maximum*/ 64).expect("opened admitted artifact");
    OpenOptions::new()
        .append(true)
        .open(&path)
        .expect("growing file")
        .write_all(&[b'x'; 1_000])
        .expect("grow after admission");
    assert!(matches!(
        snapshot_service(&mut input, sha256_bytes(b"approved"), /*maximum*/ 64),
        Err(BrowserServoError::Invalid(_))
    ));
    assert_eq!(input.stream_position().expect("bounded read position"), 65);
}
