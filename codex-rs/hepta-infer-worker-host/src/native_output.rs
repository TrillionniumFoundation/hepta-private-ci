//! Bounded per-item projection of streamed and canonical completed output.

use codex_app_server_protocol::ThreadItem;

use super::MAX_OUTPUT_BYTES;

const MAX_OUTPUT_ITEMS: usize = 1024;
const MAX_ITEM_ID_BYTES: usize = 1024;

#[derive(Clone, Default)]
pub(super) struct NativeOutputProjection {
    items: Vec<OutputItem>,
    bytes: usize,
}

#[derive(Clone)]
struct OutputItem {
    id: String,
    text: String,
    completed: bool,
}

impl NativeOutputProjection {
    pub(super) fn append_delta(&mut self, id: &str, delta: &str) -> Result<(), String> {
        let index = self.item_index(id)?;
        if index.is_some_and(|index| self.items[index].completed) {
            return Err("text delta follows a completed output item".to_string());
        }
        if delta.len() > MAX_OUTPUT_BYTES.saturating_sub(self.bytes) {
            return Err("output byte limit exceeded".to_string());
        }
        let index = self.get_or_insert(id, index);
        self.items[index].text.push_str(delta);
        self.bytes += delta.len();
        Ok(())
    }

    pub(super) fn complete_item(&mut self, id: &str, text: &str) -> Result<(), String> {
        let index = self.item_index(id)?;
        if let Some(index) = index {
            let prior = &self.items[index];
            if prior.completed {
                return if prior.text == text {
                    Ok(())
                } else {
                    Err("completed output item changed its text".to_string())
                };
            }
        }
        let prior_bytes = index.map_or(0, |index| self.items[index].text.len());
        let other_bytes = self.bytes - prior_bytes;
        if text.len() > MAX_OUTPUT_BYTES.saturating_sub(other_bytes) {
            return Err("output byte limit exceeded".to_string());
        }
        let index = self.get_or_insert(id, index);
        self.items[index].text = text.to_string();
        self.items[index].completed = true;
        self.bytes = other_bytes + text.len();
        Ok(())
    }

    pub(super) fn complete_items(&mut self, items: &[ThreadItem]) -> Result<(), String> {
        if items.len() > MAX_OUTPUT_ITEMS {
            return Err("output item limit exceeded".to_string());
        }
        // A rejected terminal snapshot must not partially replace the output.
        let mut next = self.clone();
        for item in items {
            if let ThreadItem::AgentMessage { id, text, .. } = item {
                next.complete_item(id, text)?;
            }
        }
        *self = next;
        Ok(())
    }

    pub(super) fn text(&self) -> String {
        let mut text = String::with_capacity(self.bytes);
        for item in &self.items {
            text.push_str(&item.text);
        }
        text
    }

    fn item_index(&self, id: &str) -> Result<Option<usize>, String> {
        if id.is_empty() || id.len() > MAX_ITEM_ID_BYTES {
            return Err("output item identity exceeds bounds".to_string());
        }
        let index = self.items.iter().position(|item| item.id == id);
        if index.is_none() && self.items.len() >= MAX_OUTPUT_ITEMS {
            return Err("output item limit exceeded".to_string());
        }
        Ok(index)
    }

    fn get_or_insert(&mut self, id: &str, index: Option<usize>) -> usize {
        index.unwrap_or_else(|| {
            let index = self.items.len();
            self.items.push(OutputItem {
                id: id.to_string(),
                text: String::new(),
                completed: false,
            });
            index
        })
    }
}

#[cfg(test)]
#[path = "native_output_tests.rs"]
mod tests;
