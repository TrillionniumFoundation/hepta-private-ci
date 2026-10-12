use codex_protocol::protocol::Event;
use tracing::debug;

use crate::session::session::Session;
use crate::session::turn_context::TurnContext;

pub(super) enum EventDelivery {
    Immediate,
    AfterTerminalization,
}

impl Session {
    /// Prepares a terminal without granting permission for another turn.
    pub(crate) async fn prepare_terminal_event(&self, turn_context: &TurnContext, event: &Event) {
        assert!(
            self.send_event_with_delivery(
                turn_context,
                event.msg.clone(),
                EventDelivery::AfterTerminalization,
            )
            .await
            .is_some(),
            "terminal event delivery is deferred",
        );
    }

    /// The finish owner calls this with active_turn locked. The channel is
    /// unbounded, so delivery and admission release require no await.
    pub(crate) fn enqueue_prepared_terminal_event(&self, retained: &mut Option<Event>) -> bool {
        let event = retained
            .take()
            .unwrap_or_else(|| panic!("prepared terminal remains owned until publication"));
        match self.tx_event.try_send(event) {
            Ok(()) => true,
            Err(error) => {
                debug!("failed to queue terminal event: {error}");
                *retained = Some(error.into_inner());
                false
            }
        }
    }
}
