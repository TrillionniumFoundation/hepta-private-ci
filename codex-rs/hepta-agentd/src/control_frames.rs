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
    let started = std::time::Instant::now();
    let result = timeout(IO_TIMEOUT, reader.read_until(b'\n', &mut frame))
        .await
        .map_err(|_| AgentdError::Protocol("agentd control request frame timed out".into()))?;
    let count = result.inspect_err(|error| {
        report_io_failure("read_until", frame.len(), started.elapsed(), error);
    })?;
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
    let started = std::time::Instant::now();
    let mut stage = "write_all";
    let result = timeout(IO_TIMEOUT, async {
        writer.write_all(bytes).await?;
        stage = "shutdown";
        // A peer can read the complete frame and close before this half-close.
        // Only the shutdown syscall may report that already-closed connection;
        // a failed or partial write must still propagate.
        match writer.shutdown().await {
            Err(error) if error.kind() == std::io::ErrorKind::NotConnected => Ok(()),
            result => result,
        }
    })
    .await
    .map_err(|_| AgentdError::Protocol("agentd control response frame timed out".into()))?;
    result.inspect_err(|error| {
        report_io_failure(stage, bytes.len(), started.elapsed(), error);
    })?;
    Ok(())
}

fn report_io_failure(
    stage: &'static str,
    frame_len: usize,
    elapsed: std::time::Duration,
    error: &std::io::Error,
) {
    use std::io::Write;

    let kind = error.kind();
    let raw_os = error.raw_os_error();
    let elapsed_us = elapsed.as_micros();
    let _ = writeln!(
        std::io::stderr(),
        "hepta-agentd control-frame io-error stage={stage} kind={kind:?} raw_os={raw_os:?} frame_len={frame_len} elapsed_us={elapsed_us}"
    );
}

#[cfg(test)]
#[path = "control_frames_tests.rs"]
mod tests;
