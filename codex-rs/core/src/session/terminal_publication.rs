use super::Session;
use super::turn_context::TurnContext;
use codex_history::RolloutItem;
use codex_protocol::protocol::Event;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::HasLegacyEvent;

/// One original terminal event, already appended but not yet published.
/// Only the original task/start owner may consume it after retiring admission.
pub(crate) struct TerminalEventPublication {
    event: Event,
}

impl Session {
    pub(super) fn record_turn_event(&self, turn_context: &TurnContext, msg: &EventMsg) {
        self.services
            .rollout_thread_trace
            .record_codex_turn_event(&turn_context.sub_id, msg);
        self.services
            .rollout_thread_trace
            .record_tool_call_event(turn_context.sub_id.clone(), msg);
    }

    pub(crate) async fn persist_terminal_event(
        &self,
        turn_context: &TurnContext,
        msg: EventMsg,
    ) -> TerminalEventPublication {
        assert!(matches!(
            msg,
            EventMsg::TurnComplete(_) | EventMsg::TurnAborted(_)
        ));
        self.record_turn_event(turn_context, &msg);
        self.persist_rollout_items(&[RolloutItem::EventMsg(msg.clone())])
            .await;
        self.services
            .rollout_thread_trace
            .record_protocol_event(&msg);
        TerminalEventPublication {
            event: Event {
                id: turn_context.sub_id.clone(),
                msg,
            },
        }
    }

    pub(crate) async fn deliver_terminal_event(
        &self,
        turn_context: &TurnContext,
        publication: TerminalEventPublication,
    ) {
        let msg = publication.event.msg.clone();
        self.services.mcp_runtime.observe_event(&msg);
        self.deliver_event_raw(publication.event).await;
        self.finish_event_delivery(turn_context, &msg).await;
    }

    pub(super) async fn finish_event_delivery(
        &self,
        turn_context: &TurnContext,
        legacy_source: &EventMsg,
    ) {
        self.maybe_notify_parent_of_terminal_turn(turn_context, legacy_source)
            .await;
        self.maybe_mirror_event_text_to_realtime(legacy_source)
            .await;
        self.maybe_clear_realtime_handoff_for_event(legacy_source)
            .await;

        let show_raw_agent_reasoning = self.show_raw_agent_reasoning();
        for legacy in legacy_source.as_legacy_events(show_raw_agent_reasoning) {
            self.services
                .rollout_thread_trace
                .record_tool_call_event(turn_context.sub_id.clone(), &legacy);
            let legacy_event = Event {
                id: turn_context.sub_id.clone(),
                msg: legacy,
            };
            self.send_event_raw(legacy_event).await;
        }
    }
}
