//! Bounded test-peer I/O, including connections rejected before accept.

use std::io;
use std::io::Read;
use std::io::Write;
use std::os::unix::net::UnixStream;
use std::time::Duration;
use std::time::Instant;

const MAXIMUM_FRAME_BYTES: usize = 64 * 1024;

pub(super) enum FrameEnd {
    Newline,
    Eof,
}

pub(super) struct FixtureIo {
    stream: UnixStream,
    deadline: Instant,
}

pub(super) fn context(operation: &str, error: io::Error) -> io::Error {
    io::Error::new(error.kind(), format!("socket fixture {operation}: {error}"))
}

impl FixtureIo {
    pub(super) fn new(stream: UnixStream, budget: Duration) -> io::Result<Self> {
        let deadline = Instant::now().checked_add(budget).ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::InvalidInput,
                "socket fixture deadline overflow",
            )
        })?;
        // Darwin rejects setsockopt after the peer has closed both directions.
        // FIONBIO remains valid; explicitly normalize Linux's non-inheritance.
        stream
            .set_nonblocking(/*nonblocking*/ true)
            .map_err(|error| context("set accepted stream nonblocking", error))?;
        let fixture = Self { stream, deadline };
        fixture.remaining("initialize accepted stream")?;
        Ok(fixture)
    }

    fn remaining(&self, operation: &str) -> io::Result<Duration> {
        self.deadline
            .checked_duration_since(Instant::now())
            .filter(|remaining| !remaining.is_zero())
            .ok_or_else(|| {
                io::Error::new(
                    io::ErrorKind::TimedOut,
                    format!("socket fixture {operation}: absolute deadline expired"),
                )
            })
    }

    fn wait(&self, operation: &str) -> io::Result<()> {
        let remaining = self.remaining(operation)?;
        std::thread::sleep(remaining.min(Duration::from_millis(/*millis*/ 1)));
        self.remaining(operation)?;
        Ok(())
    }

    pub(super) fn read_frame(&mut self, end: FrameEnd) -> io::Result<Vec<u8>> {
        let mut frame = Vec::new();
        let mut buffer = [0_u8; 1024];
        loop {
            self.remaining("read request")?;
            // One extra byte distinguishes an exact bound followed by EOF from
            // an oversized request without allowing unbounded allocation.
            let capacity = buffer.len().min(MAXIMUM_FRAME_BYTES - frame.len() + 1);
            match self.stream.read(&mut buffer[..capacity]) {
                Ok(count) => {
                    self.remaining("read request")?;
                    if count == 0 {
                        return Ok(frame);
                    }
                    let bytes = &buffer[..count];
                    let count = match end {
                        FrameEnd::Newline => bytes
                            .iter()
                            .position(|byte| *byte == b'\n')
                            .map_or(count, |position| position + 1),
                        FrameEnd::Eof => count,
                    };
                    frame.extend_from_slice(&bytes[..count]);
                    if frame.len() > MAXIMUM_FRAME_BYTES {
                        return Err(io::Error::new(
                            io::ErrorKind::InvalidData,
                            "socket fixture read request: frame exceeds 64 KiB",
                        ));
                    }
                    if matches!(end, FrameEnd::Newline) && frame.last() == Some(&b'\n') {
                        self.remaining("read request")?;
                        return Ok(frame);
                    }
                }
                Err(error)
                    if matches!(
                        error.kind(),
                        io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted
                    ) =>
                {
                    self.wait("read request")?;
                }
                Err(error) => return Err(context("read request", error)),
            }
        }
    }

    pub(super) fn write_frame(&mut self, frame: &[u8]) -> io::Result<()> {
        if frame.len() > MAXIMUM_FRAME_BYTES {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "socket fixture write reply: frame exceeds 64 KiB",
            ));
        }
        let mut written = 0;
        while written < frame.len() {
            self.remaining("write reply")?;
            match self.stream.write(&frame[written..]) {
                Ok(count) => {
                    self.remaining("write reply")?;
                    if count == 0 {
                        return Err(io::Error::new(
                            io::ErrorKind::WriteZero,
                            "socket fixture write reply: no progress",
                        ));
                    }
                    written += count;
                }
                Err(error)
                    if matches!(
                        error.kind(),
                        io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted
                    ) =>
                {
                    self.wait("write reply")?;
                }
                Err(error) => return Err(context("write reply", error)),
            }
        }
        self.remaining("write reply")?;
        Ok(())
    }
}
