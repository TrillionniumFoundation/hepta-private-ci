//! Bind a health/control connection to the task the driver already owns or
//! is independently acquiring. A response's process_id is not peer authority.

use std::io;
use std::os::unix::net::UnixStream;

/// Verify before writing a request. Agentd and Matrixd create their own control
/// listeners; transferring a listener to another task is outside this contract.
/// This check does not replace the lifetime reference or the wire identity proof.
pub(super) fn ensure_process_peer(stream: &UnixStream, expected: u32) -> io::Result<()> {
    let expected = super::process_ref::checked_pid(expected)?;
    let actual = peer_pid(stream)?;
    if actual != expected {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "control socket peer does not match the managed process",
        ));
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn peer_pid(stream: &UnixStream) -> io::Result<libc::pid_t> {
    use std::os::fd::AsRawFd;

    let mut credentials = libc::ucred {
        pid: 0,
        uid: 0,
        gid: 0,
    };
    let expected_size = std::mem::size_of::<libc::ucred>() as libc::socklen_t;
    let mut size = expected_size;
    // SAFETY: one live AF_UNIX stream and correctly sized initialized writable
    // credentials/length storage; getsockopt does not retain either pointer.
    let result = unsafe {
        libc::getsockopt(
            stream.as_raw_fd(),
            libc::SOL_SOCKET,
            libc::SO_PEERCRED,
            std::ptr::addr_of_mut!(credentials).cast(),
            &mut size,
        )
    };
    if result != 0 {
        return Err(io::Error::last_os_error());
    }
    if size != expected_size || credentials.pid <= 0 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "invalid socket peer credentials",
        ));
    }
    Ok(credentials.pid)
}

#[cfg(target_os = "macos")]
fn peer_pid(stream: &UnixStream) -> io::Result<libc::pid_t> {
    use std::os::fd::AsRawFd;

    let mut pid: libc::pid_t = 0;
    let expected_size = std::mem::size_of::<libc::pid_t>() as libc::socklen_t;
    let mut size = expected_size;
    // SAFETY: one live AF_UNIX stream and initialized pid_t/length storage.
    // LOCAL_PEERPID returns the connected peer socket's kernel process ID.
    let result = unsafe {
        libc::getsockopt(
            stream.as_raw_fd(),
            libc::SOL_LOCAL,
            libc::LOCAL_PEERPID,
            std::ptr::addr_of_mut!(pid).cast(),
            &mut size,
        )
    };
    if result != 0 {
        return Err(io::Error::last_os_error());
    }
    if size != expected_size || pid <= 0 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "invalid socket peer process ID",
        ));
    }
    Ok(pid)
}

#[cfg(not(any(target_os = "linux", target_os = "macos")))]
fn peer_pid(_stream: &UnixStream) -> io::Result<libc::pid_t> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "this host cannot bind a control socket to a managed process",
    ))
}
