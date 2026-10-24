//! App Server observations projected into the existing Timeline. This module
//! owns no conversation, transport, grant, signing key, or durable state.

use super::*;
use crate::chat_owner::ChatCapability;
use crate::chat_timeline::{History, Message, MessagePhase, ProjectionError as E, Role, ViewFence};
use serde_json::Value;

/// Fences one original owner/room and one physical App Server subscription.
pub struct StreamBinding {
    ticket: HistoryTicket,
    connection_id: u64,
}

impl ChatWorkspace {
    /// Requires the already-authenticated original owner. Socket connectivity
    /// alone must never install an OwnerSession or grant these capabilities.
    pub fn begin_stream(&mut self, room: u64, connection_id: u64, now_ms: u64) -> Result<StreamBinding, E> {
        if connection_id == 0 { return Err(E::Invalid); }
        let scope = self.owner.require_capability(ChatCapability::Subscribe, now_ms).map_err(|_| E::WrongOwner)?.clone();
        self.owner.require_capability(ChatCapability::ReadHistory, now_ms).map_err(|_| E::WrongOwner)?;
        let ticket = self.begin_history(room, &scope.thread_id, ViewFence {
            owner_session: scope.session_id, generation: scope.connection_generation,
        })?;
        if self.timelines.get(&room).and_then(|timeline| timeline.history()).is_none() {
            self.receive_history(&ticket, History {
                thread_id: scope.thread_id, title: self.drafts[&room].title.clone(),
                revision: 1, event_sequence: 0, messages: Vec::new(),
            })?;
        }
        Ok(StreamBinding { ticket, connection_id })
    }

    /// The host supplies the serialization of an actual original notification.
    /// This parser cannot turn a DTO into authenticated runtime/effect evidence.
    /// Local revision/sequence fields fence presentation updates only.
    pub fn receive_app_server_notification(&mut self, binding: &StreamBinding, connection_id: u64, notification: &Value, now_ms: u64) -> Result<(), E> {
        self.validate_stream(binding, connection_id, now_ms)?;
        if serde_json::to_vec(notification).map_err(|_| E::Invalid)?.len() > 256 * 1024 { return Err(E::Limit); }
        let method = string(notification, "method")?;
        let params = notification.get("params").ok_or(E::Invalid)?;
        if string(params, "threadId")? != binding.ticket.thread { return Err(E::WrongThread); }
        let mut history = self.stream_history(binding)?;
        match method {
            "item/started" | "item/completed" => {
                let turn_id = string(params, "turnId")?;
                let item = item_message(params.get("item").ok_or(E::Invalid)?, turn_id,
                    if method == "item/completed" { MessagePhase::Observed } else { MessagePhase::Streaming })?;
                if let Some(old) = history.messages.iter_mut().find(|old| old.id == item.id) {
                    if old.turn_id != item.turn_id { return Err(E::Conflict); }
                    if method == "item/started" && old != &item { return Err(E::Stale); }
                    *old = item;
                } else { history.messages.push(item); }
            }
            "item/agentMessage/delta" | "item/commandExecution/outputDelta" | "item/plan/delta" => {
                let turn_id = string(params, "turnId")?;
                let item_id = string(params, "itemId")?;
                let item = history.messages.iter().find(|item| item.id == item_id).ok_or(E::UnknownItem)?;
                if item.turn_id != turn_id { return Err(E::Conflict); }
                let sequence = history.event_sequence.checked_add(1).ok_or(E::Limit)?;
                return self.receive_delta(&binding.ticket, item_id, sequence, string(params, "delta")?).map(|_| ());
            }
            "turn/completed" => {
                let turn = params.get("turn").ok_or(E::Invalid)?;
                return self.receive_app_server_turn(binding, connection_id, turn, now_ms);
            }
            // Structured plan/diff progress remains in the original item stream.
            // Unsupported notifications do not manufacture a chat message.
            _ => return Ok(()),
        }
        history.revision = history.revision.checked_add(1).ok_or(E::Limit)?;
        history.event_sequence = history.event_sequence.checked_add(1).ok_or(E::Limit)?;
        self.receive_history(&binding.ticket, history)
    }

    /// Replaces the specified original turn after ReconcileOnly lookup. It does
    /// not append a second copy of user, tool, artifact, or assistant items.
    pub fn receive_app_server_turn(&mut self, binding: &StreamBinding, connection_id: u64, turn: &Value, now_ms: u64) -> Result<(), E> {
        self.validate_stream(binding, connection_id, now_ms)?;
        if serde_json::to_vec(turn).map_err(|_| E::Invalid)?.len() > 256 * 1024 { return Err(E::Limit); }
        let turn_id = string(turn, "id")?;
        let phase = match string(turn, "status")? {
            "inProgress" => MessagePhase::Streaming,
            "completed" => MessagePhase::Completed,
            "failed" => MessagePhase::Failed,
            "interrupted" => MessagePhase::Interrupted,
            _ => return Err(E::Invalid),
        };
        let items = turn.get("items").and_then(Value::as_array).ok_or(E::Invalid)?;
        let mut history = self.stream_history(binding)?;
        if !items.is_empty() {
            let messages = items.iter().map(|item| item_message(item, turn_id, phase)).collect::<Result<Vec<_>, E>>()?;
            let index = history.messages.iter().position(|item| item.turn_id == turn_id).unwrap_or(history.messages.len());
            history.messages.retain(|item| item.turn_id != turn_id);
            history.messages.splice(index..index, messages);
        } else {
            // Live turn/completed can omit persisted items; retain exact items
            // already observed on this subscription and update only their phase.
            for message in &mut history.messages {
                if message.turn_id == turn_id && message.role != Role::User { message.phase = phase; }
            }
        }
        history.revision = history.revision.checked_add(1).ok_or(E::Limit)?;
        history.event_sequence = history.event_sequence.checked_add(1).ok_or(E::Limit)?;
        self.receive_history(&binding.ticket, history)
    }

    fn validate_stream(&self, binding: &StreamBinding, connection_id: u64, now_ms: u64) -> Result<(), E> {
        if connection_id != binding.connection_id || self.bindings.get(&binding.ticket.room) != Some(&binding.ticket) { return Err(E::Stale); }
        let scope = self.owner.require_capability(ChatCapability::Subscribe, now_ms).map_err(|_| E::WrongOwner)?;
        if scope.thread_id != binding.ticket.thread || scope.session_id != binding.ticket.fence.owner_session
            || scope.connection_generation != binding.ticket.fence.generation { return Err(E::WrongOwner); }
        Ok(())
    }

    fn stream_history(&self, binding: &StreamBinding) -> Result<History, E> {
        self.timelines.get(&binding.ticket.room).and_then(|timeline| timeline.history()).cloned().ok_or(E::UnknownItem)
    }
}

fn string<'a>(value: &'a Value, key: &str) -> Result<&'a str, E> {
    value.get(key).and_then(Value::as_str).ok_or(E::Invalid)
}

fn item_message(item: &Value, turn_id: &str, phase: MessagePhase) -> Result<Message, E> {
    let id = string(item, "id")?.to_owned();
    let kind = string(item, "type")?;
    let (role, text, phase) = match kind {
        "userMessage" => {
            let content = item.get("content").and_then(Value::as_array).ok_or(E::Invalid)?;
            let text = content.iter().map(|part| {
                if string(part, "type")? != "text" { return Err(E::Invalid); }
                string(part, "text").map(str::to_owned)
            }).collect::<Result<Vec<_>, E>>()?.join("\n");
            (Role::User, text, MessagePhase::Observed)
        }
        "agentMessage" | "plan" => (Role::Assistant, string(item, "text")?.to_owned(), phase),
        // Tool/artifact data is displayed as inert observed content. No string
        // here becomes a command, local file open, external fetch, or grant.
        _ => (Role::System, serde_json::to_string_pretty(item).map_err(|_| E::Invalid)?, phase),
    };
    Ok(Message { id, turn_id: turn_id.to_owned(), role, text, phase })
}

#[cfg(test)]
#[path = "chat_stream_tests.rs"]
mod tests;
