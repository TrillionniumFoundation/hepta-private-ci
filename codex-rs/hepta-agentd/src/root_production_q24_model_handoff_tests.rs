//! Actual Root/pidfd/SCM_RIGHTS framing qualification. Synthetic sealed bytes
//! here do not construct a registered factory or ordinary learning operation.

use super::*;
use pretty_assertions::assert_eq;
use std::io::Seek;
use std::os::fd::FromRawFd;
use std::os::unix::fs::MetadataExt;

fn root_pin() -> anyhow::Result<OwnedFd> {
    // SAFETY: credential queries observe only the actual test process.
    anyhow::ensure!(
        unsafe { libc::getuid() } == 0 && unsafe { libc::geteuid() } == 0,
        "actual Root handoff qualification required"
    );
    // SAFETY: pidfd_open returns one owned descriptor for this retained process.
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
    anyhow::ensure!(fd >= 0, "{}", io::Error::last_os_error());
    // SAFETY: the successful syscall exclusively transferred this new descriptor.
    Ok(unsafe { OwnedFd::from_raw_fd(fd as i32) })
}

#[test]
#[ignore = "explicit actual Root Model handoff qualification"]
fn root_model_handoff_preserves_four_original_rights_and_cloexec() -> anyhow::Result<()> {
    let root = root_pin()?;
    let journal = tempfile::tempfile()?;
    let witness = tempfile::tempfile()?;
    let identity = |file: &File| -> io::Result<(u64, u64)> {
        let metadata = file.metadata()?;
        Ok((metadata.dev(), metadata.ino()))
    };
    let expected = (identity(&journal)?, identity(&witness)?);
    let bootstrap =
        crate::authority_host_bootstrap_seal::seal_bytes(b"synthetic non-capability framing data")?;
    let (send, receive) = UnixDatagram::pair()?;
    send_root_q24_model_factory_handoff(
        send,
        RootQ24ModelFactoryOfferV1 {
            bootstrap,
            journal,
            witness,
        },
        &root,
        Duration::from_secs(1),
    )?;
    let mut received = receive_root_q24_model_factory_handoff(receive, Duration::from_secs(1))?;
    assert_eq!(
        (identity(&received.journal)?, identity(&received.witness)?),
        expected
    );
    assert_eq!(received.root_pid, std::process::id());
    for number in [
        received.bootstrap.as_raw_fd(),
        received.root_pidfd.as_raw_fd(),
        received.journal.as_raw_fd(),
        received.witness.as_raw_fd(),
    ] {
        // SAFETY: F_GETFD only observes each currently owned descriptor.
        assert_ne!(
            unsafe { libc::fcntl(number, libc::F_GETFD) } & libc::FD_CLOEXEC,
            0
        );
    }
    received.bootstrap.rewind()?;
    let mut bytes = Vec::new();
    received.bootstrap.read_to_end(&mut bytes)?;
    assert_eq!(bytes, b"synthetic non-capability framing data");
    Ok(())
}

#[test]
#[ignore = "explicit actual Root purpose/rights confusion qualification"]
fn root_model_handoff_rejects_learning_purpose_and_reordered_rights() -> anyhow::Result<()> {
    let root = root_pin()?;
    let bootstrap = crate::authority_host_bootstrap_seal::seal_bytes(b"synthetic descriptor")?;
    let journal = tempfile::tempfile()?;
    let witness = tempfile::tempfile()?;
    let (send, receive) = UnixDatagram::pair()?;
    crate::send_root_learning_handoff(send, &bootstrap, &root, Duration::from_secs(1))?;
    assert!(receive_root_q24_model_factory_handoff(receive, Duration::from_secs(1)).is_err());
    let (send, receive) = UnixDatagram::pair()?;
    send_packet(
        &send,
        MODEL_FRAME,
        &[
            journal.as_raw_fd(),
            root.as_raw_fd(),
            bootstrap.as_raw_fd(),
            witness.as_raw_fd(),
        ],
        Duration::from_secs(1),
    )?;
    assert!(receive_root_q24_model_factory_handoff(receive, Duration::from_secs(1)).is_err());
    Ok(())
}
