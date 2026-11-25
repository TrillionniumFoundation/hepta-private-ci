//! Bounded text observations for the original, exactly bound App Server turn.
//!
//! Item completion is a full snapshot, not another delta. The buffer lives only
//! for this observation attempt; it creates no authority or persistent journal.

use codex_app_server_client::AppServerEvent;
use codex_app_server_client::RemoteAppServerObservedEvent;
use codex_app_server_protocol::ServerNotification;
use codex_app_server_protocol::ThreadItem;
use codex_app_server_protocol::TurnItemsView;
use codex_hepta_codex_adapter::AdapterStatus;
use codex_hepta_codex_adapter::adapt_observed_event;
use codex_hepta_types::StableId;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

use super::CodexTurnBinding;
use super::LOCAL_CANCELLED;
use super::LOCAL_DEADLINE_ELAPSED;
use super::MAX_OUTPUT_BYTES;
use super::NativeBoundaryStatus;
use super::NativeOwnerAuthority;
use super::NativeRunOutput;
use super::NativeRunStatus;
use super::classify_observation_failure;
use super::downgrade_for_owner_loss;

// Empty messages must not permit unbounded retained item identities. StableId
// independently retains the existing 128-byte identity bound.
const MAX_OUTPUT_ITEMS: usize = 128;

pub(super) struct NativeTurnObservation {
    binding: CodexTurnBinding,
    messages: MessageBuffer,
}

impl NativeTurnObservation {
    pub(super) fn new(binding: CodexTurnBinding) -> Self {
        Self {
            binding,
            messages: MessageBuffer::default(),
        }
    }

    /// Linearize a selected notification against the original local stop gates.
    /// Cancellation read before reduction wins over an already selected event;
    /// a terminal accepted before a later cancellation remains a provider fact.
    pub(super) fn observe_selected_event(
        &mut self,
        output: &mut NativeRunOutput,
        observed: &RemoteAppServerObservedEvent,
        deadline: Instant,
        cancellation: &CancellationToken,
    ) -> Result<bool, String> {
        if output.terminal_observed {
            return Ok(false);
        }
        let reason = if cancellation.is_cancelled() {
            Some(LOCAL_CANCELLED)
        } else if Instant::now() >= deadline {
            Some(LOCAL_DEADLINE_ELAPSED)
        } else {
            None
        };
        if let Some(reason) = reason {
            if output.boundary_status == NativeBoundaryStatus::Indeterminate {
                output.boundary_status = classify_observation_failure(reason);
            }
            if output.stop_reason.is_none() {
                output.stop_reason = Some(reason.to_string());
            }
            // Freeze text before reducing. An authenticated usage/terminal
            // event still records physical facts; invalid witnesses still fail.
            self.observe_event(output, observed)?;
            return Err(reason.to_string());
        }
        self.observe_event(output, observed)
    }

    pub(super) fn observe_event(
        &mut self,
        output: &mut NativeRunOutput,
        observed: &RemoteAppServerObservedEvent,
    ) -> Result<bool, String> {
        if output.thread_id != self.binding.intent.thread_id.as_str()
            || output.turn_id != self.binding.turn_id.as_str()
        {
            return Err("output observation binding mismatch".to_string());
        }
        if output.terminal_observed {
            return Ok(false);
        }
        let AppServerEvent::ServerNotification(notification) = observed.event() else {
            return Ok(false);
        };
        let accept_text = output.boundary_status == NativeBoundaryStatus::Indeterminate
            && !matches!(output.owner_authority, NativeOwnerAuthority::Lost { .. });
        match notification.as_ref() {
            ServerNotification::AgentMessageDelta(delta)
                if delta.thread_id == output.thread_id && delta.turn_id == output.turn_id =>
            {
                self.validate_transport(observed)?;
                if accept_text {
                    self.messages
                        .update(&delta.item_id, TextUpdate::Delta(&delta.delta))?;
                    output.output = self.messages.render();
                }
            }
            ServerNotification::ItemStarted(started)
                if started.thread_id == output.thread_id && started.turn_id == output.turn_id =>
            {
                self.validate_transport(observed)?;
                if accept_text && let ThreadItem::AgentMessage { id, .. } = &started.item {
                    // A start establishes item order; its provisional text is
                    // supplied by subsequent deltas or the completed snapshot.
                    self.messages.update(id, TextUpdate::Started)?;
                }
            }
            ServerNotification::ItemCompleted(completed)
                if completed.thread_id == output.thread_id
                    && completed.turn_id == output.turn_id =>
            {
                self.validate_transport(observed)?;
                if accept_text && let ThreadItem::AgentMessage { id, text, .. } = &completed.item {
                    self.messages.update(id, TextUpdate::Completed(text))?;
                    output.output = self.messages.render();
                }
            }
            ServerNotification::ThreadTokenUsageUpdated(usage)
                if usage.thread_id == output.thread_id && usage.turn_id == output.turn_id =>
            {
                self.validate_transport(observed)?;
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
                if completed.thread_id == output.thread_id
                    && completed.turn.id == output.turn_id =>
            {
                let receipt =
                    adapt_observed_event(&self.binding.intent, &self.binding.turn_id, observed)
                        .map_err(|error| format!("invalid App Server terminal witness: {error}"))?
                        .ok_or_else(|| {
                            "turn/completed did not produce terminal receipt".to_string()
                        })?;
                if accept_text {
                    self.messages
                        .reconcile(&completed.turn.items, completed.turn.items_view)?;
                    output.output = self.messages.render();
                }
                let physical_boundary = match receipt.status {
                    AdapterStatus::Succeeded => {
                        output.status = NativeRunStatus::Completed;
                        NativeBoundaryStatus::Succeeded
                    }
                    AdapterStatus::Failed => {
                        output.status = NativeRunStatus::Failed;
                        NativeBoundaryStatus::Failed
                    }
                    AdapterStatus::Interrupted => {
                        output.status = NativeRunStatus::Interrupted;
                        NativeBoundaryStatus::Interrupted
                    }
                    _ => return Err("nonterminal adapter status for turn/completed".to_string()),
                };
                if output.boundary_status == NativeBoundaryStatus::Indeterminate {
                    output.boundary_status = physical_boundary;
                }
                output.codex_terminal_correlation_digest = Some(
                    receipt
                        .correlation_digest
                        .ok_or_else(|| "terminal receipt omitted correlation digest".to_string())?
                        .to_string(),
                );
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

    fn validate_transport(&self, observed: &RemoteAppServerObservedEvent) -> Result<(), String> {
        adapt_observed_event(&self.binding.intent, &self.binding.turn_id, observed)
            .map(|_| ())
            .map_err(|error| format!("invalid App Server observation witness: {error}"))
    }
}

#[derive(Clone, Default)]
struct MessageBuffer {
    // First item/start, delta, or completion establishes order. A nonempty
    // terminal Full view supplies canonical order; Summary never replaces it.
    messages: Vec<Message>,
    bytes: usize,
}

#[derive(Clone)]
struct Message {
    id: StableId,
    text: String,
    completed: bool,
}

#[derive(Clone, Copy)]
enum TextUpdate<'a> {
    Started,
    Delta(&'a str),
    Completed(&'a str),
}

impl MessageBuffer {
    fn update(&mut self, id: &str, update: TextUpdate<'_>) -> Result<(), String> {
        let id = StableId::new(id.to_string())
            .map_err(|_| "invalid provider output item identity".to_string())?;
        let index = self.messages.iter().position(|message| message.id == id);
        if index.is_none() && self.messages.len() >= MAX_OUTPUT_ITEMS {
            return Err("output item limit exceeded".to_string());
        }
        let old = index.map(|index| &self.messages[index]);
        let old_text = old.map_or("", |message| message.text.as_str());
        let new_len = match update {
            TextUpdate::Started => old_text.len(),
            TextUpdate::Delta(text) => {
                if old.is_some_and(|message| message.completed) {
                    return Err("provider delta followed completed output item".to_string());
                }
                old_text
                    .len()
                    .checked_add(text.len())
                    .ok_or_else(|| "output byte limit exceeded".to_string())?
            }
            TextUpdate::Completed(text) => {
                if !text.starts_with(old_text)
                    || old.is_some_and(|message| message.completed && message.text != text)
                {
                    return Err(
                        "provider output item completion conflicts with observed text".to_string(),
                    );
                }
                text.len()
            }
        };
        let bytes = self.bytes - old_text.len();
        if new_len > MAX_OUTPUT_BYTES.saturating_sub(bytes) {
            return Err("output byte limit exceeded".to_string());
        }
        let index = index.unwrap_or_else(|| {
            self.messages.push(Message {
                id,
                text: String::new(),
                completed: false,
            });
            self.messages.len() - 1
        });
        let message = &mut self.messages[index];
        match update {
            TextUpdate::Started => {}
            TextUpdate::Delta(text) => message.text.push_str(text),
            TextUpdate::Completed(text) => {
                message.text = text.to_string();
                message.completed = true;
            }
        }
        self.bytes = bytes + new_len;
        Ok(())
    }

    fn reconcile(&mut self, items: &[ThreadItem], view: TurnItemsView) -> Result<(), String> {
        // Older valid terminal notifications omit items. They add no text
        // observation and must not erase text already observed for this turn.
        if items.is_empty() {
            return Ok(());
        }
        if view == TurnItemsView::NotLoaded {
            return Err("unloaded terminal view contained output items".to_string());
        }
        let mut checked = self.clone();
        let mut ordered = Self::default();
        for item in items {
            if let ThreadItem::AgentMessage { id, text, .. } = item {
                if ordered
                    .messages
                    .iter()
                    .any(|message| message.id.as_str() == id)
                {
                    return Err("duplicate terminal output item identity".to_string());
                }
                checked.update(id, TextUpdate::Completed(text))?;
                ordered.update(id, TextUpdate::Completed(text))?;
            }
        }
        if view == TurnItemsView::Full {
            if self.messages.iter().any(|message| {
                message.completed
                    && !ordered
                        .messages
                        .iter()
                        .any(|candidate| candidate.id == message.id)
            }) {
                return Err("full terminal view omitted completed output item".to_string());
            }
            *self = ordered;
        } else {
            *self = checked;
        }
        Ok(())
    }

    fn render(&self) -> String {
        let mut text = String::with_capacity(self.bytes);
        for message in &self.messages {
            text.push_str(&message.text);
        }
        text
    }
}
