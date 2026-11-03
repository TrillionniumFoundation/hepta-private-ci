//! Terminal persistence is distinct from advertising that a turn has finished.
//! The task owner keeps its exact admission fence through all old-turn cleanup.

use super::*;

struct ParentTerminalNotification {
    parent_thread_id: ThreadId,
    child_agent_path: codex_protocol::AgentPath,
    status: AgentStatus,
}

/// Prepared once while the original terminalizer owns admission. None of the
/// status watch, protocol channel, MCP observer, or parent receives completion
/// until the owner commits this value together with retiring its exact fence.
pub(crate) struct PreparedTerminalEvent {
    events: Vec<Event>,
    status: Option<AgentStatus>,
    parent: Option<ParentTerminalNotification>,
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
        // Core creates this channel with async_channel::unbounded. Publication
        // must be synchronous once admission is released; reject a different
        // internal channel contract before persisting or publishing anything.
        assert!(self.tx_event.capacity().is_none());

        self.services
            .rollout_thread_trace
            .record_codex_turn_event(&turn_context.sub_id, &msg);
        self.services
            .rollout_thread_trace
            .record_tool_call_event(turn_context.sub_id.clone(), &msg);
        self.persist_rollout_items(&[RolloutItem::EventMsg(msg.clone())])
            .await;
        self.services
            .rollout_thread_trace
            .record_protocol_event(&msg);

        let mut status = agent_status_from_event(&msg);
        // Capture the same V2 parent envelope as send_event, but neither send
        // it nor update the child's status while admission remains fenced.
        let parent = if turn_context.multi_agent_version == MultiAgentVersion::V2 {
            if let SessionSource::SubAgent(SubAgentSource::ThreadSpawn {
                parent_thread_id,
                agent_path: Some(child_agent_path),
                ..
            }) = &turn_context.session_source
            {
                if let Some(error) = turn_context.terminal_error.lock().await.take() {
                    status = Some(AgentStatus::Errored(error.message));
                }
                status
                    .as_ref()
                    .filter(|status| is_final(status))
                    .map(|status| ParentTerminalNotification {
                        parent_thread_id: *parent_thread_id,
                        child_agent_path: child_agent_path.clone(),
                        status: status.clone(),
                    })
            } else {
                None
            }
        } else {
            None
        };

        // These touch session-wide realtime handoff state and must finish
        // before a later turn can attach. They are never repeated on recovery.
        self.maybe_mirror_event_text_to_realtime(&msg).await;
        self.maybe_clear_realtime_handoff_for_event(&msg).await;

        let mut events = vec![Event {
            id: turn_context.sub_id.clone(),
            msg: msg.clone(),
        }];
        for legacy in msg.as_legacy_events(self.show_raw_agent_reasoning()) {
            self.services
                .rollout_thread_trace
                .record_tool_call_event(turn_context.sub_id.clone(), &legacy);
            self.persist_rollout_items(&[RolloutItem::EventMsg(legacy.clone())])
                .await;
            self.services
                .rollout_thread_trace
                .record_protocol_event(&legacy);
            if let Some(legacy_status) = agent_status_from_event(&legacy) {
                status = Some(legacy_status);
            }
            events.push(Event {
                id: turn_context.sub_id.clone(),
                msg: legacy,
            });
        }
        PreparedTerminalEvent {
            events,
            status,
            parent,
        }
    }

    /// Called only in the task owner's active-slot/registry commit section.
    /// No await or persistence occurs here, and consuming the fields prevents
    /// a duplicate live event or a later stale status write.
    pub(crate) fn publish_prepared_terminal_event(&self, prepared: &mut PreparedTerminalEvent) {
        if let Some(status) = prepared.status.take() {
            self.agent_status.send_replace(status);
        }
        for event in prepared.events.drain(..) {
            self.services.mcp_runtime.observe_event(&event.msg);
            if let Err(error) = self.tx_event.try_send(event) {
                match error {
                    async_channel::TrySendError::Closed(_) => {
                        debug!("dropping terminal event because the channel is closed");
                    }
                    async_channel::TrySendError::Full(_) => {
                        unreachable!("Core terminal event channel is unbounded");
                    }
                }
            }
        }
    }

    /// Best-effort parent delivery after the live completion commit. This
    /// deliberately cannot update the child's status or realtime handoff:
    /// another turn may already be running while parent delivery awaits.
    pub(crate) async fn notify_prepared_terminal_parent(
        &self,
        turn_context: &TurnContext,
        prepared: &mut PreparedTerminalEvent,
    ) {
        if let Some(parent) = prepared.parent.take() {
            self.forward_child_completion_to_parent(
                turn_context,
                parent.parent_thread_id,
                &parent.child_agent_path,
                parent.status,
            )
            .await;
        }
    }
}
