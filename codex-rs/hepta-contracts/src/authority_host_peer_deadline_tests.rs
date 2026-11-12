use super::*;
use pretty_assertions::assert_eq;
use std::io::Read;
use std::io::Write;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

fn original_policy() -> HostAuthorityPeerPolicy {
    HostAuthorityPeerPolicy {
        peer: HostIssuerPeer {
            uid: rustix::process::getuid().as_raw(),
            pid: rustix::process::getpid().as_raw_nonzero().get() as u32,
        },
        timeout: Duration::from_secs(30),
        lifetime: Duration::from_secs(300),
        request_bound: 32,
        response_bound: 32,
    }
}

fn original_pidfd() -> OwnedFd {
    rustix::process::pidfd_open(
        rustix::process::getpid(),
        rustix::process::PidfdFlags::empty(),
    )
    .unwrap()
}

fn original_channel(end: Instant) -> (HostAuthorityPeerChannel, UnixStream) {
    let (stream, peer) = UnixStream::pair().unwrap();
    let channel = HostAuthorityPeerChannel::from_stream_until(
        stream,
        original_policy(),
        original_pidfd(),
        end,
    )
    .unwrap();
    assert_eq!(channel.owner.end(), end);
    (channel, peer)
}

fn after_original_end(end: Instant) {
    std::thread::sleep(end.saturating_duration_since(Instant::now()) + Duration::from_millis(1));
}

#[test]
fn absolute_end_preserves_original_peer_request_and_exact_end() {
    let end = Instant::now() + Duration::from_secs(60);
    let (mut channel, mut peer) = original_channel(end);
    let server = std::thread::spawn(move || {
        let mut request = [0; 8];
        peer.read_exact(&mut request).unwrap();
        assert_eq!(&request[..4], &4_u32.to_be_bytes());
        assert_eq!(&request[4..], b"once");
        peer.write_all(&4_u32.to_be_bytes()).unwrap();
        peer.write_all(b"done").unwrap();
    });
    assert_eq!(channel.request(b"once"), Ok(b"done".to_vec()));
    assert_eq!(channel.owner.end(), end);
    server.join().unwrap();
}

#[test]
fn absolute_end_rejects_expiry_and_both_original_lifetime_bounds() {
    let policy = original_policy();
    let short = HostAuthorityPeerPolicy {
        lifetime: Duration::from_secs(1),
        ..policy
    };
    let zero = HostAuthorityPeerPolicy {
        lifetime: Duration::ZERO,
        ..policy
    };
    let excessive = HostAuthorityPeerPolicy {
        lifetime: Duration::from_secs(301),
        ..policy
    };
    for (policy, end, expected) in [
        (
            policy,
            Instant::now(),
            HostIssuerTransportError::DeadlineElapsed,
        ),
        (
            policy,
            Instant::now() + Duration::from_secs(301),
            HostIssuerTransportError::InvalidConfiguration,
        ),
        (
            short,
            Instant::now() + Duration::from_secs(60),
            HostIssuerTransportError::InvalidConfiguration,
        ),
        (
            zero,
            Instant::now() + Duration::from_secs(60),
            HostIssuerTransportError::InvalidConfiguration,
        ),
        (
            excessive,
            Instant::now() + Duration::from_secs(60),
            HostIssuerTransportError::InvalidConfiguration,
        ),
    ] {
        let (stream, _peer) = UnixStream::pair().unwrap();
        assert_eq!(
            HostAuthorityPeerChannel::from_stream_until(stream, policy, original_pidfd(), end)
                .err(),
            Some(expected)
        );
    }
    assert_eq!(
        OwnerChannel::new_until(
            original_pidfd(),
            policy.peer.pid,
            Instant::now() + Duration::from_secs(301),
        )
        .err(),
        Some(HostIssuerTransportError::InvalidConfiguration)
    );
}

#[test]
fn absolute_end_keeps_socket_peer_and_original_pidfd_validation() {
    let policy = original_policy();
    let end = Instant::now() + Duration::from_secs(60);
    let wrong_peer = HostAuthorityPeerPolicy {
        peer: HostIssuerPeer {
            uid: policy.peer.uid.wrapping_add(1),
            ..policy.peer
        },
        ..policy
    };
    let (stream, _peer) = UnixStream::pair().unwrap();
    assert_eq!(
        HostAuthorityPeerChannel::from_stream_until(stream, wrong_peer, original_pidfd(), end)
            .err(),
        Some(HostIssuerTransportError::PeerDenied)
    );
    let (stream, _peer) = UnixStream::pair().unwrap();
    assert_eq!(
        HostAuthorityPeerChannel::from_stream_until(
            stream,
            policy,
            std::fs::File::open("/dev/null").unwrap().into(),
            end,
        )
        .err(),
        Some(HostIssuerTransportError::InvalidConfiguration)
    );
    assert_eq!(
        OwnerChannel::new_until(original_pidfd(), policy.peer.pid + 1, end).err(),
        Some(HostIssuerTransportError::PeerDenied)
    );
}

#[test]
fn expired_original_end_emits_no_request_and_cannot_rearm() {
    let end = Instant::now() + Duration::from_secs(2);
    let (mut channel, mut peer) = original_channel(end);
    after_original_end(end);
    assert_eq!(
        channel.request(b"once"),
        Err(HostIssuerTransportError::DeadlineElapsed)
    );
    let mut bytes = Vec::new();
    peer.read_to_end(&mut bytes).unwrap();
    assert!(bytes.is_empty());
    assert_eq!(
        channel.request(b"retry"),
        Err(HostIssuerTransportError::Closed)
    );
}

#[test]
fn handler_finishing_after_original_end_emits_no_success_and_cannot_rearm() {
    let end = Instant::now() + Duration::from_secs(2);
    let (mut channel, mut peer) = original_channel(end);
    peer.write_all(&4_u32.to_be_bytes()).unwrap();
    peer.write_all(b"once").unwrap();
    let called = AtomicBool::new(false);
    assert_eq!(
        channel.exchange(|request| {
            assert_eq!(request, b"once");
            called.store(true, Ordering::SeqCst);
            after_original_end(end);
            Ok(b"late".to_vec())
        }),
        Err(HostIssuerTransportError::DeadlineElapsed)
    );
    assert!(called.load(Ordering::SeqCst));
    let mut bytes = Vec::new();
    peer.read_to_end(&mut bytes).unwrap();
    assert!(bytes.is_empty());
    assert_eq!(
        channel.exchange(|_| unreachable!()),
        Err(HostIssuerTransportError::Closed)
    );
}
