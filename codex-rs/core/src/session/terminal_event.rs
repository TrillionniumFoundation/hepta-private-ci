//! Separates durable terminal records from the notification that admits a new turn.

use super::session::Session;
use super::turn_context::TurnContext;
use crate::agent::agent_status_from_event;
use crate::agent::status::is_final;
use codex_history::RolloutItem;
use codex_protocol::protocol::AgentStatus;
use codex_protocol::protocol::Event;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::MultiAgentVersion;
use codex_protocol::protocol::SessionSource;
use codex_protocol::protocol::SubAgentSource;
use tracing::debug;

#[cfg(test)]
#[path = "terminal_event_tests.rs"]
mod tests;

/// A terminal record whose persistence and turn-local cleanup already ran.
/// Its exact terminalization owner controls when clients may observe it.
pub(crate) struct PreparedTerminalEvent {
    event: Event,
    status: Option<AgentStatus>,
}

impl Session {
    pub(crate) async fn prepare_terminal_event(
        &self,
        turn_context: &TurnContext,
        msg: EventMsg,
    ) -> PreparedTerminalEvent {
        assert!(matches!(
            msg,
            EventMsg::TurnComplete(_) | EventMsg::TurnAborted(_)
        ));
        self.services
            .rollout_thread_trace
            .record_codex_turn_event(&turn_context.sub_id, &msg);
        self.services
            .rollout_thread_trace
            .record_tool_call_event(turn_context.sub_id.clone(), &msg);
        self.services.mcp_runtime.observe_event(&msg);
        self.persist_rollout_items(&[RolloutItem::EventMsg(msg.clone())])
            .await;
        self.services
            .rollout_thread_trace
            .record_protocol_event(&msg);
        self.maybe_mirror_event_text_to_realtime(&msg).await;
        self.maybe_clear_realtime_handoff_for_event(&msg).await;

        // Resolve the old turn's status before opening admission. Parent
        // notification must never overwrite a subsequently started turn.
        let status = if turn_context.multi_agent_version == MultiAgentVersion::V2
            && matches!(
                &turn_context.session_source,
                SessionSource::SubAgent(SubAgentSource::ThreadSpawn {
                    agent_path: Some(_),
                    ..
                })
            ) {
            turn_context
                .terminal_error
                .lock()
                .await
                .take()
                .map(|error| AgentStatus::Errored(error.message))
                .or_else(|| agent_status_from_event(&msg))
        } else {
            agent_status_from_event(&msg)
        };
        PreparedTerminalEvent {
            event: Event {
                id: turn_context.sub_id.clone(),
                msg,
            },
            status,
        }
    }

    /// Called while the exact owner's admission registry is locked. A client
    /// receiving this event cannot inspect admission until that same critical
    /// section has opened it. The production event channel is unbounded.
    pub(crate) fn deliver_prepared_terminal_event(&self, terminal: &PreparedTerminalEvent) -> bool {
        match self.tx_event.try_send(terminal.event.clone()) {
            Ok(()) => {}
            Err(async_channel::TrySendError::Closed(_)) => {
                debug!("dropping terminal event because channel is closed");
            }
            Err(async_channel::TrySendError::Full(_)) => {
                // A future bounded-channel configuration must not silently
                // drop completion or open admission before delivery.
                return false;
            }
        }
        if let Some(status) = &terminal.status {
            self.agent_status.send_replace(status.clone());
        }
        true
    }

    pub(crate) async fn notify_parent_of_prepared_terminal_event(
        &self,
        turn_context: &TurnContext,
        terminal: &PreparedTerminalEvent,
    ) {
        if turn_context.multi_agent_version != MultiAgentVersion::V2 {
            return;
        }
        let SessionSource::SubAgent(SubAgentSource::ThreadSpawn {
            parent_thread_id,
            agent_path: Some(child_agent_path),
            ..
        }) = &turn_context.session_source
        else {
            return;
        };
        let Some(status) = terminal.status.as_ref().filter(|status| is_final(status)) else {
            return;
        };
        self.forward_child_completion_to_parent(
            turn_context,
            *parent_thread_id,
            child_agent_path,
            status.clone(),
        )
        .await;
    }
}
