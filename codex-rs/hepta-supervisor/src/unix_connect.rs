use std::io;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

/// Bound only connection establishment; callers retain their existing I/O timeouts.
pub(super) fn connect(path: &Path, timeout: Duration) -> io::Result<UnixStream> {
    let deadline = Instant::now().checked_add(timeout).ok_or_else(|| {
        io::Error::new(io::ErrorKind::InvalidInput, "Unix connect timeout overflow")
    })?;
    connect_before_deadline(path, deadline)
}

fn connect_before_deadline(path: &Path, deadline: Instant) -> io::Result<UnixStream> {
    let (address, address_len) = socket_addr(path)?;
    remaining_poll_millis(deadline)?;

    let socket_type = libc::SOCK_STREAM;
    #[cfg(any(
        target_os = "android",
        target_os = "dragonfly",
        target_os = "freebsd",
        target_os = "illumos",
        target_os = "hurd",
        target_os = "linux",
        target_os = "netbsd",
        target_os = "openbsd",
        target_os = "cygwin",
        target_os = "nto",
        target_os = "solaris"
    ))]
    let socket_type = socket_type | libc::SOCK_CLOEXEC;
    // SAFETY: the domain/type are fixed Unix stream constants and use no protocol override.
    let raw = unsafe { libc::socket(libc::AF_UNIX, socket_type, /*protocol*/ 0) };
    if raw < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: socket returned a new, uniquely owned descriptor.
    let owned = unsafe { OwnedFd::from_raw_fd(raw) };
    // Retain atomic CLOEXEC where std uses it, and its fcntl fallback elsewhere.
    // SAFETY: owned keeps this descriptor valid for both fcntl calls.
    let flags = unsafe { libc::fcntl(owned.as_raw_fd(), libc::F_GETFD) };
    if flags < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: the descriptor remains owned and the existing flags are preserved.
    if flags & libc::FD_CLOEXEC == 0
        && unsafe { libc::fcntl(owned.as_raw_fd(), libc::F_SETFD, flags | libc::FD_CLOEXEC) } < 0
    {
        return Err(io::Error::last_os_error());
    }
    #[cfg(any(
        target_vendor = "apple",
        target_os = "dragonfly",
        target_os = "freebsd",
        target_os = "netbsd"
    ))]
    {
        // Match std UnixStream creation: writes must not terminate the process via SIGPIPE.
        let enabled: libc::c_int = 1;
        // SAFETY: the option points to a live c_int with the matching length.
        let result = unsafe {
            libc::setsockopt(
                owned.as_raw_fd(),
                libc::SOL_SOCKET,
                libc::SO_NOSIGPIPE,
                &enabled as *const libc::c_int as *const libc::c_void,
                std::mem::size_of_val(&enabled) as libc::socklen_t,
            )
        };
        if result != 0 {
            return Err(io::Error::last_os_error());
        }
    }
    let stream = UnixStream::from(owned);
    stream.set_nonblocking(/*nonblocking*/ true)?;
    remaining_poll_millis(deadline)?;
    // SAFETY: address is a fully initialized sockaddr_un, address_len was checked, and
    // stream owns the descriptor for the entire call.
    let result = unsafe {
        libc::connect(
            stream.as_raw_fd(),
            &address as *const libc::sockaddr_un as *const libc::sockaddr,
            address_len,
        )
    };
    if result != 0 {
        let error = io::Error::last_os_error();
        if !matches!(
            error.raw_os_error(),
            Some(code)
                if code == libc::EINPROGRESS
                    || code == libc::EALREADY
                    || code == libc::EINTR
        ) {
            // In particular, Linux AF_UNIX EAGAIN did not enqueue a connection.
            // Return it to the existing adoption/health retry policy, never as success.
            return Err(error);
        }
        wait_for_connection(&stream, deadline)?;
    }
    // A writable descriptor and SO_ERROR=0 alone need not mean a connected Unix socket.
    stream.peer_addr()?;
    remaining_poll_millis(deadline)?;
    stream.set_nonblocking(/*nonblocking*/ false)?;
    Ok(stream)
}

fn socket_addr(path: &Path) -> io::Result<(libc::sockaddr_un, libc::socklen_t)> {
    let bytes = path.as_os_str().as_bytes();
    // SAFETY: sockaddr_un consists only of integer/byte fields, all valid when zeroed.
    let mut address: libc::sockaddr_un = unsafe { std::mem::zeroed() };
    address.sun_family = libc::AF_UNIX as libc::sa_family_t;
    if bytes.contains(/*x*/ &0) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "Unix control socket path contains a NUL byte",
        ));
    }
    if bytes.len() >= address.sun_path.len() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "Unix control socket path is too long",
        ));
    }
    for (slot, byte) in address.sun_path.iter_mut().zip(bytes) {
        *slot = *byte as libc::c_char;
    }
    // Follow std 1.95's pathname encoding, including an empty pathname and the
    // platform's sun_path offset. A leading NUL is rejected, not an abstract address.
    let length = std::mem::offset_of!(libc::sockaddr_un, sun_path)
        + bytes.len()
        + usize::from(!bytes.is_empty());
    let length = libc::socklen_t::try_from(length).map_err(|_| {
        io::Error::new(io::ErrorKind::InvalidInput, "Unix socket address overflow")
    })?;
    Ok((address, length))
}

fn wait_for_connection(stream: &UnixStream, deadline: Instant) -> io::Result<()> {
    loop {
        let mut descriptor = libc::pollfd {
            fd: stream.as_raw_fd(),
            events: libc::POLLOUT,
            revents: 0,
        };
        // SAFETY: descriptor is live writable storage for one valid owned socket.
        let result = unsafe {
            libc::poll(
                &mut descriptor,
                /*nfds*/ 1,
                remaining_poll_millis(deadline)?,
            )
        };
        if result < 0 {
            let error = io::Error::last_os_error();
            if error.kind() == io::ErrorKind::Interrupted {
                continue;
            }
            return Err(error);
        }
        if result == 0 {
            // poll rounds to milliseconds; recompute from the same deadline after a
            // short poll or interruption rather than resetting the timeout.
            continue;
        }
        if descriptor.revents & libc::POLLNVAL != 0 {
            return Err(io::Error::from_raw_os_error(libc::EBADF));
        }
        if descriptor.revents & (libc::POLLOUT | libc::POLLERR | libc::POLLHUP) != 0 {
            if let Some(error) = stream.take_error()? {
                return Err(error);
            }
            stream.peer_addr()?;
            return Ok(());
        }
    }
}

fn remaining_poll_millis(deadline: Instant) -> io::Result<libc::c_int> {
    let remaining = deadline
        .checked_duration_since(Instant::now())
        .filter(|duration| !duration.is_zero())
        .ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::TimedOut,
                "Unix control socket connection timed out",
            )
        })?;
    let millis = remaining.as_millis().max(/*other*/ 1);
    Ok(libc::c_int::try_from(millis).unwrap_or(libc::c_int::MAX))
}

#[cfg(test)]
#[path = "unix_connect_tests.rs"]
mod tests;
