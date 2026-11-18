//! Actual socket/pidfd framing, without a Root session or authority bootstrap.
//! The caller's remaining deadline must bound all I/O even though the stream's
//! original single-frame maximum is larger.

use super::OriginalPublicationStream;
use pretty_assertions::assert_eq;
use std::io::Read;
use std::io::Write;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::time::Duration;
use std::time::Instant;

fn pair() -> anyhow::Result<(OriginalPublicationStream, UnixStream)> {
    let (stream, peer) = UnixStream::pair()?;
    stream.set_nonblocking(true)?;
    // SAFETY: the kernel creates a new owned pidfd for this actual live test
    // process. No Root identity or authority is constructed by this test.
    let descriptor = unsafe {
        libc::syscall(libc::SYS_pidfd_open, std::process::id(), /*flags*/ 0)
    };
    anyhow::ensure!(
        descriptor >= 0,
        "actual test pidfd: {}",
        std::io::Error::last_os_error()
    );
    // SAFETY: only this newly returned descriptor is adopted exactly once.
    let root = unsafe { OwnedFd::from_raw_fd(descriptor as i32) };
    Ok((
        OriginalPublicationStream {
            stream,
            root,
            timeout: Duration::from_millis(500),
            end: Instant::now() + Duration::from_secs(5),
        },
        peer,
    ))
}

#[test]
fn initial_frame_expired_queue_end_sends_no_bytes() -> anyhow::Result<()> {
    let (mut stream, mut peer) = pair()?;
    assert!(
        stream
            .exchange_until(b"original-request", Instant::now())
            .is_err()
    );
    peer.set_nonblocking(true)?;
    assert_eq!(
        peer.read(&mut [0; 1])
            .expect_err("no expired request")
            .kind(),
        std::io::ErrorKind::WouldBlock
    );
    Ok(())
}

#[test]
fn initial_frame_late_reply_cannot_renew_the_supplied_queue_deadline() -> anyhow::Result<()> {
    let (mut stream, mut peer) = pair()?;
    let started = Instant::now();
    let original_end = started + Duration::from_millis(60);
    let late_reply = original_end + Duration::from_millis(60);
    let server = std::thread::spawn(move || -> anyhow::Result<UnixStream> {
        peer.set_read_timeout(Some(Duration::from_secs(2)))?;
        let mut prefix = [0; 4];
        peer.read_exact(&mut prefix)?;
        let size = u32::from_be_bytes(prefix) as usize;
        anyhow::ensure!(size <= 16_384, "bounded test request");
        let mut request = vec![0; size];
        peer.read_exact(&mut request)?;
        assert_eq!(request.as_slice(), b"original-request");
        let (_keep_open, wait) = crossbeam_channel::bounded::<()>(/*cap*/ 0);
        assert!(matches!(
            wait.recv_deadline(late_reply),
            Err(crossbeam_channel::RecvTimeoutError::Timeout)
        ));
        let actual = Instant::now();
        anyhow::ensure!(
            actual >= original_end && actual < started + Duration::from_millis(400),
            "late reply must precede the larger stream frame limit"
        );
        peer.write_all(&3u32.to_be_bytes())?;
        peer.write_all(b"old")?;
        Ok(peer)
    });
    let result = stream.exchange_until(b"original-request", original_end);
    let mut peer = server.join().expect("actual framing server")?;
    assert!(
        result.is_err(),
        "a fresh per-I/O timeout must not admit the late response"
    );
    assert!(
        stream
            .exchange_until(b"second-request", original_end)
            .is_err()
    );
    peer.set_nonblocking(true)?;
    assert_eq!(
        peer.read(&mut [0; 1])
            .expect_err("no second request")
            .kind(),
        std::io::ErrorKind::WouldBlock
    );
    Ok(())
}

fn consume_original_request(peer: &mut UnixStream) -> anyhow::Result<()> {
    peer.set_read_timeout(Some(Duration::from_secs(2)))?;
    let mut prefix = [0; 4];
    peer.read_exact(&mut prefix)?;
    let size = u32::from_be_bytes(prefix) as usize;
    anyhow::ensure!(size <= 16_384, "bounded original test request");
    let mut request = vec![0; size];
    peer.read_exact(&mut request)?;
    assert_eq!(request.as_slice(), b"original-request");
    Ok(())
}

#[test]
fn initial_frame_task_capacity_transfers_complete_large_response() -> anyhow::Result<()> {
    let bound = crate::root_historical_task_read_protocol::TASK_RESPONSE_BOUND;
    assert!(bound > 16_384 && bound <= 65_536);
    let expected = vec![b'T'; bound];
    let response = expected.clone();
    let (mut stream, mut peer) = pair()?;
    let server = std::thread::spawn(move || -> anyhow::Result<UnixStream> {
        consume_original_request(&mut peer)?;
        peer.write_all(&(response.len() as u32).to_be_bytes())?;
        peer.write_all(&response)?;
        Ok(peer)
    });
    let actual = stream.exchange_with_response_bound(b"original-request", bound);
    let _peer = server.join().expect("actual bounded framing server")?;
    assert_eq!(actual?, expected);
    Ok(())
}

#[test]
fn initial_frame_default_and_task_caps_reject_prefix_before_body() -> anyhow::Result<()> {
    let task_bound = crate::root_historical_task_read_protocol::TASK_RESPONSE_BOUND;
    for (length, selected_task) in [(16_384 + 1, false), (task_bound + 1, true), (0, true)] {
        let (mut stream, mut peer) = pair()?;
        let server = std::thread::spawn(move || -> anyhow::Result<UnixStream> {
            consume_original_request(&mut peer)?;
            // No response body is sent. Rejection must come from the prefix,
            // before allocating or waiting for the peer's claimed body.
            peer.write_all(&(length as u32).to_be_bytes())?;
            Ok(peer)
        });
        let actual = if selected_task {
            stream.exchange_with_response_bound(b"original-request", task_bound)
        } else {
            stream.exchange(b"original-request")
        };
        let _peer = server.join().expect("actual rejected-prefix server")?;
        let error = actual.expect_err("response prefix must be rejected");
        assert!(
            error.to_string().contains("response frame length rejected"),
            "{error}"
        );
    }
    Ok(())
}

#[test]
fn initial_frame_task_capacity_preserves_request_deadline_and_policy_caps() -> anyhow::Result<()> {
    let task_bound = crate::root_historical_task_read_protocol::TASK_RESPONSE_BOUND;
    for invalid_bound in [0, 65_536 + 1] {
        let (mut stream, mut peer) = pair()?;
        assert!(
            stream
                .exchange_with_response_bound(b"original-request", invalid_bound)
                .is_err()
        );
        peer.set_nonblocking(true)?;
        assert_eq!(
            peer.read(&mut [0; 1])
                .expect_err("no invalid-capacity request")
                .kind(),
            std::io::ErrorKind::WouldBlock
        );
    }
    let (mut stream, mut peer) = pair()?;
    assert!(
        stream
            .exchange_with_response_bound(&vec![b'Q'; 16_384 + 1], task_bound)
            .is_err()
    );
    assert!(
        stream
            .exchange_until_with_response_bound(b"original-request", Instant::now(), task_bound)
            .is_err()
    );
    peer.set_nonblocking(true)?;
    assert_eq!(
        peer.read(&mut [0; 1])
            .expect_err("no oversized or expired request")
            .kind(),
        std::io::ErrorKind::WouldBlock
    );
    Ok(())
}
