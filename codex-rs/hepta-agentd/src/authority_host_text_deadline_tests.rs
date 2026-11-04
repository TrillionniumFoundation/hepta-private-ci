//! Actual peer-channel framing and time limits only. These tests create no
//! authority, human registration, model turn, writer or external effect.
use super::text_peer_policy;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_contracts::HostIssuerTransportError;
use pretty_assertions::assert_eq;
use std::io::Read;
use std::io::Write;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

fn channel(timeout: Duration, root_remaining: Duration) -> (HostAuthorityPeerChannel, UnixStream) {
    let (server, client) = UnixStream::pair().expect("actual socket pair");
    let pid = std::process::id();
    // SAFETY: getuid reads the current process identity and takes no pointers.
    let uid = unsafe { libc::getuid() };
    // SAFETY: the current test process is alive; pidfd_open receives no pointers.
    let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    assert!(raw >= 0, "pin the actual test process");
    // SAFETY: successful pidfd_open returned precisely this fresh descriptor.
    let owner = unsafe { OwnedFd::from_raw_fd(raw as i32) };
    let policy = text_peer_policy(HostIssuerPeer { uid, pid }, timeout, root_remaining);
    let server = HostAuthorityPeerChannel::from_stream(server, policy, owner)
        .expect("actual same-process peer and held lifetime");
    client
        .set_read_timeout(Some(Duration::from_secs(2)))
        .expect("bound test response observation");
    (server, client)
}

#[test]
fn idle_text_connection_respects_exchange_and_remaining_root_budgets() {
    for (timeout, remaining) in [
        (Duration::from_millis(50), Duration::from_secs(3)),
        (Duration::from_secs(3), Duration::from_millis(50)),
    ] {
        let (mut server, mut client) = channel(timeout, remaining);
        let handled = AtomicBool::new(false);
        let started = Instant::now();
        let result = server.exchange(|_| {
            handled.store(true, Ordering::SeqCst);
            Ok(b"unexpected".to_vec())
        });
        assert_eq!(result, Err(HostIssuerTransportError::DeadlineElapsed));
        assert!(started.elapsed() < Duration::from_secs(2));
        assert!(!handled.load(Ordering::SeqCst));
        let mut response = Vec::new();
        client.read_to_end(&mut response).expect("closed peer");
        assert_eq!(response, Vec::<u8>::new());
        assert_eq!(
            server.exchange(|_| unreachable!()),
            Err(HostIssuerTransportError::Closed)
        );
    }
}

#[test]
fn first_text_byte_does_not_refresh_the_connection_budget() {
    let (mut server, mut client) = channel(Duration::from_millis(400), Duration::from_secs(3));
    let sender = std::thread::spawn(move || {
        std::thread::sleep(Duration::from_millis(200));
        let first = client.write_all(&[0]).is_ok();
        std::thread::sleep(Duration::from_millis(300));
        let remainder_refused = client
            .write_all(&[0, 0, 4, b'r', b'e', b'a', b'd'])
            .is_err();
        (first, remainder_refused)
    });
    let handled = AtomicBool::new(false);
    let result = server.exchange(|_| {
        handled.store(true, Ordering::SeqCst);
        Ok(b"late".to_vec())
    });
    let delivery = sender.join().expect("owned peer completed");
    assert_eq!(result, Err(HostIssuerTransportError::DeadlineElapsed));
    assert_eq!(delivery, (true, true));
    assert!(!handled.load(Ordering::SeqCst));
}

#[test]
fn timely_text_frame_still_uses_the_original_peer_channel() {
    let (mut server, mut client) = channel(Duration::from_secs(1), Duration::from_secs(3));
    client
        .write_all(&4_u32.to_be_bytes())
        .expect("request length");
    client.write_all(b"read").expect("complete request");
    assert_eq!(
        server.exchange(|request| {
            assert_eq!(request, b"read");
            Ok(b"ok".to_vec())
        }),
        Ok(true)
    );
    let mut response = [0; 6];
    client
        .read_exact(&mut response)
        .expect("complete original response");
    assert_eq!(response, [0, 0, 0, 2, b'o', b'k']);
}
