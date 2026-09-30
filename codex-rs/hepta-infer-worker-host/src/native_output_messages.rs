//! Bounded per-turn text assembly from streamed and completed message items.

use super::MAX_OUTPUT_BYTES;

const MAX_MESSAGE_ITEMS: usize = 1024;

#[derive(Default)]
pub(super) struct ObservedAgentMessages {
    items: Vec<MessageItem>,
    item_id_bytes: usize,
    text_bytes: usize,
}

struct MessageItem {
    id: String,
    text: String,
    completed: bool,
}

impl ObservedAgentMessages {
    pub(super) fn start(
        &mut self,
        output: &mut String,
        id: &str,
        text: &str,
    ) -> Result<(), String> {
        if self.items.iter().any(|item| item.id == id) {
            // A duplicate or delayed start must not replay an initial prefix.
            return Ok(());
        }
        self.update(output, id, text, false)
    }

    pub(super) fn delta(
        &mut self,
        output: &mut String,
        id: &str,
        delta: &str,
    ) -> Result<(), String> {
        self.update(output, id, delta, false)
    }

    pub(super) fn complete(
        &mut self,
        output: &mut String,
        id: &str,
        text: &str,
    ) -> Result<(), String> {
        self.update(output, id, text, true)
    }

    fn update(
        &mut self,
        output: &mut String,
        id: &str,
        text: &str,
        completed: bool,
    ) -> Result<(), String> {
        let existing = if self.items.last().is_some_and(|item| item.id == id) {
            Some(self.items.len() - 1)
        } else {
            self.items.iter().position(|item| item.id == id)
        };
        let previous_len = existing.map_or(0, |index| self.items[index].text.len());
        if let Some(index) = existing
            && self.items[index].completed
        {
            if completed && self.items[index].text == text {
                return Ok(());
            }
            return Err("completed message item changed".to_string());
        }
        let added_bytes = if completed {
            text.len()
        } else {
            previous_len.saturating_add(text.len())
        };
        if added_bytes > MAX_OUTPUT_BYTES.saturating_sub(self.text_bytes - previous_len) {
            return Err("output byte limit exceeded".to_string());
        }
        if existing.is_none()
            && (self.items.len() >= MAX_MESSAGE_ITEMS
                || id.len() > MAX_OUTPUT_BYTES.saturating_sub(self.item_id_bytes))
        {
            return Err("output message identity limit exceeded".to_string());
        }
        let index = existing.unwrap_or_else(|| {
            self.item_id_bytes += id.len();
            self.items.push(MessageItem {
                id: id.to_string(),
                text: String::new(),
                completed: false,
            });
            self.items.len() - 1
        });
        let is_last = index + 1 == self.items.len();
        let item = &mut self.items[index];
        if completed {
            // Completed items are authoritative snapshots, not extra deltas.
            // Drop the partial buffer so shrinking snapshots release capacity.
            item.text = text.to_string();
        } else {
            item.text.push_str(text);
        }
        item.completed = completed;
        self.text_bytes = self.text_bytes - previous_len + added_bytes;
        if is_last {
            // Normal streaming appends in constant time without rebuilding
            // the already observed prefix for every small token delta.
            if completed {
                output.truncate(output.len() - previous_len);
            }
            output.push_str(text);
        } else {
            output.clear();
            for item in &self.items {
                output.push_str(&item.text);
            }
        }
        Ok(())
    }
}
