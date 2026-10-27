//! Bounded assembly of streamed and completed agent messages. A completion is
//! authoritative for its item; receiving it without deltas is a valid stream.

use codex_app_server_protocol::ServerNotification;
use codex_app_server_protocol::ThreadItem;

use super::MAX_OUTPUT_BYTES;
use super::NativeRunOutput;

const MAX_OUTPUT_ITEMS: usize = 1024;
const MAX_OUTPUT_ID_BYTES: usize = 64 * 1024;

#[derive(Default)]
pub(super) struct AgentOutput {
    items: Vec<OutputItem>,
    id_bytes: usize,
}

struct OutputItem {
    id: String,
    bytes: usize,
    completed: bool,
}

enum Update {
    Delta,
    Completed,
}

impl AgentOutput {
    pub(super) fn observe(
        &mut self,
        output: &mut NativeRunOutput,
        notification: &ServerNotification,
    ) -> Result<(), String> {
        let (id, text, update) = match notification {
            ServerNotification::AgentMessageDelta(delta)
                if delta.thread_id == output.thread_id && delta.turn_id == output.turn_id =>
            {
                (&delta.item_id, &delta.delta, Update::Delta)
            }
            ServerNotification::ItemCompleted(completed)
                if completed.thread_id == output.thread_id
                    && completed.turn_id == output.turn_id =>
            {
                let ThreadItem::AgentMessage { id, text, .. } = &completed.item else {
                    return Ok(());
                };
                (id, text, Update::Completed)
            }
            _ => return Ok(()),
        };
        let index = self.items.iter().position(|item| item.id == *id);
        let start: usize = self.items[..index.unwrap_or(self.items.len())]
            .iter()
            .map(|item| item.bytes)
            .sum();
        let previous = index.map(|index| &self.items[index]);
        let old_bytes = previous.map_or(0, |item| item.bytes);
        let end = start + old_bytes;
        if previous.is_some_and(|item| item.completed) {
            return match update {
                Update::Completed if output.output.get(start..end) == Some(text.as_str()) => Ok(()),
                Update::Completed => Err("completed agent message changed".to_string()),
                Update::Delta => Err("agent message delta followed completion".to_string()),
            };
        }
        let new_bytes = match update {
            Update::Delta => old_bytes.checked_add(text.len()),
            Update::Completed => Some(text.len()),
        }
        .ok_or_else(|| "output byte limit exceeded".to_string())?;
        if new_bytes > MAX_OUTPUT_BYTES.saturating_sub(output.output.len() - old_bytes) {
            return Err("output byte limit exceeded".to_string());
        }
        if index.is_none()
            && (self.items.len() >= MAX_OUTPUT_ITEMS
                || id.len() > MAX_OUTPUT_ID_BYTES.saturating_sub(self.id_bytes))
        {
            return Err("output item metadata limit exceeded".to_string());
        }
        match update {
            Update::Delta => output.output.insert_str(end, text),
            Update::Completed => output.output.replace_range(start..end, text),
        }
        let completed = matches!(update, Update::Completed);
        if let Some(index) = index {
            self.items[index].bytes = new_bytes;
            self.items[index].completed = completed;
        } else {
            self.items.push(OutputItem { id: id.clone(), bytes: new_bytes, completed });
            self.id_bytes += id.len();
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "native_agent_output_tests.rs"]
mod tests;
