//! Single-session model/tool loop with durable admission before every effect.
//!
//! This independent Responses loop does not render Core's
//! `ContextualUserFragment` objects. It checks serialized instructions, each
//! tool definition, and every input item against its frozen ContextPolicy.
//! Original user/provider message items may grow with the request budget up
//! to 64 KiB. Host instructions and system/developer messages, tool schemas,
//! calls and presented outputs retain the 8 KiB ceiling. Requests have the
//! host's context byte budget; complete history has a separate bound derived
//! from its frozen step budget. These are
//! byte bounds, not tokenizer counts. The requested output budget is at most
//! 8192 tokens under the provider's token semantics; no local tokenizer proof
//! is implied for retained original text. Source history remains append-only.
//! Older completed observations may be projected into explicitly marked
//! request-only excerpts; current inputs and the newest exchange stay intact.

use std::time::Instant;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use codex_hepta_types::Digest32;
use codex_hepta_types::ExecutionStatusV1;
use codex_hepta_types::RuntimeReceiptV1;
use serde_json::Value;
use serde_json::json;
use tokio_util::sync::CancellationToken;

use crate::Limits;
use crate::ModelEvent;
use crate::ModelPort;
use crate::NativeEvent;
use crate::NativeEventSink;
use crate::NativeTextDelta;
use crate::ObservedModelCompletion;
use crate::PendingTool;
use crate::RunOutcome;
use crate::ToolCall;
use crate::ToolObservation;
use crate::ToolPort;
use crate::TurnOwner;
use crate::TurnState;

/// Frozen provider and tool definitions used for every model call in this turn.
pub struct NativeAgent {
    pub model_name: String,
    pub instructions: String,
    pub tools: Vec<Value>,
    pub store_responses: bool,
    pub limits: Limits,
}

impl NativeAgent {
    /// Freeze this value into the existing owner's configuration binding.
    pub fn context_policy(&self) -> Result<crate::ContextPolicy> {
        crate::ContextPolicy::from_limits(&self.limits)
    }

    /// Assemble the exact bounded request without admitting or sending it.
    /// Hosted turn preparation fingerprints these same bytes before the Core
    /// history owner records its original recovery binding.
    pub fn model_request_body(&self, state: &TurnState) -> Result<Vec<u8>> {
        let policy = self.context_policy()?;
        self.validate_context(&state.context, &[])?;
        let mut request = json!({
            "model": self.model_name,
            "instructions": self.instructions,
            "input": [],
            "tools": self.tools,
            "tool_choice": "auto",
            "parallel_tool_calls": false,
            "max_output_tokens": policy.requested_output_tokens,
            "store": self.store_responses,
            "stream": true
        });
        Self::bounded_fragment_bytes(&request["instructions"], policy.host_item_bytes)?;
        for tool in &self.tools {
            Self::bounded_fragment_bytes(tool, policy.tool_item_bytes)?;
        }
        let overhead = serde_json::to_vec(&request)?.len().saturating_sub(2);
        let input_budget = self
            .limits
            .context_bytes
            .checked_sub(overhead)
            .context("assembled model request exceeds context byte budget")?;
        request["input"] = Value::Array(crate::context_projection::project(
            &state.context,
            input_budget,
        )?);
        let body = serde_json::to_vec(&request)?;
        if body.len() > self.limits.context_bytes {
            bail!("assembled model request exceeds context byte budget");
        }
        Ok(body)
    }

    fn bounded_fragment_bytes(fragment: &Value, limit: usize) -> Result<usize> {
        let bytes = serde_json::to_vec(fragment)?.len();
        if bytes > limit {
            bail!("native context item exceeds serialized byte limit");
        }
        Ok(bytes)
    }

    /// Upper bound for the append-only context retained by the durable owner.
    /// Hosts must use this separate storage budget instead of the smaller
    /// per-request context cap. Snapshot envelope/pending bytes are additional.
    pub fn retained_context_byte_limit(&self) -> Result<usize> {
        Ok(self.context_policy()?.retained_context_bytes)
    }

    fn validate_context(&self, retained: &[Value], appended: &[Value]) -> Result<()> {
        let policy = self.context_policy()?;
        let mut bytes = 2usize; // Array brackets; commas are counted below.
        for (index, item) in retained.iter().chain(appended).enumerate() {
            let item_bytes = Self::bounded_fragment_bytes(item, policy.item_bytes(item))?;
            bytes = bytes
                .checked_add(item_bytes)
                .and_then(|bytes| bytes.checked_add(usize::from(index != 0)))
                .context("native context length overflow")?;
        }
        // The complete owner history is separately bounded by the frozen turn
        // step budget. Model requests retain their tighter original byte cap.
        let history_budget = self.retained_context_byte_limit()?;
        if bytes > history_budget {
            bail!("native retained history exceeds bounded turn storage budget");
        }
        if bytes > self.limits.context_bytes {
            let combined = retained.iter().chain(appended).cloned().collect::<Vec<_>>();
            crate::context_projection::project(&combined, self.limits.context_bytes)?;
        }
        if self.limits.context_bytes == 0 {
            bail!("retained native context exceeds context byte budget");
        }
        Ok(())
    }

    pub async fn run<O: TurnOwner, T: ToolPort, M: ModelPort>(
        &self,
        owner: &O,
        tools: &T,
        model: &M,
        state: &mut TurnState,
        cancel: &CancellationToken,
    ) -> Result<RunOutcome> {
        self.run_with_events(
            owner,
            tools,
            model,
            state,
            cancel,
            &crate::events::NoopEventSink,
        )
        .await
    }

    /// Run through the same durable owner while publishing provisional text.
    /// The original pending operation survives UI delivery failure or timeout.
    pub async fn run_with_events<O: TurnOwner, T: ToolPort, M: ModelPort, E: NativeEventSink>(
        &self,
        owner: &O,
        tools: &T,
        model: &M,
        state: &mut TurnState,
        cancel: &CancellationToken,
        events: &E,
    ) -> Result<RunOutcome> {
        if self.limits.context_bytes == 0
            || self.limits.output_tokens == 0
            || self.limits.model_timeout.is_zero()
            || self.limits.tool_timeout.is_zero()
            || self.limits.observation_interval.is_zero()
        {
            bail!("native agent requires nonzero context, output and time budgets");
        }
        self.validate_context(&state.context, &[])?;
        owner.verify_current(&state.binding).await?;
        if let Some(answer) = &state.final_answer {
            return Ok(RunOutcome::Completed(answer.clone()));
        }
        // A repeated run must not turn an uncertain model POST into a new POST.
        if let Some(request) = &state.pending_model {
            let Some(response_id) = &state.provider_response_id else {
                return Ok(RunOutcome::PendingModel);
            };
            let observed = tokio::time::timeout(
                self.limits.model_timeout,
                model.reconcile(request, response_id),
            )
            .await;
            match observed {
                Ok(Ok(Some(completion))) => self.reconcile_model(owner, state, completion).await?,
                _ => return Ok(RunOutcome::PendingModel),
            }
            if let Some(answer) = &state.final_answer {
                return Ok(RunOutcome::Completed(answer.clone()));
            }
        }
        loop {
            owner.verify_current(&state.binding).await?;
            if state.pending_tool.is_some() {
                if let Some(outcome) = self.drive_tool(owner, tools, state, cancel).await? {
                    return Ok(outcome);
                }
                continue;
            }
            if state.cancelled || cancel.is_cancelled() {
                state.cancelled = true;
                owner.checkpoint(state).await?;
                return Ok(RunOutcome::Cancelled);
            }
            if !state.queued_tools.is_empty() {
                if state.tool_calls >= self.limits.tool_calls {
                    bail!("tool call budget exhausted before admission");
                }
                let call = state.queued_tools[0].clone();
                let admission = owner.admit_tool(&state.binding, &call).await?;
                let intent = admission.intent;
                intent.validate()?;
                if intent.cell.generation != state.binding.generation
                    || intent.arguments_digest != Digest32::of_bytes(&admission.arguments)
                    || intent.cell.input_digest != Digest32::of_bytes(&call.arguments)
                {
                    bail!("tool owner returned a mismatched generation or payload");
                }
                state.pending_tool = Some(PendingTool {
                    call,
                    intent,
                    arguments: admission.arguments,
                    submission_attempted: false,
                    cancel_requested: false,
                });
                state.queued_tools.remove(0);
                state.tool_calls += 1;
                owner.checkpoint(state).await?;
                continue;
            }
            if state.model_calls >= self.limits.model_calls {
                bail!("model call budget exhausted before admission");
            }
            let body = self.model_request_body(state)?;
            let request = owner
                .admit_model(&state.binding, state.model_calls, &body)
                .await?;
            if request.body != body || request.operation_id.is_empty() {
                bail!("model owner did not preserve exact request binding");
            }
            state.pending_model = Some(request);
            state.provider_response_id = None;
            state.model_calls += 1;
            owner.checkpoint(state).await?;
            let result = tokio::select! {
                // Cancellation may become ready while the owner commits the
                // admission. Do not poll a first POST before that cancellation.
                biased;
                _ = cancel.cancelled() => {
                    state.cancelled = true;
                    Err(anyhow::anyhow!("model observation cancelled; original operation pending"))
                }
                result = tokio::time::timeout(
                    self.limits.model_timeout,
                    self.collect_model(owner, model, state, events),
                ) => result.context("model turn deadline; original operation pending").and_then(|v| v)
            };
            let (items, usage) = match result {
                Ok(items) => items,
                Err(error) => {
                    state.last_error = Some(error.to_string());
                    owner.checkpoint(state).await?;
                    return Ok(RunOutcome::PendingModel);
                }
            };
            self.apply_model_completion(state, items, usage)?;
            owner.checkpoint(state).await?;
            if let Some(answer) = &state.final_answer {
                return Ok(RunOutcome::Completed(answer.clone()));
            }
        }
    }

    async fn collect_model<O: TurnOwner, M: ModelPort, E: NativeEventSink>(
        &self,
        owner: &O,
        model: &M,
        state: &mut TurnState,
        events: &E,
    ) -> Result<(Vec<Value>, Value)> {
        let request = state
            .pending_model
            .as_ref()
            .context("model admission missing")?;
        // Admission persistence may yield while the host revokes this owner.
        // Recheck at entry; the target still owns its atomic FinalUse fence.
        owner.verify_current(&state.binding).await?;
        let operation_id = request.operation_id.clone();
        let context_base = state.context.len();
        let mut stream = model.open(request).await?;
        let mut items = Vec::new();
        while let Some(event) = stream.next().await? {
            match event {
                ModelEvent::Created(id) => {
                    state.provider_response_id = Some(id);
                    owner.checkpoint(state).await?;
                }
                ModelEvent::TextDelta(delta) => {
                    let context_index = context_base
                        .checked_add(delta.output_index)
                        .context("native text delta context index overflow")?;
                    let mut remaining = delta.text.as_str();
                    while !remaining.is_empty() {
                        let mut end = remaining.len().min(crate::events::MAX_TEXT_DELTA_BYTES);
                        while !remaining.is_char_boundary(end) {
                            end -= 1;
                        }
                        owner.verify_current(&state.binding).await?;
                        events
                            .emit(
                                &state.binding,
                                NativeEvent::TextDelta(NativeTextDelta {
                                    operation_id: operation_id.clone(),
                                    response_id: delta.response_id.clone(),
                                    provider_item_id: delta.item_id.clone(),
                                    context_index,
                                    output_index: delta.output_index,
                                    content_index: delta.content_index,
                                    text: remaining[..end].to_owned(),
                                    phase: delta.phase.clone(),
                                }),
                            )
                            .await?;
                        remaining = &remaining[end..];
                    }
                }
                ModelEvent::Item(item) => items.push(item),
                ModelEvent::Completed { usage, .. } => {
                    return Ok((items, usage));
                }
            }
        }
        bail!("model ended without a terminal observation")
    }

    /// Apply independently reconciled output only to the original pending POST.
    /// The host must obtain it from the same provider response, not a model replay.
    pub async fn reconcile_model<O: TurnOwner>(
        &self,
        owner: &O,
        state: &mut TurnState,
        completion: ObservedModelCompletion,
    ) -> Result<()> {
        owner.verify_current(&state.binding).await?;
        if state
            .pending_model
            .as_ref()
            .map(|r| r.operation_id.as_str())
            != Some(completion.operation_id.as_str())
            || state.provider_response_id.as_deref() != Some(completion.response_id.as_str())
        {
            bail!("model reconciliation does not match the original operation and response");
        }
        self.apply_model_completion(state, completion.items, completion.usage)?;
        owner.checkpoint(state).await
    }

    /// Pure replay of the same model-result projection used by the live loop.
    /// The caller must independently verify its original operation and terminal
    /// evidence. This method admits nothing and cannot create such evidence.
    pub fn project_model_completion(
        &self,
        previous: &TurnState,
        items: Vec<Value>,
        usage: Value,
    ) -> Result<TurnState> {
        let mut projected = previous.clone();
        self.apply_model_completion(&mut projected, items, usage)?;
        Ok(projected)
    }

    fn apply_model_completion(
        &self,
        state: &mut TurnState,
        items: Vec<Value>,
        usage: Value,
    ) -> Result<()> {
        self.apply_model_items(state, items)?;
        state.model_usage.push(usage);
        Ok(())
    }

    /// Pure replay of the exact bounded tool-output projection. Original raw
    /// bytes and a matching original terminal receipt are still required.
    pub fn project_tool_completion(
        &self,
        previous: &TurnState,
        receipt: &RuntimeReceiptV1,
        stdout: &[u8],
        stderr: &[u8],
    ) -> Result<TurnState> {
        let mut projected = previous.clone();
        self.apply_tool_completion(&mut projected, receipt, stdout, stderr)?;
        Ok(projected)
    }

    fn apply_tool_completion(
        &self,
        state: &mut TurnState,
        receipt: &RuntimeReceiptV1,
        stdout: &[u8],
        stderr: &[u8],
    ) -> Result<()> {
        self.validate_tool_completion(state, receipt, stdout, stderr)?;
        self.apply_tool_output(
            state,
            crate::state::terminal_output_json(receipt, stdout, stderr),
        )
    }

    fn validate_tool_completion(
        &self,
        state: &TurnState,
        receipt: &RuntimeReceiptV1,
        stdout: &[u8],
        stderr: &[u8],
    ) -> Result<()> {
        let pending = state
            .pending_tool
            .as_ref()
            .context("pending tool missing")?;
        receipt.validate_against(&pending.intent)?;
        if !receipt.tool_outcome.terminal_observed
            || !matches!(
                receipt.execution.status,
                ExecutionStatusV1::Completed | ExecutionStatusV1::Failed
            )
            || receipt.tool_outcome.stdout_digest != Some(Digest32::of_bytes(stdout))
            || receipt.tool_outcome.stderr_digest != Some(Digest32::of_bytes(stderr))
        {
            bail!("tool result is not an exact terminal observation");
        }
        if stdout.len().saturating_add(stderr.len()) > self.limits.tool_output_bytes {
            bail!("tool result exceeds retained output budget");
        }
        Ok(())
    }

    fn apply_tool_output(&self, state: &mut TurnState, output: String) -> Result<()> {
        let pending = state
            .pending_tool
            .as_ref()
            .context("pending tool missing")?;
        let item = json!({ "type":"function_call_output", "call_id":pending.call.call_id, "output":output });
        // Escaping and lossy UTF-8 rendering can expand the original bytes.
        self.validate_context(&state.context, std::slice::from_ref(&item))?;
        state.completed_call_ids.push(pending.call.call_id.clone());
        state.context.push(item);
        state.pending_tool = None;
        state.last_error = None;
        Ok(())
    }

    fn apply_model_items(&self, state: &mut TurnState, items: Vec<Value>) -> Result<()> {
        // Validate the complete append before changing context, pending calls,
        // final-answer state, or usage. A later oversized item cannot partially
        // publish an earlier item from the same observed response.
        self.validate_context(&state.context, &items)?;
        let mut calls = Vec::new();
        let mut answer = String::new();
        for item in &items {
            match item["type"].as_str() {
                Some("function_call") => {
                    let call_id = item["call_id"]
                        .as_str()
                        .context("tool call identity missing")?;
                    let name = item["name"].as_str().context("tool name missing")?;
                    let args = item["arguments"]
                        .as_str()
                        .context("tool arguments missing")?;
                    let arguments = serde_json::to_vec(&serde_json::from_str::<Value>(args)?)?;
                    if call_id.is_empty()
                        || call_id.len() > 512
                        || name.is_empty()
                        || !self
                            .tools
                            .iter()
                            .any(|tool| tool["type"] == "function" && tool["name"] == name)
                        || calls.iter().any(|call: &ToolCall| call.call_id == call_id)
                        || state.completed_call_ids.iter().any(|id| id == call_id)
                    {
                        bail!("empty or reused model tool call identity");
                    }
                    calls.push(ToolCall {
                        call_id: call_id.to_owned(),
                        name: name.to_owned(),
                        arguments,
                    });
                }
                Some("message") if item["role"] == "assistant" => {
                    for content in item["content"]
                        .as_array()
                        .context("message content missing")?
                    {
                        if content["type"] == "output_text" {
                            answer.push_str(
                                content["text"].as_str().context("message text missing")?,
                            );
                        }
                    }
                }
                Some("reasoning") => {}
                _ => bail!("unsupported completed model item"),
            }
        }
        if calls.is_empty() && answer.is_empty() {
            bail!("completed model response has neither tools nor a final answer");
        }
        state.context.extend(items);
        state.queued_tools = calls;
        state.pending_model = None;
        state.last_error = None;
        if state.queued_tools.is_empty() && !state.cancelled {
            state.final_answer = Some(answer);
        }
        Ok(())
    }

    async fn drive_tool<O: TurnOwner, T: ToolPort>(
        &self,
        owner: &O,
        tools: &T,
        state: &mut TurnState,
        cancel: &CancellationToken,
    ) -> Result<Option<RunOutcome>> {
        let deadline = Instant::now() + self.limits.tool_timeout;
        loop {
            owner.verify_current(&state.binding).await?;
            let pending = state
                .pending_tool
                .as_ref()
                .context("pending tool missing")?
                .clone();
            if (state.cancelled || cancel.is_cancelled() || Instant::now() >= deadline)
                && !pending.cancel_requested
            {
                state.cancelled |= cancel.is_cancelled();
                state
                    .pending_tool
                    .as_mut()
                    .context("pending tool missing")?
                    .cancel_requested = true;
                owner.checkpoint(state).await?;
                let _ =
                    tokio::time::timeout(self.limits.tool_timeout, tools.cancel(&pending.intent))
                        .await;
                state.last_error =
                    Some("tool cancellation requested; terminal observation required".to_owned());
                owner.checkpoint(state).await?;
                return Ok(Some(RunOutcome::PendingTool));
            }
            // Cancellation is durable even if it happened before the first
            // submission. Recovery may observe that admission but never launch it.
            let observe_only =
                pending.submission_attempted || pending.cancel_requested || state.cancelled;
            // This checkpoint precedes crossing the effect boundary only for
            // a still-live admission. Observing never marks it as submitted.
            if !observe_only {
                state
                    .pending_tool
                    .as_mut()
                    .context("pending tool missing")?
                    .submission_attempted = true;
                owner.checkpoint(state).await?;
            }
            let remaining = deadline.saturating_duration_since(Instant::now());
            let observation = tokio::select! {
                // The durable checkpoint above may have observed cancellation.
                // A ready cancellation must win before the first dispatch poll.
                biased;
                _ = cancel.cancelled(), if !pending.cancel_requested => None,
                result = tokio::time::timeout(remaining, async {
                    if observe_only {
                        tools.observe(&pending.intent).await
                    } else {
                        // The submission checkpoint can outlive currentness.
                        owner.verify_current(&state.binding).await?;
                        tools.execute_or_observe(&pending.intent, &pending.arguments).await
                    }
                }) => Some(result),
            };
            let observation = match observation {
                Some(Ok(Ok(observation))) => observation,
                Some(Ok(Err(error))) => {
                    state.last_error = Some(format!("tool observation unavailable: {error}"));
                    owner.checkpoint(state).await?;
                    return Ok(Some(RunOutcome::PendingTool));
                }
                None | Some(Err(_)) => {
                    state.cancelled |= cancel.is_cancelled();
                    state
                        .pending_tool
                        .as_mut()
                        .context("pending tool missing")?
                        .cancel_requested = true;
                    owner.checkpoint(state).await?;
                    if !pending.cancel_requested {
                        let _ = tokio::time::timeout(
                            self.limits.tool_timeout,
                            tools.cancel(&pending.intent),
                        )
                        .await;
                    }
                    state.last_error = Some(
                        "tool timed out or cancelled; terminal observation required".to_owned(),
                    );
                    owner.checkpoint(state).await?;
                    return Ok(Some(RunOutcome::PendingTool));
                }
            };
            match observation {
                ToolObservation::Accepted => {
                    if pending.cancel_requested {
                        return Ok(Some(RunOutcome::PendingTool));
                    }
                    tokio::select! {
                        biased;
                        _ = cancel.cancelled() => {}
                        _ = tokio::time::sleep(self.limits.observation_interval) => {}
                    }
                }
                ToolObservation::Terminal {
                    receipt,
                    stdout,
                    stderr,
                } => {
                    // Presentation cannot turn a truncated or rebound terminal
                    // into evidence. Keep the complete raw-byte gate first.
                    self.validate_tool_completion(state, &receipt, &stdout, &stderr)?;
                    let presentation = tokio::select! {
                        biased;
                        _ = cancel.cancelled(), if !pending.cancel_requested && !state.cancelled => {
                            state.cancelled = true;
                            Err(anyhow::anyhow!("tool output presentation cancelled"))
                        }
                        result = tokio::time::timeout(
                            deadline.saturating_duration_since(Instant::now()),
                            tools.present_output(&pending.intent, &receipt, &stdout, &stderr),
                        ) => result.context("tool output presentation deadline").and_then(|value| value),
                    };
                    let output = match presentation {
                        Ok(output) => output,
                        Err(error) => {
                            state.last_error =
                                Some(format!("tool output presentation unavailable: {error}"));
                            owner.checkpoint(state).await?;
                            return Ok(Some(RunOutcome::PendingTool));
                        }
                    };
                    self.apply_tool_output(state, output)?;
                    owner.checkpoint(state).await?;
                    return Ok(None);
                }
            }
        }
    }
}
