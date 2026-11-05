//! Bounded message text from the exact live App Server turn. Completed items
//! replace their streamed fragments; text never establishes terminal or usage.

use codex_app_server_protocol::ServerNotification;
use codex_app_server_protocol::ThreadItem;

use super::MAX_OUTPUT_BYTES;
use super::NativeRunOutput;

const MAX_MESSAGE_ITEMS: usize = 1024;

struct AgentMessage {
    id: String,
    text: String,
    completed: bool,
}

enum Update<'a> {
    Started(&'a str),
    Delta(&'a str),
    Completed(&'a str),
}

#[derive(Default)]
pub(super) struct AgentMessageOutput {
    items: Vec<AgentMessage>,
    id_bytes: usize,
    text_bytes: usize,
}

impl AgentMessageOutput {
    pub(super) fn observe(
        &mut self,
        notification: &ServerNotification,
        output: &mut NativeRunOutput,
    ) -> Result<(), String> {
        let (thread_id, turn_id, item_id, update) = match notification {
            ServerNotification::ItemStarted(started) => {
                let ThreadItem::AgentMessage { id, text, .. } = &started.item else {
                    return Ok(());
                };
                (
                    &started.thread_id,
                    &started.turn_id,
                    id,
                    Update::Started(text),
                )
            }
            ServerNotification::AgentMessageDelta(delta) => (
                &delta.thread_id,
                &delta.turn_id,
                &delta.item_id,
                Update::Delta(&delta.delta),
            ),
            ServerNotification::ItemCompleted(completed) => {
                let ThreadItem::AgentMessage { id, text, .. } = &completed.item else {
                    return Ok(());
                };
                (
                    &completed.thread_id,
                    &completed.turn_id,
                    id,
                    Update::Completed(text),
                )
            }
            _ => return Ok(()),
        };
        if thread_id != &output.thread_id || turn_id != &output.turn_id {
            return Ok(());
        }
        let index = self.items.iter().position(|item| &item.id == item_id);
        let previous = index.map(|index| &self.items[index]);
        if matches!(update, Update::Started(_)) && previous.is_some() {
            return Ok(());
        }
        let previous_len = previous.map_or(0, |item| item.text.len());
        let (text, replacement_len, completed) = match update {
            Update::Started(text) => (text, text.len(), false),
            Update::Delta(text) => {
                if previous.is_some_and(|item| item.completed) {
                    return Err("agent message delta followed its completed item".to_string());
                }
                let length = previous_len
                    .checked_add(text.len())
                    .ok_or_else(|| "output byte limit exceeded".to_string())?;
                (text, length, false)
            }
            Update::Completed(text) => {
                if previous.is_some_and(|item| item.completed && item.text != text) {
                    return Err("completed agent message changed its text".to_string());
                }
                (text, text.len(), true)
            }
        };
        let retained_bytes = self.text_bytes - previous_len;
        if replacement_len > MAX_OUTPUT_BYTES.saturating_sub(retained_bytes) {
            return Err("output byte limit exceeded".to_string());
        }
        if index.is_none()
            && (self.items.len() >= MAX_MESSAGE_ITEMS
                || item_id.len() > MAX_OUTPUT_BYTES.saturating_sub(self.id_bytes))
        {
            return Err("output message metadata limit exceeded".to_string());
        }
        let index = match index {
            Some(index) => index,
            None => {
                self.id_bytes += item_id.len();
                self.items.push(AgentMessage {
                    id: item_id.clone(),
                    text: String::new(),
                    completed: false,
                });
                self.items.len() - 1
            }
        };
        let item = &mut self.items[index];
        if completed || previous_len == 0 {
            item.text = text.to_string();
        } else {
            item.text.push_str(text);
        }
        item.completed = completed;
        self.text_bytes = retained_bytes + replacement_len;
        output.output.clear();
        for item in &self.items {
            output.output.push_str(&item.text);
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "native_output_tests.rs"]
mod tests;
