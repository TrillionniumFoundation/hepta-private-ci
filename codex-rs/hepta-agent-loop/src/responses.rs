//! Projection of the existing Responses API parser into the native loop.
//!
//! The inference owner must claim a single physical send before supplying the
//! stream. This adapter neither dispatches nor retries a model request. It only
//! accepts the bounded text/function-tool profile and retains every complete
//! provider item before publishing terminal completion.

use std::future::Future;

use codex_api::ApiError;
use codex_api::ResponseEvent;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use codex_protocol::models::ContentItem;
use codex_protocol::models::ResponseItem;
use codex_protocol::protocol::TokenUsage;
use futures::Stream;
use futures::StreamExt;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

use crate::Error;
use crate::ModelEvent;
use crate::ModelRequest;
use crate::Result;
use crate::ToolCall;
use crate::TurnBinding;
use crate::Usage;

/// Passed intact to the existing inference/context owner. In particular,
/// reasoning, message phases and encrypted content may not be reconstructed
/// from the visible text/tool projection.
pub struct ResponsesContinuation {
    pub provider_response_id: String,
    pub server_model: Option<String>,
    pub items: Vec<ResponseItem>,
    pub usage: TokenUsage,
    /// TokenUsage intentionally skips this field during serialization.
    pub provider_rollout_budget_units: Option<serde_json::Number>,
    pub end_turn: Option<bool>,
}

pub trait ResponsesContinuationOwner: Send {
    /// Atomically retain the full continuation under this exact admitted
    /// binding/request. An identical retry is idempotent; changed data conflicts.
    fn retain(
        &mut self,
        binding: &TurnBinding,
        request: &ModelRequest,
        continuation: ResponsesContinuation,
    ) -> impl Future<Output = Result<Digest32>> + Send;
}

#[derive(Clone, Copy, Debug)]
pub struct ResponsesBridgeLimits {
    pub maximum_items: usize,
    pub maximum_retained_bytes: usize,
    pub maximum_visible_bytes: usize,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ResponsesBridgeStatus {
    Completed,
    /// No provider terminal event was observed. The owner remains unresolved.
    Incomplete,
    /// Local stream consumption stopped; this is not provider cancellation ACK.
    LocalCancellation,
}

pub async fn forward_responses_stream<S, O>(
    binding: &TurnBinding,
    request: &ModelRequest,
    mut stream: S,
    owner: &mut O,
    events: mpsc::Sender<Result<ModelEvent>>,
    limits: ResponsesBridgeLimits,
    cancellation: &CancellationToken,
) -> Result<ResponsesBridgeStatus>
where
    S: Stream<Item = std::result::Result<ResponseEvent, ApiError>> + Unpin + Send,
    O: ResponsesContinuationOwner,
{
    let mut items = Vec::new();
    let mut retained_bytes = 0usize;
    let mut visible = String::new();
    let mut canonical_visible = String::new();
    let mut call_ids = std::collections::BTreeSet::new();
    let mut pending_items = std::collections::BTreeSet::new();
    let mut completed_items = std::collections::BTreeSet::new();
    let mut reasoning_started = false;
    let mut reasoning_completed = false;
    let mut server_model = None;
    loop {
        let event = tokio::select! {
            biased;
            _ = cancellation.cancelled() => return Ok(ResponsesBridgeStatus::LocalCancellation),
            event = stream.next() => event,
        };
        let Some(event) = event else {
            return Ok(ResponsesBridgeStatus::Incomplete);
        };
        match event.map_err(|_| Error::Owner("Responses stream failed".into()))? {
            ResponseEvent::OutputTextDelta(delta) => {
                checked_extend(&mut visible, &delta, limits.maximum_visible_bytes)?;
                send(&events, ModelEvent::TextDelta(delta), cancellation).await?;
            }
            ResponseEvent::OutputItemDone(item) => {
                if items.len() >= limits.maximum_items {
                    return Err(Error::Limit("retained provider items"));
                }
                let encoded = serde_json::to_vec(&crate::response_item_evidence(&item)?)
                    .map_err(|_| Error::Contract("provider item serialization"))?;
                retained_bytes = retained_bytes
                    .checked_add(encoded.len())
                    .ok_or(Error::Limit("retained provider bytes"))?;
                if retained_bytes > limits.maximum_retained_bytes {
                    return Err(Error::Limit("retained provider bytes"));
                }
                if let Some(id) = item_id(&item)? {
                    if !completed_items.insert(id.clone()) {
                        return Err(Error::Contract("duplicate completed provider item"));
                    }
                    pending_items.remove(&id);
                }
                match &item {
                    ResponseItem::Message { role, content, .. } if role == "assistant" => {
                        for part in content {
                            let ContentItem::OutputText { text } = part else {
                                return Err(Error::Contract("non-text provider output"));
                            };
                            checked_extend(
                                &mut canonical_visible,
                                text,
                                limits.maximum_visible_bytes,
                            )?;
                        }
                    }
                    ResponseItem::FunctionCall {
                        name,
                        namespace,
                        arguments,
                        encrypted_function_args,
                        call_id,
                        ..
                    } => {
                        if namespace.is_some() || encrypted_function_args.is_some() {
                            return Err(Error::Contract("unsupported function-call projection"));
                        }
                        let call_id = StableId::new(call_id)
                            .map_err(|_| Error::Contract("invalid provider call ID"))?;
                        if !call_ids.insert(call_id.clone()) {
                            return Err(Error::Contract("duplicate provider call ID"));
                        }
                        let name = StableId::new(name)
                            .map_err(|_| Error::Contract("invalid provider tool name"))?;
                        send(
                            &events,
                            ModelEvent::ToolCall(ToolCall {
                                call_id,
                                name,
                                arguments: arguments.clone(),
                            }),
                            cancellation,
                        )
                        .await?;
                    }
                    ResponseItem::Reasoning { .. } => reasoning_completed = true,
                    ResponseItem::Compaction { .. } => {}
                    _ => return Err(Error::Contract("unsupported provider output item")),
                }
                items.push(item);
            }
            ResponseEvent::ServerModel(model) => {
                if model.len() > 256 || model.is_empty() {
                    return Err(Error::Contract("invalid provider model identity"));
                }
                if server_model
                    .as_ref()
                    .is_some_and(|previous| previous != &model)
                {
                    return Err(Error::Contract("provider model identity changed"));
                }
                server_model = Some(model);
            }
            ResponseEvent::Completed {
                response_id,
                token_usage,
                end_turn,
            } => {
                if !pending_items.is_empty() || (reasoning_started && !reasoning_completed) {
                    return Err(Error::Contract("provider completion has unfinished items"));
                }
                if response_id.is_empty() || response_id.len() > 256 {
                    return Err(Error::Contract("invalid provider response ID"));
                }
                if end_turn == Some(false) && call_ids.is_empty() {
                    return Err(Error::Contract("provider did not end its turn"));
                }
                if visible.is_empty() && !canonical_visible.is_empty() {
                    send(
                        &events,
                        ModelEvent::TextDelta(canonical_visible.clone()),
                        cancellation,
                    )
                    .await?;
                    visible.clone_from(&canonical_visible);
                }
                if visible != canonical_visible {
                    return Err(Error::Contract("provider text projection mismatch"));
                }
                let token_usage = token_usage.ok_or(Error::Contract("provider usage absent"))?;
                let usage = usage(&token_usage)?;
                let continuation = ResponsesContinuation {
                    provider_response_id: response_id,
                    server_model,
                    items,
                    provider_rollout_budget_units: token_usage.codex_rollout_budget_units.clone(),
                    usage: token_usage,
                    end_turn,
                };
                let receipt = owner.retain(binding, request, continuation).await?;
                if receipt.is_zero() {
                    return Err(Error::Contract("provider continuation was not retained"));
                }
                send(
                    &events,
                    ModelEvent::Completed {
                        request_id: request.request_id.clone(),
                        continuation_digest: receipt,
                        usage,
                    },
                    cancellation,
                )
                .await?;
                return Ok(ResponsesBridgeStatus::Completed);
            }
            ResponseEvent::OutputItemAdded(item) => {
                let id = item_id(&item)?
                    .ok_or(Error::Contract("partial provider item lacks identity"))?;
                pending_item(
                    id,
                    &mut pending_items,
                    &completed_items,
                    limits.maximum_items,
                )?;
            }
            // Partial tool deltas are never executable, but their identity must
            // be completed before the response can be retained as terminal.
            ResponseEvent::ToolCallInputDelta { item_id, .. } => {
                pending_item(
                    item_id,
                    &mut pending_items,
                    &completed_items,
                    limits.maximum_items,
                )?;
            }
            ResponseEvent::ReasoningSummaryDone { item_id, .. } => {
                reasoning_started = true;
                if !completed_items.contains(&item_id) {
                    pending_item(
                        item_id,
                        &mut pending_items,
                        &completed_items,
                        limits.maximum_items,
                    )?;
                }
            }
            ResponseEvent::ReasoningSummaryDelta { .. }
            | ResponseEvent::ReasoningContentDelta { .. }
            | ResponseEvent::ReasoningSummaryPartAdded { .. } => reasoning_started = true,
            ResponseEvent::Created
            | ResponseEvent::SafetyBuffering(_)
            | ResponseEvent::ModelVerifications(_)
            | ResponseEvent::TurnModerationMetadata(_)
            | ResponseEvent::ServerReasoningIncluded(_)
            | ResponseEvent::RateLimits(_)
            | ResponseEvent::ModelsEtag(_) => {}
        }
    }
}

fn item_id(item: &ResponseItem) -> Result<Option<String>> {
    let value = serde_json::to_value(item)
        .map_err(|_| Error::Contract("provider item identity serialization"))?;
    let Some(id) = value.get("id").and_then(serde_json::Value::as_str) else {
        return Ok(None);
    };
    if id.is_empty() || id.len() > 256 {
        return Err(Error::Contract("invalid provider item ID"));
    }
    Ok(Some(id.to_string()))
}

fn pending_item(
    id: String,
    pending: &mut std::collections::BTreeSet<String>,
    completed: &std::collections::BTreeSet<String>,
    maximum: usize,
) -> Result<()> {
    if id.is_empty() || id.len() > 256 || completed.contains(&id) {
        return Err(Error::Contract("invalid partial provider item identity"));
    }
    pending.insert(id);
    if pending.len().saturating_add(completed.len()) > maximum {
        return Err(Error::Limit("partial provider items"));
    }
    Ok(())
}

fn checked_extend(target: &mut String, value: &str, maximum: usize) -> Result<()> {
    if target
        .len()
        .checked_add(value.len())
        .is_none_or(|size| size > maximum)
    {
        return Err(Error::Limit("provider visible bytes"));
    }
    target.push_str(value);
    Ok(())
}

fn usage(value: &TokenUsage) -> Result<Usage> {
    let input_tokens = u64::try_from(value.input_tokens)
        .map_err(|_| Error::Contract("negative provider input usage"))?;
    let output_tokens = u64::try_from(value.output_tokens)
        .map_err(|_| Error::Contract("negative provider output usage"))?;
    if value.cached_input_tokens < 0
        || value.cached_input_tokens > value.input_tokens
        || value.cache_write_input_tokens < 0
        || value.reasoning_output_tokens < 0
        || value.reasoning_output_tokens > value.output_tokens
        || value.total_tokens < 0
        || u64::try_from(value.total_tokens).ok() != input_tokens.checked_add(output_tokens)
    {
        return Err(Error::Contract("inconsistent provider token usage"));
    }
    Ok(Usage {
        input_tokens,
        output_tokens,
    })
}

async fn send(
    events: &mpsc::Sender<Result<ModelEvent>>,
    event: ModelEvent,
    cancellation: &CancellationToken,
) -> Result<()> {
    tokio::select! {
        biased;
        _ = cancellation.cancelled() => Err(Error::Owner("local stream consumer cancelled".into())),
        result = events.send(Ok(event)) => result.map_err(|_| Error::Owner("stream consumer closed".into())),
    }
}
