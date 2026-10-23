//! Bounded, item-aware observations of streamed and completed assistant text.

use std::collections::BTreeMap;
use std::ops::Range;

pub(super) const MAX_OUTPUT_BYTES: usize = 1024 * 1024;

#[derive(Default)]
pub(super) struct NativeTextObservation {
    items: BTreeMap<String, ItemText>,
    bookkeeping_bytes: usize,
}

#[derive(Default)]
struct ItemText {
    // Ranges refer to the append-only published output, without copying deltas.
    ranges: Vec<Range<usize>>,
    observed_bytes: usize,
    completed: bool,
}

impl NativeTextObservation {
    fn reserve_bookkeeping(&mut self, bytes: usize) -> Result<(), String> {
        let next = self
            .bookkeeping_bytes
            .checked_add(bytes)
            .filter(|next| *next <= MAX_OUTPUT_BYTES)
            .ok_or_else(|| "agent message bookkeeping byte limit exceeded".to_string())?;
        self.bookkeeping_bytes = next;
        Ok(())
    }

    fn ensure_item(&mut self, id: &str) -> Result<(), String> {
        if !self.items.contains_key(id) {
            let bytes = id
                .len()
                .checked_add(std::mem::size_of::<(String, ItemText)>())
                .ok_or_else(|| "agent message bookkeeping byte limit exceeded".to_string())?;
            // IDs are opaque protocol strings. Bound their storage before copying
            // them, without imposing an unrelated StableId grammar.
            self.reserve_bookkeeping(bytes)?;
            self.items.insert(id.to_string(), ItemText::default());
        }
        Ok(())
    }

    fn append(&mut self, output: &mut String, id: &str, text: &str) -> Result<(), String> {
        if text.is_empty() {
            return Ok(());
        }
        let contiguous = self
            .items
            .get(id)
            .ok_or_else(|| "agent message observation state missing".to_string())?
            .ranges
            .last()
            .is_some_and(|range| range.end == output.len());
        if !contiguous {
            self.reserve_bookkeeping(std::mem::size_of::<Range<usize>>())?;
        }
        let start = output.len();
        let item = self
            .items
            .get_mut(id)
            .ok_or_else(|| "agent message observation state missing".to_string())?;
        if contiguous {
            let range = item
                .ranges
                .last_mut()
                .ok_or_else(|| "agent message observation range missing".to_string())?;
            output.push_str(text);
            range.end = output.len();
        } else {
            output.push_str(text);
            item.ranges.push(start..output.len());
        }
        item.observed_bytes += text.len();
        Ok(())
    }

    pub(super) fn delta(
        &mut self,
        output: &mut String,
        id: &str,
        text: &str,
    ) -> Result<(), String> {
        self.ensure_item(id)?;
        let item = self
            .items
            .get(id)
            .ok_or_else(|| "agent message observation state missing".to_string())?;
        if item.completed && !text.is_empty() {
            return Err("agent message delta arrived after completion".to_string());
        }
        if text.len() > MAX_OUTPUT_BYTES.saturating_sub(output.len()) {
            return Err("output byte limit exceeded".to_string());
        }
        self.append(output, id, text)
    }

    pub(super) fn complete(
        &mut self,
        output: &mut String,
        id: &str,
        text: &str,
    ) -> Result<(), String> {
        self.ensure_item(id)?;
        let item = self
            .items
            .get(id)
            .ok_or_else(|| "agent message observation state missing".to_string())?;
        let mut offset = 0;
        for range in &item.ranges {
            let part = output
                .get(range.clone())
                .ok_or_else(|| "agent message observation range invalid".to_string())?;
            if !text
                .get(offset..)
                .is_some_and(|suffix| suffix.starts_with(part))
            {
                return Err("completed agent message contradicts observed prefix".to_string());
            }
            offset += part.len();
        }
        if item.completed {
            return if text.len() == item.observed_bytes {
                Ok(())
            } else {
                Err("completed agent message changed".to_string())
            };
        }
        let suffix = &text[offset..];
        let mut end = suffix
            .len()
            .min(MAX_OUTPUT_BYTES.saturating_sub(output.len()));
        while !suffix.is_char_boundary(end) {
            end -= 1;
        }
        self.append(output, id, &suffix[..end])?;
        if end != suffix.len() {
            return Err("output byte limit exceeded".to_string());
        }
        self.items
            .get_mut(id)
            .ok_or_else(|| "agent message observation state missing".to_string())?
            .completed = true;
        Ok(())
    }
}

#[cfg(test)]
#[path = "native_text_tests.rs"]
mod tests;
