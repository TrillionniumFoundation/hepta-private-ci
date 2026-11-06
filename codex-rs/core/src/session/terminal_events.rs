//! Public terminal events observe their exact cleanup owner without changing admission.

use std::collections::HashMap;
use std::collections::VecDeque;
use std::sync::Arc;
use std::sync::Mutex;

use async_channel::Receiver;
use async_channel::SendError;
use async_channel::Sender;
use codex_protocol::protocol::Event;
use codex_protocol::protocol::EventMsg;

use super::SessionLoopTermination;
use crate::state::StartTransitionCompletion;
use codex_protocol::error::CodexErr;
use codex_protocol::error::Result as CodexResult;

#[derive(Clone, Copy, Eq, Hash, PartialEq)]
enum TerminalKind {
    Complete,
    Aborted,
}

impl TerminalKind {
    fn from_event(message: &EventMsg) -> Option<Self> {
        match message {
            EventMsg::TurnComplete(_) => Some(Self::Complete),
            EventMsg::TurnAborted(_) => Some(Self::Aborted),
            _ => None,
        }
    }
}

type TerminalKey = (String, TerminalKind);

struct PublicationRecord {
    identity: Arc<()>,
    completion: Option<Arc<StartTransitionCompletion>>,
}

type TerminalOwners = HashMap<TerminalKey, VecDeque<PublicationRecord>>;

struct DeliveryOrder(tokio::sync::Semaphore);

impl Default for DeliveryOrder {
    fn default() -> Self {
        Self(tokio::sync::Semaphore::new(/*permits*/ 1))
    }
}

impl DeliveryOrder {
    async fn acquire(&self) -> tokio::sync::SemaphorePermit<'_> {
        // This private semaphore is never closed. The permit represents FIFO
        // admission across asynchronous work, rather than a borrowed data lock.
        self.0
            .acquire()
            .await
            .unwrap_or_else(|error| panic!("terminal delivery admission closed: {error}"))
    }
}

#[derive(Default)]
struct PublicationState {
    order: DeliveryOrder,
    owners: Mutex<TerminalOwners>,
}

#[derive(Clone, Default)]
pub(crate) struct TerminalPublications(Arc<PublicationState>);

struct PendingPublication {
    publications: TerminalPublications,
    key: TerminalKey,
    identity: Arc<()>,
    delivered: bool,
}

impl Drop for PendingPublication {
    fn drop(&mut self) {
        if self.delivered {
            return;
        }
        let mut owners =
            self.publications.0.owners.lock().unwrap_or_else(|error| {
                panic!("terminal publication registry poisoned: {error:?}")
            });
        if let Some(queue) = owners.get_mut(&self.key) {
            queue.retain(|record| !Arc::ptr_eq(&record.identity, &self.identity));
            if queue.is_empty() {
                owners.remove(&self.key);
            }
        }
    }
}

impl TerminalPublications {
    pub(crate) async fn deliver(
        &self,
        sender: &Sender<Event>,
        event: Event,
        completion: Option<Arc<StartTransitionCompletion>>,
    ) -> Result<(), SendError<Event>> {
        let Some(kind) = TerminalKind::from_event(&event.msg) else {
            return sender.send(event).await;
        };
        // Serialize terminal registration and actual send, including ownerless
        // terminal events. Ordinary events retain their original send path.
        let _order = self.0.order.acquire().await;
        let key = (event.id.clone(), kind);
        let identity = Arc::new(());
        self.0
            .owners
            .lock()
            .unwrap_or_else(|error| panic!("terminal publication registry poisoned: {error:?}"))
            .entry(key.clone())
            .or_default()
            .push_back(PublicationRecord {
                identity: Arc::clone(&identity),
                completion,
            });
        let mut publication = PendingPublication {
            publications: self.clone(),
            key,
            identity,
            delivered: false,
        };
        // async_channel::send preserves bounded-channel backpressure and does
        // not deliver if cancelled while pending. The RAII guard removes only
        // this receipt on cancellation/error. No await separates successful
        // enqueue from commit; the short registry lock never spans send.await.
        sender.send(event).await?;
        publication.delivered = true;
        Ok(())
    }

    fn take(&self, event: &Event) -> Option<Arc<StartTransitionCompletion>> {
        let kind = TerminalKind::from_event(&event.msg)?;
        let key = (event.id.clone(), kind);
        let mut owners =
            self.0.owners.lock().unwrap_or_else(|error| {
                panic!("terminal publication registry poisoned: {error:?}")
            });
        let queue = owners.get_mut(&key)?;
        let record = queue.pop_front();
        if queue.is_empty() {
            owners.remove(&key);
        }
        record.and_then(|record| record.completion)
    }
}

struct PendingEvent {
    event: Event,
    completion: Option<Arc<StartTransitionCompletion>>,
}

#[derive(Default)]
pub(crate) struct PublicEventDelivery {
    order: DeliveryOrder,
    pending: Mutex<Option<PendingEvent>>,
}

impl PublicEventDelivery {
    pub(crate) async fn next(
        &self,
        receiver: &Receiver<Event>,
        publications: &TerminalPublications,
        stopped: SessionLoopTermination,
    ) -> CodexResult<Event> {
        // Keep one admitted receiver across awaits, while every data access
        // holds only a short synchronous lock. Cancelling releases admission
        // without discarding an event already removed from the raw channel.
        let _order = self.order.acquire().await;
        let needs_event = {
            let pending = self
                .pending
                .lock()
                .unwrap_or_else(|error| panic!("terminal pending event poisoned: {error:?}"));
            pending.is_none()
        };
        if needs_event {
            let event = receiver
                .recv()
                .await
                .map_err(|_| CodexErr::InternalAgentDied)?;
            let completion = publications.take(&event);
            // Store before the next await: cancellation must not lose a
            // terminal event already removed from the raw FIFO channel.
            *self
                .pending
                .lock()
                .unwrap_or_else(|error| panic!("terminal pending event poisoned: {error:?}")) =
                Some(PendingEvent { event, completion });
        }
        let completion = {
            let pending = self
                .pending
                .lock()
                .unwrap_or_else(|error| panic!("terminal pending event poisoned: {error:?}"));
            pending
                .as_ref()
                .and_then(|event| event.completion.as_ref())
                .cloned()
        };
        if let Some(completion) = completion
            && !completion.is_complete()
        {
            tokio::select! {
                () = completion.wait() => {},
                () = stopped => {
                    // A dead loop cannot certify an unfinished cleanup. Keep
                    // the event and its witness instead of publishing false
                    // completion or retiring an authority fence.
                    if !completion.is_complete() {
                        return Err(CodexErr::InternalAgentDied);
                    }
                },
            }
        }
        // No await may occur after removing the retained event. Holding this
        // admission permit also keeps concurrent next_event callers in FIFO order.
        self.pending
            .lock()
            .unwrap_or_else(|error| panic!("terminal pending event poisoned: {error:?}"))
            .take()
            .map(|pending| pending.event)
            .ok_or(CodexErr::InternalAgentDied)
    }
}

#[cfg(test)]
#[path = "terminal_events_tests.rs"]
mod tests;
