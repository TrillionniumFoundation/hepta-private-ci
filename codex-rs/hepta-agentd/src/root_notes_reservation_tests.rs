//! Real kernel credentials and rights; these packets are transport fixtures,
//! not an original Session lifecycle or an authority qualification.

use super::*;
use pretty_assertions::assert_eq;
use std::io::Read;
use std::os::unix::net::UnixStream;

fn packet() -> Vec<u8> {
    let target = NotesTargetIdentity {
        session_instance: "1".repeat(32),
        task_id: 1,
        incarnation: "2".repeat(32),
    };
    serde_json::to_vec(&serde_json::json!({
        "schema_version": 1, "action": "notes_target_reserved",
        "destination_id": target.destination_id(), "target": target,
        "nonce": "3".repeat(32),
    }))
    .unwrap()
}

fn credential() -> libc::ucred {
    // SAFETY: these calls only read the current process's actual credentials.
    unsafe {
        libc::ucred {
            pid: libc::getpid(),
            uid: libc::getuid(),
            gid: libc::getgid(),
        }
    }
}

#[test]
fn reservation_checks_real_sender_and_rejects_missing_credential_option() {
    let (root, session) = UnixDatagram::pair().unwrap();
    assert!(receive_packet(&root, credential()).is_err());
    set_passcred(&root, 1).unwrap();
    session.send(&packet()).unwrap();
    let release = receive_packet(&root, credential()).unwrap();
    assert_eq!((release.target.task_id, release.nonce), (1, "3".repeat(32)));
    session.send(&packet()).unwrap();
    let mut wrong = credential();
    wrong.pid += 1;
    assert!(receive_packet(&root, wrong).is_err());
    root.set_read_timeout(Some(Duration::from_millis(5)))
        .unwrap();
    assert!(
        receive_packet(&root, credential()).is_err(),
        "no hidden replay of the consumed packet"
    );
}

#[test]
fn reservation_rejects_extra_authority_fields_zero_nonce_and_wrong_destination() {
    let (root, session) = UnixDatagram::pair().unwrap();
    set_passcred(&root, 1).unwrap();
    for (field, value) in [
        ("current_cut", serde_json::json!("untrusted")),
        ("nonce", serde_json::json!("0".repeat(32))),
        ("nonce", serde_json::json!("A".repeat(32))),
        ("destination_id", serde_json::json!("another-target")),
    ] {
        let mut frame: serde_json::Value = serde_json::from_slice(&packet()).unwrap();
        frame[field] = value;
        session.send(&serde_json::to_vec(&frame).unwrap()).unwrap();
        assert!(receive_packet(&root, credential()).is_err());
    }
    let mut frame: serde_json::Value = serde_json::from_slice(&packet()).unwrap();
    frame["target"]["task_id"] = serde_json::json!(2);
    let target: NotesTargetIdentity = serde_json::from_value(frame["target"].clone()).unwrap();
    frame["destination_id"] = serde_json::json!(target.destination_id());
    session.send(&serde_json::to_vec(&frame).unwrap()).unwrap();
    assert!(
        receive_packet(&root, credential()).is_err(),
        "a self-consistent noninitial task still cannot be attached"
    );
}

#[test]
fn reservation_closes_unexpected_rights_and_disables_credentials_for_original_offer() {
    let (root, session) = UnixDatagram::pair().unwrap();
    set_passcred(&root, 1).unwrap();
    let (right, mut peer) = UnixStream::pair().unwrap();
    send_rights(&session, &packet(), &[right.as_raw_fd()]);
    drop(right);
    assert!(receive_packet(&root, credential()).is_err());
    peer.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
    assert_eq!(
        peer.read(&mut [0]).unwrap(),
        0,
        "unexpected effect rights close on refusal"
    );

    // This is the same socket option shared by Agentd's inherited duplicate.
    set_passcred(&root, 0).unwrap();
    let root = root.try_clone().unwrap();
    let first = tempfile::tempfile().unwrap();
    let second = tempfile::tempfile().unwrap();
    send_rights(
        &session,
        b"original-offer",
        &[first.as_raw_fd(), second.as_raw_fd()],
    );
    let mut bytes = [0_u8; 64];
    let mut control = [0_usize; 32];
    let mut vector = libc::iovec {
        iov_base: bytes.as_mut_ptr().cast(),
        iov_len: bytes.len(),
    };
    // SAFETY: recvmsg's pointers refer only to these retained bounded buffers.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    message.msg_controllen = mem::size_of_val(&control);
    assert_eq!(
        unsafe { libc::recvmsg(root.as_raw_fd(), &mut message, libc::MSG_CMSG_CLOEXEC) },
        14
    );
    // SAFETY: the completed recvmsg's aligned buffer remains alive and no
    // returned descriptor has previously been adopted.
    let (rights, valid) = unsafe { crate::notes_bootstrap::received_descriptors(&message) };
    assert_eq!(
        (rights.len(), valid),
        (2, true),
        "original strict two-right parser receives no extra credential"
    );
}

fn send_rights(socket: &UnixDatagram, bytes: &[u8], rights: &[i32]) {
    let mut control = [0_usize; 32];
    let length = mem::size_of_val(rights);
    let mut vector = libc::iovec {
        iov_base: bytes.as_ptr().cast_mut().cast(),
        iov_len: bytes.len(),
    };
    // SAFETY: all message buffers remain live and bounded until sendmsg returns.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    message.msg_controllen = unsafe { libc::CMSG_SPACE(length as u32) } as usize;
    assert!(message.msg_controllen <= mem::size_of_val(&control));
    // SAFETY: the header and borrowed rights fit in the aligned retained buffer.
    unsafe {
        let header = libc::CMSG_FIRSTHDR(&message);
        (*header).cmsg_level = libc::SOL_SOCKET;
        (*header).cmsg_type = libc::SCM_RIGHTS;
        (*header).cmsg_len = libc::CMSG_LEN(length as u32) as usize;
        std::ptr::copy_nonoverlapping(
            rights.as_ptr(),
            libc::CMSG_DATA(header).cast(),
            rights.len(),
        );
        assert_eq!(
            libc::sendmsg(socket.as_raw_fd(), &message, libc::MSG_NOSIGNAL),
            bytes.len() as isize
        );
    }
}
