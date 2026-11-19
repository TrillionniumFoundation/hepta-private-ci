use std::io::ErrorKind;
use std::pin::Pin;
use std::task::Context;
use std::task::Poll;

use pretty_assertions::assert_eq;
use tokio::io::AsyncWriteExt;

use super::*;

#[tokio::test]
async fn original_control_frame_rejects_partial_input_with_unchanged_io_budget() {
    let (mut peer, reader) = tokio::io::duplex(/*max_buf_size*/ 16);
    peer.write_all(b"{").await.expect("partial transport frame");
    let error = read_frame(reader, Instant::now() + IO_TIMEOUT)
        .await
        .expect_err("partial frame cannot admit a request");
    assert!(matches!(
        error,
        AgentdError::Protocol(message) if message == "agentd control request frame timed out"
    ));
}

#[tokio::test]
async fn original_control_frame_rejects_oversize_input_before_admission() {
    let (mut peer, reader) = tokio::io::duplex(/*max_buf_size*/ 256);
    let sender = tokio::spawn(async move {
        peer.write_all(&vec![b'x'; MAX_CONTROL_FRAME_BYTES as usize + 1])
            .await
    });
    let error = read_frame(reader, Instant::now() + IO_TIMEOUT)
        .await
        .expect_err("oversize frame cannot admit a request");
    assert!(matches!(
        error,
        AgentdError::Protocol(message)
            if message == "agentd control request must be one bounded newline JSON frame"
    ));
    let _closed_peer = sender.await.expect("bounded oversized frame sender");
}

#[tokio::test]
async fn original_control_frame_bounds_a_nonreading_response_peer() {
    let (mut writer, _nonreading_peer) = tokio::io::duplex(/*max_buf_size*/ 1);
    let error = write_frame(&mut writer, b"response\n")
        .await
        .expect_err("slow reader must not hold the connection indefinitely");
    assert!(matches!(
        error,
        AgentdError::Protocol(message) if message == "agentd control response frame timed out"
    ));
}

struct ShutdownErrorWriter {
    written: Vec<u8>,
    write_error_after: Option<(usize, ErrorKind)>,
    shutdown_error: ErrorKind,
    shutdown_calls: usize,
}

impl ShutdownErrorWriter {
    fn new(shutdown_error: ErrorKind) -> Self {
        Self {
            written: Vec::new(),
            write_error_after: None,
            shutdown_error,
            shutdown_calls: 0,
        }
    }
}

impl AsyncWrite for ShutdownErrorWriter {
    fn poll_write(
        mut self: Pin<&mut Self>,
        _context: &mut Context<'_>,
        bytes: &[u8],
    ) -> Poll<std::io::Result<usize>> {
        let count = if let Some((limit, kind)) = self.write_error_after {
            let remaining = limit.saturating_sub(self.written.len());
            if remaining == 0 {
                return Poll::Ready(Err(kind.into()));
            }
            bytes.len().min(remaining)
        } else {
            bytes.len()
        };
        self.written.extend_from_slice(&bytes[..count]);
        Poll::Ready(Ok(count))
    }

    fn poll_flush(self: Pin<&mut Self>, _context: &mut Context<'_>) -> Poll<std::io::Result<()>> {
        Poll::Ready(Ok(()))
    }

    fn poll_shutdown(
        mut self: Pin<&mut Self>,
        _context: &mut Context<'_>,
    ) -> Poll<std::io::Result<()>> {
        self.shutdown_calls += 1;
        Poll::Ready(Err(self.shutdown_error.into()))
    }
}

#[tokio::test]
async fn original_control_frame_accepts_not_connected_only_after_complete_write()
-> Result<(), AgentdError> {
    let mut writer = ShutdownErrorWriter::new(ErrorKind::NotConnected);
    write_frame(&mut writer, b"response\n").await?;
    assert_eq!(writer.written, b"response\n");
    assert_eq!(writer.shutdown_calls, 1);
    Ok(())
}

#[tokio::test]
async fn original_control_frame_preserves_partial_write_errors_before_shutdown() {
    for kind in [
        ErrorKind::NotConnected,
        ErrorKind::BrokenPipe,
        ErrorKind::ConnectionReset,
    ] {
        let mut writer = ShutdownErrorWriter::new(ErrorKind::NotConnected);
        writer.write_error_after = Some((3, kind));
        let result = write_frame(&mut writer, b"response\n").await;
        assert!(matches!(result, Err(AgentdError::Io(error)) if error.kind() == kind));
        assert_eq!(writer.written, b"res");
        assert_eq!(writer.shutdown_calls, 0);
    }
}

#[tokio::test]
async fn original_control_frame_preserves_other_shutdown_errors() {
    for kind in [
        ErrorKind::BrokenPipe,
        ErrorKind::ConnectionReset,
        ErrorKind::PermissionDenied,
    ] {
        let mut writer = ShutdownErrorWriter::new(kind);
        let result = write_frame(&mut writer, b"response\n").await;
        assert!(matches!(result, Err(AgentdError::Io(error)) if error.kind() == kind));
        assert_eq!(writer.written, b"response\n");
        assert_eq!(writer.shutdown_calls, 1);
    }
}

#[tokio::test]
async fn expired_transport_budget_rejects_even_a_buffered_complete_frame() -> Result<(), AgentdError>
{
    let (mut peer, reader) = tokio::io::duplex(/*max_buf_size*/ 16);
    peer.write_all(b"{}\n").await?;
    let error = read_frame(reader, Instant::now())
        .await
        .expect_err("elapsed transport budget");
    assert!(matches!(error, AgentdError::Protocol(message)
        if message == "agentd control request frame timed out"));
    Ok(())
}

#[tokio::test]
async fn transport_handshake_does_not_restart_the_original_frame_budget() {
    let (_peer, reader) = tokio::io::duplex(/*max_buf_size*/ 16);
    let remaining_end = Instant::now() + std::time::Duration::from_millis(20);
    let error = timeout(
        std::time::Duration::from_secs(1),
        read_frame(reader, remaining_end),
    )
    .await
    .expect("read must use the remaining original budget")
    .expect_err("unreceived frame must expire");
    assert!(matches!(error, AgentdError::Protocol(message)
        if message == "agentd control request frame timed out"));
}
