//! Bounded native control exchange. The same absolute deadline covers connect,
//! write and the complete frame, including peers that trickle bytes forever.
use std::io;
use std::io::Read;
use std::io::Write;
use std::net::Shutdown;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

pub(super) fn exchange(
    path: &Path,
    request: &[u8],
    limit: usize,
    timeout: Duration,
) -> io::Result<Vec<u8>> {
    let deadline = Instant::now()
        .checked_add(timeout)
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "control deadline overflow"))?;
    // SAFETY: a zeroed sockaddr_un is initialized below before connect reads it.
    let mut address: libc::sockaddr_un = unsafe { std::mem::zeroed() };
    let bytes = path.as_os_str().as_bytes();
    if bytes.is_empty() || bytes.contains(&0) || bytes.len() >= address.sun_path.len() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "invalid Unix control path",
        ));
    }
    address.sun_family = libc::AF_UNIX as libc::sa_family_t;
    for (dst, src) in address.sun_path.iter_mut().zip(bytes) {
        *dst = *src as libc::c_char;
    }
    #[cfg(any(
        target_os = "macos",
        target_os = "ios",
        target_os = "freebsd",
        target_os = "openbsd",
        target_os = "netbsd",
        target_os = "dragonfly"
    ))]
    {
        address.sun_len = std::mem::size_of::<libc::sockaddr_un>() as u8;
    }
    // SAFETY: socket has no borrowed pointers; the returned descriptor is checked.
    let raw = unsafe { libc::socket(libc::AF_UNIX, libc::SOCK_STREAM, 0) };
    if raw < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: raw is a new descriptor and ownership is transferred exactly once.
    let fd = unsafe { OwnedFd::from_raw_fd(raw) };
    // SAFETY: fcntl operates on our live descriptor and takes an integer flag.
    if unsafe { libc::fcntl(fd.as_raw_fd(), libc::F_SETFD, libc::FD_CLOEXEC) } < 0 {
        return Err(io::Error::last_os_error());
    }
    let mut stream = UnixStream::from(fd);
    stream.set_nonblocking(true)?;
    // SAFETY: address points to a fully initialized sockaddr_un of the given size.
    let connected = unsafe {
        libc::connect(
            stream.as_raw_fd(),
            (&raw const address).cast(),
            std::mem::size_of_val(&address) as libc::socklen_t,
        )
    };
    if connected < 0 {
        let error = io::Error::last_os_error();
        if error.raw_os_error() != Some(libc::EINPROGRESS) {
            return Err(error);
        }
        wait(&stream, libc::POLLOUT, deadline)?;
        if let Some(error) = stream.take_error()? {
            return Err(error);
        }
    }
    let mut sent = 0;
    while sent < request.len() {
        remaining(deadline)?;
        match stream.write(&request[sent..]) {
            Ok(0) => {
                return Err(io::Error::new(
                    io::ErrorKind::WriteZero,
                    "control socket closed",
                ));
            }
            Ok(count) => sent += count,
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                wait(&stream, libc::POLLOUT, deadline)?
            }
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error),
        }
    }
    stream.shutdown(Shutdown::Write)?;
    let capacity = limit.checked_add(1).ok_or_else(|| {
        io::Error::new(io::ErrorKind::InvalidInput, "control frame bound overflow")
    })?;
    let mut response = Vec::new();
    let mut buffer = [0_u8; 4096];
    while response.len() < capacity {
        remaining(deadline)?;
        let count = buffer.len().min(capacity - response.len());
        match stream.read(&mut buffer[..count]) {
            Ok(0) => break,
            Ok(count) => {
                let newline = buffer[..count].iter().position(|byte| *byte == b'\n');
                response.extend_from_slice(&buffer[..newline.map_or(count, |index| index + 1)]);
                if newline.is_some() {
                    break;
                }
            }
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                wait(&stream, libc::POLLIN, deadline)?
            }
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error),
        }
    }
    Ok(response)
}

fn remaining(deadline: Instant) -> io::Result<Duration> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|left| !left.is_zero())
        .ok_or_else(|| io::Error::new(io::ErrorKind::TimedOut, "control exchange deadline elapsed"))
}

fn wait(stream: &UnixStream, events: libc::c_short, deadline: Instant) -> io::Result<()> {
    loop {
        let left = remaining(deadline)?;
        let millis = left.as_millis().saturating_add(1).min(i32::MAX as u128) as i32;
        let mut descriptor = libc::pollfd {
            fd: stream.as_raw_fd(),
            events,
            revents: 0,
        };
        // SAFETY: descriptor is valid for one pollfd and stream stays alive.
        let result = unsafe { libc::poll(&raw mut descriptor, 1, millis) };
        if result > 0 {
            return Ok(());
        }
        if result == 0 {
            return Err(io::Error::new(
                io::ErrorKind::TimedOut,
                "control exchange deadline elapsed",
            ));
        }
        let error = io::Error::last_os_error();
        if error.kind() != io::ErrorKind::Interrupted {
            return Err(error);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::net::UnixListener;

    #[test]
    fn trickled_bytes_do_not_extend_total_response_deadline() -> io::Result<()> {
        let temp = tempfile::tempdir_in("/tmp")?;
        let socket = temp.path().join("control.sock");
        let listener = UnixListener::bind(&socket)?;
        let worker = std::thread::spawn(move || {
            let (mut peer, _) = listener.accept().expect("accept");
            for _ in 0..100 {
                if peer.write_all(b"x").is_err() {
                    break;
                }
                std::thread::sleep(Duration::from_millis(5));
            }
        });
        let start = Instant::now();
        let result = exchange(&socket, b"request\n", 4096, Duration::from_millis(75));
        let elapsed = start.elapsed();
        worker.join().expect("peer worker");
        assert_eq!(
            result.expect_err("absolute deadline").kind(),
            io::ErrorKind::TimedOut
        );
        assert!(elapsed < Duration::from_millis(400), "{elapsed:?}");
        Ok(())
    }

    #[test]
    fn response_is_bounded_before_a_newline_arrives() -> io::Result<()> {
        let temp = tempfile::tempdir_in("/tmp")?;
        let socket = temp.path().join("control.sock");
        let listener = UnixListener::bind(&socket)?;
        let worker = std::thread::spawn(move || {
            let (mut peer, _) = listener.accept().expect("accept");
            let _ = peer.write_all(&[b'x'; 1024]);
        });
        let response = exchange(&socket, b"request\n", 64, Duration::from_secs(1))?;
        worker.join().expect("peer worker");
        assert_eq!(response, vec![b'x'; 65]);
        Ok(())
    }
}
