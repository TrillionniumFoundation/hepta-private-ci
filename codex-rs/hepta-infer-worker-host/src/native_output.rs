//! Bounded transient message assembly for one already-bound App Server turn.

const MAX_ITEMS: usize = 1_024;
const MAX_ITEM_ID_BYTES: usize = 128;

#[derive(Clone)]
struct Message {
    id: String,
    text: String,
    completed: bool,
}

#[derive(Clone, Default)]
pub(super) struct MessageOutput {
    items: Vec<Message>,
    bytes: usize,
}

impl MessageOutput {
    fn index(&self, id: &str) -> Result<Option<usize>, String> {
        if id.is_empty() || id.len() > MAX_ITEM_ID_BYTES {
            return Err("invalid output item identity".to_string());
        }
        let index = self.items.iter().position(|item| item.id == id);
        if index.is_none() && self.items.len() >= MAX_ITEMS {
            return Err("output item count exceeded".to_string());
        }
        Ok(index)
    }

    pub(super) fn delta(&mut self, id: &str, delta: &str) -> Result<(), String> {
        let index = self.index(id)?;
        if index.is_some_and(|index| self.items[index].completed) {
            return Err("output delta after item completion".to_string());
        }
        if delta.len() > super::MAX_OUTPUT_BYTES.saturating_sub(self.bytes) {
            return Err("output byte limit exceeded".to_string());
        }
        match index {
            Some(index) => self.items[index].text.push_str(delta),
            None => self.items.push(Message {
                id: id.to_string(),
                text: delta.to_string(),
                completed: false,
            }),
        }
        self.bytes += delta.len();
        Ok(())
    }

    /// Completed text replaces this item's deltas. A repeated completion may
    /// only confirm the identical final bytes; it cannot revise them.
    pub(super) fn complete(&mut self, id: &str, text: &str) -> Result<bool, String> {
        let index = self.index(id)?;
        let previous = index.map_or(0, |index| self.items[index].text.len());
        if let Some(index) = index
            && self.items[index].completed
        {
            return if self.items[index].text == text {
                Ok(false)
            } else {
                Err("completed output item changed".to_string())
            };
        }
        let retained = self.bytes - previous;
        if text.len() > super::MAX_OUTPUT_BYTES.saturating_sub(retained) {
            return Err("output byte limit exceeded".to_string());
        }
        match index {
            Some(index) => {
                self.items[index].text = text.to_string();
                self.items[index].completed = true;
            }
            None => self.items.push(Message {
                id: id.to_string(),
                text: text.to_string(),
                completed: true,
            }),
        }
        self.bytes = retained + text.len();
        Ok(true)
    }

    pub(super) fn render(&self) -> String {
        let mut text = String::with_capacity(self.bytes);
        for item in &self.items {
            text.push_str(&item.text);
        }
        text
    }

    /// Validate the complete snapshot before replacing any observed bytes.
    pub(super) fn full<'a>(
        &mut self,
        items: impl IntoIterator<Item = (&'a str, &'a str)>,
    ) -> Result<(), String> {
        let mut replacement = Self::default();
        for (id, text) in items {
            if replacement.items.iter().any(|item| item.id == id) {
                return Err("duplicate full output item".to_string());
            }
            replacement.complete(id, text)?;
        }
        for observed in &self.items {
            let item = replacement
                .items
                .iter()
                .find(|item| item.id == observed.id)
                .ok_or_else(|| "full output omitted observed item".to_string())?;
            if observed.completed && item.text != observed.text {
                return Err("completed output item changed".to_string());
            }
        }
        *self = replacement;
        Ok(())
    }
}

#[cfg(test)]
#[path = "native_output_tests.rs"]
mod tests;
