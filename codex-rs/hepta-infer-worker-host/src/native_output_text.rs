//! Private, bounded assembly of assistant text from one filtered observation stream.
//!
//! The driver owns thread/turn filtering, terminal witnesses, cancellation, owner
//! authority, and the separate thread/read recovery path. This helper owns only
//! item identity, output order, text reconciliation, and local resource bounds.

use std::fmt;

pub(super) const MAX_OUTPUT_BYTES: usize = 1024 * 1024;
// New conservative limits, independent of the existing aggregate text limit.
const MAX_ASSISTANT_ITEMS: usize = 1024;
const MAX_ITEM_ID_BYTES: usize = 1024;
const MAX_TOTAL_ITEM_ID_BYTES: usize = 64 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum OutputTextError {
    EmptyItemId,
    ItemIdTooLong,
    ItemCountLimit,
    ItemIdBudget,
    TextBudget,
    ConflictingStart,
    ConflictingCompletion,
    DeltaAfterCompletion,
    AfterTerminal,
}

impl fmt::Display for OutputTextError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::EmptyItemId => "assistant item ID is empty",
            Self::ItemIdTooLong => "assistant item ID byte limit exceeded",
            Self::ItemCountLimit => "assistant item count limit exceeded",
            Self::ItemIdBudget => "assistant item ID aggregate byte limit exceeded",
            Self::TextBudget => "output byte limit exceeded",
            Self::ConflictingStart => "assistant start snapshot conflicts with observed text",
            Self::ConflictingCompletion => "assistant completion conflicts with observed text",
            Self::DeltaAfterCompletion => "assistant delta arrived after item completion",
            Self::AfterTerminal => "assistant text event arrived after terminal observation",
        })
    }
}

impl std::error::Error for OutputTextError {}

struct AssistantItem {
    id: Box<str>,
    text: String,
    completed: bool,
}

enum TextEvent<'a> {
    Started(&'a str),
    Delta(&'a str),
    Completed(&'a str),
}

/// Each identity gets one immutable output position on first observation.
/// An early ItemStarted reserves that position; a late/repeated start cannot
/// reorder the item or reopen a completed item. Start snapshots seed text and
/// must remain prefix-consistent with existing text. Deltas lack sequence IDs and
/// therefore append exactly as delivered, including repeated equal fragments.
/// An empty delta for an existing finalized item is an idempotent no-op. An
/// unknown identity still reserves its bounded first-observation slot.
pub(super) struct NativeOutputText {
    items: Vec<AssistantItem>,
    text_bytes: usize,
    item_id_bytes: usize,
    failure: Option<OutputTextError>,
    sealed: bool,
}

impl NativeOutputText {
    pub(super) fn new() -> Self {
        Self {
            items: Vec::new(),
            text_bytes: 0,
            item_id_bytes: 0,
            failure: None,
            sealed: false,
        }
    }

    pub(super) fn item_started(
        &mut self,
        item_id: &str,
        initial_text: &str,
    ) -> Result<(), OutputTextError> {
        self.observe(item_id, TextEvent::Started(initial_text))
    }

    pub(super) fn delta(&mut self, item_id: &str, fragment: &str) -> Result<(), OutputTextError> {
        self.observe(item_id, TextEvent::Delta(fragment))
    }

    /// Reconcile one complete item against its streamed prefix. The live driver
    /// does not treat terminal summaries as a replacement transcript.
    pub(super) fn item_completed(
        &mut self,
        item_id: &str,
        full_text: &str,
    ) -> Result<(), OutputTextError> {
        self.observe(item_id, TextEvent::Completed(full_text))
    }

    /// Freeze only after the driver validates and reconciles a terminal event.
    /// Repeated sealing is harmless; no text event is accepted after sealing.
    pub(super) fn seal(&mut self) -> Result<(), OutputTextError> {
        if let Some(error) = self.failure {
            return Err(error);
        }
        self.sealed = true;
        Ok(())
    }

    pub(super) fn is_rejected(&self) -> bool {
        self.failure.is_some()
    }

    pub(super) fn is_sealed(&self) -> bool {
        self.sealed
    }

    /// Snapshot only at the abort boundary if existing cancellation journaling
    /// needs output before its interrupt-grace observation pass. Keep this same
    /// accumulator alive for that pass; never recreate it or snapshot per delta.
    pub(super) fn snapshot_output(&self) -> String {
        let mut output = String::with_capacity(self.text_bytes);
        for item in &self.items {
            output.push_str(&item.text);
        }
        output
    }

    /// Assemble exactly once after observation stops, including abort/error.
    /// This returns accepted partial text even after an error; the caller must
    /// preserve that error and must not interpret text availability as success.
    pub(super) fn into_output(self) -> String {
        self.snapshot_output()
    }

    fn observe(&mut self, item_id: &str, event: TextEvent<'_>) -> Result<(), OutputTextError> {
        let result = self.observe_inner(item_id, event);
        if let Err(error) = result {
            self.failure = Some(error);
        }
        result
    }

    fn observe_inner(
        &mut self,
        item_id: &str,
        event: TextEvent<'_>,
    ) -> Result<(), OutputTextError> {
        if let Some(error) = self.failure {
            return Err(error);
        }
        if self.sealed {
            return Err(OutputTextError::AfterTerminal);
        }
        if item_id.is_empty() {
            return Err(OutputTextError::EmptyItemId);
        }
        if item_id.len() > MAX_ITEM_ID_BYTES {
            return Err(OutputTextError::ItemIdTooLong);
        }

        let index = self
            .items
            .iter()
            .position(|item| item.id.as_ref() == item_id);
        let suffix = if let Some(index) = index {
            let item = &self.items[index];
            match event {
                TextEvent::Started(initial_text) if item.text.starts_with(initial_text) => "",
                TextEvent::Started(_) if item.completed => {
                    return Err(OutputTextError::ConflictingStart);
                }
                TextEvent::Started(initial_text) => initial_text
                    .strip_prefix(&item.text)
                    .ok_or(OutputTextError::ConflictingStart)?,
                TextEvent::Delta(fragment) if item.completed && !fragment.is_empty() => {
                    return Err(OutputTextError::DeltaAfterCompletion);
                }
                TextEvent::Delta(fragment) => fragment,
                TextEvent::Completed(full_text) if item.completed => {
                    if item.text != full_text {
                        return Err(OutputTextError::ConflictingCompletion);
                    }
                    ""
                }
                TextEvent::Completed(full_text) => full_text
                    .strip_prefix(&item.text)
                    .ok_or(OutputTextError::ConflictingCompletion)?,
            }
        } else {
            if self.items.len() == MAX_ASSISTANT_ITEMS {
                return Err(OutputTextError::ItemCountLimit);
            }
            if item_id.len() > MAX_TOTAL_ITEM_ID_BYTES - self.item_id_bytes {
                return Err(OutputTextError::ItemIdBudget);
            }
            match event {
                TextEvent::Started(fragment)
                | TextEvent::Delta(fragment)
                | TextEvent::Completed(fragment) => fragment,
            }
        };

        if suffix.len() > MAX_OUTPUT_BYTES - self.text_bytes {
            return Err(OutputTextError::TextBudget);
        }
        // Validate the entire event before inserting or changing any item.
        // Vec lookup is bounded by MAX_ASSISTANT_ITEMS. Per-item String append
        // uses amortized growth; the aggregate is never rebuilt on the hot path.
        let suffix_bytes = suffix.len();
        if let Some(index) = index {
            let item = &mut self.items[index];
            item.text.push_str(suffix);
            if matches!(event, TextEvent::Completed(_)) {
                item.completed = true;
            }
        } else {
            self.items.push(AssistantItem {
                id: item_id.into(),
                text: suffix.to_owned(),
                completed: matches!(event, TextEvent::Completed(_)),
            });
            self.item_id_bytes += item_id.len();
        }
        self.text_bytes += suffix_bytes;
        Ok(())
    }
}

#[cfg(test)]
#[path = "native_output_text_tests.rs"]
mod tests;
