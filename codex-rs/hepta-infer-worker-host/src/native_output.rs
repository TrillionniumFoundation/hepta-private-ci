//! Bounded assistant text for one observed App Server turn.
//!
//! Deltas are provisional per-item text. A completed assistant item replaces
//! that item's text without changing the order in which items were started (or
//! first observed when the stream has no item/started notification).

use std::collections::HashMap;

use codex_app_server_protocol::ServerNotification;
use codex_app_server_protocol::ThreadItem;

use super::NativeRunOutput;

pub(super) const MAX_OUTPUT_BYTES: usize = 1024 * 1024;

#[derive(Default)]
pub(super) struct ObservedMessages {
    by_id: HashMap<String, usize>,
    items: Vec<MessageSlot>,
    metadata_bytes: usize,
}

#[derive(Default)]
struct MessageSlot {
    len: usize,
    completed: bool,
}

enum MessageUpdate<'a> {
    Started,
    Delta(&'a str),
    Completed(&'a str),
}

impl ObservedMessages {
    pub(super) fn observe(
        &mut self,
        output: &mut NativeRunOutput,
        notification: &ServerNotification,
    ) -> Result<(), String> {
        let (item_id, update) = match notification {
            ServerNotification::ItemStarted(started)
                if started.thread_id == output.thread_id && started.turn_id == output.turn_id =>
            {
                let ThreadItem::AgentMessage { id, .. } = &started.item else {
                    return Ok(());
                };
                (id.as_str(), MessageUpdate::Started)
            }
            ServerNotification::AgentMessageDelta(delta)
                if delta.thread_id == output.thread_id && delta.turn_id == output.turn_id =>
            {
                (delta.item_id.as_str(), MessageUpdate::Delta(&delta.delta))
            }
            ServerNotification::ItemCompleted(completed)
                if completed.thread_id == output.thread_id
                    && completed.turn_id == output.turn_id =>
            {
                let ThreadItem::AgentMessage { id, text, .. } = &completed.item else {
                    return Ok(());
                };
                (id.as_str(), MessageUpdate::Completed(text))
            }
            _ => return Ok(()),
        };
        self.update(&mut output.output, item_id, update)
    }

    fn update(
        &mut self,
        output: &mut String,
        item_id: &str,
        update: MessageUpdate<'_>,
    ) -> Result<(), String> {
        let existing = self.by_id.get(item_id).copied();
        let previous_len = existing.map_or(0, |index| self.items[index].len);
        let new_len = match update {
            MessageUpdate::Started => previous_len,
            MessageUpdate::Delta(text) => {
                if existing.is_some_and(|index| self.items[index].completed) {
                    return Err("agent message delta followed completed item".to_string());
                }
                previous_len.saturating_add(text.len())
            }
            MessageUpdate::Completed(text) => text.len(),
        };
        if new_len > MAX_OUTPUT_BYTES.saturating_sub(output.len() - previous_len) {
            return Err("output byte limit exceeded".to_string());
        }

        let index = match existing {
            Some(index) => index,
            None => {
                // Bound retained IDs and empty-item traffic independently of
                // text. Hash table capacity is also bounded by this item count.
                let metadata = item_id
                    .len()
                    .saturating_add(size_of::<(String, usize, MessageSlot)>());
                if metadata > MAX_OUTPUT_BYTES.saturating_sub(self.metadata_bytes) {
                    return Err("output byte limit exceeded".to_string());
                }
                let index = self.items.len();
                self.by_id.insert(item_id.to_string(), index);
                self.items.push(MessageSlot::default());
                self.metadata_bytes += metadata;
                index
            }
        };

        // The usual streaming case appends to the last item. Interleaved item
        // updates replace only their own UTF-8 range in the ordered output.
        let start = if index + 1 == self.items.len() {
            output.len() - previous_len
        } else {
            self.items[..index].iter().map(|item| item.len).sum()
        };
        match update {
            MessageUpdate::Started => {}
            MessageUpdate::Delta(text) => output.insert_str(start + previous_len, text),
            MessageUpdate::Completed(text) => {
                output.replace_range(start..start + previous_len, text);
                self.items[index].completed = true;
            }
        }
        self.items[index].len = new_len;
        Ok(())
    }
}

#[cfg(test)]
#[path = "native_output_tests.rs"]
mod tests;
