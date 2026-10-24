//! Real private socket packets, with no authority or effect executor fixture.
use super::*;
use pretty_assertions::assert_eq;

fn release() -> AgentdNotesStartupRelease {
    AgentdNotesStartupRelease {
        target: NotesTargetIdentity {
            session_instance: "1".repeat(32), task_id: 1, incarnation: "2".repeat(32),
        },
        nonce: "3".repeat(32),
    }
}

#[test]
fn notes_startup_sends_exact_reserved_identity_without_descriptors() {
    let (host, session) = UnixDatagram::pair().unwrap();
    let release = release();
    activate_startup(&host, &release).unwrap();
    session.set_read_timeout(Some(Duration::from_millis(500))).unwrap();
    let mut bytes = [0_u8; MAX_BOOTSTRAP_BYTES + 1];
    let mut control = [0_usize; 32];
    let mut vector = libc::iovec { iov_base: bytes.as_mut_ptr().cast(), iov_len: bytes.len() };
    // SAFETY: the message contains only initialized bounded buffers, retained
    // through recvmsg. Any accidentally transferred rights are owned below.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    message.msg_controllen = mem::size_of_val(&control);
    let count = unsafe { libc::recvmsg(session.as_raw_fd(), &mut message, libc::MSG_CMSG_CLOEXEC) };
    assert!(count > 0 && count as usize <= MAX_BOOTSTRAP_BYTES);
    // SAFETY: recvmsg initialized the live aligned ancillary buffer, and no
    // received descriptor has been adopted before this single parser call.
    let (rights, valid) = unsafe { received_descriptors(&message) };
    assert!(valid && rights.is_empty());
    assert_eq!(message.msg_controllen, 0);
    assert_eq!(message.msg_flags & (libc::MSG_TRUNC | libc::MSG_CTRUNC), 0);
    let actual: serde_json::Value = serde_json::from_slice(&bytes[..count as usize]).unwrap();
    assert_eq!(actual, serde_json::json!({
        "schema_version": 1, "action": "activate_notes_bootstrap", "target": release.target,
        "destination_id": release.target.destination_id(), "nonce": release.nonce,
    }));
}

#[test]
fn notes_startup_refuses_uncleared_root_credential_mode_before_send() {
    let (host, session) = UnixDatagram::pair().unwrap();
    let enabled: libc::c_int = 1;
    // SAFETY: the live socket and one correctly sized integer are retained.
    assert_eq!(unsafe { libc::setsockopt(host.as_raw_fd(), libc::SOL_SOCKET, libc::SO_PASSCRED,
        std::ptr::from_ref(&enabled).cast(), mem::size_of_val(&enabled) as libc::socklen_t) }, 0);
    assert!(activate_startup(&host, &release()).is_err());
    session.set_nonblocking(true).unwrap();
    assert_eq!(session.recv(&mut [0_u8; MAX_BOOTSTRAP_BYTES]).unwrap_err().kind(), io::ErrorKind::WouldBlock);
}

#[test]
fn notes_startup_refuses_invalid_reservations_before_send() {
    let (host, session) = UnixDatagram::pair().unwrap();
    session.set_nonblocking(true).unwrap();
    for nonce in ["0".repeat(32), "A".repeat(32), "3".repeat(31)] {
        let mut invalid = release();
        invalid.nonce = nonce;
        assert!(activate_startup(&host, &invalid).is_err());
        assert_eq!(session.recv(&mut [0_u8; MAX_BOOTSTRAP_BYTES]).unwrap_err().kind(), io::ErrorKind::WouldBlock);
    }
    let mut invalid = release();
    invalid.target.task_id = 2;
    assert!(activate_startup(&host, &invalid).is_err());
    assert_eq!(session.recv(&mut [0_u8; MAX_BOOTSTRAP_BYTES]).unwrap_err().kind(), io::ErrorKind::WouldBlock);
}
