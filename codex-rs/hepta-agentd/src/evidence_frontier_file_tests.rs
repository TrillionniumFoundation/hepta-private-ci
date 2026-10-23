use std::fs;
use std::os::unix::fs::PermissionsExt;

use super::*;
use crate::objective_runtime::tests::run_start_owner_fixture;

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
    use std::os::unix::fs::OpenOptionsExt;
    use std::sync::mpsc;
    use std::time::Duration;

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
    assert!(observed.expect("external frontier read must not wait for a FIFO writer"));
}

#[test]
fn inspected_external_frontier_fifo_replacement_is_rejected_without_waiting_for_a_writer() {
    let (temp, identity) = run_start_owner_fixture();
    let path = temp
        .path()
        .canonicalize()
        .expect("canonical root")
        .join("frontier.json");
    fs::write(&path, b"external frontier bytes").expect("external fixture");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).expect("nonwritable sharing");
    assert_eq!(
        read_external_file(&path, &identity, TEST_MAXIMUM).expect("regular shared read"),
        b"external frontier bytes"
    );
    let inspected = InspectedExternalFrontierFile::inspect(&path, &identity, TEST_MAXIMUM)
        .expect("successful real external preflight");
    let retained = path.with_extension("retained");
    fs::rename(&path, &retained).expect("retain preflight inode");
    make_fifo(&path);
    expect_bounded_fifo_rejection(&path, move || inspected.read().is_err());
    assert_eq!(
        fs::read(retained).expect("original frontier bytes"),
        b"external frontier bytes"
    );
}

#[test]
fn inspected_external_frontier_symlink_to_fifo_is_rejected_at_open_without_following_it() {
    let (temp, identity) = run_start_owner_fixture();
    let path = temp
        .path()
        .canonicalize()
        .expect("canonical root")
        .join("frontier.json");
    fs::write(&path, b"external frontier bytes").expect("external fixture");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).expect("nonwritable sharing");
    let inspected = InspectedExternalFrontierFile::inspect(&path, &identity, TEST_MAXIMUM)
        .expect("successful real external preflight");
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
        fs::read(retained).expect("original frontier bytes"),
        b"external frontier bytes"
    );
}

#[test]
fn external_frontier_rejects_writable_parent_and_unsafe_ancestor() {
    let (temp, identity) = run_start_owner_fixture();
    let root = temp.path().canonicalize().expect("canonical owner root");
    let parent = root.join("independent-frontier");
    fs::create_dir(&parent).expect("external parent");
    fs::set_permissions(&parent, fs::Permissions::from_mode(0o700)).expect("private parent");
    let path = parent.join("frontier.json");
    let bytes = b"independently provisioned external frontier";
    fs::write(&path, bytes).expect("external frontier");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).expect("not writable by others");
    assert_eq!(
        read_external_file(&path, &identity, TEST_MAXIMUM).expect("external bytes"),
        bytes
    );
    fs::set_permissions(&parent, fs::Permissions::from_mode(0o777)).expect("unsafe parent");
    assert!(read_external_file(&path, &identity, TEST_MAXIMUM).is_err());
    fs::set_permissions(&parent, fs::Permissions::from_mode(0o700)).expect("restore parent");
    fs::set_permissions(&root, fs::Permissions::from_mode(0o777)).expect("unsafe ancestor");
    assert!(read_external_file(&path, &identity, TEST_MAXIMUM).is_err());
    fs::set_permissions(&root, fs::Permissions::from_mode(0o1777))
        .expect("trusted sticky ancestor");
    assert_eq!(
        read_external_file(&path, &identity, TEST_MAXIMUM).expect("external bytes"),
        bytes
    );
}
