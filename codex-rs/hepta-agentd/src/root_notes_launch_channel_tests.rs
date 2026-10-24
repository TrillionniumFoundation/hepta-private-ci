//! Actual Linux stream fixtures; no Root role or authority is granted.
use super::*;
use pretty_assertions::assert_eq;
use std::fs::File;
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;

fn fixture(stream: UnixStream) -> RootNotesLaunchChannel {
    let status = std::fs::read_to_string("/proc/self/stat").unwrap();
    let start = status
        .rsplit_once(") ")
        .unwrap()
        .1
        .split_whitespace()
        .nth(19)
        .unwrap()
        .parse()
        .unwrap();
    let root = CognitiveCheckpointPeerLifetime {
        // SAFETY: getter has no pointer or memory preconditions.
        uid: unsafe { libc::geteuid() },
        pid: std::process::id(),
        boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")
            .unwrap()
            .trim()
            .to_owned(),
        process_start_ticks: start,
    };
    // SAFETY: this live test PID and zero flags create an exclusively owned fd.
    let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
    assert!(raw >= 0);
    // SAFETY: successful pidfd_open returned a fresh exclusively owned fd.
    let pidfd = unsafe { OwnedFd::from_raw_fd(raw as i32) };
    // Actual original peer guard, explicitly same-UID component fixture only.
    // Role admission belongs to the production Root/Host wrappers.
    RootNotesLaunchChannel::from_peer_stream(stream, root, pidfd, now().unwrap() + 5_000_000_000)
        .unwrap()
}

fn channels() -> RootNotesLaunchFrame {
    RootNotesLaunchFrame::SessionChannelsV1 {
        schema_version: 1,
        launch_nonce: "1".repeat(32),
    }
}

#[test]
fn real_stream_transfers_exact_descriptors_cloexec_and_preserves_open_files() {
    let (a, b) = UnixStream::pair().unwrap();
    let mut sender = fixture(a);
    let mut receiver = fixture(b);
    let input = [
        File::open("/dev/null").unwrap().into(),
        File::open("/dev/zero").unwrap().into(),
    ];
    let end = now().unwrap() + 1_000_000_000;
    sender.send(&channels(), &input, end).unwrap();
    let (_, fds) = receiver.read(end).unwrap();
    assert_eq!(fds.len(), 2);
    for (input, output) in input.iter().zip(&fds) {
        // SAFETY: borrowed live fd and getter command with no pointer argument.
        assert_ne!(
            unsafe { libc::fcntl(output.as_raw_fd(), libc::F_GETFD) } & libc::FD_CLOEXEC,
            0
        );
        assert_eq!(
            std::fs::read_link(format!("/proc/self/fd/{}", input.as_raw_fd())).unwrap(),
            std::fs::read_link(format!("/proc/self/fd/{}", output.as_raw_fd())).unwrap()
        );
    }
}

fn raw_rights(stream: &UnixStream, raw: &[u8], files: &[OwnedFd]) {
    let mut control = [0usize; 64];
    let mut iov = libc::iovec {
        iov_base: raw.as_ptr().cast_mut().cast(),
        iov_len: raw.len(),
    };
    // SAFETY: all pointers target live aligned buffers for the synchronous call;
    // the test intentionally sends excess rights, all fd owners stay alive.
    unsafe {
        let mut message: libc::msghdr = std::mem::zeroed();
        message.msg_iov = &mut iov;
        message.msg_iovlen = 1;
        message.msg_control = control.as_mut_ptr().cast();
        let size = (files.len() * std::mem::size_of::<libc::c_int>()) as u32;
        message.msg_controllen = libc::CMSG_SPACE(size) as usize;
        let header = libc::CMSG_FIRSTHDR(&message);
        (*header).cmsg_level = libc::SOL_SOCKET;
        (*header).cmsg_type = libc::SCM_RIGHTS;
        (*header).cmsg_len = libc::CMSG_LEN(size) as usize;
        for (index, file) in files.iter().enumerate() {
            libc::CMSG_DATA(header)
                .cast::<libc::c_int>()
                .add(index)
                .write_unaligned(file.as_raw_fd());
        }
        assert_eq!(
            libc::sendmsg(stream.as_raw_fd(), &message, libc::MSG_NOSIGNAL),
            raw.len() as isize
        );
    }
}

#[test]
fn extra_truncated_or_late_rights_fence_the_whole_stream() {
    for count in [1, 3, 40] {
        let (a, b) = UnixStream::pair().unwrap();
        let mut receiver = fixture(b);
        let body = serde_json::to_vec(&channels()).unwrap();
        let mut raw = (body.len() as u32).to_be_bytes().to_vec();
        raw.extend(body);
        let files: Vec<OwnedFd> = (0..count)
            .map(|_| File::open("/dev/null").unwrap().into())
            .collect();
        raw_rights(&a, &raw, &files);
        assert!(receiver.read(now().unwrap() + 1_000_000_000).is_err());
        assert!(receiver.read(now().unwrap() + 1_000_000_000).is_err());
    }
    let (mut a, b) = UnixStream::pair().unwrap();
    let mut receiver = fixture(b);
    let body = serde_json::to_vec(&channels()).unwrap();
    a.write_all(&(body.len() as u32).to_be_bytes()).unwrap();
    raw_rights(
        &a,
        &body,
        &[
            File::open("/dev/null").unwrap().into(),
            File::open("/dev/null").unwrap().into(),
        ],
    );
    assert!(receiver.read(now().unwrap() + 1_000_000_000).is_err());
}

#[test]
fn queued_rights_inside_the_length_header_are_not_first_byte_rights() {
    for prefix_length in [1, 2, 3] {
        let (mut sender, stream) = UnixStream::pair().unwrap();
        let mut receiver = fixture(stream);
        let body = serde_json::to_vec(&channels()).unwrap();
        let mut raw = (body.len() as u32).to_be_bytes().to_vec();
        raw.extend(body);
        sender.write_all(&raw[..prefix_length]).unwrap();
        raw_rights(
            &sender,
            &raw[prefix_length..],
            &[
                File::open("/dev/null").unwrap().into(),
                File::open("/dev/zero").unwrap().into(),
            ],
        );
        // Both writes are queued BEFORE the receiver runs. A four-byte first
        // recvmsg can otherwise coalesce the unadorned prefix with SCM_RIGHTS
        // attached to header byte 2, 3 or 4 and incorrectly call it byte 1.
        assert!(receiver.read(now().unwrap() + 1_000_000_000).is_err());
        assert!(receiver.read(now().unwrap() + 1_000_000_000).is_err());
    }
}

#[test]
fn drip_bytes_do_not_get_a_fresh_budget_and_failure_is_not_retryable() {
    let (mut a, b) = UnixStream::pair().unwrap();
    let mut receiver = fixture(b);
    let end = now().unwrap() + 50_000_000;
    let writer = std::thread::spawn(move || {
        for byte in [0, 0, 0, 100] {
            if a.write_all(&[byte]).is_err() {
                break;
            }
            std::thread::sleep(Duration::from_millis(25));
        }
    });
    assert_eq!(
        receiver.read(end).unwrap_err().kind(),
        io::ErrorKind::TimedOut
    );
    assert!(receiver.read(now().unwrap() + 1_000_000_000).is_err());
    writer.join().unwrap();
}

#[test]
fn invalid_or_oversized_header_closes_without_allocating_a_frame() {
    for length in [0, ROOT_NOTES_LAUNCH_FRAME_BOUND as u32 + 1, u32::MAX] {
        let (mut a, b) = UnixStream::pair().unwrap();
        let mut receiver = fixture(b);
        a.write_all(&length.to_be_bytes()).unwrap();
        assert!(receiver.read(now().unwrap() + 1_000_000_000).is_err());
        assert!(
            receiver
                .send(&channels(), &[], now().unwrap() + 1_000_000_000)
                .is_err()
        );
    }
}

#[test]
fn cancellation_shutdown_alias_interrupts_the_retained_stream() {
    let (mut a, b) = UnixStream::pair().unwrap();
    let mut receiver = fixture(b);
    let cancel = receiver.abort_handle().unwrap();
    let reader = std::thread::spawn(move || receiver.read(now().unwrap() + 1_000_000_000));
    drop(cancel);
    assert!(reader.join().unwrap().is_err());
    assert!(a.write_all(&[1]).is_err());
}

#[test]
fn duplicate_keys_and_unknown_fields_are_not_normalized_through_a_value_map() {
    for body in [
        r#"{"action":"recovered_owner_registered_v1","schema_version":1,"schema_version":1,"launch_nonce":"11111111111111111111111111111111"}"#,
        r#"{"action":"recovered_owner_registered_v1","schema_version":1,"launch_nonce":"11111111111111111111111111111111","current":{}}"#,
    ] {
        let (mut a, b) = UnixStream::pair().unwrap();
        let mut receiver = fixture(b);
        a.write_all(&(body.len() as u32).to_be_bytes()).unwrap();
        a.write_all(body.as_bytes()).unwrap();
        assert!(receiver.read(now().unwrap() + 1_000_000_000).is_err());
    }
}

#[test]
fn mismatched_boot_start_uid_and_pidfd_are_not_accepted() {
    for field in 0..4 {
        let (a, _b) = UnixStream::pair().unwrap();
        let (held, _other) = UnixStream::pair().unwrap();
        let source = fixture(held);
        let mut peer = source.peer.clone();
        match field {
            0 => peer.uid = peer.uid.wrapping_add(1),
            1 => peer.pid = peer.pid.wrapping_add(1),
            2 => peer.process_start_ticks += 1,
            3 => peer.boot_id = "0".repeat(36),
            _ => unreachable!(),
        }
        assert!(
            RootNotesLaunchChannel::from_peer_stream(
                a,
                peer,
                source.pidfd.try_clone().unwrap(),
                source.end
            )
            .is_err()
        );
    }
    let (a, _b) = UnixStream::pair().unwrap();
    let (held, _other) = UnixStream::pair().unwrap();
    let source = fixture(held);
    assert!(
        RootNotesLaunchChannel::from_peer_stream(
            a,
            source.peer.clone(),
            File::open("/dev/null").unwrap().into(),
            source.end
        )
        .is_err()
    );
}

#[test]
fn disarmed_abort_preserves_channel_but_deadline_failure_permanently_closes_it() {
    let (mut sender, stream) = UnixStream::pair().unwrap();
    let mut receiver = fixture(stream);
    receiver.abort_handle().unwrap().disarm();
    let frame = RootNotesLaunchFrame::RecoveredOwnerRegisteredV1 {
        schema_version: 1,
        launch_nonce: "1".repeat(32),
    };
    let body = serde_json::to_vec(&frame).unwrap();
    sender
        .write_all(&(body.len() as u32).to_be_bytes())
        .unwrap();
    sender.write_all(&body).unwrap();
    assert!(receiver.read(now().unwrap() + 1_000_000_000).is_ok());
    assert!(receiver.check(now().unwrap().saturating_sub(1)).is_err());
    assert!(receiver.check(now().unwrap() + 1_000_000_000).is_err());
}

#[test]
fn actual_child_stream_cannot_borrow_the_parent_peer_guard() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("launch.sock");
    let listener = std::os::unix::net::UnixListener::bind(&path).unwrap();
    let mut child = std::process::Command::new("python3")
        .arg("-c").arg("import socket,sys,time; s=socket.socket(socket.AF_UNIX); s.connect(sys.argv[1]); time.sleep(1)")
        .arg(&path).spawn().unwrap();
    let (stream, _) = listener.accept().unwrap();
    let (parent_stream, _other) = UnixStream::pair().unwrap();
    let parent = fixture(parent_stream);
    assert!(
        RootNotesLaunchChannel::from_peer_stream(
            stream.try_clone().unwrap(),
            parent.peer.clone(),
            parent.pidfd.try_clone().unwrap(),
            parent.end
        )
        .is_err()
    );
    let mut peer = parent.peer.clone();
    peer.pid = child.id();
    peer.process_start_ticks = std::fs::read_to_string(format!("/proc/{}/stat", child.id()))
        .unwrap()
        .rsplit_once(") ")
        .unwrap()
        .1
        .split_whitespace()
        .nth(19)
        .unwrap()
        .parse()
        .unwrap();
    // SAFETY: live child PID and zero flags create a fresh owned pidfd.
    let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, child.id(), 0) };
    assert!(raw >= 0);
    // SAFETY: successful syscall returns a new exclusively owned descriptor.
    let pidfd = unsafe { OwnedFd::from_raw_fd(raw as i32) };
    let actual = RootNotesLaunchChannel::from_peer_stream(stream, peer, pidfd, parent.end).unwrap();
    actual.check(parent.end).unwrap();
    assert!(child.wait().unwrap().success());
    assert!(actual.check(parent.end).is_err());
}

#[test]
fn first_byte_starts_a_frame_budget_even_with_a_long_preparation_end() {
    let (mut sender, stream) = UnixStream::pair().unwrap();
    let mut receiver = fixture(stream);
    sender.write_all(&[0]).unwrap();
    let start = std::time::Instant::now();
    assert_eq!(
        receiver
            .read(now().unwrap() + 4_000_000_000)
            .unwrap_err()
            .kind(),
        io::ErrorKind::TimedOut
    );
    assert!(start.elapsed() < Duration::from_secs(2));
    assert!(receiver.read(now().unwrap() + 4_000_000_000).is_err());
}
