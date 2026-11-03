//! Fold every original checkpoint transition against the complete original
//! writer scope. This module can verify evidence, never admit or execute work.

use std::collections::{BTreeMap, BTreeSet};

use anyhow::{Context, Result, bail, ensure};
use codex_hepta_memory::{LocalOutcomeState, ProductionScopeClaimState, ProductionScopeFrontier, ProductionScopeOperation};
use codex_hepta_native_agent::{NativeAgent, ObservedModelTerminal, TurnState};
use codex_thread_store::StoredNativeCheckpoint;

use crate::NativeTurnAnchorV1;
use crate::native_admission::NativeProductionAdmission;
use crate::native_model_target::NativeResponsesTarget;
use crate::native_runtime_target::{NativeRuntimeTarget, NativeToolTerminalEvidence};
use crate::native_turn_checkpoint::{decode, encode, validate_transition};

pub(super) struct NativeCheckpointFold<'a> {
    pub(super) agent: &'a NativeAgent,
    pub(super) anchor: &'a NativeTurnAnchorV1,
    pub(super) admission: &'a NativeProductionAdmission,
    pub(super) model: &'a NativeResponsesTarget,
    pub(super) runtime: &'a NativeRuntimeTarget,
}

struct OperationFold<'a> {
    original: BTreeMap<&'a str, &'a ProductionScopeOperation>,
    tools: &'a BTreeMap<String, NativeToolTerminalEvidence>,
    admitted: BTreeSet<String>,
    settled: BTreeSet<String>,
}

impl NativeCheckpointFold<'_> {
    pub(super) fn decode_chain(&self, records: &[StoredNativeCheckpoint],
        initial: &TurnState) -> Result<Vec<TurnState>> {
        ensure!(!records.is_empty() && records.len() <= 4096, "original checkpoint chain has an invalid length");
        ensure!(records[0].state.payload == encode(self.anchor, initial)?,
            "first checkpoint is not the exact original canonical initial state");
        let mut states = Vec::with_capacity(records.len());
        let mut bytes = 0usize;
        for (index, record) in records.iter().enumerate() {
            bytes = bytes.checked_add(record.state.payload.len()).context("original checkpoint chain byte length overflow")?;
            ensure!(bytes <= 64 * 1024 * 1024, "original checkpoint chain exceeds its aggregate evidence bound");
            ensure!(record.version.revision == u64::try_from(index)?.checked_add(1).context("checkpoint revision overflow")?
                && record.state.binding == self.anchor.checkpoint, "original checkpoint chain omitted or moved a revision");
            let (anchor, state) = decode(&record.state.payload, &self.anchor.checkpoint)?;
            ensure!(&anchor == self.anchor, "original checkpoint chain changed its immutable anchor");
            ensure!(!state.cancelled, "a cancelled original checkpoint cannot authorize continuation");
            ensure!(state.model_calls <= self.agent.limits.model_calls && state.tool_calls <= self.agent.limits.tool_calls,
                "original checkpoint exceeds the unchanged execution budgets");
            states.push(state);
        }
        Ok(states)
    }

    /// Fetch raw original runtime output before taking the writer's exclusive
    /// frontier. Text in a checkpoint cannot reconstruct non-UTF8 source bytes.
    pub(super) async fn observe_tools(&self, states: &[TurnState])
        -> Result<BTreeMap<String, NativeToolTerminalEvidence>> {
        let mut tools = BTreeMap::new();
        let mut bytes = 0usize;
        for pair in states.windows(2) {
            let Some(pending) = pair[0].pending_tool.as_ref().filter(|_| pair[1].pending_tool.is_none()) else { continue; };
            let key = pending.intent.idempotency_key.as_str();
            ensure!(!tools.contains_key(key), "original checkpoint chain settles a tool operation twice");
            let request = self.admission.host.writer().resolve_operation_request(key,
                &self.admission.runtime_destination).await?;
            self.admission.verify_request(&request)?;
            ensure!(request.payload_json.as_bytes() == pending.arguments,
                "original checkpoint tool arguments differ from the admitted operation");
            let evidence = tokio::time::timeout(self.agent.limits.tool_timeout,
                self.runtime.observe_tool_evidence(&request, &pending.intent)).await
                .context("original runtime evidence observation timed out")??
                .context("original runtime has no complete raw terminal output")?;
            bytes = bytes.checked_add(evidence.stdout.len()).and_then(|value| value.checked_add(evidence.stderr.len()))
                .context("original runtime evidence byte length overflow")?;
            ensure!(bytes <= 64 * 1024 * 1024, "original runtime evidence exceeds its aggregate bound");
            ensure!(tools.insert(key.to_owned(), evidence).is_none(), "duplicate original tool evidence");
        }
        Ok(tools)
    }

    /// This method has no await and is called while the original writer's
    /// exclusive frontier is retained. Every scope row must be explained by
    /// exactly one admission and exact terminal projection in this full chain.
    pub(super) fn verify(&self, records: &[StoredNativeCheckpoint], states: &[TurnState],
        frontier: &ProductionScopeFrontier, tools: &BTreeMap<String, NativeToolTerminalEvidence>) -> Result<()> {
        ensure!(records.len() == states.len() && states.len() > 1, "terminal continuation requires its complete original chain");
        let mut evidence = OperationFold { original: BTreeMap::new(), tools,
            admitted: BTreeSet::new(), settled: BTreeSet::new() };
        for operation in frontier.records() {
            let request = operation.request();
            self.admission.verify_request(request)?;
            ensure!(request.payload_sha256 == codex_hepta_contracts::Sha256Digest::for_bytes(request.payload_json.as_bytes()),
                "original native operation payload differs from its admitted digest");
            ensure!(operation.state() == LocalOutcomeState::Committed && operation.terminal_receipt().is_some()
                && operation.terminal_event_id().is_some(),
                "original execution scope contains an unresolved or non-applied operation");
            ensure!(operation.claims().last().is_some_and(|claim| claim.state() == ProductionScopeClaimState::Settled),
                "original execution scope contains an unsettled dispatch claim");
            ensure!(evidence.original.insert(request.occurrence_key.as_str(), operation).is_none(),
                "original scope contains duplicate operation identities");
        }
        ensure!(!evidence.original.is_empty(), "terminal checkpoint chain has no original operation evidence");
        for (index, pair) in states.windows(2).enumerate() {
            validate_transition(&pair[0], &pair[1])?;
            let expected = self.transition(&pair[0], &pair[1], &mut evidence)?;
            ensure!(encode(self.anchor, &expected)? == records[index + 1].state.payload,
                "original checkpoint revision {} is not an exact native transition", index + 2);
        }
        ensure!(evidence.admitted.len() == evidence.original.len() && evidence.settled == evidence.admitted,
            "original scope and checkpoint chain do not cover the same complete execution frontier");
        ensure!(tools.len() == states.last().context("original final state missing")?.completed_call_ids.len(),
            "original raw tool evidence does not cover every completed call");
        Ok(())
    }

    fn transition(&self, previous: &TurnState, next: &TurnState, evidence: &mut OperationFold<'_>) -> Result<TurnState> {
        if previous.pending_model.is_none() && next.pending_model.is_some() {
            ensure!(previous.final_answer.is_none() && previous.pending_tool.is_none() && previous.queued_tools.is_empty()
                && previous.model_calls < self.agent.limits.model_calls, "model admission is not the original next step");
            let pending = next.pending_model.as_ref().context("original new model admission missing")?;
            let key = self.admission.operation_id("model", &previous.model_calls.to_string())?;
            let body = self.agent.model_request_body(previous)?;
            ensure!(pending.operation_id == key && pending.body == body, "original model admission changed its identity or exact request body");
            let operation = evidence.original.get(key.as_str()).context("checkpoint model admission has no original scope row")?;
            let original = self.model.original_request(operation.request())?;
            ensure!(original.operation_id == key && original.body == body, "original model operation differs from its checkpoint admission");
            ensure!(evidence.admitted.insert(key), "original model operation was admitted twice in the checkpoint chain");
            let mut expected = previous.clone();
            expected.pending_model = Some(pending.clone());
            expected.provider_response_id = None;
            expected.model_calls = previous.model_calls.checked_add(1).context("model admission count overflow")?;
            return Ok(expected);
        }
        if previous.pending_tool.is_none() && next.pending_tool.is_some() {
            ensure!(previous.final_answer.is_none() && previous.pending_model.is_none()
                && previous.tool_calls < self.agent.limits.tool_calls, "tool admission is not the original next step");
            let pending = next.pending_tool.as_ref().context("original new tool admission missing")?;
            ensure!(previous.queued_tools.first() == Some(&pending.call) && !pending.submission_attempted && !pending.cancel_requested,
                "original tool admission changed its proposal or submission flags");
            let key = self.admission.operation_id("tool", &pending.call.call_id)?;
            let operation = evidence.original.get(key.as_str()).context("checkpoint tool admission has no original scope row")?;
            let params = self.runtime.original_params(operation.request())?;
            ensure!(operation.request().payload_json.as_bytes() == pending.arguments,
                "checkpoint tool admission changed the original compiled process bytes");
            let deadline = self.anchor.run.as_ref().context("original native run missing")?.snapshot.deadline_ms;
            let intent = self.admission.intent_for_arguments(&previous.binding, &pending.call,
                &pending.arguments, &params.host, deadline)?;
            ensure!(pending.intent == intent, "checkpoint tool admission changed its original intent");
            ensure!(evidence.admitted.insert(key), "original tool operation was admitted twice in the checkpoint chain");
            let mut expected = previous.clone();
            expected.pending_tool = Some(pending.clone());
            expected.queued_tools.remove(0);
            expected.tool_calls = previous.tool_calls.checked_add(1).context("tool admission count overflow")?;
            return Ok(expected);
        }
        if let Some(pending) = &previous.pending_model {
            if next.pending_model.is_none() {
                let key = pending.operation_id.as_str();
                ensure!(evidence.admitted.contains(key) && evidence.settled.insert(key.to_owned()),
                    "model settlement lacks its one original admission");
                let operation = evidence.original.get(key).context("original model operation missing")?;
                let response = previous.provider_response_id.as_deref().context("model settlement has no original response identity")?;
                ensure!(next.model_usage.len() == previous.model_usage.len().checked_add(1).context("model usage count overflow")?,
                    "model settlement must append exactly one complete usage record");
                let items = next.context.get(previous.context.len()..).context("model completion replaced original context")?.to_vec();
                let usage = next.model_usage.last().context("model terminal usage missing")?.clone();
                let digest = ObservedModelTerminal::evidence_digest_for_output(key, response, &items, &usage)?;
                let receipt = serde_json::json!({ "schema":"hepta.native.model.observed.v1", "operation_id":key,
                    "response_id":response, "evidence_sha256":digest.to_string() });
                let receipt = receipt.to_string();
                ensure!(operation.terminal_receipt() == Some(receipt.as_str()),
                    "model output or usage differs from the original terminal evidence");
                return self.agent.project_model_completion(previous, items, usage);
            }
            if previous.provider_response_id.is_none() && next.provider_response_id.is_some() {
                let mut expected = previous.clone();
                expected.provider_response_id = next.provider_response_id.clone();
                return Ok(expected);
            }
            if next.last_error.is_some() && next.last_error != previous.last_error {
                let mut expected = previous.clone();
                expected.last_error = next.last_error.clone();
                return Ok(expected);
            }
            bail!("unrecognized original pending-model checkpoint transition");
        }
        if let Some(pending) = &previous.pending_tool {
            if next.pending_tool.is_none() {
                let key = pending.intent.idempotency_key.as_str();
                ensure!(evidence.admitted.contains(key) && evidence.settled.insert(key.to_owned()),
                    "tool settlement lacks its one original admission");
                let operation = evidence.original.get(key).context("original tool operation missing")?;
                let raw = evidence.tools.get(key).context("tool completion lacks original raw runtime output")?;
                ensure!(operation.terminal_receipt() == Some(raw.terminal_receipt.as_str()),
                    "tool raw output differs from the original terminal receipt");
                return self.agent.project_tool_completion(previous, &raw.receipt, &raw.stdout, &raw.stderr);
            }
            let next_pending = next.pending_tool.as_ref().context("original pending tool disappeared")?;
            if !pending.submission_attempted && !pending.cancel_requested && next_pending.submission_attempted {
                let mut expected = previous.clone();
                expected.pending_tool.as_mut().context("original pending tool missing")?.submission_attempted = true;
                return Ok(expected);
            }
            if !pending.cancel_requested && next_pending.cancel_requested {
                let mut expected = previous.clone();
                expected.pending_tool.as_mut().context("original pending tool missing")?.cancel_requested = true;
                return Ok(expected);
            }
            if next.last_error.is_some() && next.last_error != previous.last_error {
                let mut expected = previous.clone();
                expected.last_error = next.last_error.clone();
                return Ok(expected);
            }
            bail!("unrecognized original pending-tool checkpoint transition");
        }
        bail!("unrecognized original checkpoint transition without an admitted operation")
    }
}
