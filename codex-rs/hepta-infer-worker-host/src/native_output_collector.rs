//! Bounded, per-item output projection for streamed and completed messages.
//!
//! The caller must first bind every event to the exact thread and turn. Item
//! completion replaces that item's partial text; it never appends a second copy.
//! Ranges index UTF-8 boundaries in the existing output string, so streaming
//! the current last item retains the ordinary append path.

use std::ops::Range;

use codex_app_server_protocol::ThreadItem;
use codex_app_server_protocol::TurnItemsView;

use super::MAX_OUTPUT_BYTES;

const MAX_OUTPUT_ITEMS: usize = 1_024;
const MAX_OUTPUT_ITEM_ID_BYTES: usize = 256;

#[derive(Clone)]
struct CollectedMessageV1 {
    id: String,
    range: Range<usize>,
    completed: bool,
}

#[derive(Clone, Default)]
pub(super) struct NativeOutputCollectorV1 {
    messages: Vec<CollectedMessageV1>,
}

impl NativeOutputCollectorV1 {
    pub(super) fn started(
        &mut self,
        output: &mut String,
        id: &str,
        text: &str,
    ) -> Result<(), String> {
        validate_item_id(id)?;
        if self.messages.iter().any(|message| message.id == id) {
            return Ok(());
        }
        self.insert_message(output, id, text)
    }

    pub(super) fn delta(
        &mut self,
        output: &mut String,
        id: &str,
        delta: &str,
    ) -> Result<(), String> {
        validate_item_id(id)?;
        let index = self.messages.iter().position(|message| message.id == id);
        if let Some(index) = index
            && self.messages[index].completed
        {
            return Ok(());
        }
        if delta.len() > MAX_OUTPUT_BYTES.saturating_sub(output.len()) {
            return Err("output byte limit exceeded".to_string());
        }
        let index = match index {
            Some(index) => index,
            None => {
                self.insert_message(output, id, "")?;
                self.messages.len() - 1
            }
        };
        let end = self.messages[index].range.end;
        if end == output.len() {
            output.push_str(delta);
        } else {
            output.insert_str(end, delta);
        }
        self.messages[index].range.end += delta.len();
        self.shift_following(index, /*old_len*/ 0, delta.len());
        Ok(())
    }

    pub(super) fn completed(
        &mut self,
        output: &mut String,
        id: &str,
        text: &str,
    ) -> Result<(), String> {
        validate_item_id(id)?;
        let Some(index) = self.messages.iter().position(|message| message.id == id) else {
            let index = self.messages.len();
            self.insert_message(output, id, text)?;
            self.messages[index].completed = true;
            return Ok(());
        };
        let message = &self.messages[index];
        if message.completed {
            return if &output[message.range.clone()] == text {
                Ok(())
            } else {
                Err("completed output item changed".to_string())
            };
        }
        let range = message.range.clone();
        let old_len = range.len();
        if text.len() > MAX_OUTPUT_BYTES.saturating_sub(output.len() - old_len) {
            return Err("output byte limit exceeded".to_string());
        }
        output.replace_range(range.clone(), text);
        self.messages[index].range.end = range.start + text.len();
        self.messages[index].completed = true;
        self.shift_following(index, old_len, text.len());
        Ok(())
    }

    pub(super) fn turn_completed(
        &mut self,
        output: &mut String,
        items: &[ThreadItem],
        view: TurnItemsView,
    ) -> Result<(), String> {
        if view == TurnItemsView::NotLoaded {
            return Ok(());
        }
        // Validate the entire terminal projection before changing live output.
        // A Summary may contain only the final message. Full fixes both the
        // authoritative order and membership of the final output projection.
        let mut projected = if view == TurnItemsView::Full {
            Self::default()
        } else {
            self.clone()
        };
        let mut text = if view == TurnItemsView::Full {
            String::new()
        } else {
            output.clone()
        };
        for item in items {
            if let ThreadItem::AgentMessage {
                id,
                text: final_text,
                ..
            } = item
            {
                if view == TurnItemsView::Full
                    && projected.messages.iter().any(|message| message.id == *id)
                {
                    return Err("duplicate completed output item id".to_string());
                }
                if let Some(message) = self.messages.iter().find(|message| message.id == *id)
                    && message.completed
                    && &output[message.range.clone()] != final_text
                {
                    return Err("completed output item changed".to_string());
                }
                projected.completed(&mut text, id, final_text)?;
            }
        }
        *self = projected;
        *output = text;
        Ok(())
    }

    /// Recovery has no retained item stream to supplement a display summary.
    /// Only a complete history view can supply the entire recovered output.
    pub(super) fn reconciled_turn(
        &mut self,
        output: &mut String,
        items: &[ThreadItem],
        view: TurnItemsView,
    ) -> Result<(), String> {
        if view != TurnItemsView::Full {
            return Err("reconciled output requires a full turn view".to_string());
        }
        self.turn_completed(output, items, view)
    }

    fn insert_message(&mut self, output: &mut String, id: &str, text: &str) -> Result<(), String> {
        if self.messages.len() >= MAX_OUTPUT_ITEMS {
            return Err("output item limit exceeded".to_string());
        }
        if text.len() > MAX_OUTPUT_BYTES.saturating_sub(output.len()) {
            return Err("output byte limit exceeded".to_string());
        }
        let start = output.len();
        output.push_str(text);
        self.messages.push(CollectedMessageV1 {
            id: id.to_string(),
            range: start..output.len(),
            completed: false,
        });
        Ok(())
    }

    fn shift_following(&mut self, index: usize, old_len: usize, new_len: usize) {
        for message in &mut self.messages[index + 1..] {
            message.range.start = message.range.start - old_len + new_len;
            message.range.end = message.range.end - old_len + new_len;
        }
    }
}

fn validate_item_id(id: &str) -> Result<(), String> {
    if id.is_empty() || id.len() > MAX_OUTPUT_ITEM_ID_BYTES {
        return Err("invalid output item id".to_string());
    }
    Ok(())
}

#[cfg(test)]
#[path = "native_output_collector_tests.rs"]
mod tests;
