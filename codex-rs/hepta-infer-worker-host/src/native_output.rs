//! Bounded per-item output assembly on one exact App Server turn.
//!
//! Completion events can carry the only copy of an assistant message. Deltas
//! and completion snapshots describe the same item, not additional output.

use super::*;

const MAX_OUTPUT_ITEMS: usize = 4_096;
const MAX_ITEM_ID_BYTES: usize = 256;

type ObservationResult<T> = std::result::Result<T, String>;

#[derive(Clone, Debug)]
struct Message {
    id: String,
    text: String,
    completed: bool,
}

#[derive(Clone, Debug, Default)]
pub(super) struct NativeOutputAssembly {
    messages: Vec<Message>,
    total_bytes: usize,
}

impl NativeOutputAssembly {
    fn record(&mut self, id: &str, text: &str, complete: bool) -> ObservationResult<()> {
        if id.is_empty() || id.len() > MAX_ITEM_ID_BYTES {
            return Err("invalid output item identity".to_string());
        }
        let position = self.messages.iter().position(|message| message.id == id);
        let previous = position.map(|index| &self.messages[index]);
        if let Some(previous) = previous {
            if previous.completed {
                return if complete && previous.text == text {
                    Ok(())
                } else {
                    Err("output changed after item completion".to_string())
                };
            }
            if complete && !text.starts_with(&previous.text) {
                return Err("completed output disagrees with observed deltas".to_string());
            }
        } else if self.messages.len() >= MAX_OUTPUT_ITEMS {
            return Err("output item count limit exceeded".to_string());
        }
        let old_length = previous.map_or(0, |message| message.text.len());
        let new_length = if complete {
            text.len()
        } else {
            old_length
                .checked_add(text.len())
                .ok_or_else(|| "output byte arithmetic overflow".to_string())?
        };
        let total_bytes = self
            .total_bytes
            .checked_sub(old_length)
            .and_then(|value| value.checked_add(new_length))
            .filter(|value| *value <= MAX_OUTPUT_BYTES)
            .ok_or_else(|| "output byte limit exceeded".to_string())?;
        // All checks precede mutation. First-seen item order is stable even when
        // deltas interleave, and completed duplicates do not append text again.
        if let Some(index) = position {
            let message = &mut self.messages[index];
            if complete {
                message.text.clear();
            }
            message.text.push_str(text);
            message.completed = complete;
        } else {
            self.messages.push(Message {
                id: id.to_string(),
                text: text.to_string(),
                completed: complete,
            });
        }
        self.total_bytes = total_bytes;
        Ok(())
    }

    fn completed_items(&mut self, items: &[ThreadItem]) -> ObservationResult<()> {
        // A conflicting later item must not partially replace a valid earlier
        // observation. This clone is bounded by MAX_OUTPUT_BYTES/MAX_OUTPUT_ITEMS.
        let mut next = self.clone();
        for item in items {
            if let ThreadItem::AgentMessage { id, text, .. } = item {
                next.record(id, text, /*complete*/ true)?;
            }
        }
        *self = next;
        Ok(())
    }

    fn render(&self) -> String {
        let mut text = String::with_capacity(self.total_bytes);
        for message in &self.messages {
            text.push_str(&message.text);
        }
        text
    }
}

pub(super) fn observe_event(
    output: &mut NativeRunOutput,
    observed: &RemoteAppServerObservedEvent,
    binding: &CodexTurnBinding,
) -> ObservationResult<bool> {
    let AppServerEvent::ServerNotification(notification) = observed.event() else {
        return Ok(false);
    };
    match notification.as_ref() {
        ServerNotification::AgentMessageDelta(delta)
            if delta.thread_id == output.thread_id && delta.turn_id == output.turn_id =>
        {
            let mut assembly = binding
                .output_assembly
                .lock()
                .map_err(|_| "output observation lock poisoned".to_string())?;
            assembly.record(&delta.item_id, &delta.delta, /*complete*/ false)?;
            output.output = assembly.render();
        }
        ServerNotification::ItemCompleted(completed)
            if completed.thread_id == output.thread_id && completed.turn_id == output.turn_id =>
        {
            if let ThreadItem::AgentMessage { id, text, .. } = &completed.item {
                let mut assembly = binding
                    .output_assembly
                    .lock()
                    .map_err(|_| "output observation lock poisoned".to_string())?;
                assembly.record(id, text, /*complete*/ true)?;
                output.output = assembly.render();
            }
        }
        ServerNotification::ThreadTokenUsageUpdated(usage)
            if usage.thread_id == output.thread_id && usage.turn_id == output.turn_id =>
        {
            let observed_tokens = u64::try_from(usage.token_usage.total.output_tokens)
                .map_err(|_| "invalid negative provider usage".to_string())?;
            if output
                .observed_output_tokens
                .is_some_and(|previous| observed_tokens < previous)
            {
                return Err("provider cumulative usage regressed".to_string());
            }
            output.observed_output_tokens = Some(observed_tokens);
        }
        ServerNotification::TurnCompleted(completed)
            if completed.thread_id == output.thread_id && completed.turn.id == output.turn_id =>
        {
            let receipt = adapt_observed_event(&binding.intent, &binding.turn_id, observed)
                .map_err(|error| format!("invalid App Server terminal witness: {error}"))?
                .ok_or_else(|| "turn/completed did not produce terminal receipt".to_string())?;
            let (status, physical_boundary) = match receipt.status {
                AdapterStatus::Succeeded => {
                    (NativeRunStatus::Completed, NativeBoundaryStatus::Succeeded)
                }
                AdapterStatus::Failed => (NativeRunStatus::Failed, NativeBoundaryStatus::Failed),
                AdapterStatus::Interrupted => (
                    NativeRunStatus::Interrupted,
                    NativeBoundaryStatus::Interrupted,
                ),
                _ => return Err("nonterminal adapter status for turn/completed".to_string()),
            };
            let correlation = receipt
                .correlation_digest
                .ok_or_else(|| "terminal receipt omitted correlation digest".to_string())?;
            {
                let mut assembly = binding
                    .output_assembly
                    .lock()
                    .map_err(|_| "output observation lock poisoned".to_string())?;
                // A summary contains only the final message. Merge by item ID;
                // never replace the complete output with that partial snapshot.
                assembly.completed_items(&completed.turn.items)?;
                output.output = assembly.render();
            }
            output.status = status;
            if output.boundary_status == NativeBoundaryStatus::Indeterminate {
                output.boundary_status = physical_boundary;
            }
            output.codex_terminal_correlation_digest = Some(correlation.to_string());
            if let Some(error) = &completed.turn.error {
                output.stop_reason = Some(error.message.chars().take(1024).collect());
            }
            output.terminal_observed = true;
            downgrade_for_owner_loss(output);
            return Ok(true);
        }
        _ => {}
    }
    Ok(false)
}

#[cfg(test)]
#[path = "native_output_tests.rs"]
mod tests;
