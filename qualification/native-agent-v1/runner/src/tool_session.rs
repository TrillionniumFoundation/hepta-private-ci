//! The same bounded runtime tool path used by the external Codex tool bridge.
use crate::owner::SessionOwner;
use anyhow::Context;
use anyhow::Result;
use codex_hepta_native_agent::PendingTool;
use codex_hepta_native_agent::ToolCall;
use codex_hepta_native_agent::ToolObservation;
use codex_hepta_native_agent::ToolPort;
use codex_hepta_native_agent::TurnOwner;
use codex_hepta_native_agent::TurnState;
use codex_hepta_types::Digest32;
use codex_hepta_types::ExecutionStatusV1;
use serde_json::Value;
use serde_json::json;
use std::time::Duration;
use tokio_util::sync::CancellationToken;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ToolSessionPolicy {
    /// The original fixture API, retained for existing callers/tests.
    LegacySingleOperation,
    /// One fresh, explicitly versioned backend owner for an entire Codex turn.
    SharedTurn { max_calls: usize },
    /// An old per-call owner may only observe its already recorded operation.
    ObserveOriginal,
}

pub async fn run_tool<T: ToolPort>(
    owner: &SessionOwner,
    tools: &T,
    state: &mut TurnState,
    call: ToolCall,
    timeout: Duration,
    cancel: &CancellationToken,
) -> Result<Value> {
    run_tool_with_policy(
        owner,
        tools,
        state,
        call,
        timeout,
        cancel,
        ToolSessionPolicy::LegacySingleOperation,
    )
    .await
}

pub async fn run_tool_with_policy<T: ToolPort>(
    owner: &SessionOwner,
    tools: &T,
    state: &mut TurnState,
    call: ToolCall,
    timeout: Duration,
    cancel: &CancellationToken,
    policy: ToolSessionPolicy,
) -> Result<Value> {
    owner.verify_current(&state.binding).await?;
    if state.pending_model.is_some() || !state.queued_tools.is_empty() {
        anyhow::bail!("external tool owner cannot replace a model-loop continuation");
    }
    // Cancellation belongs to the original turn, including when it arrives
    // before any tool admission. Persist that stop before returning: a fresh
    // token after reopening this owner must not make another call admissible.
    if cancel.is_cancelled() && !state.cancelled {
        state.cancelled = true;
        owner.checkpoint(state).await?;
    }
    if state.completed_call_ids.contains(&call.call_id) {
        owner.load_call(&call)?;
        let output = state
            .context
            .iter()
            .find(|item| item["type"] == "function_call_output" && item["call_id"] == call.call_id)
            .and_then(|item| item["output"].as_str())
            .context("completed tool output is unavailable")?;
        return Ok(json!({"status":"completed","output":output,"reused":true}));
    }
    if let Some(pending) = &state.pending_tool {
        if pending.call != call {
            anyhow::bail!("a different tool is still pending");
        }
    } else {
        if policy == ToolSessionPolicy::ObserveOriginal {
            anyhow::bail!(
                "legacy per-call session permits only its original pending/completed operation"
            );
        }
        if state.cancelled || cancel.is_cancelled() {
            // Cancellation may arrive after the earlier check. Any branch
            // that observes it must preserve that fact before refusing work.
            if !state.cancelled {
                state.cancelled = true;
                owner.checkpoint(state).await?;
            }
            anyhow::bail!("cancelled turn cannot admit another tool");
        }
        if let ToolSessionPolicy::SharedTurn { max_calls } = policy {
            if max_calls == 0 || state.tool_calls >= max_calls {
                anyhow::bail!("shared turn tool budget exhausted");
            }
        }
        let admitted = owner.admit_tool(&state.binding, &call).await?;
        if matches!(policy, ToolSessionPolicy::SharedTurn { .. }) {
            state
                .context
                .push(json!({"type":"function_call", "call_id":call.call_id,
                "name":call.name, "arguments":String::from_utf8(call.arguments.clone())?}));
            state.final_answer = None;
        }
        state.pending_tool = Some(PendingTool {
            call,
            intent: admitted.intent,
            arguments: admitted.arguments,
            submission_attempted: false,
            cancel_requested: false,
        });
        state.tool_calls += 1;
        owner.checkpoint(state).await?;
    }
    let deadline = tokio::time::Instant::now() + timeout;
    loop {
        owner.verify_current(&state.binding).await?;
        let pending = state
            .pending_tool
            .as_ref()
            .context("pending tool missing")?
            .clone();
        if cancel.is_cancelled()
            || tokio::time::Instant::now() >= deadline
            || (state.cancelled && !pending.cancel_requested)
        {
            if !pending.cancel_requested {
                state
                    .pending_tool
                    .as_mut()
                    .context("pending tool missing")?
                    .cancel_requested = true;
                // The measured shared turn is finished after either an
                // explicit cancellation or its tool deadline. Reconciling
                // this same operation later must not reopen fresh admission.
                state.cancelled |=
                    cancel.is_cancelled() || matches!(policy, ToolSessionPolicy::SharedTurn { .. });
                owner.checkpoint(state).await?;
                let _ = tokio::time::timeout(Duration::from_secs(5), tools.cancel(&pending.intent))
                    .await;
            }
            return Ok(json!({"status":"pending_tool","cancel_requested":true}));
        }
        // A cancelled admission remains observation-only even if no start was
        // attempted before the cancellation checkpoint or process restart.
        let observe_only = policy == ToolSessionPolicy::ObserveOriginal
            || pending.submission_attempted
            || pending.cancel_requested
            || state.cancelled;
        if !observe_only {
            state
                .pending_tool
                .as_mut()
                .context("pending tool missing")?
                .submission_attempted = true;
            owner.checkpoint(state).await?;
        }
        let observed = tokio::select! {
            // Prefer an already requested cancellation before polling a first
            // submission. If a call is in flight, dropping local observation
            // leaves submission_attempted durable and never authorizes replay.
            biased;
            _ = cancel.cancelled() => continue,
            observed = tokio::time::timeout_at(deadline, async {
                if observe_only { tools.observe(&pending.intent).await }
                else { tools.execute_or_observe(&pending.intent, &pending.arguments).await }
            }) => observed,
        };
        match observed {
            Ok(Ok(ToolObservation::Terminal {
                receipt,
                stdout,
                stderr,
            })) => {
                receipt.validate_against(&pending.intent)?;
                if !receipt.tool_outcome.terminal_observed
                    || !matches!(
                        receipt.execution.status,
                        ExecutionStatusV1::Completed | ExecutionStatusV1::Failed
                    )
                    || receipt.tool_outcome.stdout_digest != Some(Digest32::of_bytes(&stdout))
                    || receipt.tool_outcome.stderr_digest != Some(Digest32::of_bytes(&stderr))
                {
                    anyhow::bail!("tool output is not an exact terminal observation");
                }
                let presentation = tokio::select! {
                    biased;
                    _ = cancel.cancelled(), if !pending.cancel_requested && !state.cancelled => {
                        state.cancelled = true;
                        Err(anyhow::anyhow!("tool output presentation cancelled"))
                    }
                    result = tokio::time::timeout_at(deadline,
                        tools.present_output(&pending.intent, &receipt, &stdout, &stderr)) =>
                        result.context("tool output presentation deadline").and_then(|value| value),
                };
                let output = match presentation {
                    Ok(output) => output,
                    Err(error) => {
                        // Output presentation can itself await the original
                        // runtime. Its deadline closes the same shared turn
                        // even though the original effect is already terminal.
                        state.cancelled |= cancel.is_cancelled()
                            || (matches!(policy, ToolSessionPolicy::SharedTurn { .. })
                                && tokio::time::Instant::now() >= deadline);
                        state.last_error =
                            Some(format!("tool output presentation unavailable: {error}"));
                        owner.checkpoint(state).await?;
                        return Ok(json!({"status":"pending_tool","error":state.last_error}));
                    }
                };
                state.context.push(json!({"type":"function_call_output","call_id":pending.call.call_id,"output":output}));
                state.completed_call_ids.push(pending.call.call_id);
                state.pending_tool = None;
                // A completed tool is not completion of the surrounding
                // Codex turn. Its original receipt/output remain in this
                // owner's history while the next distinct call is admitted.
                if policy == ToolSessionPolicy::LegacySingleOperation {
                    state.final_answer = Some(output.clone());
                }
                owner.checkpoint(state).await?;
                return Ok(json!({"status":"completed","output":output,"reused":false,
                    "runtime_intent_digest":receipt.runtime_intent_digest.to_string()}));
            }
            Ok(Ok(ToolObservation::Accepted)) => {
                if pending.cancel_requested || state.cancelled {
                    return Ok(json!({"status":"pending_tool","cancel_requested":true}));
                }
                tokio::select! { _ = cancel.cancelled() => {}, _ = tokio::time::sleep(Duration::from_millis(20)) => {} }
            }
            Ok(Err(error)) => {
                state.last_error = Some(error.to_string());
                owner.checkpoint(state).await?;
                return Ok(json!({"status":"pending_tool","error":state.last_error}));
            }
            Err(_) => continue,
        }
    }
}

#[cfg(test)]
#[path = "shared_turn_tests.rs"]
mod shared_turn_tests;
