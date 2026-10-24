use super::*;
use pretty_assertions::assert_eq;
use std::io::Read;
use std::io::Write;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

fn channel(bound: usize) -> (HostAuthorityPeerChannel, UnixStream) {
    let (server, client) = UnixStream::pair().unwrap();
    let pid = rustix::process::getpid();
    let owner = rustix::process::pidfd_open(pid, rustix::process::PidfdFlags::empty()).unwrap();
    let server = HostAuthorityPeerChannel::from_stream(
        server,
        HostAuthorityPeerPolicy {
            peer: HostIssuerPeer {
                uid: rustix::process::getuid().as_raw(),
                pid: pid.as_raw_nonzero().get() as u32,
            },
            timeout: Duration::from_millis(100),
            lifetime: Duration::from_secs(3),
            request_bound: bound,
            response_bound: bound,
        },
        owner,
    )
    .unwrap();
    (server, client)
}

fn send(stream: &mut UnixStream, bytes: &[u8]) {
    stream
        .write_all(&(bytes.len() as u32).to_be_bytes())
        .unwrap();
    stream.write_all(bytes).unwrap();
}

#[test]
fn purpose_bound_rejects_request_before_handler_and_is_permanently_closed() {
    let (mut server, mut client) = channel(16);
    send(&mut client, &[0; 17]);
    let called = AtomicBool::new(false);
    assert_eq!(
        server.exchange(|_| {
            called.store(true, Ordering::SeqCst);
            Ok(b"unused".to_vec())
        }),
        Err(HostIssuerTransportError::InvalidRequest)
    );
    assert!(!called.load(Ordering::SeqCst));
    assert_eq!(
        server.exchange(|_| unreachable!()),
        Err(HostIssuerTransportError::Closed)
    );
}

#[test]
fn oversized_complete_response_emits_no_success_prefix() {
    let (mut server, mut client) = channel(16);
    send(&mut client, b"read");
    assert_eq!(
        server.exchange(|_| Ok(vec![0; 17])),
        Err(HostIssuerTransportError::Unavailable)
    );
    let mut response = Vec::new();
    client.read_to_end(&mut response).unwrap();
    assert!(response.is_empty());
}

#[test]
fn ordinary_complete_denial_can_be_followed_by_a_bounded_response() {
    let (mut server, mut client) = channel(32);
    let peer = std::thread::spawn(move || {
        for expected in [b"denied".as_slice(), b"allowed".as_slice()] {
            send(&mut client, b"request");
            let mut length = [0; 4];
            client.read_exact(&mut length).unwrap();
            let mut response = vec![0; u32::from_be_bytes(length) as usize];
            client.read_exact(&mut response).unwrap();
            assert_eq!(response, expected);
        }
    });
    for response in [b"denied".as_slice(), b"allowed".as_slice()] {
        assert_eq!(server.exchange(|_| Ok(response.to_vec())), Ok(true));
    }
    peer.join().unwrap();
}

#[test]
fn handler_finishing_after_total_deadline_cannot_emit_success() {
    let (mut server, mut client) = channel(32);
    send(&mut client, b"request");
    assert_eq!(
        server.exchange(|_| {
            std::thread::sleep(Duration::from_millis(200));
            Ok(b"late".to_vec())
        }),
        Err(HostIssuerTransportError::DeadlineElapsed)
    );
    let mut response = Vec::new();
    client.read_to_end(&mut response).unwrap();
    assert!(response.is_empty());
}

#[test]
fn pinned_client_preserves_complete_request_response_boundaries() {
    let (mut client, mut peer) = channel(32);
    let server = std::thread::spawn(move || {
        for expected in [b"first".as_slice(), b"second".as_slice()] {
            let mut length = [0; 4];
            peer.read_exact(&mut length).unwrap();
            let mut request = vec![0; u32::from_be_bytes(length) as usize];
            peer.read_exact(&mut request).unwrap();
            assert_eq!(request, expected);
            send(&mut peer, expected);
        }
    });
    assert_eq!(client.request(b"first"), Ok(b"first".to_vec()));
    assert_eq!(client.request(b"second"), Ok(b"second".to_vec()));
    server.join().unwrap();
}

#[test]
fn pinned_client_invalid_input_emits_nothing_and_closes() {
    for request in [Vec::new(), vec![0; 17]] {
        let (mut client, mut peer) = channel(16);
        assert_eq!(
            client.request(&request),
            Err(HostIssuerTransportError::InvalidRequest)
        );
        let mut bytes = Vec::new();
        peer.read_to_end(&mut bytes).unwrap();
        assert!(bytes.is_empty());
        assert_eq!(
            client.request(b"retry"),
            Err(HostIssuerTransportError::Closed)
        );
    }
}

#[test]
fn pinned_client_rejects_truncated_oversized_and_late_replies_without_retry() {
    for reply in [Vec::new(), vec![0, 0, 0, 4, 1, 2], vec![0, 0, 0, 33]] {
        let (mut client, mut peer) = channel(32);
        let server = std::thread::spawn(move || {
            let mut request = [0; 8];
            peer.read_exact(&mut request).unwrap();
            assert_eq!(&request[4..], b"once");
            peer.write_all(&reply).unwrap();
        });
        assert!(client.request(b"once").is_err());
        assert_eq!(client.request(b"once"), Err(HostIssuerTransportError::Closed));
        server.join().unwrap();
    }
    let (mut client, _silent_peer) = channel(32);
    assert_eq!(
        client.request(b"once"),
        Err(HostIssuerTransportError::DeadlineElapsed)
    );
    assert_eq!(client.request(b"once"), Err(HostIssuerTransportError::Closed));
}
