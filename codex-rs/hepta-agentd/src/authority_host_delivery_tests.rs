use super::*;
use codex_hepta_contracts::HostIssuerPeer;
use std::io::Read;
use std::io::Write;
use std::os::fd::FromRawFd;
use std::time::Duration;
use pretty_assertions::assert_eq;

fn channel(stream: UnixStream) -> HostAuthorityPeerChannel {
    // Test-only pre-held pidfd for the actual process owning this socket pair.
    let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
    assert!(raw >= 0);
    let owner = unsafe { OwnedFd::from_raw_fd(raw as i32) };
    HostAuthorityPeerChannel::from_stream(stream, HostAuthorityPeerPolicy {
        peer:HostIssuerPeer { uid:unsafe { libc::getuid() }, pid:std::process::id() },
        timeout:Duration::from_millis(500), lifetime:Duration::from_secs(3),
        request_bound:64, response_bound:64,
    }, owner).unwrap()
}

#[test]
fn cancellation_shuts_real_lane_while_original_handler_is_stalled() {
    let delivery = Arc::new(ServiceDelivery::default());
    let (stream, mut client) = UnixStream::pair().unwrap();
    client.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
    let pin = delivery.register(&stream).unwrap();
    let mut channel = channel(stream);
    let worker_delivery = Arc::clone(&delivery);
    let (entered, waiting) = std::sync::mpsc::sync_channel(0);
    let (release, continue_work) = std::sync::mpsc::sync_channel(0);
    let worker = std::thread::spawn(move || {
        let _pin = pin;
        channel.exchange_with_response_guard(|_| {
            entered.send(()).unwrap();
            continue_work.recv_timeout(Duration::from_secs(2)).unwrap();
            // Model a real committed mutation that cannot be undone. Its late
            // result must not cross the actual framed response boundary.
            Ok(b"late-signed-result".to_vec())
        }, || worker_delivery.response_guard())
    });
    client.write_all(&4u32.to_be_bytes()).unwrap();
    client.write_all(b"sign").unwrap();
    waiting.recv_timeout(Duration::from_secs(1)).unwrap();
    delivery.close();
    let mut response = Vec::new();
    client.read_to_end(&mut response).unwrap();
    assert!(response.is_empty(), "cancel must close before handler is released");
    release.send(()).unwrap();
    assert_eq!(worker.join().unwrap(), Err(HostIssuerTransportError::Closed));
    assert_eq!(delivery.require_open(), Err(HostIssuerTransportError::Closed));
    assert!(delivery.response_guard().is_err());
    let (replacement, _) = UnixStream::pair().unwrap();
    assert!(delivery.register(&replacement).is_err(), "a replacement stream cannot reset failure");
}

#[test]
fn cancellation_closes_every_registered_alias_and_allows_no_new_publication() {
    let delivery = ServiceDelivery::default();
    let mut pins = Vec::new();
    let mut clients = Vec::new();
    for _ in 0..5 {
        let (server, client) = UnixStream::pair().unwrap();
        client.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
        pins.push(delivery.register(&server).unwrap());
        clients.push(client);
    }
    delivery.close();
    delivery.close();
    for client in &mut clients {
        let mut response = Vec::new();
        client.read_to_end(&mut response).unwrap();
        assert!(response.is_empty());
    }
    assert!(delivery.response_guard().is_err());
    drop(pins);
}
