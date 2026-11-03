//! Bounded cursor/selection memory; draft text remains owned by ChatWorkspace.
//! SDK undo histories are intentionally not retained: they have no size bound.
use crate::presentation::RoomKey;
use hepta_control_core::chat::{MAX_DRAFT_BYTES, MAX_LOCAL_DRAFTS};
use std::collections::HashMap;

pub(crate) struct EditorMemory<S> {
    epoch: Option<u64>,
    entries: HashMap<RoomKey, (String, S)>,
}

impl<S> Default for EditorMemory<S> {
    fn default() -> Self {
        Self {
            epoch: None,
            entries: HashMap::new(),
        }
    }
}

impl<S: Copy> EditorMemory<S> {
    /// Account/session changes discard all previously retained editor state.
    pub(crate) fn bind(&mut self, epoch: u64) {
        if self.epoch != Some(epoch) {
            self.entries.clear();
            self.epoch = Some(epoch);
        }
    }

    pub(crate) fn remember(&mut self, key: RoomKey, text: &str, selection: S) {
        if self.epoch != Some(key.epoch)
            || text.len() > MAX_DRAFT_BYTES
            || text.contains('\0')
            || (!self.entries.contains_key(&key) && self.entries.len() >= MAX_LOCAL_DRAFTS)
        {
            return;
        }
        self.entries.insert(key, (text.to_owned(), selection));
    }

    /// A changed draft cannot inherit a caret from an older text revision.
    pub(crate) fn restore(&mut self, key: RoomKey, text: &str) -> Option<S> {
        if self.epoch != Some(key.epoch) {
            return None;
        }
        match self.entries.get(&key) {
            Some((saved, selection)) if saved == text => Some(*selection),
            Some(_) => {
                self.entries.remove(&key);
                None
            }
            None => None,
        }
    }
}

#[cfg(test)]
#[path = "editor_memory_tests.rs"]
mod tests;
