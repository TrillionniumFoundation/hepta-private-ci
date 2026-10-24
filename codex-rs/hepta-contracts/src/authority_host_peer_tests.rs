use super::*;
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
