//! Bounded loopback transport. Accepted byte counts describe socket writes,
//! never proof that a remote application consumed those bytes.

use std::future::Future;
use std::time::Duration;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use tokio::io::AsyncWrite;
use tokio::io::AsyncWriteExt;
use tokio::task::JoinSet;

const MAX_CONNECTION_TASKS: usize = 32;
const UI_CHUNK_BYTES: usize = 64 * 1024;
const UI_TRANSFER_TIMEOUT: Duration = Duration::from_secs(30);
const MAX_UI_HEADER_BYTES: usize = 4096;

#[derive(Default)]
pub(crate) struct ConnectionTasks {
    tasks: JoinSet<()>,
}

impl ConnectionTasks {
    /// Overload closes the newly accepted socket by dropping its unpolled
    /// future. No task or permit-waiting queue is created for rejected work.
    pub(crate) fn try_spawn<F>(&mut self, connection: F) -> bool
    where
        F: Future<Output = Result<()>> + Send + 'static,
    {
        while let Some(result) = self.tasks.try_join_next() {
            if let Err(error) = result {
                eprintln!("hepta connection task failed: {error}");
            }
        }
        if self.tasks.len() >= MAX_CONNECTION_TASKS {
            return false;
        }
        self.tasks.spawn(async move {
            if let Err(error) = connection.await {
                eprintln!("hepta loopback request failed: {error:#}");
            }
        });
        true
    }

    pub(crate) async fn shutdown(&mut self) {
        self.tasks.shutdown().await;
    }
}

pub(crate) async fn write_ui_response<W: AsyncWrite + Unpin>(
    stream: &mut W,
    headers: &[u8],
    body: &[u8],
) -> Result<()> {
    write_ui_with_budget(stream, headers, body, UI_TRANSFER_TIMEOUT).await
}

async fn write_ui_with_budget<W: AsyncWrite + Unpin>(
    stream: &mut W,
    headers: &[u8],
    body: &[u8],
    budget: Duration,
) -> Result<()> {
    ensure!(
        headers.len() <= MAX_UI_HEADER_BYTES,
        "UI headers exceed bound"
    );
    ensure!(
        body.len() <= crate::ui_bundle::MAX_ASSET_BYTES,
        "UI asset exceeds bound"
    );
    let total = headers.len() + body.len();
    let mut accepted = 0;
    let outcome = tokio::time::timeout(budget, async {
        for bytes in [headers, body] {
            let mut offset = 0;
            while offset < bytes.len() {
                let end = (offset + UI_CHUNK_BYTES).min(bytes.len());
                let written = stream.write(&bytes[offset..end]).await?;
                if written == 0 {
                    return Err(std::io::Error::from(std::io::ErrorKind::WriteZero));
                }
                offset += written;
                accepted += written;
                // Yield between bounded chunks even when the socket stays ready.
                tokio::task::yield_now().await;
            }
        }
        stream.flush().await
    })
    .await;
    outcome
        .with_context(|| {
            format!("UI transfer timed out; socket accepted {accepted}/{total} bytes")
        })?
        .with_context(|| format!("UI transfer failed; socket accepted {accepted}/{total} bytes"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;
    use std::sync::atomic::AtomicBool;
    use std::sync::atomic::Ordering;
    use tokio::io::AsyncReadExt;

    #[tokio::test(start_paused = true)]
    async fn slow_reader_beyond_api_budget_receives_exact_asset() {
        let (mut writer, mut reader) = tokio::io::duplex(16);
        let task =
            tokio::spawn(async move { write_ui_response(&mut writer, b"header", &[7; 128]).await });
        tokio::time::sleep(Duration::from_secs(6)).await;
        let mut bytes = Vec::new();
        reader.read_to_end(&mut bytes).await.unwrap();
        task.await.unwrap().unwrap();
        assert_eq!(bytes, [b"header".as_slice(), &[7; 128]].concat());
    }

    #[tokio::test(start_paused = true)]
    async fn old_five_second_budget_expires_with_exact_partial_count() {
        let (mut writer, _reader) = tokio::io::duplex(16);
        let error = write_ui_with_budget(&mut writer, b"header", &[7; 128], Duration::from_secs(5))
            .await
            .unwrap_err();
        assert!(error.to_string().contains("socket accepted 16/134 bytes"));
        assert!(error.to_string().contains("timed out"));
    }

    #[tokio::test(start_paused = true)]
    async fn permanent_backpressure_still_expires_at_asset_budget() {
        let (mut writer, _reader) = tokio::io::duplex(16);
        let start = tokio::time::Instant::now();
        let error = write_ui_response(&mut writer, b"header", &[7; 128])
            .await
            .unwrap_err();
        assert_eq!(start.elapsed(), UI_TRANSFER_TIMEOUT);
        assert!(error.to_string().contains("socket accepted 16/134 bytes"));
    }

    #[tokio::test]
    async fn disconnected_writer_reports_error_without_claiming_delivery() {
        let (mut writer, reader) = tokio::io::duplex(16);
        drop(reader);
        let error = write_ui_response(&mut writer, b"header", &[7; 128])
            .await
            .unwrap_err();
        assert!(error.to_string().contains("socket accepted 0/134 bytes"));
        assert!(error.to_string().contains("failed"));
    }

    #[tokio::test]
    async fn connection_cap_drops_overload_without_polling_or_retaining_it() {
        let mut tasks = ConnectionTasks::default();
        for _ in 0..MAX_CONNECTION_TASKS {
            assert!(tasks.try_spawn(std::future::pending()));
        }
        let observed = Arc::new(AtomicBool::new(false));
        let polled = observed.clone();
        let retained = Arc::new(());
        let weak = Arc::downgrade(&retained);
        assert!(!tasks.try_spawn(async move {
            let _retained = retained;
            polled.store(true, Ordering::SeqCst);
            Ok(())
        }));
        assert!(!observed.load(Ordering::SeqCst));
        assert!(weak.upgrade().is_none());
        assert_eq!(tasks.tasks.len(), MAX_CONNECTION_TASKS);
        tasks.shutdown().await;
        assert!(tasks.tasks.is_empty());
        assert!(tasks.try_spawn(async { Ok(()) }));
        tasks.shutdown().await;
    }

    #[tokio::test]
    async fn shutdown_and_completed_connections_release_owned_resources() {
        let retained = Arc::new(());
        let weak = Arc::downgrade(&retained);
        let mut tasks = ConnectionTasks::default();
        assert!(tasks.try_spawn(async move {
            let _retained = retained;
            std::future::pending().await
        }));
        tokio::task::yield_now().await;
        tasks.shutdown().await;
        assert!(weak.upgrade().is_none());
        let mut completed = Vec::new();
        for _ in 0..MAX_CONNECTION_TASKS {
            let (sender, receiver) = tokio::sync::oneshot::channel();
            completed.push(receiver);
            assert!(tasks.try_spawn(async move {
                let _ = sender.send(());
                Ok(())
            }));
        }
        for receiver in completed {
            receiver.await.unwrap();
        }
        assert!(tasks.try_spawn(async { Ok(()) }));
        assert_eq!(tasks.tasks.len(), 1);
        tasks.shutdown().await;
    }

    #[derive(Default)]
    struct RecordingWriter {
        bytes: Vec<u8>,
        largest_write: usize,
        fail_after: Option<usize>,
    }

    impl AsyncWrite for RecordingWriter {
        fn poll_write(
            mut self: std::pin::Pin<&mut Self>,
            _cx: &mut std::task::Context<'_>,
            buffer: &[u8],
        ) -> std::task::Poll<std::io::Result<usize>> {
            self.largest_write = self.largest_write.max(buffer.len());
            let remaining = self
                .fail_after
                .map_or(buffer.len(), |limit| limit.saturating_sub(self.bytes.len()));
            if remaining == 0 {
                return std::task::Poll::Ready(Err(std::io::ErrorKind::BrokenPipe.into()));
            }
            let written = buffer.len().min(remaining);
            self.bytes.extend_from_slice(&buffer[..written]);
            std::task::Poll::Ready(Ok(written))
        }

        fn poll_flush(
            self: std::pin::Pin<&mut Self>,
            _cx: &mut std::task::Context<'_>,
        ) -> std::task::Poll<std::io::Result<()>> {
            std::task::Poll::Ready(Ok(()))
        }

        fn poll_shutdown(
            self: std::pin::Pin<&mut Self>,
            _cx: &mut std::task::Context<'_>,
        ) -> std::task::Poll<std::io::Result<()>> {
            std::task::Poll::Ready(Ok(()))
        }
    }

    #[tokio::test]
    async fn ready_writer_still_uses_bounded_chunks_and_exact_bytes() {
        let mut writer = RecordingWriter::default();
        let body = vec![7; UI_CHUNK_BYTES * 2 + 3];
        write_ui_response(&mut writer, b"header", &body)
            .await
            .unwrap();
        assert_eq!(writer.largest_write, UI_CHUNK_BYTES);
        assert_eq!(
            writer.bytes,
            [b"header".as_slice(), body.as_slice()].concat()
        );
    }

    #[tokio::test]
    async fn oversized_headers_fail_before_any_write() {
        let mut writer = RecordingWriter::default();
        assert!(
            write_ui_response(&mut writer, &vec![0; MAX_UI_HEADER_BYTES + 1], b"body")
                .await
                .is_err()
        );
        assert!(writer.bytes.is_empty());
    }

    #[tokio::test]
    async fn mid_transfer_writer_error_reports_exact_accepted_bytes() {
        let mut writer = RecordingWriter {
            fail_after: Some(17),
            ..Default::default()
        };
        let error = write_ui_response(&mut writer, b"header", &[7; 128])
            .await
            .unwrap_err();
        assert_eq!(writer.bytes.len(), 17);
        assert!(error.to_string().contains("socket accepted 17/134 bytes"));
        assert!(error.to_string().contains("failed"));
    }
}
