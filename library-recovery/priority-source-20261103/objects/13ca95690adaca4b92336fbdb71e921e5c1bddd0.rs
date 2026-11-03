//! Specific real-worker fixture for higher-level shutdown qualification.
//! Compiled only by the existing `test-support` feature, never normal clients.
use super::*;
use std::pin::Pin;
use std::sync::atomic::AtomicBool;
use std::task::Context;
use std::task::Poll;
use tokio::io::DuplexStream;
use tokio::io::ReadBuf;
use tokio::task::AbortHandle;
use tokio::task::JoinHandle;

// Test-only diagnostics tolerate loaded runners; production budgets are unchanged.
const PROBE_WAIT: Duration = Duration::from_secs(10);

struct CloseFlushGate {
    stream: DuplexStream,
    armed: Arc<AtomicBool>,
    close_written: bool,
    blocked: Option<oneshot::Sender<()>>,
    dropped: Option<oneshot::Sender<()>>,
}

impl Drop for CloseFlushGate {
    fn drop(&mut self) {
        if let Some(sender) = self.dropped.take() {
            let _ = sender.send(());
        }
    }
}

impl AsyncRead for CloseFlushGate {
    fn poll_read(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &mut ReadBuf<'_>,
    ) -> Poll<IoResult<()>> {
        Pin::new(&mut self.stream).poll_read(cx, buf)
    }
}

impl AsyncWrite for CloseFlushGate {
    fn poll_write(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        bytes: &[u8],
    ) -> Poll<IoResult<usize>> {
        let result = Pin::new(&mut self.stream).poll_write(cx, bytes);
        if matches!(result, Poll::Ready(Ok(written)) if written > 0)
            && self.armed.load(Ordering::SeqCst)
            && bytes.first().is_some_and(|byte| byte & 0x0f == 0x08)
        {
            self.close_written = true;
        }
        result
    }

    fn poll_flush(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<IoResult<()>> {
        if self.close_written {
            if let Some(sender) = self.blocked.take() {
                let _ = sender.send(());
            }
            // Deliberate permanent transport fault, only after an actual close
            // frame. Cancellation, not a background cleanup task, releases it.
            return Poll::Pending;
        }
        Pin::new(&mut self.stream).poll_flush(cx)
    }

    fn poll_shutdown(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<IoResult<()>> {
        Pin::new(&mut self.stream).poll_shutdown(cx)
    }
}

/// Test-only evidence from the real client's worker, not a synthetic task.
#[doc(hidden)]
pub struct RemoteBlockedCloseTestProbe {
    worker: AbortHandle,
    blocked: oneshot::Receiver<()>,
    dropped: Option<oneshot::Receiver<()>>,
    pending: Option<JoinHandle<IoResult<RequestResult>>>,
    peer: Option<JoinHandle<IoResult<()>>>,
}

impl RemoteBlockedCloseTestProbe {
    pub async fn wait_for_blocked_close(&mut self) -> IoResult<()> {
        timeout(PROBE_WAIT, &mut self.blocked)
            .await
            .map_err(IoError::other)?
            .map_err(IoError::other)
    }

    pub fn worker_finished(&self) -> bool {
        self.worker.is_finished()
    }

    pub fn pending_request_finished(&self) -> bool {
        self.pending.as_ref().is_none_or(JoinHandle::is_finished)
    }

    /// Observe actual resource destruction and waiter closure before cleanup.
    /// This is completion after cancellation, not synchronous joining in Drop.
    pub async fn observe_stopped(&mut self) -> IoResult<()> {
        if let Some(dropped) = self.dropped.take() {
            timeout(PROBE_WAIT, dropped)
                .await
                .map_err(IoError::other)?
                .map_err(IoError::other)?;
        }
        if let Some(pending) = self.pending.as_mut() {
            let result = timeout(PROBE_WAIT, pending)
                .await
                .map_err(IoError::other)?
                .map_err(IoError::other)?;
            self.pending.take();
            if result.is_ok() {
                return Err(IoError::other(
                    "unanswered request unexpectedly received a response",
                ));
            }
        }
        if !self.worker.is_finished() {
            return Err(IoError::other(
                "transport dropped before worker completion was observed",
            ));
        }
        Ok(())
    }

    /// Explicit bounded cleanup for the legacy negative control and peer.
    pub async fn cleanup(&mut self) -> IoResult<()> {
        self.worker.abort();
        let result = self.observe_stopped().await;
        if let Some(peer) = self.peer.take() {
            peer.abort();
            match timeout(PROBE_WAIT, peer).await.map_err(IoError::other)? {
                Ok(result) => result?,
                Err(error) if error.is_cancelled() => {}
                Err(error) => return Err(IoError::other(error)),
            }
        }
        result
    }
}

impl Drop for RemoteBlockedCloseTestProbe {
    fn drop(&mut self) {
        self.worker.abort();
        if let Some(pending) = &self.pending {
            pending.abort();
        }
        if let Some(peer) = &self.peer {
            peer.abort();
        }
    }
}

impl RemoteAppServerClient {
    /// Existing test-support only: an exclusive client with one unanswered read
    /// and a real worker that will block flushing its close frame.
    #[doc(hidden)]
    pub async fn blocked_close_fixture_for_test() -> IoResult<(Self, RemoteBlockedCloseTestProbe)> {
        let (stream, peer_stream) = tokio::io::duplex(4096);
        let armed = Arc::new(AtomicBool::new(false));
        let (blocked_tx, blocked_rx) = oneshot::channel();
        let (dropped_tx, dropped_rx) = oneshot::channel();
        let stream = CloseFlushGate {
            stream,
            armed: Arc::clone(&armed),
            close_written: false,
            blocked: Some(blocked_tx),
            dropped: Some(dropped_tx),
        };
        let client_stream = WebSocketStream::from_raw_socket(
            stream,
            tokio_tungstenite::tungstenite::protocol::Role::Client,
            None,
        )
        .await;
        let (read_tx, read_rx) = oneshot::channel();
        let peer = tokio::spawn(async move {
            let mut websocket = WebSocketStream::from_raw_socket(
                peer_stream,
                tokio_tungstenite::tungstenite::protocol::Role::Server,
                None,
            )
            .await;
            while let Some(Ok(Message::Text(text))) = websocket.next().await {
                let request: serde_json::Value =
                    serde_json::from_str(&text).map_err(IoError::other)?;
                match request["method"].as_str() {
                    Some("initialize") => websocket.send(Message::Text(serde_json::json!({
                        "id":request["id"], "result":{"userAgent":"blocked-close/1","codexHome":"fixture"}
                    }).to_string().into())).await.map_err(IoError::other)?,
                    Some("initialized") => {},
                    Some("thread/turns/list") => {
                        if request["id"] != serde_json::json!(41) {
                            return Err(IoError::other("fixture received a different read identity"));
                        }
                        read_tx.send(()).map_err(|_| IoError::other("read observer dropped"))?;
                        std::future::pending::<()>().await;
                        break;
                    }
                    other => return Err(IoError::other(format!("unexpected fixture method {other:?}"))),
                }
            }
            Ok::<(), IoError>(())
        });
        let args = RemoteAppServerConnectArgs {
            endpoint: RemoteAppServerEndpoint::WebSocket {
                websocket_url: "ws://unused.test".into(),
                auth_token: None,
            },
            client_name: "blocked-close".into(),
            client_version: "1".into(),
            experimental_api: true,
            mcp_server_openai_form_elicitation: false,
            opt_out_notification_methods: Vec::new(),
            channel_capacity: 8,
        };
        let client = match Self::connect_with_stream(
            8,
            RemoteEventMode::Unbounded,
            "in-memory blocked-close fixture".into(),
            client_stream,
            args.initialize_params(),
        )
        .await
        {
            Ok(client) => client,
            Err(error) => {
                peer.abort();
                let _ = peer.await;
                return Err(error);
            }
        };
        let handle = client.request_handle();
        let pending = tokio::spawn(async move {
            handle
                .request_json_rpc(JSONRPCRequest {
                    id: RequestId::Integer(41),
                    method: "thread/turns/list".into(),
                    params: Some(serde_json::json!({"threadId":"019153a4-3088-7e03-a56a-9b1964f75ddd","limit":1})),
                    trace: None,
                })
                .await
        });
        let mut probe = RemoteBlockedCloseTestProbe {
            worker: client.worker_handle.abort_handle(),
            blocked: blocked_rx,
            dropped: Some(dropped_rx),
            pending: Some(pending),
            peer: Some(peer),
        };
        if let Err(error) = timeout(PROBE_WAIT, read_rx)
            .await
            .map_err(IoError::other)
            .and_then(|result| result.map_err(IoError::other))
        {
            let _ = probe.cleanup().await;
            return Err(error);
        }
        armed.store(true, Ordering::SeqCst);
        Ok((client, probe))
    }
}
