//! Qualification-only bounded observations executed by the control owner.
//! This is not a snapshot across the generation and control owners.

use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::sync::mpsc;
use std::time::Duration;

const MAX_SNAPSHOT_BYTES: u64 = 64 * 1024 * 1024;
type Reply = mpsc::SyncSender<io::Result<Vec<u8>>>;

pub struct ControlTestSnapshot {
    requests: mpsc::SyncSender<Reply>,
    timeout: Duration,
}

impl ControlTestSnapshot {
    pub fn bytes(&self) -> io::Result<Vec<u8>> {
        let (reply, response) = mpsc::sync_channel(1);
        self.requests.try_send(reply).map_err(|error| match error {
            mpsc::TrySendError::Full(_) => io::Error::from(io::ErrorKind::WouldBlock),
            mpsc::TrySendError::Disconnected(_) => io::Error::from(io::ErrorKind::BrokenPipe),
        })?;
        response.recv_timeout(self.timeout).map_err(|error| match error {
            mpsc::RecvTimeoutError::Timeout => io::Error::from(io::ErrorKind::TimedOut),
            mpsc::RecvTimeoutError::Disconnected => io::Error::from(io::ErrorKind::BrokenPipe),
        })?
    }
}

pub(super) struct Observation {
    file: File,
    requests: mpsc::Receiver<Reply>,
}

impl Observation {
    pub(super) fn new(file: File, timeout: Duration) -> (Self, ControlTestSnapshot) {
        let (requests, receiver) = mpsc::sync_channel(1);
        (
            Self { file, requests: receiver },
            ControlTestSnapshot { requests, timeout },
        )
    }

    pub(super) fn poll(&mut self) {
        if let Ok(reply) = self.requests.try_recv() {
            let result = self.read_bytes();
            // A caller may have timed out. Reading never mutates durable bytes.
            let _ = reply.try_send(result);
        }
    }

    fn read_bytes(&mut self) -> io::Result<Vec<u8>> {
        let length = self.file.metadata()?.len();
        if length > MAX_SNAPSHOT_BYTES {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "control snapshot exceeds limit"));
        }
        let length = usize::try_from(length)
            .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "control snapshot length"))?;
        let position = self.file.stream_position()?;
        let read = (|| {
            self.file.seek(SeekFrom::Start(0))?;
            let mut bytes = vec![0; length];
            self.file.read_exact(&mut bytes)?;
            let mut extra = [0];
            if self.file.read(&mut extra)? != 0 {
                return Err(io::Error::new(io::ErrorKind::InvalidData, "control snapshot grew"));
            }
            Ok(bytes)
        })();
        let restored = self.file.seek(SeekFrom::Start(position))?;
        if restored != position {
            return Err(io::Error::other("control snapshot cursor restoration"));
        }
        read
    }
}
