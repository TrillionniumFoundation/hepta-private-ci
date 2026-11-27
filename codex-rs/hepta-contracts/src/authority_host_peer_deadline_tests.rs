//! Real framed sockets and pidfds; no caller-created deadline can renew a frame.

use std::io::Read;
use std::io::Write;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;

use super::*;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

fn channel() -> Result<(HostAuthorityPeerChannel, UnixStream)> {
    let (server, client) = UnixStream::pair()?;
    let pid = rustix::process::getpid();
    let owner = rustix::process::pidfd_open(pid, rustix::process::PidfdFlags::empty())?;
    let server = HostAuthorityPeerChannel::from_stream(
        server,
        HostAuthorityPeerPolicy {
            peer: HostIssuerPeer {
                uid: rustix::process::getuid().as_raw(),
                pid: pid.as_raw_nonzero().get() as u32,
            },
            timeout: Duration::from_millis(500),
            lifetime: Duration::from_secs(3),
            request_bound: 32,
            response_bound: 32,
        },
        owner,
    )?;
    Ok((server, client))
}

fn send(peer: &mut UnixStream) -> Result<()> {
    peer.write_all(&4_u32.to_be_bytes())?;
    peer.write_all(b"once")?;
    Ok(())
}

#[test]
fn durable_handler_receives_the_original_clamped_frame_deadline() -> Result<()> {
    let (mut server, mut peer) = channel()?;
    let end = Instant::now() + Duration::from_millis(300);
    server.limit_original_end(end)?;
    send(&mut peer)?;
    assert!(server.exchange_with_original_deadline(|request, deadline| {
        assert_eq!(request, b"once");
        assert_eq!(deadline, end);
        Ok(b"done".to_vec())
    })?);
    let mut reply = [0; 8];
    peer.read_exact(&mut reply)?;
    assert_eq!(&reply, b"\0\0\0\x04done");
    Ok(())
}

#[test]
fn durable_handler_cannot_emit_success_after_the_shared_frame_deadline() -> Result<()> {
    let (mut server, mut peer) = channel()?;
    let end = Instant::now() + Duration::from_millis(60);
    server.limit_original_end(end)?;
    send(&mut peer)?;
    assert_eq!(
        server.exchange_with_original_deadline(|_, deadline| {
            assert_eq!(deadline, end);
            if let Some(remaining) = deadline.checked_duration_since(Instant::now()) {
                std::thread::sleep(remaining + Duration::from_millis(5));
            }
            Ok(b"late".to_vec())
        }),
        Err(HostIssuerTransportError::DeadlineElapsed)
    );
    let mut reply = Vec::new();
    peer.read_to_end(&mut reply)?;
    assert!(reply.is_empty());
    let repeated = AtomicBool::new(false);
    assert_eq!(
        server.exchange_with_original_deadline(|_, _| {
            repeated.store(true, Ordering::SeqCst);
            Ok(b"retry".to_vec())
        }),
        Err(HostIssuerTransportError::Closed)
    );
    assert!(!repeated.load(Ordering::SeqCst));
    Ok(())
}

#[test]
fn durable_handler_is_not_entered_for_an_invalid_original_frame() -> Result<()> {
    let (mut server, mut peer) = channel()?;
    peer.write_all(&33_u32.to_be_bytes())?;
    let called = AtomicBool::new(false);
    assert_eq!(
        server.exchange_with_original_deadline(|_, _| {
            called.store(true, Ordering::SeqCst);
            Ok(b"unused".to_vec())
        }),
        Err(HostIssuerTransportError::InvalidRequest)
    );
    assert!(!called.load(Ordering::SeqCst));
    let mut reply = Vec::new();
    peer.read_to_end(&mut reply)?;
    assert!(reply.is_empty());
    Ok(())
}
