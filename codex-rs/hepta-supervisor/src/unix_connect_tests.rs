use std::ffi::OsStr;
use std::io;
use std::io::Read;
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::net::SocketAddr;
use std::os::unix::net::UnixListener;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::Instant;

use pretty_assertions::assert_eq;

use super::connect;
use super::connect_before_deadline;
use super::socket_addr;
use super::wait_for_connection;
use crate::unix::HEALTH_PROBE_IO_TIMEOUT;

#[test]
fn connects_to_owned_listener_with_blocking_cloexec_stream() -> io::Result<()> {
    let directory = tempfile::Builder::new()
        .prefix("hsup-connect-")
        .tempdir_in("/tmp")?;
    let path = directory.path().join("control.sock");
    let listener = UnixListener::bind(&path)?;
    listener.set_nonblocking(/*nonblocking*/ true)?;
    let mut client = connect(&path, HEALTH_PROBE_IO_TIMEOUT)?;
    let (mut server, _) = listener.accept()?;
    client.set_write_timeout(Some(HEALTH_PROBE_IO_TIMEOUT))?;
    server.set_read_timeout(Some(HEALTH_PROBE_IO_TIMEOUT))?;

    // SAFETY: client owns a live descriptor for both read-only flag queries.
    let (status_flags, descriptor_flags) = unsafe {
        (
            libc::fcntl(client.as_raw_fd(), libc::F_GETFL),
            libc::fcntl(client.as_raw_fd(), libc::F_GETFD),
        )
    };
    assert!(status_flags >= 0 && descriptor_flags >= 0);
    let peer = client.peer_addr()?;
    assert_eq!(
        (
            status_flags & libc::O_NONBLOCK,
            descriptor_flags & libc::FD_CLOEXEC,
            peer.as_pathname(),
        ),
        (0, libc::FD_CLOEXEC, Some(path.as_path())),
    );
    client.write_all(b"probe")?;
    let mut observed = [0_u8; 5];
    server.read_exact(&mut observed)?;
    assert_eq!(&observed, b"probe");
    Ok(())
}

#[test]
fn refused_owned_listener_preserves_connection_refused() -> io::Result<()> {
    let directory = tempfile::Builder::new()
        .prefix("hsup-connect-")
        .tempdir_in("/tmp")?;
    let path = directory.path().join("control.sock");
    let listener = UnixListener::bind(&path)?;
    drop(listener);
    let error = connect(&path, HEALTH_PROBE_IO_TIMEOUT).expect_err("listener was closed");
    assert_eq!(error.kind(), io::ErrorKind::ConnectionRefused);
    Ok(())
}

#[cfg(any(target_os = "linux", target_os = "android"))]
#[test]
fn full_owned_listener_backlog_returns_eagain_without_fake_connection() -> io::Result<()> {
    let directory = tempfile::Builder::new()
        .prefix("hsup-connect-")
        .tempdir_in("/tmp")?;
    let path = directory.path().join("control.sock");
    let listener = UnixListener::bind(&path)?;
    listener.set_nonblocking(/*nonblocking*/ true)?;
    // SAFETY: this test owns the listener; zero backlog permits one queued Linux
    // AF_UNIX stream and the test never changes another process's listener.
    if unsafe { libc::listen(listener.as_raw_fd(), /*backlog*/ 0) } != 0 {
        return Err(io::Error::last_os_error());
    }
    let _first_client = connect(&path, HEALTH_PROBE_IO_TIMEOUT)?;
    let error = connect(&path, HEALTH_PROBE_IO_TIMEOUT).expect_err("listen queue is full");
    assert_eq!(error.raw_os_error(), Some(libc::EAGAIN));
    let _accepted = listener.accept()?;
    assert_eq!(
        listener.accept().expect_err("no second connection").kind(),
        io::ErrorKind::WouldBlock,
    );
    Ok(())
}

#[test]
fn expired_connect_deadline_does_not_enqueue_a_connection() -> io::Result<()> {
    let directory = tempfile::Builder::new()
        .prefix("hsup-connect-")
        .tempdir_in("/tmp")?;
    let path = directory.path().join("control.sock");
    let listener = UnixListener::bind(&path)?;
    listener.set_nonblocking(/*nonblocking*/ true)?;
    let error =
        connect_before_deadline(&path, Instant::now()).expect_err("deadline already expired");
    assert_eq!(error.kind(), io::ErrorKind::TimedOut);
    assert_eq!(
        listener.accept().expect_err("no connection attempted").kind(),
        io::ErrorKind::WouldBlock,
    );
    Ok(())
}

#[test]
fn pathname_validation_matches_std_and_rejects_abstract_entry() {
    let (empty, _) = socket_addr(Path::new("")).expect("std permits an empty pathname encoding");
    let capacity = empty.sun_path.len();
    for bytes in [
        Vec::new(),
        b"control.sock".to_vec(),
        vec![b'x'; capacity - 1],
        vec![b'x'; capacity],
        b"control\0socket".to_vec(),
        b"\0abstract".to_vec(),
    ] {
        let path = Path::new(OsStr::from_bytes(&bytes));
        let actual = socket_addr(path);
        let expected = SocketAddr::from_pathname(path);
        assert_eq!(
            actual.as_ref().err().map(io::Error::kind),
            expected.as_ref().err().map(io::Error::kind),
            "pathname bytes: {bytes:?}",
        );
    }
}

#[test]
fn poll_uses_the_existing_deadline_when_owned_socket_stays_unwritable() -> io::Result<()> {
    let (mut client, _peer) = UnixStream::pair()?;
    client.set_nonblocking(/*nonblocking*/ true)?;
    let mut full = false;
    // The peer is owned and never reads. Cap setup work instead of relying on an
    // unbounded fill loop or changing any process-wide resource setting.
    for _ in 0..1_024 {
        match client.write(&[0_u8; 4_096]) {
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                full = true;
                break;
            }
            Err(error) if error.kind() == io::ErrorKind::Interrupted => {}
            Err(error) => return Err(error),
            Ok(_) => {}
        }
    }
    assert!(full, "owned socket must be unwritable for the deadline control");
    let deadline = Instant::now() + HEALTH_PROBE_IO_TIMEOUT;
    let error = wait_for_connection(&client, deadline).expect_err("peer does not drain the socket");
    assert_eq!(error.kind(), io::ErrorKind::TimedOut);
    assert!(Instant::now() >= deadline);
    Ok(())
}
