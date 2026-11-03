//! Authority-free native state carried by the existing ThreadStore checkpoint.
//!
//! The core recovery boundary is preserved, never recomputed from raw rollout
//! lines. `native_context_sha256` describes this codec's context only.

use std::collections::HashSet;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_native_agent::ModelRequest;
use codex_hepta_native_agent::PendingTool;
use codex_hepta_native_agent::ToolCall;
use codex_hepta_native_agent::TurnBinding;
use codex_hepta_native_agent::TurnState;
use codex_hepta_types::CellExecutionIntentV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::ExecutionIntentKindV1;
use codex_hepta_types::FinalPayloadDigestV1;
use codex_hepta_types::Generation;
use codex_hepta_types::RuntimeToolIntentV1;
use codex_hepta_types::StableId;
use codex_history::TurnRecoveryRequestBinding;
use codex_thread_store::NativeCheckpointBinding;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;

const SCHEMA: &str = "hepta.native.turn.checkpoint.v1";
const MAX_CHECKPOINT_BYTES: usize = 4 * 1024 * 1024;

/// Correlation with an existing QueueStore submission, never a dispatch lease.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NativeQueueBindingV1 {
    pub client_id: String,
    pub queued_item_id: String,
    pub payload_sha256: String,
}

/// Original execution scope and policy correlation, never the current gate's
/// policy or a reusable grant. Recovery must retain these values unchanged.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NativeExecutionBindingV1 {
    pub cell_id: String,
    pub organ_id: String,
    pub final_scope_id: String,
    pub policy_generation: u64,
}

/// Immutable original-owner identities shared by every state in one turn.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NativeTurnAnchorV1 {
    pub checkpoint: NativeCheckpointBinding,
    pub recovery: TurnRecoveryRequestBinding,
    pub queue: Option<NativeQueueBindingV1>,
    /// Taken from the original coordinator after its actual dispatch transition.
    /// Older storage-only checkpoints remain readable but cannot cold-recover
    /// an Agentd run without this correlation and its execution binding.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub run: Option<crate::RunRecovery>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub execution: Option<NativeExecutionBindingV1>,
    /// Digest of the exact native input rendering. The original canonical
    /// context/compilation receipts remain in `run` in their own domains.
    /// This persisted correlation authorizes observation, never a fresh run.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rendered_context_sha256: Option<String>,
}

impl NativeTurnAnchorV1 {
    pub(crate) fn turn_binding(&self) -> Result<TurnBinding> {
        Ok(TurnBinding {
            thread_id: StableId::new(self.checkpoint.thread_id.to_string())?,
            turn_id: StableId::new(self.checkpoint.turn_id.clone())?,
            operation_id: StableId::new(self.checkpoint.operation_id.clone())?,
            generation: Generation::new(self.checkpoint.generation)?,
        })
    }

    pub(crate) fn validate(&self) -> Result<()> {
        self.turn_binding()?;
        ensure!(!self.checkpoint.lease_id.is_empty(), "original lease identity missing");
        ensure!(self.recovery.turn_id == self.checkpoint.turn_id, "history turn changed");
        let boundary = self.recovery.history_boundary.as_ref().context("history boundary missing")?;
        let replay = self.recovery.replay.as_ref().context("history replay binding missing")?;
        ensure!(&replay.history_boundary == boundary, "history replay boundary changed");
        self.recovery.fingerprint_sha256.parse::<Digest32>()?;
        boundary.prefix_sha256.parse::<Digest32>()?;
        replay.turn_context_sha256.parse::<Digest32>()?;
        if let Some(queue) = &self.queue {
            ensure!(!queue.client_id.is_empty() && !queue.queued_item_id.is_empty(), "queue identity missing");
            queue.payload_sha256.parse::<Digest32>()?;
        }
        match (&self.run, &self.execution) {
            (Some(run), Some(execution)) => {
                ensure!(run.snapshot.run_id == self.checkpoint.operation_id
                    && run.snapshot.generation == self.checkpoint.generation,
                    "original coordinator run does not match native checkpoint");
                StableId::new(execution.cell_id.clone())?;
                StableId::new(execution.organ_id.clone())?;
                StableId::new(execution.final_scope_id.clone())?;
                Generation::new(execution.policy_generation)?;
            }
            (None, None) => {}
            (Some(_), None) | (None, Some(_)) => {
                anyhow::bail!("coordinator recovery and execution scope must be recorded together");
            }
        }
        if let Some(rendered) = &self.rendered_context_sha256 {
            ensure!(self.run.is_some(), "rendered context lacks its original coordinator binding");
            rendered.parse::<Digest32>()?;
        }
        // Core recovery generation and Fleet execution generation are distinct
        // domains. Preserve both; neither is a current authority witness.
        Ok(())
    }
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct CheckpointV1 {
    schema: String,
    anchor: NativeTurnAnchorV1,
    native_context_sha256: String,
    state: StateV1,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StateV1 {
    context: Vec<Value>,
    model_calls: usize,
    tool_calls: usize,
    pending_model: Option<ModelV1>,
    provider_response_id: Option<String>,
    queued_tools: Vec<CallV1>,
    pending_tool: Option<PendingToolV1>,
    completed_call_ids: Vec<String>,
    final_answer: Option<String>,
    cancelled: bool,
    last_error: Option<String>,
    model_usage: Vec<Value>,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct ModelV1 {
    operation_id: String,
    body: Vec<u8>,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct CallV1 {
    call_id: String,
    name: String,
    arguments: Vec<u8>,
}

impl From<&ToolCall> for CallV1 {
    fn from(call: &ToolCall) -> Self {
        Self { call_id: call.call_id.clone(), name: call.name.clone(), arguments: call.arguments.clone() }
    }
}

impl From<CallV1> for ToolCall {
    fn from(call: CallV1) -> Self {
        Self { call_id: call.call_id, name: call.name, arguments: call.arguments }
    }
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct PendingToolV1 {
    call: CallV1,
    intent: RuntimeIntentV1,
    arguments: Vec<u8>,
    submission_attempted: bool,
    cancel_requested: bool,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct RuntimeIntentV1 {
    operation_id: String,
    cell_id: String,
    organ_id: String,
    generation: u64,
    input_digest: String,
    final_scope_id: String,
    final_generation: u64,
    final_payload_kind: String,
    final_payload_digest: String,
    deadline_ms: u64,
    tool_id: String,
    arguments_digest: String,
    idempotency_key: String,
    host_scope: String,
    intent_digest: String,
}

impl From<&RuntimeToolIntentV1> for RuntimeIntentV1 {
    fn from(intent: &RuntimeToolIntentV1) -> Self {
        Self {
            operation_id: intent.cell.operation_id.to_string(),
            cell_id: intent.cell.cell_id.to_string(),
            organ_id: intent.cell.organ_id.to_string(),
            generation: intent.cell.generation.get(),
            input_digest: intent.cell.input_digest.to_string(),
            final_scope_id: intent.cell.final_payload.scope_id.to_string(),
            final_generation: intent.cell.final_payload.generation.get(),
            final_payload_kind: intent.cell.final_payload.payload_kind.to_string(),
            final_payload_digest: intent.cell.final_payload.digest.to_string(),
            deadline_ms: intent.cell.deadline_ms,
            tool_id: intent.tool_id.to_string(),
            arguments_digest: intent.arguments_digest.to_string(),
            idempotency_key: intent.idempotency_key.to_string(),
            host_scope: intent.host_scope.to_string(),
            intent_digest: intent.intent_digest().to_string(),
        }
    }
}

impl RuntimeIntentV1 {
    fn restore(self) -> Result<RuntimeToolIntentV1> {
        let intent = RuntimeToolIntentV1 {
            cell: CellExecutionIntentV1 {
                operation_id: StableId::new(self.operation_id)?,
                cell_id: StableId::new(self.cell_id)?,
                organ_id: StableId::new(self.organ_id)?,
                generation: Generation::new(self.generation)?,
                kind: ExecutionIntentKindV1::RuntimeTool,
                codex_binding: None,
                input_digest: self.input_digest.parse()?,
                final_payload: FinalPayloadDigestV1 {
                    scope_id: StableId::new(self.final_scope_id)?,
                    generation: Generation::new(self.final_generation)?,
                    payload_kind: StableId::new(self.final_payload_kind)?,
                    digest: self.final_payload_digest.parse()?,
                },
                deadline_ms: self.deadline_ms,
            },
            tool_id: StableId::new(self.tool_id)?,
            arguments_digest: self.arguments_digest.parse()?,
            idempotency_key: StableId::new(self.idempotency_key)?,
            host_scope: StableId::new(self.host_scope)?,
        };
        intent.validate()?;
        ensure!(intent.intent_digest().to_string() == self.intent_digest, "pending tool intent changed");
        Ok(intent)
    }
}

pub(crate) fn encode(anchor: &NativeTurnAnchorV1, state: &TurnState) -> Result<Vec<u8>> {
    validate_state(anchor, state)?;
    let record = CheckpointV1 {
        schema: SCHEMA.to_owned(),
        anchor: anchor.clone(),
        native_context_sha256: Digest32::of_bytes(&serde_json::to_vec(&state.context)?).to_string(),
        state: StateV1 {
            context: state.context.clone(),
            model_calls: state.model_calls,
            tool_calls: state.tool_calls,
            pending_model: state.pending_model.as_ref().map(|request| ModelV1 {
                operation_id: request.operation_id.clone(), body: request.body.clone(),
            }),
            provider_response_id: state.provider_response_id.clone(),
            queued_tools: state.queued_tools.iter().map(CallV1::from).collect(),
            pending_tool: state.pending_tool.as_ref().map(|pending| PendingToolV1 {
                call: CallV1::from(&pending.call), intent: RuntimeIntentV1::from(&pending.intent),
                arguments: pending.arguments.clone(), submission_attempted: pending.submission_attempted,
                cancel_requested: pending.cancel_requested,
            }),
            completed_call_ids: state.completed_call_ids.clone(),
            final_answer: state.final_answer.clone(),
            cancelled: state.cancelled,
            last_error: state.last_error.clone(),
            model_usage: state.model_usage.clone(),
        },
    };
    let bytes = serde_json::to_vec(&record)?;
    ensure!(bytes.len() <= MAX_CHECKPOINT_BYTES, "native checkpoint exceeds storage bound");
    Ok(bytes)
}

pub(crate) fn decode(bytes: &[u8], binding: &NativeCheckpointBinding) -> Result<(NativeTurnAnchorV1, TurnState)> {
    ensure!(!bytes.is_empty() && bytes.len() <= MAX_CHECKPOINT_BYTES, "native checkpoint size invalid");
    let record: CheckpointV1 = serde_json::from_slice(bytes)?;
    ensure!(record.schema == SCHEMA && &record.anchor.checkpoint == binding, "native checkpoint binding or schema changed");
    // Also reject ignored fields inside imported compatibility DTOs. Ordinary
    // rollout parsing remains tolerant; this authority-adjacent sidecar is exact.
    ensure!(serde_json::to_value(&record)? == serde_json::from_slice::<Value>(bytes)?, "noncanonical native checkpoint fields");
    let wire = record.state;
    let pending_tool = wire.pending_tool.map(|pending| -> Result<PendingTool> {
        Ok(PendingTool {
            call: pending.call.into(), intent: pending.intent.restore()?, arguments: pending.arguments,
            submission_attempted: pending.submission_attempted, cancel_requested: pending.cancel_requested,
        })
    }).transpose()?;
    let state = TurnState {
        binding: record.anchor.turn_binding()?,
        context: wire.context,
        model_calls: wire.model_calls,
        tool_calls: wire.tool_calls,
        pending_model: wire.pending_model.map(|request| ModelRequest { operation_id: request.operation_id, body: request.body }),
        provider_response_id: wire.provider_response_id,
        queued_tools: wire.queued_tools.into_iter().map(ToolCall::from).collect(),
        pending_tool,
        completed_call_ids: wire.completed_call_ids,
        final_answer: wire.final_answer,
        cancelled: wire.cancelled,
        last_error: wire.last_error,
        model_usage: wire.model_usage,
    };
    validate_state(&record.anchor, &state)?;
    ensure!(Digest32::of_bytes(&serde_json::to_vec(&state.context)?).to_string() == record.native_context_sha256, "native context changed");
    Ok((record.anchor, state))
}

fn validate_state(anchor: &NativeTurnAnchorV1, state: &TurnState) -> Result<()> {
    anchor.validate()?;
    ensure!(state.binding == anchor.turn_binding()?, "turn state moved to another original binding");
    ensure!(!state.context.is_empty(), "native context missing");
    ensure!(!(state.pending_model.is_some() && (state.pending_tool.is_some() || !state.queued_tools.is_empty())), "overlapping model and tool admissions");
    ensure!(state.final_answer.is_none() || (!state.cancelled && state.pending_model.is_none() && state.pending_tool.is_none() && state.queued_tools.is_empty()), "terminal state still has pending work");
    if let Some(request) = &state.pending_model {
        ensure!(state.model_calls > 0 && !request.operation_id.is_empty() && !request.body.is_empty(), "pending model admission missing");
        serde_json::from_slice::<Value>(&request.body)?;
    }
    if let Some(response_id) = &state.provider_response_id {
        ensure!(state.model_calls > 0 && !response_id.is_empty(), "provider response binding missing");
    }
    let mut ids = HashSet::new();
    for id in &state.completed_call_ids {
        ensure!(!id.is_empty() && ids.insert(id.as_str()), "reused completed tool call");
    }
    ensure!(state.completed_call_ids.len() <= state.tool_calls, "completed tool count exceeds admissions");
    for call in state.queued_tools.iter().chain(state.pending_tool.iter().map(|pending| &pending.call)) {
        ensure!(!call.call_id.is_empty() && call.call_id.len() <= 512 && !call.name.is_empty() && ids.insert(call.call_id.as_str()), "reused or empty tool proposal");
        serde_json::from_slice::<Value>(&call.arguments)?;
    }
    if let Some(pending) = &state.pending_tool {
        pending.intent.validate()?;
        ensure!(state.tool_calls > state.completed_call_ids.len()
            && pending.intent.cell.generation == state.binding.generation
            && pending.intent.cell.input_digest == Digest32::of_bytes(&pending.call.arguments)
            && pending.intent.arguments_digest == Digest32::of_bytes(&pending.arguments), "pending tool payload or generation changed");
    }
    Ok(())
}

/// Reject stale snapshots that would erase or replace an unresolved operation.
/// Terminal receipts are still checked by the engine and physical ports; this
/// only checks the durable state transition they are allowed to publish.
pub(crate) fn validate_transition(previous: &TurnState, next: &TurnState) -> Result<()> {
    ensure!(!previous.cancelled || next.cancelled, "turn cancellation cannot be reset");
    ensure!(next.completed_call_ids.starts_with(&previous.completed_call_ids)
        && next.model_usage.starts_with(&previous.model_usage), "native completion history regressed");
    let model_settled = previous.pending_model.is_some() && next.pending_model.is_none();
    let tool_settled = previous.pending_tool.is_some() && next.pending_tool.is_none();
    let tool_admitted = previous.pending_tool.is_none() && next.pending_tool.is_some();
    let model_admitted = previous.pending_model.is_none() && next.pending_model.is_some();
    ensure!(previous.model_calls.checked_add(usize::from(model_admitted)) == Some(next.model_calls)
        && previous.tool_calls.checked_add(usize::from(tool_admitted)) == Some(next.tool_calls), "native admission counters changed outside an admission");
    if let (Some(old), Some(new)) = (&previous.pending_model, &next.pending_model) {
        ensure!(old.operation_id == new.operation_id && old.body == new.body, "unresolved model request replaced");
        if previous.provider_response_id.is_some() {
            ensure!(previous.provider_response_id == next.provider_response_id, "original provider response replaced");
        }
    }
    if model_admitted {
        ensure!(previous.pending_tool.is_none() && previous.queued_tools.is_empty()
            && next.provider_response_id.is_none(), "new model admission overlaps prior work");
    } else if previous.pending_model.is_none() || model_settled {
        ensure!(previous.provider_response_id == next.provider_response_id, "provider response changed without a model event");
    }
    if let (Some(old), Some(new)) = (&previous.pending_tool, &next.pending_tool) {
        ensure!(old.call == new.call && old.intent == new.intent && old.arguments == new.arguments
            && (!old.submission_attempted || new.submission_attempted)
            && (!old.cancel_requested || new.cancel_requested), "unresolved tool request replaced or reset");
    }
    if tool_admitted {
        let pending = next.pending_tool.as_ref().context("new tool admission missing")?;
        ensure!(previous.queued_tools.first() == Some(&pending.call)
            && next.queued_tools == previous.queued_tools[1..], "tool admission did not consume the original proposal");
    } else if !model_settled {
        ensure!(previous.queued_tools == next.queued_tools, "queued proposals changed without a model completion");
    }
    if tool_settled {
        let call = &previous.pending_tool.as_ref().context("previous tool missing")?.call;
        ensure!(next.completed_call_ids.len() == previous.completed_call_ids.len() + 1
            && next.completed_call_ids.last() == Some(&call.call_id)
            && next.context.len() == previous.context.len() + 1
            && next.context.last().is_some_and(|item| item["type"] == "function_call_output" && item["call_id"] == call.call_id), "tool settlement omitted its original result binding");
    } else {
        ensure!(previous.completed_call_ids == next.completed_call_ids, "tool completion appeared without a pending operation");
    }
    if model_settled || tool_settled {
        ensure!(next.context.len() > previous.context.len() && next.context.starts_with(&previous.context), "settlement replaced original model context");
    } else {
        ensure!(previous.context == next.context, "native context changed outside a settlement");
    }
    if previous.final_answer.is_some() || !model_settled {
        ensure!(previous.final_answer == next.final_answer, "final answer changed without a model completion");
    }
    Ok(())
}

#[cfg(test)]
#[path = "native_turn_checkpoint_tests.rs"]
mod tests;
