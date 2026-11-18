//! Qualification-only bounded observations executed by the control owner.
//! This is not a snapshot across the generation and control owners.

use std::io;
use std::sync::mpsc;
use std::time::Duration;

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
        response
            .recv_timeout(self.timeout)
            .map_err(|error| match error {
                mpsc::RecvTimeoutError::Timeout => io::Error::from(io::ErrorKind::TimedOut),
                mpsc::RecvTimeoutError::Disconnected => io::Error::from(io::ErrorKind::BrokenPipe),
            })?
    }
}

pub(super) struct Observation {
    requests: mpsc::Receiver<Reply>,
}

impl Observation {
    pub(super) fn new(timeout: Duration) -> (Self, ControlTestSnapshot) {
        let (requests, receiver) = mpsc::sync_channel(1);
        (
            Self { requests: receiver },
            ControlTestSnapshot { requests, timeout },
        )
    }

    pub(super) fn poll(
        &mut self,
        control: &mut codex_hepta_infer_core::durable_control::DurableInferenceControl,
    ) {
        if let Ok(reply) = self.requests.try_recv() {
            let result = control.test_snapshot_bytes();
            // A caller may have timed out. Reading never mutates durable bytes.
            let _ = reply.try_send(result);
        }
    }
}
