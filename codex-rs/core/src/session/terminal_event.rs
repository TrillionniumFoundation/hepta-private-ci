//! Terminal records are prepared under the old task's ownership fence and
//! published only after that exact owner has finished its cleanup.

use codex_history::RolloutItem;
use codex_protocol::AgentPath;
use codex_protocol::ThreadId;
use codex_protocol::protocol::Event;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::MultiAgentVersion;
use codex_protocol::protocol::SessionSource;
use codex_protocol::protocol::SubAgentSource;
use tracing::debug;

use crate::agent::AgentStatus;
use crate::agent::agent_status_from_event;
use crate::agent::status::is_final;
use crate::session::session::Session;
use crate::session::turn_context::TurnContext;

pub(crate) struct PreparedTerminalEvent {
    event: Event,
    status: Option<AgentStatus>,
    parent: Option<(ThreadId, AgentPath, AgentStatus)>,
}

impl Session {
    /// Append exactly once, without announcing an idle agent or a finished
    /// turn. The terminalizer still owns the subsequent flush and cleanup.
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
        // This mutates session-scoped realtime state, so it must finish before
        // a client can admit another turn in response to the terminal event.
        self.maybe_clear_realtime_handoff_for_event(&msg).await;

        let mut status = agent_status_from_event(&msg);
        let mut parent = None;
        if turn_context.multi_agent_version == MultiAgentVersion::V2
            && let SessionSource::SubAgent(SubAgentSource::ThreadSpawn {
                parent_thread_id,
                agent_path: Some(child_agent_path),
                ..
            }) = &turn_context.session_source
        {
            if let Some(error) = turn_context.terminal_error.lock().await.take() {
                status = Some(AgentStatus::Errored(error.message));
            }
            if let Some(status) = status.as_ref().filter(|status| is_final(status)) {
                parent = Some((*parent_thread_id, child_agent_path.clone(), status.clone()));
            }
        }
        PreparedTerminalEvent {
            event: Event {
                id: turn_context.sub_id.clone(),
                msg,
            },
            status,
            parent,
        }
    }

    /// The caller holds active_turn across exact fence retirement and this
    /// synchronous enqueue. No subsequent TurnStarted can overtake it.
    pub(crate) fn publish_prepared_terminal_event(&self, prepared: &PreparedTerminalEvent) {
        if let Some(status) = prepared.status.as_ref() {
            self.agent_status.send_replace(status.clone());
        }
        match self.tx_event.try_send(prepared.event.clone()) {
            Ok(()) => {}
            Err(async_channel::TrySendError::Closed(_)) => {
                debug!("dropping terminal event because channel is closed");
            }
            Err(async_channel::TrySendError::Full(_)) => {
                unreachable!("the session event channel is unbounded");
            }
        }
    }

    /// Finish parent delivery while the old ownership fence still makes
    /// shutdown wait. Publication must follow this await, so no old callback
    /// can overwrite a newly admitted turn's agent status.
    pub(crate) async fn notify_parent_of_prepared_terminal(
        &self,
        turn_context: &TurnContext,
        prepared: &PreparedTerminalEvent,
    ) {
        if let Some((parent_thread_id, child_agent_path, status)) = prepared.parent.as_ref() {
            self.forward_child_completion_to_parent(
                turn_context,
                *parent_thread_id,
                child_agent_path,
                status.clone(),
            )
            .await;
        }
    }
}
