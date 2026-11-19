//! Terminal Source-capture framing. Ordinary CURRENT exchanges retain their
//! existing rejection of HUP. Only this final half-closed exchange requires a
//! bounded complete reply followed by clean EOF on the original descriptor.

use std::io;
use std::io::Read;
use std::net::Shutdown;
use std::os::fd::AsRawFd;
use std::time::Instant;

use super::OriginalPublicationStream;
use super::unavailable;

impl OriginalPublicationStream {
    pub(crate) fn exchange_source_capture_terminal(
        &mut self,
        request: &[u8],
    ) -> io::Result<Vec<u8>> {
        if request.is_empty() || request.len() > 16_384 {
            return Err(unavailable());
        }
        let end = (Instant::now() + self.timeout).min(self.end);
        crate::root_observation_stream::check_lifetime(&self.root).map_err(io::Error::other)?;
        self.write(&(request.len() as u32).to_be_bytes(), end)?;
        self.write(request, end)?;
        self.stream.shutdown(Shutdown::Write)?;
        let mut prefix = [0; 4];
        self.read_source_capture_terminal(&mut prefix, end)?;
        let size = u32::from_be_bytes(prefix) as usize;
        if size == 0 || size > 16_384 {
            return Err(unavailable());
        }
        let mut response = vec![0; size];
        self.read_source_capture_terminal(&mut response, end)?;
        loop {
            self.wait_source_capture_terminal(end)?;
            let mut trailing = [0; 1];
            match self.stream.read(&mut trailing) {
                Ok(0) => break,
                Ok(_) => return Err(unavailable()),
                Err(error)
                    if matches!(
                        error.kind(),
                        io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted
                    ) => {}
                Err(error) => return Err(error),
            }
        }
        crate::root_observation_stream::check_lifetime(&self.root).map_err(io::Error::other)?;
        if Instant::now() >= end {
            return Err(unavailable());
        }
        Ok(response)
    }

    fn read_source_capture_terminal(
        &mut self,
        mut bytes: &mut [u8],
        end: Instant,
    ) -> io::Result<()> {
        while !bytes.is_empty() {
            self.wait_source_capture_terminal(end)?;
            match self.stream.read(bytes) {
                Ok(0) => return Err(unavailable()),
                Ok(size) => bytes = &mut bytes[size..],
                Err(error)
                    if matches!(
                        error.kind(),
                        io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted
                    ) => {}
                Err(error) => return Err(error),
            }
        }
        Ok(())
    }

    fn wait_source_capture_terminal(&self, end: Instant) -> io::Result<()> {
        loop {
            let remaining = end
                .checked_duration_since(Instant::now())
                .ok_or_else(unavailable)?;
            if remaining.is_zero() {
                return Err(unavailable());
            }
            let timeout = remaining
                .as_millis()
                .saturating_add(1)
                .min(i32::MAX as u128) as i32;
            let mut fds = [
                libc::pollfd {
                    fd: self.root.as_raw_fd(),
                    events: libc::POLLIN,
                    revents: 0,
                },
                libc::pollfd {
                    fd: self.stream.as_raw_fd(),
                    events: libc::POLLIN,
                    revents: 0,
                },
            ];
            // SAFETY: the original descriptors and the complete initialized
            // pollfd array remain held during this bounded synchronous wait.
            let ready = unsafe { libc::poll(fds.as_mut_ptr(), fds.len() as libc::nfds_t, timeout) };
            if ready < 0 && io::Error::last_os_error().kind() == io::ErrorKind::Interrupted {
                continue;
            }
            if ready <= 0
                || fds[0].revents != 0
                || fds[1].revents & (libc::POLLERR | libc::POLLNVAL) != 0
                || Instant::now() >= end
            {
                return Err(unavailable());
            }
            if fds[1].revents & (libc::POLLIN | libc::POLLHUP) != 0 {
                return Ok(());
            }
        }
    }
}
