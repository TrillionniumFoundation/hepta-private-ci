use super::*;
use std::os::unix::fs::PermissionsExt;
use std::time::Duration;

#[test]
fn protected_open_rejects_links_and_never_waits_for_fifo_writer() {
    let temp = tempfile::tempdir().expect("protected files");
    let file = temp.path().join("file");
    fs::write(&file, b"configuration").expect("regular file");
    let link = temp.path().join("link");
    std::os::unix::fs::symlink(&file, &link).expect("file link");
    assert!(open_protected_file(&link).is_err());
    let fifo = temp.path().join("fifo");
    rustix::fs::mkfifoat(
        rustix::fs::CWD,
        &fifo,
        rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR,
    )
    .expect("FIFO");
    let (send, result) = std::sync::mpsc::channel();
    let worker = std::thread::spawn(move || {
        send.send(open_protected_file(&fifo).is_err())
            .expect("open result");
    });
    assert!(
        result
            .recv_timeout(Duration::from_secs(1))
            .expect("open must not block on FIFO replacement")
    );
    worker.join().expect("file opener");
}

#[test]
fn protected_reader_enforces_privacy_and_exact_byte_limit() {
    let temp = tempfile::tempdir().expect("private configuration");
    let root = temp.path().canonicalize().expect("canonical root");
    let file = root.join("config");
    let bytes = (0..64_u8).collect::<Vec<_>>();
    fs::write(&file, &bytes).expect("write config");
    fs::set_permissions(&file, fs::Permissions::from_mode(0o600)).expect("private config");
    assert_eq!(
        read_protected_file(&file, 64, "config").expect("exact limit"),
        bytes
    );
    assert!(matches!(
        read_protected_file(&file, 63, "config"),
        Err(ProtectedFileError::Invalid(_))
    ));
    fs::set_permissions(&file, fs::Permissions::from_mode(0o640)).expect("exposed config");
    assert!(matches!(
        read_protected_file(&file, 64, "config"),
        Err(ProtectedFileError::Invalid(_))
    ));
}

#[test]
fn protected_reader_rejects_noncanonical_link_paths() {
    let temp = tempfile::tempdir().expect("private configuration");
    let root = temp.path().canonicalize().expect("canonical root");
    let file = root.join("config");
    fs::write(&file, b"configuration").expect("write config");
    fs::set_permissions(&file, fs::Permissions::from_mode(0o600)).expect("private config");
    let link = root.join("link");
    std::os::unix::fs::symlink(&file, &link).expect("link config");
    assert!(matches!(
        read_protected_file(&link, 64, "config"),
        Err(ProtectedFileError::Invalid(_))
    ));
}
