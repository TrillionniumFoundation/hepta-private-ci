use super::*;
use crate::objective_runtime::tests::run_start_owner_fixture;
use std::fs;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::sync::mpsc;
use std::time::Duration;

const TEST_MAXIMUM: u64 = 4096;

fn make_fifo(path: &Path) {
    assert!(
        std::process::Command::new("mkfifo")
            .args(["-m", "600"])
            .arg(path)
            .status()
            .expect("POSIX mkfifo")
            .success()
    );
}

fn expect_bounded_fifo_rejection(fifo: &Path, operation: impl FnOnce() -> bool + Send + 'static) {
    let (sender, receiver) = mpsc::channel();
    let worker =
        std::thread::spawn(move || sender.send(operation()).expect("open result receiver"));
    let observed = receiver.recv_timeout(Duration::from_secs(/*secs*/ 2));
    if observed.is_err() {
        let rescue = OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(fifo)
            .expect("release regressed FIFO reader");
        receiver
            .recv_timeout(Duration::from_secs(/*secs*/ 2))
            .expect("reader finishes after cleanup");
        drop(rescue);
    }
    worker.join().expect("reader worker");
    assert!(observed.expect("owner trust read must not wait for a FIFO writer"));
}

#[test]
fn inspected_private_owner_fifo_replacement_is_rejected_without_waiting_for_a_writer() {
    let (_temp, identity) = run_start_owner_fixture();
    let path = identity.home_root.join("trust.json");
    fs::write(&path, b"trusted owner bytes").expect("owner fixture");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).expect("private file");
    assert_eq!(
        read_private_owner_file(&path, &identity, TEST_MAXIMUM).expect("regular read"),
        b"trusted owner bytes"
    );
    let inspected = InspectedPrivateOwnerFile::inspect(&path, &identity, TEST_MAXIMUM)
        .expect("successful real owner preflight");
    let retained = path.with_extension("retained");
    fs::rename(&path, &retained).expect("retain preflight inode");
    make_fifo(&path);
    expect_bounded_fifo_rejection(&path, move || inspected.read().is_err());
    assert_eq!(
        fs::read(retained).expect("original owner bytes"),
        b"trusted owner bytes"
    );
}

#[test]
fn inspected_private_owner_symlink_to_fifo_is_rejected_at_open_without_following_it() {
    let (_temp, identity) = run_start_owner_fixture();
    let path = identity.home_root.join("trust.json");
    fs::write(&path, b"trusted owner bytes").expect("owner fixture");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).expect("private file");
    let inspected = InspectedPrivateOwnerFile::inspect(&path, &identity, TEST_MAXIMUM)
        .expect("successful real owner preflight");
    let retained = path.with_extension("retained");
    fs::rename(&path, &retained).expect("retain preflight inode");
    let fifo = path.with_extension("fifo");
    make_fifo(&fifo);
    std::os::unix::fs::symlink(&fifo, &path).expect("replace final component after preflight");
    expect_bounded_fifo_rejection(
        &fifo,
        move || matches!(inspected.read(), Err(AgentdError::Io(error)) if error.raw_os_error() == Some(libc::ELOOP)),
    );
    assert_eq!(
        fs::read(retained).expect("original owner bytes"),
        b"trusted owner bytes"
    );
}
