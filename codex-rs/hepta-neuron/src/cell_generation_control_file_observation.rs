//! Qualification observation is serialized by the existing control actor.

use std::io;
use std::sync::atomic::Ordering;
use std::sync::mpsc;

use super::Command;
use super::ControlledCellGenerationPortV2;

pub(super) enum ActorCommand {
    Operation(Box<Command>),
    ObserveFile {
        maximum_bytes: u64,
        reply: mpsc::SyncSender<io::Result<Vec<u8>>>,
    },
}

pub(super) fn read_port(
    port: &mut ControlledCellGenerationPortV2,
    maximum_bytes: u64,
) -> io::Result<Vec<u8>> {
    if port.stopping.load(Ordering::Acquire) {
        return Err(io::Error::new(
            io::ErrorKind::BrokenPipe,
            "control owner is stopping",
        ));
    }
    let (reply, response) = mpsc::sync_channel(/*bound*/ 1);
    port.commands
        .as_ref()
        .ok_or_else(|| io::Error::new(io::ErrorKind::BrokenPipe, "control owner is closed"))?
        .try_send(ActorCommand::ObserveFile {
            maximum_bytes,
            reply,
        })
        .map_err(|error| match error {
            mpsc::TrySendError::Full(_) => io::Error::new(
                io::ErrorKind::WouldBlock,
                "control observation queue is full",
            ),
            mpsc::TrySendError::Disconnected(_) => {
                io::Error::new(io::ErrorKind::BrokenPipe, "control owner is closed")
            }
        })?;
    response
        .recv_timeout(port.config.rpc_timeout)
        .map_err(|error| match error {
            mpsc::RecvTimeoutError::Timeout => {
                io::Error::new(io::ErrorKind::TimedOut, "control observation timed out")
            }
            mpsc::RecvTimeoutError::Disconnected => io::Error::new(
                io::ErrorKind::BrokenPipe,
                "control observation response is closed",
            ),
        })?
}
