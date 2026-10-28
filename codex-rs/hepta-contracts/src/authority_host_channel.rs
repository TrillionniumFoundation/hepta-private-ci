use super::HostIssuerTransportError;
use super::io_error;
use rustix::event::PollFd;
use rustix::event::PollFlags;
use rustix::event::Timespec;
use rustix::event::poll;
use std::io;
use std::io::Read;
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::time::Duration;
use std::time::Instant;

const MAX_SESSION_LIFETIME: Duration = Duration::from_secs(300);

pub(crate) struct OwnerChannel {
    owner: OwnedFd,
    end: Instant,
}

impl OwnerChannel {
    pub(crate) fn new(
        owner: OwnedFd,
        pid: u32,
        lifetime: Duration,
    ) -> Result<Self, HostIssuerTransportError> {
        if lifetime.is_zero() || lifetime > MAX_SESSION_LIFETIME {
            return Err(HostIssuerTransportError::InvalidConfiguration);
        }
        let number = owner.as_raw_fd();
        if std::fs::read_link(format!("/proc/self/fd/{number}")).map_err(io_error)?
            != std::path::Path::new("anon_inode:[pidfd]")
        {
            return Err(HostIssuerTransportError::InvalidConfiguration);
        }
        let mut bytes = String::new();
        std::fs::File::open(format!("/proc/self/fdinfo/{number}"))
            .map_err(io_error)?
            .take(4096)
            .read_to_string(&mut bytes)
            .map_err(io_error)?;
        let actual = bytes.lines().find_map(|line| {
            line.strip_prefix("Pid:")
                .and_then(|value| value.trim().parse::<u32>().ok())
        });
        if actual != Some(pid) {
            return Err(HostIssuerTransportError::PeerDenied);
        }
        let channel = Self {
            owner,
            end: Instant::now() + lifetime,
        };
        channel.check(channel.end)?;
        Ok(channel)
    }

    pub(crate) fn end(&self) -> Instant {
        self.end
    }

    pub(crate) fn deadline(&self, timeout: Duration) -> Instant {
        (Instant::now() + timeout).min(self.end)
    }

    pub(crate) fn check(&self, deadline: Instant) -> Result<(), HostIssuerTransportError> {
        remaining(deadline.min(self.end))?;
        let mut descriptors = [PollFd::new(&self.owner, PollFlags::IN)];
        loop {
            match poll(&mut descriptors, Some(&Timespec::default())) {
                Ok(_) if descriptors[0].revents().is_empty() => return Ok(()),
                Ok(_) => return Err(HostIssuerTransportError::PeerDenied),
                Err(rustix::io::Errno::INTR) => {
                    remaining(deadline.min(self.end))?;
                }
                Err(error) => return Err(io_error(error)),
            }
        }
    }

    fn wait(
        &self,
        stream: &UnixStream,
        event: PollFlags,
        deadline: Instant,
    ) -> Result<(), HostIssuerTransportError> {
        loop {
            let timeout = Timespec::try_from(remaining(deadline.min(self.end))?)
                .map_err(|_| HostIssuerTransportError::InvalidConfiguration)?;
            let mut descriptors = [
                PollFd::new(stream, event),
                PollFd::new(&self.owner, PollFlags::IN),
            ];
            match poll(&mut descriptors, Some(&timeout)) {
                Ok(0) => return Err(HostIssuerTransportError::DeadlineElapsed),
                Ok(_) => {
                    // Owner exit wins even when an inherited stream is also
                    // ready. The pidfd pins the original process instance.
                    if !descriptors[1].revents().is_empty() {
                        return Err(HostIssuerTransportError::PeerDenied);
                    }
                    if descriptors[0]
                        .revents()
                        .intersects(PollFlags::ERR | PollFlags::NVAL)
                    {
                        return Err(HostIssuerTransportError::Unavailable);
                    }
                    if descriptors[0].revents().intersects(event | PollFlags::HUP) {
                        return Ok(());
                    }
                }
                Err(rustix::io::Errno::INTR) => {}
                Err(error) => return Err(io_error(error)),
            }
        }
    }

    pub(crate) fn read(
        &self,
        stream: &mut UnixStream,
        bytes: &mut [u8],
        deadline: Instant,
    ) -> Result<usize, HostIssuerTransportError> {
        loop {
            self.wait(stream, PollFlags::IN, deadline)?;
            match stream.read(bytes) {
                Ok(count) => return Ok(count),
                Err(error)
                    if matches!(
                        error.kind(),
                        io::ErrorKind::Interrupted | io::ErrorKind::WouldBlock
                    ) => {}
                Err(error) => return Err(io_error(error)),
            }
        }
    }

    pub(crate) fn read_until(
        &self,
        stream: &mut UnixStream,
        mut bytes: &mut [u8],
        deadline: Instant,
    ) -> Result<(), HostIssuerTransportError> {
        while !bytes.is_empty() {
            match self.read(stream, bytes, deadline)? {
                0 => return Err(HostIssuerTransportError::Closed),
                count => bytes = &mut bytes[count..],
            }
        }
        Ok(())
    }

    pub(crate) fn write_until(
        &self,
        stream: &mut UnixStream,
        mut bytes: &[u8],
        deadline: Instant,
    ) -> Result<(), HostIssuerTransportError> {
        while !bytes.is_empty() {
            self.wait(stream, PollFlags::OUT, deadline)?;
            match stream.write(bytes) {
                Ok(0) => return Err(HostIssuerTransportError::Closed),
                Ok(count) => bytes = &bytes[count..],
                Err(error)
                    if matches!(
                        error.kind(),
                        io::ErrorKind::Interrupted | io::ErrorKind::WouldBlock
                    ) => {}
                Err(error) => return Err(io_error(error)),
            }
        }
        Ok(())
    }
}

fn remaining(deadline: Instant) -> Result<Duration, HostIssuerTransportError> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|duration| !duration.is_zero())
        .ok_or(HostIssuerTransportError::DeadlineElapsed)
}
