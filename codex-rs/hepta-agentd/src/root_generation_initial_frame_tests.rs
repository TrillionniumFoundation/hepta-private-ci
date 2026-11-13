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
