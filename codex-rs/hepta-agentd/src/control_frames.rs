//! Transport budgets never stand in for an authenticated task deadline.

use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncRead;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWrite;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::time::timeout;

use super::IO_TIMEOUT;
use crate::AgentdError;
use crate::MAX_CONTROL_FRAME_BYTES;

pub(super) async fn read_frame(reader: impl AsyncRead + Unpin) -> Result<Vec<u8>, AgentdError> {
    let mut reader = BufReader::new(reader).take(MAX_CONTROL_FRAME_BYTES + 1);
    let mut frame = Vec::new();
    let count = timeout(IO_TIMEOUT, reader.read_until(b'\n', &mut frame))
        .await
        .map_err(|_| AgentdError::Protocol("agentd control request frame timed out".into()))??;
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
        writer.shutdown().await
    })
    .await
    .map_err(|_| AgentdError::Protocol("agentd control response frame timed out".into()))??;
    Ok(())
}

#[cfg(test)]
#[path = "control_frames_tests.rs"]
mod tests;
