//! One-use owner checks at the remote transport's first-write boundary.

use std::future::Future;
use std::future::poll_fn;
use std::io;
use std::pin::Pin;

use codex_app_server_protocol::JSONRPCMessage;
use futures::Sink;
use futures::SinkExt;
use tokio::io::AsyncRead;
use tokio::io::AsyncWrite;
use tokio::sync::oneshot;
use tokio_tungstenite::WebSocketStream;
use tokio_tungstenite::tungstenite::Message;

pub(crate) type BeforeSend = Pin<Box<dyn Future<Output = io::Result<()>> + Send + 'static>>;

pub(crate) enum GuardedWriteError {
    BeforeSend(io::Error),
    Transport(io::Error),
}

pub(crate) async fn write_guarded_request<S, T>(
    stream: &mut WebSocketStream<S>,
    message: JSONRPCMessage,
    before_send: BeforeSend,
    response_tx: &mut oneshot::Sender<T>,
) -> Result<(), GuardedWriteError>
where
    S: AsyncRead + AsyncWrite + Unpin,
{
    let payload = serde_json::to_string(&message)
        .map_err(|error| GuardedWriteError::Transport(io::Error::other(error)))?;
    // Wait for transport readiness before polling the owner's live check.
    // Only this worker owns the stream, so no other command can consume readiness.
    tokio::select! {
        biased;
        _ = response_tx.closed() => return Err(cancelled()),
        result = poll_fn(|cx| Pin::new(&mut *stream).poll_ready(cx)) => {
            result.map_err(|error| GuardedWriteError::Transport(io::Error::other(error)))?;
        }
    }
    tokio::select! {
        biased;
        _ = response_tx.closed() => return Err(cancelled()),
        result = before_send => result.map_err(GuardedWriteError::BeforeSend)?,
    }
    if response_tx.is_closed() {
        return Err(cancelled());
    }
    // No await or channel handoff lies between the live check and first send.
    stream
        .start_send_unpin(Message::Text(payload.into()))
        .map_err(|error| GuardedWriteError::Transport(io::Error::other(error)))?;
    stream
        .flush()
        .await
        .map_err(|error| GuardedWriteError::Transport(io::Error::other(error)))
}

fn cancelled() -> GuardedWriteError {
    GuardedWriteError::BeforeSend(io::Error::new(
        io::ErrorKind::Interrupted,
        "guarded request was cancelled before first send",
    ))
}

#[cfg(test)]
#[path = "remote_send_guard_tests.rs"]
mod tests;
