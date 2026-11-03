//! Kernel-authenticated process identity for owner-local lifecycle probes.
//! Linux and Apple peers are supported; other Unix platforms return Unsupported
//! rather than trusting response fields or transmitting a lifecycle request.

use std::io;
use std::os::unix::net::UnixStream;

pub(super) fn ensure_process_owner(stream: &UnixStream, expected_pid: u32) -> io::Result<()> {
    let (pid, uid) = peer_credentials(stream)?;
    // SAFETY: geteuid takes no arguments and has no preconditions.
    if pid <= 0
        || u32::try_from(pid).ok() != Some(expected_pid)
        || uid != unsafe { libc::geteuid() }
    {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "control socket peer does not match the expected process and owner",
        ));
    }
    Ok(())
}

#[cfg(any(target_os = "linux", target_os = "android"))]
fn peer_credentials(stream: &UnixStream) -> io::Result<(libc::pid_t, libc::uid_t)> {
    use std::os::fd::AsRawFd;

    let mut credentials = libc::ucred {
        pid: 0,
        uid: 0,
        gid: 0,
    };
    let expected_len = std::mem::size_of::<libc::ucred>() as libc::socklen_t;
    let mut len = expected_len;
    // SAFETY: the connected stream owns a live fd and both output pointers
    // refer to correctly sized writable storage for SO_PEERCRED.
    let result = unsafe {
        libc::getsockopt(
            stream.as_raw_fd(),
            libc::SOL_SOCKET,
            libc::SO_PEERCRED,
            std::ptr::addr_of_mut!(credentials).cast(),
            &mut len,
        )
    };
    if result != 0 {
        return Err(io::Error::last_os_error());
    }
    if len != expected_len {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "invalid peer credential length",
        ));
    }
    Ok((credentials.pid, credentials.uid))
}

#[cfg(target_vendor = "apple")]
fn peer_credentials(stream: &UnixStream) -> io::Result<(libc::pid_t, libc::uid_t)> {
    use std::os::fd::AsRawFd;

    let mut pid: libc::pid_t = 0;
    let expected_len = std::mem::size_of::<libc::pid_t>() as libc::socklen_t;
    let mut len = expected_len;
    // SAFETY: the connected stream owns a live fd and the output pointers
    // refer to correctly sized writable storage for LOCAL_PEERPID.
    let result = unsafe {
        libc::getsockopt(
            stream.as_raw_fd(),
            libc::SOL_LOCAL,
            libc::LOCAL_PEERPID,
            std::ptr::addr_of_mut!(pid).cast(),
            &mut len,
        )
    };
    if result != 0 {
        return Err(io::Error::last_os_error());
    }
    if len != expected_len {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "invalid peer PID length",
        ));
    }
    let mut uid = 0;
    let mut gid = 0;
    // SAFETY: uid and gid are writable output values and the fd is live.
    if unsafe { libc::getpeereid(stream.as_raw_fd(), &mut uid, &mut gid) } != 0 {
        return Err(io::Error::last_os_error());
    }
    Ok((pid, uid))
}

#[cfg(not(any(target_os = "linux", target_os = "android", target_vendor = "apple")))]
fn peer_credentials(_stream: &UnixStream) -> io::Result<(libc::pid_t, libc::uid_t)> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "exact control socket peer process identity is unavailable on this platform",
    ))
}
