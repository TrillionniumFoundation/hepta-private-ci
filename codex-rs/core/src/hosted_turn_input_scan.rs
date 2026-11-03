//! Bounded, read-only classification of an original hosted user input.
//! Current rollout policy persists ResponseItem plus ItemCompleted for
//! paginated history; ItemStarted is transient and is never required here.

use codex_history::{RolloutItem, TurnRecoveryRequestBinding};
use codex_protocol::ThreadId;
use codex_protocol::error::Result as CodexResult;
use codex_protocol::items::{TurnItem, UserMessageItem};
use codex_protocol::models::ResponseItem;
use codex_protocol::protocol::{EventMsg, ItemCompletedEvent, ThreadHistoryMode};
use codex_protocol::protocol::HasLegacyEvent;
use codex_protocol::user_input::{UserInput, user_input_payload_sha256};
use serde_json::Value;

use crate::hosted_turn::{HostedQueueBinding, invalid};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum OriginalInputState { Absent, Complete }

pub(super) struct InputHistoryScan<'a> {
    thread_id: ThreadId,
    original: &'a TurnRecoveryRequestBinding,
    queue: &'a HostedQueueBinding,
    mode: ThreadHistoryMode,
    expected_response: Value,
    expected_legacy: Value,
    current_turn: Option<String>,
    original_seen: bool,
    response_seen: bool,
    started_id: Option<String>,
    completed_id: Option<String>,
    legacy_seen: bool,
}

impl<'a> InputHistoryScan<'a> {
    pub(super) fn new(thread_id: ThreadId, original: &'a TurnRecoveryRequestBinding,
        queue: &'a HostedQueueBinding, input: &[UserInput], response: &ResponseItem,
        mode: ThreadHistoryMode) -> CodexResult<Self> {
        if user_input_payload_sha256(input).map_err(|error| invalid(&error.to_string()))? != queue.payload_sha256 {
            return Err(invalid("original input scan payload differs from the Queue binding"));
        }
        let mut item = UserMessageItem::new(input);
        item.client_id = Some(queue.client_id.clone());
        let expected_event = EventMsg::ItemCompleted(ItemCompletedEvent {
            thread_id, turn_id: original.turn_id.clone(), item: TurnItem::UserMessage(item),
            started_at_ms: None, completed_at_ms: 0,
        });
        let legacy = expected_event.as_legacy_events(/*show_raw_agent_reasoning*/ false)
            .into_iter().find_map(|event| match event { EventMsg::UserMessage(value) => Some(value), _ => None })
            .ok_or_else(|| invalid("original Core user input has no legacy projection"))?;
        Ok(Self { thread_id, original, queue, mode,
            expected_response: response_projection(response)?,
            expected_legacy: serde_json::to_value(legacy).map_err(|error| invalid(&error.to_string()))?,
            current_turn: None, original_seen: false, response_seen: false,
            started_id: None, completed_id: None, legacy_seen: false })
    }

    pub(super) fn observe(&mut self, item: &RolloutItem) -> CodexResult<()> {
        match item {
            RolloutItem::EventMsg(EventMsg::TurnStarted(event)) => {
                self.current_turn = Some(event.turn_id.clone());
            }
            RolloutItem::TurnRecoveryRequestBinding(binding)
                if binding.turn_id == self.original.turn_id && binding.generation == self.original.generation => {
                    if self.original_seen || binding != self.original {
                        return Err(invalid("original hosted input provenance is duplicated or changed"));
                    }
                    self.original_seen = true;
                }
            RolloutItem::ResponseItem(envelope)
                if matches!(&envelope.item, ResponseItem::Message { role, .. } if role == "user")
                    && (envelope.item.turn_id() == Some(self.original.turn_id.as_str())
                        || self.current_turn.as_deref() == Some(self.original.turn_id.as_str())) => {
                    if !self.original_seen || self.response_seen
                        || envelope.item.turn_id() != Some(self.original.turn_id.as_str())
                        || self.current_turn.as_deref() != Some(self.original.turn_id.as_str())
                        || envelope.item.id().is_none_or(|id| id.is_empty())
                        || response_projection(&envelope.item)? != self.expected_response
                    {
                        return Err(invalid("original hosted user response is duplicated, reordered or changed"));
                    }
                    self.response_seen = true;
                }
            RolloutItem::EventMsg(EventMsg::ItemStarted(event)) => {
                if let TurnItem::UserMessage(input) = &event.item
                    && (input.client_id.as_deref() == Some(self.queue.client_id.as_str())
                        || event.turn_id == self.original.turn_id)
                {
                    self.verify_typed(event.thread_id, &event.turn_id, input)?;
                    if self.started_id.is_some() || self.completed_id.is_some() {
                        return Err(invalid("original hosted input start is duplicated or reordered"));
                    }
                    self.started_id = Some(input.id.clone());
                }
            }
            RolloutItem::EventMsg(EventMsg::ItemCompleted(event)) => {
                if let TurnItem::UserMessage(input) = &event.item
                    && (input.client_id.as_deref() == Some(self.queue.client_id.as_str())
                        || event.turn_id == self.original.turn_id)
                {
                    self.verify_typed(event.thread_id, &event.turn_id, input)?;
                    if self.mode != ThreadHistoryMode::Paginated || self.completed_id.is_some()
                        || self.started_id.as_ref().is_some_and(|id| id != &input.id)
                    {
                        return Err(invalid("original hosted input completion is duplicated or changed"));
                    }
                    self.completed_id = Some(input.id.clone());
                }
            }
            RolloutItem::EventMsg(EventMsg::UserMessage(event))
                if event.client_id.as_deref() == Some(self.queue.client_id.as_str())
                    || self.current_turn.as_deref() == Some(self.original.turn_id.as_str()) => {
                    if self.mode != ThreadHistoryMode::Legacy || !self.original_seen || !self.response_seen
                        || self.legacy_seen || self.current_turn.as_deref() != Some(self.original.turn_id.as_str())
                        || serde_json::to_value(event).map_err(|error| invalid(&error.to_string()))? != self.expected_legacy
                    {
                        return Err(invalid("original hosted legacy input is duplicated, incomplete or changed"));
                    }
                    self.legacy_seen = true;
                }
            _ => {}
        }
        Ok(())
    }

    fn verify_typed(&self, thread_id: ThreadId, turn_id: &str, input: &UserMessageItem) -> CodexResult<()> {
        if !self.original_seen || !self.response_seen || thread_id != self.thread_id
            || turn_id != self.original.turn_id || input.id.is_empty()
            || input.client_id.as_deref() != Some(self.queue.client_id.as_str())
            || user_input_payload_sha256(&input.content).map_err(|error| invalid(&error.to_string()))? != self.queue.payload_sha256
        {
            return Err(invalid("original hosted typed input has a partial or conflicting client/payload/turn binding"));
        }
        Ok(())
    }

    pub(super) fn finish(self) -> CodexResult<OriginalInputState> {
        if !self.original_seen { return Err(invalid("original hosted input provenance is missing")); }
        let complete = self.response_seen && match self.mode {
            ThreadHistoryMode::Paginated => self.completed_id.is_some(),
            ThreadHistoryMode::Legacy => self.legacy_seen,
        };
        if complete { return Ok(OriginalInputState::Complete); }
        if !self.response_seen && self.started_id.is_none() && self.completed_id.is_none() && !self.legacy_seen {
            return Ok(OriginalInputState::Absent);
        }
        Err(invalid("original hosted user input is only partially persisted; it cannot be appended again"))
    }
}

fn response_projection(item: &ResponseItem) -> CodexResult<Value> {
    let ResponseItem::Message { role, content, phase, .. } = item else {
        return Err(invalid("original hosted input response is not a user message"));
    };
    if role != "user" { return Err(invalid("original hosted input response changed its role")); }
    // Core owns the generated response ID, turn stamp and creation timestamp.
    // The exact model-visible role/content/phase must still match its input.
    serde_json::to_value((role, content, phase)).map_err(|error| invalid(&error.to_string()))
}

#[cfg(test)]
#[path = "hosted_turn_input_tests.rs"]
mod tests;
