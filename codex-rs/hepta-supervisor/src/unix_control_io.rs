//! One elapsed-time budget for an exact-peer control exchange. Successful
//! partial progress never renews the budget or grants process authority.

use std::io;
use std::path::Path;
use std::time::Duration;

#[cfg(any(target_os = "linux", target_os = "macos"))]
mod platform {
    use std::io;
    use std::io::Read;
    use std::net::Shutdown;
    use std::os::fd::AsRawFd;
    use std::os::fd::FromRawFd;
    use std::os::unix::ffi::OsStrExt;
    use std::os::unix::net::UnixStream;
    use std::path::Path;
    use std::time::Duration;
    use std::time::Instant;

    fn remaining(deadline: Instant) -> io::Result<Duration> {
        deadline
            .checked_duration_since(Instant::now())
            .filter(|remaining| !remaining.is_zero())
            .ok_or_else(|| io::Error::new(io::ErrorKind::TimedOut, "control exchange timed out"))
    }

    fn wait(stream: &UnixStream, events: i16, deadline: Instant) -> io::Result<()> {
        loop {
            let duration = remaining(deadline)?;
            let millis =
                duration.as_millis() + u128::from(duration.subsec_nanos() % 1_000_000 != 0);
            let timeout = millis.min(i32::MAX as u128) as i32;
            let mut descriptor = libc::pollfd {
                fd: stream.as_raw_fd(),
                events,
                revents: 0,
            };
            // SAFETY: one initialized descriptor and a finite remaining timeout.
            let result = unsafe {
                libc::poll(&mut descriptor, /*nfds*/ 1, timeout)
            };
            let error = (result < 0).then(io::Error::last_os_error);
            remaining(deadline)?;
            if let Some(error) = error {
                if error.kind() == io::ErrorKind::Interrupted {
                    continue;
                }
                return Err(error);
            }
            if descriptor.revents & libc::POLLNVAL != 0 {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidInput,
                    "invalid control socket",
                ));
            }
            if descriptor.revents & (events | libc::POLLERR | libc::POLLHUP) != 0 {
                // Nonblocking I/O consumes buffered bytes before EOF and reports
                // the actual socket error. A HUP is not itself an empty frame.
                return Ok(());
            }
        }
    }

    fn connect(path: &Path, deadline: Instant) -> io::Result<UnixStream> {
        remaining(deadline)?;
        // SAFETY: sockaddr_un contains integer fields and byte arrays only.
        let mut address: libc::sockaddr_un = unsafe { std::mem::zeroed() };
        let bytes = path.as_os_str().as_bytes();
        if bytes.is_empty() || bytes.contains(&0) || bytes.len() >= address.sun_path.len() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "invalid control socket path",
            ));
        }
        address.sun_family = libc::AF_UNIX as libc::sa_family_t;
        for (destination, source) in address.sun_path.iter_mut().zip(bytes) {
            *destination = *source as libc::c_char;
        }
        let length = std::mem::offset_of!(libc::sockaddr_un, sun_path) + bytes.len() + 1;
        #[cfg(target_os = "macos")]
        {
            address.sun_len = length as u8;
        }
        let kind = libc::SOCK_STREAM;
        #[cfg(target_os = "linux")]
        let kind = kind | libc::SOCK_CLOEXEC | libc::SOCK_NONBLOCK;
        // SAFETY: fixed AF_UNIX stream type; no caller-owned pointers.
        let descriptor = unsafe {
            libc::socket(libc::AF_UNIX, kind, /*protocol*/ 0)
        };
        if descriptor < 0 {
            return Err(io::Error::last_os_error());
        }
        // SAFETY: successful socket transfers one newly owned descriptor.
        let stream = unsafe { UnixStream::from_raw_fd(descriptor) };
        #[cfg(target_os = "macos")]
        {
            // Darwin has no SOCK_CLOEXEC/SOCK_NONBLOCK creation flags.
            // SAFETY: this live descriptor is exclusively owned by stream.
            if unsafe { libc::fcntl(descriptor, libc::F_SETFD, libc::FD_CLOEXEC) } < 0 {
                return Err(io::Error::last_os_error());
            }
            stream.set_nonblocking(/*nonblocking*/ true)?;
            let enabled: libc::c_int = 1;
            // Preserve std's Darwin socket protection, including raw-fd creation.
            // SAFETY: initialized int storage with the matching option length.
            if unsafe {
                libc::setsockopt(
                    descriptor,
                    libc::SOL_SOCKET,
                    libc::SO_NOSIGPIPE,
                    std::ptr::addr_of!(enabled).cast(),
                    std::mem::size_of_val(&enabled) as libc::socklen_t,
                )
            } < 0
            {
                return Err(io::Error::last_os_error());
            }
        }
        remaining(deadline)?;
        // SAFETY: the address is initialized, NUL terminated and correctly sized.
        let result = unsafe {
            libc::connect(
                descriptor,
                std::ptr::addr_of!(address).cast(),
                length as libc::socklen_t,
            )
        };
        if result < 0 {
            let error = io::Error::last_os_error();
            if !matches!(
                error.raw_os_error(),
                Some(libc::EINPROGRESS | libc::EALREADY)
            ) {
                // Linux AF_UNIX backlog pressure returns EAGAIN, not a pending
                // connection. Never interpret its SO_ERROR=0 as connection proof.
                // An interrupted connect also closes; failed socket state is unspecified.
                return Err(error);
            }
            wait(&stream, libc::POLLOUT, deadline)?;
            let mut error: libc::c_int = 0;
            let mut size = std::mem::size_of_val(&error) as libc::socklen_t;
            // SAFETY: live socket and initialized int/length storage.
            if unsafe {
                libc::getsockopt(
                    descriptor,
                    libc::SOL_SOCKET,
                    libc::SO_ERROR,
                    std::ptr::addr_of_mut!(error).cast(),
                    &mut size,
                )
            } < 0
            {
                return Err(io::Error::last_os_error());
            }
            if size != std::mem::size_of_val(&error) as libc::socklen_t {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    "invalid connect result",
                ));
            }
            if error != 0 {
                return Err(io::Error::from_raw_os_error(error));
            }
            // peer_addr uses getpeername: writability alone is not connectedness.
            stream.peer_addr()?;
        }
        remaining(deadline)?;
        Ok(stream)
    }

    pub(super) fn exchange_frame(
        path: &Path,
        expected_pid: u32,
        request: &[u8],
        maximum: u64,
        budget: Duration,
    ) -> io::Result<Vec<u8>> {
        let deadline = Instant::now().checked_add(budget).ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::InvalidInput,
                "invalid control exchange budget",
            )
        })?;
        let limit = maximum
            .checked_add(1)
            .and_then(|bound| usize::try_from(bound).ok())
            .ok_or_else(|| {
                io::Error::new(io::ErrorKind::InvalidInput, "invalid control frame bound")
            })?;
        let mut stream = connect(path, deadline)?;
        super::super::peer_identity::ensure_process_peer(&stream, expected_pid)?;
        remaining(deadline)?;
        let mut unsent = request;
        while !unsent.is_empty() {
            remaining(deadline)?;
            // SAFETY: live nonblocking socket and the readable request slice.
            let count = unsafe {
                libc::send(
                    stream.as_raw_fd(),
                    unsent.as_ptr().cast(),
                    unsent.len(),
                    libc::MSG_NOSIGNAL,
                )
            };
            let error = (count < 0).then(io::Error::last_os_error);
            remaining(deadline)?;
            if let Some(error) = error {
                match error.kind() {
                    io::ErrorKind::Interrupted => continue,
                    io::ErrorKind::WouldBlock => wait(&stream, libc::POLLOUT, deadline)?,
                    _ => return Err(error),
                }
            } else if count == 0 {
                return Err(io::Error::new(
                    io::ErrorKind::WriteZero,
                    "control socket write stopped",
                ));
            } else {
                unsent = &unsent[count as usize..];
            }
        }
        remaining(deadline)?;
        stream.shutdown(Shutdown::Write)?;
        remaining(deadline)?;
        let mut response = Vec::new();
        let mut chunk = [0_u8; 4096];
        while response.len() < limit {
            remaining(deadline)?;
            let bound = chunk.len().min(limit - response.len());
            let result = stream.read(&mut chunk[..bound]);
            remaining(deadline)?;
            match result {
                Ok(0) => break,
                Ok(count) => {
                    if let Some(end) = chunk[..count].iter().position(|byte| *byte == b'\n') {
                        response.extend_from_slice(&chunk[..=end]);
                        break;
                    }
                    response.extend_from_slice(&chunk[..count]);
                }
                Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                    wait(&stream, libc::POLLIN, deadline)?;
                }
                Err(error) => return Err(error),
            }
        }
        remaining(deadline)?;
        Ok(response)
    }
}

pub(super) fn exchange_frame(
    path: &Path,
    expected_pid: u32,
    request: &[u8],
    maximum: u64,
    budget: Duration,
) -> io::Result<Vec<u8>> {
    #[cfg(any(target_os = "linux", target_os = "macos"))]
    {
        platform::exchange_frame(path, expected_pid, request, maximum, budget)
    }
    #[cfg(not(any(target_os = "linux", target_os = "macos")))]
    {
        let _ = (path, expected_pid, request, maximum, budget);
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "bounded control transport is unsupported",
        ))
    }
}

#[cfg(all(test, any(target_os = "linux", target_os = "macos")))]
#[path = "unix_control_io_tests.rs"]
mod tests;

#[cfg(all(test, target_os = "linux"))]
#[path = "unix_control_io_linux_tests.rs"]
mod linux_tests;
