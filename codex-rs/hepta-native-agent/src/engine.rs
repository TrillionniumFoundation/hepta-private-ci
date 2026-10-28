//! Single-session model/tool loop with durable admission before every effect.

use std::time::Instant;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use codex_hepta_types::Digest32;
use codex_hepta_types::ExecutionStatusV1;
use serde_json::Value;
use serde_json::json;
use tokio_util::sync::CancellationToken;

use crate::Limits;
use crate::ModelEvent;
use crate::ObservedModelCompletion;
use crate::PendingTool;
use crate::ResponsesModel;
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
    pub async fn run<O: TurnOwner, T: ToolPort>(
        &self,
        owner: &O,
        tools: &T,
        model: &ResponsesModel,
        state: &mut TurnState,
        cancel: &CancellationToken,
    ) -> Result<RunOutcome> {
        if self.limits.context_bytes == 0
            || self.limits.output_tokens == 0
            || self.limits.model_timeout.is_zero()
            || self.limits.tool_timeout.is_zero()
            || self.limits.observation_interval.is_zero()
        {
            bail!("native agent requires nonzero context, output and time budgets");
        }
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
            let body = serde_json::to_vec(&json!({
                "model": self.model_name,
                "instructions": self.instructions,
                "input": state.context,
                "tools": self.tools,
                "tool_choice": "auto",
                "parallel_tool_calls": false,
                "max_output_tokens": self.limits.output_tokens,
                "store": self.store_responses,
                "stream": true
            }))?;
            if body.len() > self.limits.context_bytes {
                bail!("assembled model request exceeds context byte budget");
            }
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
                    self.collect_model(owner, model, state),
                ) => result.context("model turn deadline; original operation pending").and_then(|v| v)
            };
            let items = match result {
                Ok(items) => items,
                Err(error) => {
                    state.last_error = Some(error.to_string());
                    owner.checkpoint(state).await?;
                    return Ok(RunOutcome::PendingModel);
                }
            };
            self.apply_model_items(state, items)?;
            owner.checkpoint(state).await?;
            if let Some(answer) = &state.final_answer {
                return Ok(RunOutcome::Completed(answer.clone()));
            }
        }
    }

    async fn collect_model<O: TurnOwner>(
        &self,
        owner: &O,
        model: &ResponsesModel,
        state: &mut TurnState,
    ) -> Result<Vec<Value>> {
        let request = state
            .pending_model
            .as_ref()
            .context("model admission missing")?;
        // Admission persistence may yield while the host revokes this owner.
        // Recheck at entry; the target still owns its atomic FinalUse fence.
        owner.verify_current(&state.binding).await?;
        let mut stream = model.open(request).await?;
        let mut items = Vec::new();
        while let Some(event) = stream.next().await? {
            match event {
                ModelEvent::Created(id) => {
                    state.provider_response_id = Some(id);
                    owner.checkpoint(state).await?;
                }
                ModelEvent::TextDelta(_) => {}
                ModelEvent::Item(item) => items.push(item),
                ModelEvent::Completed { usage, .. } => {
                    state.model_usage.push(usage);
                    return Ok(items);
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
        self.apply_model_items(state, completion.items)?;
        state.model_usage.push(completion.usage);
        owner.checkpoint(state).await
    }

    fn apply_model_items(&self, state: &mut TurnState, items: Vec<Value>) -> Result<()> {
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
        if serde_json::to_vec(&items)?.len() > self.limits.context_bytes {
            bail!("model output exceeds retained context budget");
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
                    receipt.validate_against(&pending.intent)?;
                    if !receipt.tool_outcome.terminal_observed
                        || !matches!(
                            receipt.execution.status,
                            ExecutionStatusV1::Completed | ExecutionStatusV1::Failed
                        )
                        || receipt.tool_outcome.stdout_digest != Some(Digest32::of_bytes(&stdout))
                        || receipt.tool_outcome.stderr_digest != Some(Digest32::of_bytes(&stderr))
                    {
                        bail!("tool result is not an exact terminal observation");
                    }
                    if stdout.len().saturating_add(stderr.len()) > self.limits.tool_output_bytes {
                        bail!("tool result exceeds retained output budget");
                    }
                    let output = json!({
                        "exit_code": receipt.tool_outcome.exit_code,
                        "stdout": String::from_utf8_lossy(&stdout),
                        "stderr": String::from_utf8_lossy(&stderr)
                    })
                    .to_string();
                    state.context.push(json!({
                        "type":"function_call_output",
                        "call_id":pending.call.call_id,
                        "output":output
                    }));
                    state.completed_call_ids.push(pending.call.call_id);
                    state.pending_tool = None;
                    state.last_error = None;
                    owner.checkpoint(state).await?;
                    return Ok(None);
                }
            }
        }
    }
}
