//! Transport budgets never stand in for an authenticated task deadline.

use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncRead;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWrite;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::time::Instant;
use tokio::time::timeout;
use tokio::time::timeout_at;

use super::IO_TIMEOUT;
use crate::AgentdError;
use crate::MAX_CONTROL_FRAME_BYTES;

pub(super) async fn read_frame(
    reader: impl AsyncRead + Unpin,
    end: Instant,
) -> Result<Vec<u8>, AgentdError> {
    // A transport handshake consumes the same original request budget. A ready
    // buffered frame cannot regain admission after that deadline has elapsed.
    if Instant::now() >= end {
        return Err(AgentdError::Protocol(
            "agentd control request frame timed out".into(),
        ));
    }
    let mut reader = BufReader::new(reader).take(MAX_CONTROL_FRAME_BYTES + 1);
    let mut frame = Vec::new();
    let count = timeout_at(end, reader.read_until(b'\n', &mut frame))
        .await
        .map_err(|_| AgentdError::Protocol("agentd control request frame timed out".into()))??;
    if Instant::now() >= end {
        return Err(AgentdError::Protocol(
            "agentd control request frame timed out".into(),
        ));
    }
    if count == 0 || count as u64 > MAX_CONTROL_FRAME_BYTES || !frame.ends_with(b"\n") {
        return Err(AgentdError::Protocol(
            "agentd control request must be one bounded newline JSON frame".into(),
        ));
    }
    Ok(frame)
}

pub(super) async fn write_frame(
    writer: &mut (impl AsyncWrite + Unpin),
    bytes: &[u8],
) -> Result<(), AgentdError> {
    if bytes.len() as u64 > MAX_CONTROL_FRAME_BYTES || !bytes.ends_with(b"\n") {
        return Err(AgentdError::Protocol(
            "agentd control response exceeded frame bound".into(),
        ));
    }
    timeout(IO_TIMEOUT, async {
        writer.write_all(bytes).await?;
        // A peer can read the complete frame and close before this half-close.
        // Only the shutdown syscall may report that already-closed connection;
        // a failed or partial write must still propagate.
        match writer.shutdown().await {
            Err(error) if error.kind() == std::io::ErrorKind::NotConnected => Ok(()),
            result => result,
        }
    })
    .await
    .map_err(|_| AgentdError::Protocol("agentd control response frame timed out".into()))??;
    Ok(())
}

#[cfg(test)]
#[path = "control_frames_tests.rs"]
mod tests;
