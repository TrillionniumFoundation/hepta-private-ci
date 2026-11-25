//! In-process event delivery. Completion belongs to the emitting owner, never to a turn-ID lookup.

use std::sync::Arc;

use async_channel::RecvError;
use async_channel::SendError;
#[cfg(test)]
use async_channel::TryRecvError;
use codex_protocol::protocol::Event;

use crate::state::StartTransitionCompletion;

/// Read-only completion of the exact owner that emitted a terminal event.
///
/// An unresolved failed-closed owner does not authorize a completed notification. This handle
/// neither clears its admission fence nor waits for any subsequent turn, even if IDs are reused.
#[derive(Clone, Default)]
pub struct TerminalEventCompletion(Option<Arc<StartTransitionCompletion>>);

impl TerminalEventCompletion {
    pub(crate) fn owned(completion: Arc<StartTransitionCompletion>) -> Self {
        Self(Some(completion))
    }

    pub async fn wait(&self) {
        if let Some(completion) = &self.0 {
            completion.wait().await;
        }
    }
}

impl std::fmt::Debug for TerminalEventCompletion {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("TerminalEventCompletion")
            .field("owner_bound", &self.0.is_some())
            .finish_non_exhaustive()
    }
}

/// An event and its in-process terminalization witness, delivered as one channel item.
/// No completion state is serialized into the protocol event or persisted in a rollout.
#[derive(Clone, Debug)]
pub struct EventDelivery {
    pub event: Event,
    pub terminalization: TerminalEventCompletion,
}

impl From<Event> for EventDelivery {
    fn from(event: Event) -> Self {
        Self {
            event,
            terminalization: TerminalEventCompletion::default(),
        }
    }
}

/// Sends ordinary protocol events to the same queue used by owner-bound terminal events.
#[derive(Clone)]
pub struct EventSender(async_channel::Sender<EventDelivery>);

impl EventSender {
    pub async fn send(&self, event: Event) -> Result<(), SendError<Event>> {
        self.0
            .send(event.into())
            .await
            .map_err(|error| SendError(error.0.event))
    }

    pub(crate) async fn send_delivery(
        &self,
        delivery: EventDelivery,
    ) -> Result<(), SendError<EventDelivery>> {
        self.0.send(delivery).await
    }

    pub(crate) async fn closed(&self) {
        self.0.closed().await;
    }
}

#[derive(Clone)]
pub(crate) struct EventReceiver(async_channel::Receiver<EventDelivery>);

impl EventReceiver {
    pub(crate) async fn recv(&self) -> Result<Event, RecvError> {
        self.0.recv().await.map(|delivery| delivery.event)
    }

    /// This future only receives one item. Waiting for its owner is a separate, explicit step,
    /// so cancelling a listener's select cannot discard an event after it has been received.
    pub(crate) async fn recv_delivery(&self) -> Result<EventDelivery, RecvError> {
        self.0.recv().await
    }

    #[cfg(test)]
    pub(crate) fn try_recv(&self) -> Result<Event, TryRecvError> {
        self.0.try_recv().map(|delivery| delivery.event)
    }
}

pub(crate) fn unbounded() -> (EventSender, EventReceiver) {
    let (sender, receiver) = async_channel::unbounded();
    (EventSender(sender), EventReceiver(receiver))
}

pub(crate) fn bounded(capacity: usize) -> (EventSender, EventReceiver) {
    let (sender, receiver) = async_channel::bounded(capacity);
    (EventSender(sender), EventReceiver(receiver))
}

#[cfg(test)]
#[path = "event_delivery_tests.rs"]
mod tests;
