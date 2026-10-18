//! One monotonic budget for connect, authenticated request and bounded response.
//! Kernel peer authentication remains mandatory before any request byte is sent.

use std::io;
use std::io::Read;
use std::io::Write;
use std::net::Shutdown;
use std::os::fd::AsRawFd;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

use rustix::io::Errno;
use rustix::net::AddressFamily;
use rustix::net::SocketAddrUnix;
#[cfg(not(target_vendor = "apple"))]
use rustix::net::SocketFlags;
use rustix::net::SocketType;

pub(super) fn exchange(
    path: &Path,
    expected_pid: u32,
    request: &[u8],
    frame_limit: u64,
    budget: Duration,
) -> io::Result<Vec<u8>> {
    let deadline = Instant::now()
        .checked_add(budget)
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "probe deadline overflow"))?;
    remaining(deadline)?;
    let read_limit = frame_limit
        .checked_add(1)
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "probe frame limit overflow"))?;
    if request.len() as u64 > frame_limit {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "probe request exceeds frame limit",
        ));
    }
    let address = SocketAddrUnix::new(path)?;
    #[cfg(not(target_vendor = "apple"))]
    let stream = UnixStream::from(rustix::net::socket_with(
        AddressFamily::UNIX,
        SocketType::STREAM,
        SocketFlags::CLOEXEC | SocketFlags::NONBLOCK,
        /*protocol*/ None,
    )?);
    #[cfg(target_vendor = "apple")]
    let stream = socket_with_fcntl_flags()?;
    // Preserve std's Apple socket initialization: converting an OwnedFd does
    // not set SO_NOSIGPIPE, and Apple's std write path has no MSG_NOSIGNAL.
    #[cfg(target_vendor = "apple")]
    rustix::net::sockopt::set_socket_nosigpipe(&stream, /*value*/ true)?;
    match rustix::net::connect(&stream, &address) {
        Ok(()) => {}
        Err(Errno::INPROGRESS) => {
            wait_ready(&stream, libc::POLLOUT, deadline)?;
            rustix::net::sockopt::socket_error(&stream)??;
        }
        // Linux AF_UNIX EAGAIN means a saturated accept queue, not a pending
        // connection. Return unavailable now; the lifecycle owner may retry.
        // Do not poll SO_ERROR=0 into a false connected/admitted observation.
        Err(error) => return Err(error.into()),
    }
    remaining(deadline)?;
    super::peer::ensure_process_owner(&stream, expected_pid)?;
    let mut writer = &stream;
    let mut pending = request;
    while !pending.is_empty() {
        remaining(deadline)?;
        match writer.write(pending) {
            Ok(0) => return Err(io::ErrorKind::WriteZero.into()),
            Ok(count) => pending = &pending[count..],
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                wait_ready(&stream, libc::POLLOUT, deadline)?;
            }
            Err(error) => return Err(error),
        }
    }
    stream.shutdown(Shutdown::Write)?;
    let mut reader = &stream;
    let mut response = Vec::new();
    let mut buffer = [0_u8; 8_192];
    loop {
        remaining(deadline)?;
        let capacity = usize::try_from(read_limit - response.len() as u64)
            .unwrap_or(usize::MAX)
            .min(buffer.len());
        match reader.read(&mut buffer[..capacity]) {
            Ok(count) => {
                remaining(deadline)?;
                let newline = buffer[..count].iter().position(|byte| *byte == b'\n');
                response.extend_from_slice(&buffer[..newline.map_or(count, |index| index + 1)]);
                if count == 0 || newline.is_some() || response.len() as u64 == read_limit {
                    return Ok(response);
                }
            }
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                wait_ready(&stream, libc::POLLIN, deadline)?;
            }
            Err(error) => return Err(error),
        }
    }
}

/// Apple lacks socket-time CLOEXEC/NONBLOCK flags. Set both before connecting.
/// The owned descriptor closes on every initialization error; it never escapes
/// partially configured. Linux keeps its atomic socket-time initialization.
#[cfg(any(target_vendor = "apple", test))]
pub(super) fn socket_with_fcntl_flags() -> io::Result<UnixStream> {
    let fd = rustix::net::socket(
        AddressFamily::UNIX,
        SocketType::STREAM,
        /*protocol*/ None,
    )?;
    let descriptor_flags = rustix::io::fcntl_getfd(&fd)?;
    rustix::io::fcntl_setfd(&fd, descriptor_flags | rustix::io::FdFlags::CLOEXEC)?;
    // SAFETY: fd is owned and live; F_GETFL takes no additional argument.
    let status_flags = unsafe { libc::fcntl(fd.as_raw_fd(), libc::F_GETFL) };
    if status_flags < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: fd remains live; F_SETFL takes the integer flags returned above.
    if unsafe {
        libc::fcntl(
            fd.as_raw_fd(),
            libc::F_SETFL,
            status_flags | libc::O_NONBLOCK,
        )
    } < 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok(UnixStream::from(fd))
}

fn remaining(deadline: Instant) -> io::Result<Duration> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|duration| !duration.is_zero())
        .ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::TimedOut,
                "control socket exchange exceeded its deadline",
            )
        })
}

fn wait_ready(stream: &UnixStream, events: libc::c_short, deadline: Instant) -> io::Result<()> {
    loop {
        let milliseconds = remaining(deadline)?.as_nanos().div_ceil(1_000_000);
        let timeout = i32::try_from(milliseconds).unwrap_or(i32::MAX);
        let mut descriptor = libc::pollfd {
            fd: stream.as_raw_fd(),
            events,
            revents: 0,
        };
        let count = 1;
        // SAFETY: descriptor is one initialized writable pollfd containing the
        // live borrowed stream fd; count is exactly one and timeout is bounded.
        let observed = unsafe { libc::poll(&mut descriptor, count, timeout) };
        if observed > 0 {
            remaining(deadline)?;
            if descriptor.revents & libc::POLLNVAL != 0 {
                return Err(io::Error::from_raw_os_error(libc::EBADF));
            }
            // HUP/ERR must reach read/write/SO_ERROR, not be treated as success.
            return Ok(());
        }
        if observed == 0 {
            continue;
        }
        let error = io::Error::last_os_error();
        if error.kind() != io::ErrorKind::Interrupted {
            return Err(error);
        }
    }
}
