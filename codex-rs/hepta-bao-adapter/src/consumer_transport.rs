//! A deadline covers connect, kernel peer verification, first dispatch and ACK.

use std::io::Read;
use std::io::Write;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

use rustix::event::PollFd;
use rustix::event::PollFlags;
use rustix::event::Timespec;
use rustix::net::AddressFamily;
use rustix::net::SocketAddrUnix;
use rustix::net::SocketFlags;
use rustix::net::SocketType;

use super::ConsumerPortError;
use super::consumer_wire::MAX_FRAME_BYTES;

pub(crate) struct PreparedConnection {
    stream: UnixStream,
    deadline: Instant,
    peer_uid: u32,
}

impl PreparedConnection {
    pub fn connect(
        path: &Path,
        peer_uid: u32,
        timeout: Duration,
    ) -> Result<Self, ConsumerPortError> {
        if !path.is_absolute() || timeout.is_zero() || timeout > Duration::from_secs(5) {
            return Err(ConsumerPortError::Invalid);
        }
        let deadline = Instant::now() + timeout;
        let address = SocketAddrUnix::new(path).map_err(unavailable)?;
        let descriptor = rustix::net::socket_with(
            AddressFamily::UNIX,
            SocketType::STREAM,
            SocketFlags::CLOEXEC | SocketFlags::NONBLOCK,
            None,
        )
        .map_err(unavailable)?;
        match rustix::net::connect(&descriptor, &address) {
            Ok(()) => {}
            Err(rustix::io::Errno::INPROGRESS) => {
                wait(&descriptor, PollFlags::OUT, deadline)?;
                rustix::net::sockopt::socket_error(&descriptor)
                    .map_err(unavailable)?
                    .map_err(unavailable)?;
            }
            // A saturated local listen backlog is admission failure, not an
            // invitation to block or fabricate a fresh operation identity.
            Err(_) => return Err(ConsumerPortError::Unavailable),
        }
        let connection = Self {
            stream: UnixStream::from(descriptor),
            deadline,
            peer_uid,
        };
        connection.verify_peer()?;
        Ok(connection)
    }

    pub fn exchange<Request: serde::Serialize, Response: serde::de::DeserializeOwned>(
        mut self,
        request: &Request,
    ) -> Result<Response, ConsumerPortError> {
        self.verify_peer()?;
        let body = serde_json::to_vec(request).map_err(unavailable)?;
        if body.is_empty() || body.len() > MAX_FRAME_BYTES {
            return Err(ConsumerPortError::Invalid);
        }
        let mut frame = Vec::with_capacity(4 + body.len());
        frame.extend_from_slice(&(body.len() as u32).to_be_bytes());
        frame.extend_from_slice(&body);
        if Instant::now() >= self.deadline {
            return Err(ConsumerPortError::Unavailable);
        }
        // This is the first irreversible local dispatch. The connection and
        // peer were prepared before final-use entry. Never wait or retry when
        // this initial nonblocking write cannot cross the boundary immediately.
        let first = self.stream.write(&frame).map_err(unavailable)?;
        if first == 0 {
            return Err(ConsumerPortError::Unavailable);
        }
        let mut position = first;
        while position < frame.len() {
            wait(&self.stream, PollFlags::OUT, self.deadline)?;
            match self.stream.write(&frame[position..]) {
                Ok(0) => return Err(ConsumerPortError::Unavailable),
                Ok(count) => position += count,
                Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => continue,
                Err(_) => return Err(ConsumerPortError::Unavailable),
            }
        }
        let mut header = [0; 4];
        read_exact(&mut self.stream, &mut header, self.deadline)?;
        let length = u32::from_be_bytes(header) as usize;
        if length == 0 || length > MAX_FRAME_BYTES {
            return Err(ConsumerPortError::Unavailable);
        }
        let mut body = vec![0; length];
        read_exact(&mut self.stream, &mut body, self.deadline)?;
        self.verify_peer()?;
        serde_json::from_slice(&body).map_err(unavailable)
    }

    fn verify_peer(&self) -> Result<(), ConsumerPortError> {
        let credentials =
            rustix::net::sockopt::socket_peercred(&self.stream).map_err(unavailable)?;
        if credentials.uid.as_raw() != self.peer_uid {
            return Err(ConsumerPortError::Unavailable);
        }
        Ok(())
    }
}

fn read_exact(
    stream: &mut UnixStream,
    body: &mut [u8],
    deadline: Instant,
) -> Result<(), ConsumerPortError> {
    let mut position = 0;
    while position < body.len() {
        wait(stream, PollFlags::IN, deadline)?;
        match stream.read(&mut body[position..]) {
            Ok(0) => return Err(ConsumerPortError::Unavailable),
            Ok(count) => position += count,
            Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => continue,
            Err(_) => return Err(ConsumerPortError::Unavailable),
        }
    }
    Ok(())
}

fn wait(
    descriptor: &impl std::os::fd::AsFd,
    flags: PollFlags,
    deadline: Instant,
) -> Result<(), ConsumerPortError> {
    loop {
        let remaining = deadline
            .checked_duration_since(Instant::now())
            .ok_or(ConsumerPortError::Unavailable)?;
        let timeout = Timespec::try_from(remaining).map_err(unavailable)?;
        let mut descriptors = [PollFd::new(descriptor, flags)];
        match rustix::event::poll(&mut descriptors, Some(&timeout)) {
            Ok(0) => return Err(ConsumerPortError::Unavailable),
            Ok(_) if descriptors[0].revents().contains(flags) => return Ok(()),
            Ok(_) => return Err(ConsumerPortError::Unavailable),
            Err(rustix::io::Errno::INTR) => continue,
            Err(_) => return Err(ConsumerPortError::Unavailable),
        }
    }
}

fn unavailable(_error: impl std::fmt::Display) -> ConsumerPortError {
    ConsumerPortError::Unavailable
}
