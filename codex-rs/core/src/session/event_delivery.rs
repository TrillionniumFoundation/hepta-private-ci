use codex_protocol::protocol::Event;
use codex_protocol::protocol::EventMsg;
use tracing::debug;

use crate::session::session::Session;
use crate::session::turn_context::TurnContext;
use crate::state::StartTransitionCompletion;

pub(super) enum EventDelivery {
    Immediate,
    AfterTerminalization,
}

impl Session {
    /// Retains the normal status, parent-notification and realtime ordering,
    /// but keeps the client terminal event private until admission is ready.
    pub(crate) async fn prepare_terminal_event(
        &self,
        turn_context: &TurnContext,
        event: EventMsg,
    ) -> Event {
        self.send_event_with_delivery(turn_context, event, EventDelivery::AfterTerminalization)
            .await
            .unwrap_or_else(|| panic!("terminal event delivery is deferred"))
    }

    pub(crate) async fn publish_terminal_event_and_release_admission(
        &self,
        event: Option<Event>,
        completion: &StartTransitionCompletion,
    ) {
        // Starts recheck their fences under this lock. Queue the old terminal
        // synchronously before a newly admitted turn can publish TurnStarted.
        // Session event channels are unbounded, so no send can wait for space.
        let _active_turn = self.active_turn.lock().await;
        completion.release_admission();
        if let Some(event) = event
            && let Err(err) = self.tx_event.try_send(event)
        {
            debug!("failed to queue terminal event: {err}");
        }
    }
}
