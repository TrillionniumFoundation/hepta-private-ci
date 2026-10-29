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

pub async fn run_tool<T: ToolPort>(
    owner: &SessionOwner,
    tools: &T,
    state: &mut TurnState,
    call: ToolCall,
    timeout: Duration,
    cancel: &CancellationToken,
) -> Result<Value> {
    owner.verify_current(&state.binding).await?;
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
        let admitted = owner.admit_tool(&state.binding, &call).await?;
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
                state.cancelled |= cancel.is_cancelled();
                owner.checkpoint(state).await?;
                let _ = tokio::time::timeout(Duration::from_secs(5), tools.cancel(&pending.intent))
                    .await;
            }
            return Ok(json!({"status":"pending_tool","cancel_requested":true}));
        }
        // A cancelled admission remains observation-only even if no start was
        // attempted before the cancellation checkpoint or process restart.
        let observe_only =
            pending.submission_attempted || pending.cancel_requested || state.cancelled;
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
                        state.last_error = Some(format!("tool output presentation unavailable: {error}"));
                        owner.checkpoint(state).await?;
                        return Ok(json!({"status":"pending_tool","error":state.last_error}));
                    }
                };
                state.context.push(json!({"type":"function_call_output","call_id":pending.call.call_id,"output":output}));
                state.completed_call_ids.push(pending.call.call_id);
                state.pending_tool = None;
                state.final_answer = Some(output.clone());
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
