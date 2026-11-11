//! Bounded synchronous framing for the original CURRENT owner lane. Product
//! publication already runs in its exclusive blocking lane; there is no nested
//! Tokio block_on, reconnect, late-response reuse or replacement PID discovery.

use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

use crate::AgentdRootAuthorityPeer;

pub(crate) struct OriginalPublicationStream {
    stream: UnixStream,
    root: OwnedFd,
    timeout: Duration,
    end: Instant,
}

impl OriginalPublicationStream {
    pub(crate) fn from_stream(
        stream: UnixStream,
        root: OwnedFd,
        peer: AgentdRootAuthorityPeer,
        timeout: Duration,
        lifetime: Duration,
    ) -> io::Result<Self> {
        if peer.pid == 0 || peer.pid > i32::MAX as u32 || peer.process_start_ticks == 0
            || timeout.is_zero() || timeout > Duration::from_millis(500)
            || lifetime.is_zero() || lifetime > Duration::from_secs(300)
        {
            return Err(unavailable());
        }
        let number = root.as_raw_fd();
        if std::fs::read_link(format!("/proc/self/fd/{number}"))? != Path::new("anon_inode:[pidfd]")
            || bounded_text(&format!("/proc/self/fdinfo/{number}"), 4096)?.lines()
                .find_map(|line| line.strip_prefix("Pid:")?.trim().parse::<u32>().ok()) != Some(peer.pid)
            || bounded_text("/proc/sys/kernel/random/boot_id", 128)?.trim() != peer.boot_id
        {
            return Err(unavailable());
        }
        let stat = bounded_text(&format!("/proc/{}/stat", peer.pid), 8192)?;
        if stat.rsplit_once(") ").and_then(|(_, values)| values.split_whitespace().nth(19))
            .and_then(|value| value.parse::<u64>().ok()) != Some(peer.process_start_ticks)
        {
            return Err(unavailable());
        }
        let mut actual = libc::ucred { pid: 0, uid: u32::MAX, gid: u32::MAX };
        let mut size = std::mem::size_of_val(&actual) as libc::socklen_t;
        // SAFETY: the live original stream and exactly sized initialized ucred
        // remain owned here for this kernel observation.
        if unsafe { libc::getsockopt(stream.as_raw_fd(), libc::SOL_SOCKET, libc::SO_PEERCRED,
            (&mut actual as *mut libc::ucred).cast(), &mut size) } != 0
            || size as usize != std::mem::size_of::<libc::ucred>()
            || actual.uid != 0 || actual.pid != peer.pid as i32
        {
            return Err(unavailable());
        }
        crate::root_observation_stream::check_lifetime(&root).map_err(io::Error::other)?;
        stream.set_nonblocking(true)?;
        Ok(Self { stream, root, timeout, end: Instant::now() + lifetime })
    }

    pub(crate) fn exchange(&mut self, request: &[u8]) -> io::Result<Vec<u8>> {
        if request.is_empty() || request.len() > 16_384 { return Err(unavailable()); }
        let end = (Instant::now() + self.timeout).min(self.end);
        crate::root_observation_stream::check_lifetime(&self.root).map_err(io::Error::other)?;
        self.write(&(request.len() as u32).to_be_bytes(), end)?;
        self.write(request, end)?;
        let mut prefix = [0; 4];
        self.read(&mut prefix, end)?;
        let size = u32::from_be_bytes(prefix) as usize;
        if size == 0 || size > 16_384 { return Err(unavailable()); }
        let mut response = vec![0; size];
        self.read(&mut response, end)?;
        crate::root_observation_stream::check_lifetime(&self.root).map_err(io::Error::other)?;
        if Instant::now() >= end { return Err(unavailable()); }
        Ok(response)
    }

    fn wait(&self, events: i16, end: Instant) -> io::Result<()> {
        loop {
            let remaining = end.checked_duration_since(Instant::now()).ok_or_else(unavailable)?;
            if remaining.is_zero() { return Err(unavailable()); }
            let timeout = remaining.as_millis().saturating_add(1).min(i32::MAX as u128) as i32;
            let mut fds = [
                libc::pollfd { fd: self.root.as_raw_fd(), events: libc::POLLIN, revents: 0 },
                libc::pollfd { fd: self.stream.as_raw_fd(), events, revents: 0 },
            ];
            // SAFETY: both held original descriptors and the writable pollfd
            // array remain live for this bounded blocking poll.
            let ready = unsafe { libc::poll(fds.as_mut_ptr(), fds.len() as libc::nfds_t, timeout) };
            if ready < 0 && io::Error::last_os_error().kind() == io::ErrorKind::Interrupted { continue; }
            if ready <= 0 || fds[0].revents != 0
                || fds[1].revents & (libc::POLLERR | libc::POLLHUP | libc::POLLNVAL) != 0
                || Instant::now() >= end
            { return Err(unavailable()); }
            if fds[1].revents & events != 0 { return Ok(()); }
        }
    }

    fn write(&mut self, mut bytes: &[u8], end: Instant) -> io::Result<()> {
        while !bytes.is_empty() {
            self.wait(libc::POLLOUT, end)?;
            match self.stream.write(bytes) {
                Ok(0) => return Err(unavailable()),
                Ok(size) => bytes = &bytes[size..],
                Err(error) if matches!(error.kind(), io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted) => {}
                Err(error) => return Err(error),
            }
        }
        Ok(())
    }

    fn read(&mut self, mut bytes: &mut [u8], end: Instant) -> io::Result<()> {
        while !bytes.is_empty() {
            self.wait(libc::POLLIN, end)?;
            match self.stream.read(bytes) {
                Ok(0) => return Err(unavailable()),
                Ok(size) => bytes = &mut bytes[size..],
                Err(error) if matches!(error.kind(), io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted) => {}
                Err(error) => return Err(error),
            }
        }
        Ok(())
    }
}

fn bounded_text(path: &str, limit: u64) -> io::Result<String> {
    let mut value = String::new();
    File::open(path)?.take(limit + 1).read_to_string(&mut value)?;
    if value.len() as u64 > limit { return Err(unavailable()); }
    Ok(value)
}

fn unavailable() -> io::Error { io::Error::other("original Root publication lane unavailable") }
