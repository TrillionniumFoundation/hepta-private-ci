//! Host-owned event delivery without an intermediate forwarding task or queue.

use std::future::Future;
use std::sync::Arc;

use async_channel::SendError;
use async_channel::Sender;
use codex_protocol::protocol::Event;
use futures::future::BoxFuture;

type SendEvent = dyn Fn(Event) -> BoxFuture<'static, Result<(), SendError<Event>>> + Send + Sync;

/// The MCP runtime reports ordinary events through the host's original event queue.
#[derive(Clone)]
pub struct McpEventSender(Arc<SendEvent>);

impl McpEventSender {
    pub fn new<F, Fut>(send: F) -> Self
    where
        F: Fn(Event) -> Fut + Send + Sync + 'static,
        Fut: Future<Output = Result<(), SendError<Event>>> + Send + 'static,
    {
        Self(Arc::new(move |event| Box::pin(send(event))))
    }

    pub async fn send(&self, event: Event) -> Result<(), SendError<Event>> {
        (self.0)(event).await
    }
}

impl From<Sender<Event>> for McpEventSender {
    fn from(sender: Sender<Event>) -> Self {
        Self::new(move |event| {
            let sender = sender.clone();
            async move { sender.send(event).await }
        })
    }
}
