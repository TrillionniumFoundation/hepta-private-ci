//! Connection-local assembly of bounded agent-message output.
//! Completed items can arrive without deltas; repeated completion must not
//! duplicate output. Keep this observation state through interruption grace.

const MAX_MESSAGE_ITEMS: usize = 1024;
const MAX_MESSAGE_ID_BYTES: usize = 128;

#[derive(Default)]
pub(super) struct NativeMessageOutput {
    items: Vec<MessageSpan>,
}

struct MessageSpan {
    id: String,
    bytes: std::ops::Range<usize>,
    completed: bool,
}

impl NativeMessageOutput {
    pub(super) fn record(
        &mut self,
        output: &mut String,
        id: &str,
        text: &str,
        completed: bool,
    ) -> Result<(), String> {
        if id.is_empty() || id.len() > MAX_MESSAGE_ID_BYTES {
            return Err("agent message identity exceeds bounds".to_string());
        }
        let index = self.items.iter().position(|item| item.id == id);
        let (position, suffix) = if let Some(index) = index {
            let item = &self.items[index];
            let previous = output
                .get(item.bytes.clone())
                .ok_or_else(|| "agent message output range invalid".to_string())?;
            let suffix = if completed {
                if (item.completed && previous != text) || !text.starts_with(previous) {
                    return Err(
                        "agent message completion conflicts with observed output".to_string()
                    );
                }
                &text[previous.len()..]
            } else {
                if item.completed && !text.is_empty() {
                    return Err("agent message delta followed completion".to_string());
                }
                text
            };
            (item.bytes.end, suffix)
        } else {
            if self.items.len() >= MAX_MESSAGE_ITEMS {
                return Err("agent message item limit exceeded".to_string());
            }
            (output.len(), text)
        };
        if suffix.len() > super::MAX_OUTPUT_BYTES.saturating_sub(output.len()) {
            return Err("output byte limit exceeded".to_string());
        }
        // Insert only newly observed bytes. No full-output clone is needed;
        // earlier interleaved items retain their original ordering.
        output.insert_str(position, suffix);
        if let Some(index) = index {
            self.items[index].bytes.end += suffix.len();
            self.items[index].completed |= completed;
            for item in &mut self.items[index + 1..] {
                item.bytes.start += suffix.len();
                item.bytes.end += suffix.len();
            }
        } else {
            self.items.push(MessageSpan {
                id: id.to_string(),
                bytes: position..position + suffix.len(),
                completed,
            });
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn completed_only_message_is_preserved_and_repeated_completion_is_idempotent() {
        let mut state = NativeMessageOutput::default();
        let mut output = String::new();
        state
            .record(&mut output, "a", "fresh context accepted", true)
            .unwrap();
        state
            .record(&mut output, "a", "fresh context accepted", true)
            .unwrap();
        assert_eq!(output, "fresh context accepted");
    }

    #[test]
    fn interleaved_deltas_and_completions_preserve_message_order_and_utf8() {
        let mut state = NativeMessageOutput::default();
        let mut output = String::new();
        state.record(&mut output, "a", "前", false).unwrap();
        state.record(&mut output, "b", "后", false).unwrap();
        state.record(&mut output, "a", "前半", true).unwrap();
        state.record(&mut output, "b", "后半", true).unwrap();
        assert_eq!(output, "前半后半");
        state.record(&mut output, "a", "前半", true).unwrap();
        assert_eq!(output, "前半后半");
    }

    #[test]
    fn conflicting_completion_and_late_delta_leave_previous_output_unchanged() {
        let mut state = NativeMessageOutput::default();
        let mut output = String::new();
        state.record(&mut output, "a", "prefix", false).unwrap();
        assert!(state.record(&mut output, "a", "different", true).is_err());
        assert_eq!(output, "prefix");
        state
            .record(&mut output, "a", "prefix suffix", true)
            .unwrap();
        assert!(state.record(&mut output, "a", "!", false).is_err());
        assert!(
            state
                .record(&mut output, "a", "prefix suffix changed", true)
                .is_err()
        );
        assert_eq!(output, "prefix suffix");
    }

    #[test]
    fn completion_and_zero_length_items_obey_output_and_metadata_limits() {
        let mut state = NativeMessageOutput::default();
        let mut output = String::new();
        state.record(&mut output, "a", "x", false).unwrap();
        assert!(
            state
                .record(
                    &mut output,
                    "b",
                    &"x".repeat(super::super::MAX_OUTPUT_BYTES),
                    true
                )
                .is_err()
        );
        assert_eq!(output, "x");
        for id in 1..MAX_MESSAGE_ITEMS {
            state
                .record(&mut output, &format!("item-{id}"), "", true)
                .unwrap();
        }
        assert!(state.record(&mut output, "overflow", "", true).is_err());
        assert!(
            state
                .record(&mut output, &"a".repeat(MAX_MESSAGE_ID_BYTES + 1), "", true)
                .is_err()
        );
        assert_eq!(output, "x");
    }
}
