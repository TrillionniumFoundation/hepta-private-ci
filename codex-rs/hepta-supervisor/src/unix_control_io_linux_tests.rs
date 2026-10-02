use std::io;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::net::UnixListener;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::sync::mpsc;
use std::thread;
use std::time::Duration;

use pretty_assertions::assert_eq;

use super::exchange_frame;

fn queued_connection(path: &Path) -> io::Result<UnixStream> {
    // SAFETY: fixed Unix stream type; the returned descriptor is newly owned.
    let descriptor = unsafe {
        libc::socket(
            libc::AF_UNIX,
            libc::SOCK_STREAM | libc::SOCK_NONBLOCK | libc::SOCK_CLOEXEC,
            /*protocol*/ 0,
        )
    };
    if descriptor < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: successful socket transfers ownership to the stream guard.
    let stream = unsafe { UnixStream::from_raw_fd(descriptor) };
    // SAFETY: sockaddr_un is entirely integer/array fields.
    let mut address: libc::sockaddr_un = unsafe { std::mem::zeroed() };
    let bytes = path.as_os_str().as_bytes();
    assert!(bytes.len() < address.sun_path.len());
    address.sun_family = libc::AF_UNIX as libc::sa_family_t;
    for (destination, source) in address.sun_path.iter_mut().zip(bytes) {
        *destination = *source as libc::c_char;
    }
    let length = std::mem::offset_of!(libc::sockaddr_un, sun_path) + bytes.len() + 1;
    // SAFETY: initialized NUL-terminated address and its matching length.
    if unsafe {
        libc::connect(
            descriptor,
            std::ptr::addr_of!(address).cast(),
            length as libc::socklen_t,
        )
    } < 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok(stream)
}

#[test]
fn full_unix_accept_backlog_cannot_hold_the_lifecycle_transport()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::Builder::new()
        .prefix("hsup-queue-")
        .tempdir_in("/tmp")?;
    let path = temp.path().join("control.sock");
    let listener = UnixListener::bind(&path)?;
    // SAFETY: this owned listener is already bound; a tiny backlog is deliberate.
    if unsafe {
        libc::listen(listener.as_raw_fd(), /*backlog*/ 1)
    } < 0
    {
        return Err(io::Error::last_os_error().into());
    }
    let mut queued = Vec::new();
    let mut saturated = false;
    for _ in 0..8 {
        match queued_connection(&path) {
            Ok(connection) => queued.push(connection),
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                saturated = true;
                break;
            }
            Err(error) => return Err(error.into()),
        }
    }
    assert!(saturated, "the real Linux accept queue must be full");
    let (sender, receiver) = mpsc::channel();
    let worker = thread::spawn(move || {
        let result = exchange_frame(
            &path,
            std::process::id(),
            b"request\n",
            /*maximum*/ 64,
            Duration::from_millis(200),
        );
        let _ = sender.send(result);
    });
    let result = receiver.recv_timeout(Duration::from_secs(2));
    // Release the kernel wait even if a regression used a blocking connect.
    // No helper thread or accepted child survives a failing watchdog assertion.
    drop(listener);
    drop(queued);
    worker.join().expect("backlog worker does not panic");
    let error = result
        .expect("backlog exchange exceeded its outer watchdog")
        .expect_err("a full queue cannot connect");
    assert_eq!(error.kind(), io::ErrorKind::WouldBlock);
    Ok(())
}
