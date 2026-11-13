//! Actual Root descriptor transport only. Arbitrary sealed bytes below have no
//! valid Root authority DTO; these tests create no writer owner or native role.

use super::*;
use crate::receive_root_production_writer_handoff;
use crate::send_root_production_writer_handoff;
use std::os::fd::FromRawFd;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::net::UnixDatagram;
use std::time::Duration;

fn root_pidfd() -> std::os::fd::OwnedFd {
    // SAFETY: open this still-live test process's actual pidfd, with zero flags.
    let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
    assert!(raw >= 0);
    // SAFETY: successful pidfd_open returned one fresh owned descriptor.
    unsafe { std::os::fd::OwnedFd::from_raw_fd(raw as i32) }
}

#[test]
#[ignore = "requires actual Root and the explicit original descriptor-transport qualification"]
fn root_writer_transfer_consumes_sender_and_releases_original_lock_after_recipient_closes() {
    let root = std::env::var_os("HEPTA_CHECKPOINT_TEST_ROOT").unwrap();
    let directory = tempfile::tempdir_in(root).unwrap();
    let path = directory.path().join("original-writer.lock");
    let writer = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&path)
        .unwrap();
    let independent = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .unwrap();
    let bootstrap = seal_bytes(b"transport-only; this is not a Root authority bundle").unwrap();
    let (sender, receiver) = UnixDatagram::pair().unwrap();
    send_root_production_writer_handoff(
        sender,
        &bootstrap,
        &root_pidfd(),
        writer,
        Duration::from_millis(500),
    )
    .unwrap();
    let (_sealed, _root, received) =
        receive_root_production_writer_handoff(receiver, Duration::from_millis(500)).unwrap();
    let received = received.into_file();
    received.try_lock().unwrap();
    assert!(independent.try_lock().is_err());
    drop(received);
    independent
        .try_lock()
        .expect("consumed sender must not keep the recipient's original OFD lock alive");
}

#[test]
#[ignore = "requires actual Root and the explicit original descriptor-transport qualification"]
fn root_native_writer_purpose_cannot_pass_the_unchanged_original_two_rights_receiver() {
    let root = std::env::var_os("HEPTA_CHECKPOINT_TEST_ROOT").unwrap();
    let directory = tempfile::tempdir_in(root).unwrap();
    let writer = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(directory.path().join("original-writer.lock"))
        .unwrap();
    let bootstrap = seal_bytes(b"transport-only; no authority is installed").unwrap();
    let (sender, receiver) = UnixDatagram::pair().unwrap();
    send_root_production_writer_handoff(
        sender,
        &bootstrap,
        &root_pidfd(),
        writer,
        Duration::from_millis(500),
    )
    .unwrap();
    let error = crate::receive_root_production_handoff(receiver, Duration::from_millis(500))
        .err()
        .unwrap();
    assert!(
        error
            .to_string()
            .contains("exact original handoff marker and two ordered rights required")
    );
}
