use super::*;
use pretty_assertions::assert_eq;
use std::error::Error;
use std::io::Read;
use std::io::Write;

type TestResult = Result<(), Box<dyn Error>>;

#[derive(Deserialize)]
struct Fixture {
    offer_utf8: String,
    attached_ack_utf8: String,
    rejected_ack_utf8: String,
}

fn fixture() -> Fixture {
    serde_json::from_str(include_str!("../tests/fixtures/notes-bootstrap-v2.json"))
        .expect("shared bootstrap fixture")
}

fn send_offer(socket: &UnixDatagram, payload: &[u8], descriptors: &[RawFd]) -> io::Result<()> {
    let mut vector = libc::iovec {
        iov_base: payload.as_ptr().cast_mut().cast(),
        iov_len: payload.len(),
    };
    let mut control = [0_usize; 128];
    // SAFETY: only the initialized bounded payload and aligned control buffer
    // below are given to one synchronous sendmsg call.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector;
    message.msg_iovlen = 1;
    if !descriptors.is_empty() {
        let bytes = mem::size_of_val(descriptors);
        message.msg_control = control.as_mut_ptr().cast();
        message.msg_controllen = unsafe { libc::CMSG_SPACE(bytes as u32) } as usize;
        assert!(message.msg_controllen <= mem::size_of_val(&control));
        // SAFETY: the header and descriptor payload fit the retained control
        // buffer. Sending borrows the fixture's descriptors; it never owns them.
        unsafe {
            let header = libc::CMSG_FIRSTHDR(&message);
            (*header).cmsg_level = libc::SOL_SOCKET;
            (*header).cmsg_type = libc::SCM_RIGHTS;
            (*header).cmsg_len = libc::CMSG_LEN(bytes as u32) as usize;
            std::ptr::copy_nonoverlapping(
                descriptors.as_ptr(),
                libc::CMSG_DATA(header).cast(),
                descriptors.len(),
            );
        }
    }
    // SAFETY: all borrowed payload/control pointers remain valid through the
    // synchronous syscall and describe their actual initialized bounds.
    let result = unsafe { libc::sendmsg(socket.as_raw_fd(), &message, libc::MSG_NOSIGNAL) };
    if result < 0 {
        return Err(io::Error::last_os_error());
    }
    assert_eq!(result as usize, payload.len());
    Ok(())
}

#[test]
fn bootstrap_golden_transfers_two_ordered_cloexec_endpoints_and_correlates_only_registration()
-> TestResult {
    let fixture = fixture();
    let (parent, session) = UnixDatagram::pair()?;
    let (offered, mut application) = UnixStream::pair()?;
    let (recovery, _recovery_peer) = UnixDatagram::pair()?;
    send_offer(
        &session,
        fixture.offer_utf8.as_bytes(),
        &[offered.as_raw_fd(), recovery.as_raw_fd()],
    )?;
    drop(offered);
    let deadline = Instant::now() + Duration::from_secs(2);
    let (offer, mut received, received_recovery) = receive_offer(&parent, deadline)?;
    require_socket(received_recovery.as_raw_fd(), libc::SOCK_DGRAM)?;
    // SAFETY: F_GETFD reads the flags of the retained received descriptor.
    let flags = unsafe { libc::fcntl(received.as_raw_fd(), libc::F_GETFD) };
    assert!(flags >= 0 && flags & libc::FD_CLOEXEC != 0);
    received.write_all(b"private")?;
    let mut bytes = [0; 7];
    application.read_exact(&mut bytes)?;
    assert_eq!(&bytes, b"private");
    session.set_nonblocking(true)?;
    let mut ack = [0; MAX_BOOTSTRAP_BYTES];
    assert_eq!(
        session
            .recv(&mut ack)
            .expect_err("receive alone must not acknowledge")
            .kind(),
        io::ErrorKind::WouldBlock
    );
    acknowledge(&parent, &offer, RegistrationStatus::Attached, deadline)?;
    let size = session.recv(&mut ack)?;
    assert_eq!(&ack[..size], fixture.attached_ack_utf8.as_bytes());
    acknowledge(&parent, &offer, RegistrationStatus::Rejected, deadline)?;
    let size = session.recv(&mut ack)?;
    assert_eq!(&ack[..size], fixture.rejected_ack_utf8.as_bytes());
    Ok(())
}

#[test]
fn duplicate_unknown_wrong_identity_and_oversized_offers_close_received_descriptor() -> TestResult {
    let original = fixture().offer_utf8;
    let mut wrong_task: serde_json::Value = serde_json::from_str(&original)?;
    wrong_task["target"]["task_id"] = serde_json::json!(2);
    let mut wrong_destination: serde_json::Value = serde_json::from_str(&original)?;
    wrong_destination["destination_id"] = serde_json::json!("another-destination");
    for payload in [
        original.replace("\"schema_version\":2", "\"schema_version\":1"),
        original.replacen("{", "{\"schema_version\":1,", 1),
        original.replacen("{", "{\"extra\":true,", 1),
        serde_json::to_string(&wrong_task)?,
        serde_json::to_string(&wrong_destination)?,
        "x".repeat(MAX_BOOTSTRAP_BYTES + 1),
    ] {
        let (parent, session) = UnixDatagram::pair()?;
        let (offered, mut application) = UnixStream::pair()?;
        let (recovery, _recovery_peer) = UnixDatagram::pair()?;
        send_offer(
            &session,
            payload.as_bytes(),
            &[offered.as_raw_fd(), recovery.as_raw_fd()],
        )?;
        drop(offered);
        assert!(receive_offer(&parent, Instant::now() + Duration::from_secs(2)).is_err());
        application.set_read_timeout(Some(Duration::from_secs(1)))?;
        assert_eq!(application.read(&mut [0])?, 0);
    }
    Ok(())
}

#[test]
fn absent_multiple_and_truncated_descriptor_sets_are_rejected_and_closed() -> TestResult {
    let fixture = fixture();
    for count in [0, 1, 2, 3, 80] {
        let (parent, session) = UnixDatagram::pair()?;
        let (offered, mut application) = UnixStream::pair()?;
        let descriptors = vec![offered.as_raw_fd(); count];
        send_offer(&session, fixture.offer_utf8.as_bytes(), &descriptors)?;
        drop(offered);
        assert!(receive_offer(&parent, Instant::now() + Duration::from_secs(2)).is_err());
        application.set_read_timeout(Some(Duration::from_secs(1)))?;
        assert_eq!(application.read(&mut [0])?, 0);
    }
    Ok(())
}

#[test]
fn datagram_or_named_effect_descriptor_cannot_be_attached() -> TestResult {
    let fixture = fixture();
    let (parent, session) = UnixDatagram::pair()?;
    let (offered, _peer) = UnixDatagram::pair()?;
    let (recovery, _recovery_peer) = UnixDatagram::pair()?;
    send_offer(
        &session,
        fixture.offer_utf8.as_bytes(),
        &[offered.as_raw_fd(), recovery.as_raw_fd()],
    )?;
    assert!(receive_offer(&parent, Instant::now() + Duration::from_secs(2)).is_err());
    let directory = tempfile::tempdir()?;
    let listener = std::os::unix::net::UnixListener::bind(directory.path().join("named.sock"))?;
    let offered = UnixStream::connect(directory.path().join("named.sock"))?;
    let (_peer, _) = listener.accept()?;
    send_offer(
        &session,
        fixture.offer_utf8.as_bytes(),
        &[offered.as_raw_fd(), recovery.as_raw_fd()],
    )?;
    assert!(receive_offer(&parent, Instant::now() + Duration::from_secs(2)).is_err());
    Ok(())
}

#[test]
fn expired_deadline_cannot_receive_an_offer_or_emit_an_ack() -> TestResult {
    let (parent, session) = UnixDatagram::pair()?;
    let deadline = Instant::now();
    assert!(receive_offer(&parent, deadline).is_err());
    let offer: NotesOffer = serde_json::from_str(&fixture().offer_utf8)?;
    assert!(acknowledge(&parent, &offer, RegistrationStatus::Attached, deadline).is_err());
    session.set_nonblocking(true)?;
    assert_eq!(
        session
            .recv(&mut [0; MAX_BOOTSTRAP_BYTES])
            .expect_err("no ACK after deadline")
            .kind(),
        io::ErrorKind::WouldBlock
    );
    Ok(())
}
