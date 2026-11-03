//! Original canonical preparation publication and read validation.
//!
//! The codec is common run-owner state. It owns no queue, effect record, grant,
//! or replay authorization. Import is crate-private and requires a committed
//! read capability from the original Objective journal, then live owner checks.

use super::*;
use anyhow::{Result, ensure};
use codex_hepta_learning_ledger::{CommittedRunPreparedV1, MAX_RUN_PREPARED_BYTES, RunPreparedRecordV1};

#[path = "canonical_prepared_wire.rs"]
mod wire;

const SCHEMA: &str = "hepta.agentd.canonical-prepared.v1";

/// Validated owner state, still not permission to restore a queue/turn phase.
/// Only the original coordinator may consume it after the original Queue and
/// ThreadStore have classified the operation's existing dispatch state.
pub(crate) struct RestoredCanonicalPreparationV1 {
    prepared: PreparedAgentdIntelligenceRunV1,
    attached_revision: u64,
    context: NativeContextBindingV1,
}

impl RestoredCanonicalPreparationV1 {
    pub(crate) fn prepared(&self) -> &PreparedAgentdIntelligenceRunV1 { &self.prepared }
    pub(crate) fn attached_revision(&self) -> u64 { self.attached_revision }
    pub(crate) fn context(&self) -> &NativeContextBindingV1 { &self.context }
    /// A factual view of the exact journaled attachment. It neither inserts a
    /// run nor grants dispatch permission; current lifecycle remains with the
    /// original coordinator and the original Core/Queue reservation.
    pub(crate) fn attached_run_receipt(&self) -> crate::RunReceipt {
        let snapshot = self.context.original_run_snapshot();
        crate::RunReceipt {
            run_id: snapshot.run_id.clone(), revision: self.attached_revision,
            phase: crate::RunPhase::ContextAttached,
            context_digest: Some(self.context.context_receipt_digest().to_string()),
            authority_epoch: snapshot.authority_epoch, generation: snapshot.generation,
            fence_digest: snapshot.fence_digest.clone(), deadline_ms: snapshot.deadline_ms,
            cancel_reason: None, cancel_ack_deadline_ms: None,
            compilation_receipt_digest: Some(self.context.compilation_receipt_digest().to_string()),
            terminal_observed: false, idempotent: false,
        }
    }
}

impl PreparedAgentdIntelligenceRunV1 {
    /// Export only the real sealed result, including actual selected material.
    /// The 2 MiB journal payload bound covers metadata; bind_native_context
    /// retains its original 8 KiB/item and 48 KiB selected rendering bounds.
    pub(crate) fn prepared_record(&self, original_record_digest: Digest32, attached: &crate::RunReceipt, mut materials: Vec<NativeContextMaterialV1>)
        -> Result<RunPreparedRecordV1> {
        validate_fields(self)?;
        materials.sort_by(|left, right| left.item_id.cmp(&right.item_id));
        let context = self.bind_native_context(materials.clone())?;
        ensure!(attached.phase == crate::RunPhase::ContextAttached && attached.revision > 0 && attached.cancel_reason.is_none(),
            "durable preparation requires the actual original context-attached coordinator record");
        context.verify_run(attached, context.context())?;
        let payload = wire::Payload { schema: SCHEMA.to_owned(), request: wire::Request::capture(&self.request),
            envelope: wire::Envelope::capture(&self.original_envelope)?, dispatch_proposal_digest: self.dispatch_proposal_digest.to_string(),
            run: context.original_run_snapshot().clone(), attachment: wire::Attachment {
                revision: attached.revision, run: attachment_snapshot(&self.context_attachment), context_digest: self.context_attachment.context_digest.clone(),
                compilation_receipt_digest: self.context_attachment.compilation_receipt_digest.clone(),
            }, context: wire::Context::capture(&self.context_request, &self.context_receipt),
            materials: materials.iter().map(wire::Material::capture).collect(), rendered_context: context.context().to_vec(),
            rendered_context_digest: context.rendered_context_digest().to_string() };
        let payload = serde_json::to_vec(&payload)?;
        ensure!(!payload.is_empty() && payload.len() <= MAX_RUN_PREPARED_BYTES, "canonical prepared journal payload exceeds storage bound");
        Ok(RunPreparedRecordV1 { run_id: self.request.run_id.clone(), run_start_record_digest: original_record_digest,
            payload_digest: Digest32::of_bytes(&payload), payload })
    }
}

impl AgentdIntelligenceProductRunnerV1 {
    /// Read-only recovery of the exact completed preparation. No invocation
    /// provider or owner stage is called here. AuthBus is checked by the same
    /// Objective host before and after this function, including at final entry.
    pub(crate) fn restore_canonical_handoff(&self, committed: &CommittedRunPreparedV1,
        current_generation: u64, now_ms: u64) -> Result<RestoredCanonicalPreparationV1> {
        let record = committed.record();
        let original = committed.original();
        ensure!(record.run_id == original.snapshot.run_id && original.snapshot.generation == current_generation
            && original.admission.deadline_unix_micros.div_ceil(1_000) > now_ms,
            "original canonical prepared generation or deadline is stale");
        ensure!(record.payload.len() <= MAX_RUN_PREPARED_BYTES && Digest32::of_bytes(&record.payload) == record.payload_digest,
            "committed prepared payload changed");
        let value: wire::Payload = serde_json::from_slice(&record.payload)?;
        ensure!(value.schema == SCHEMA && serde_json::to_vec(&value)? == record.payload,
            "canonical prepared payload is not exact typed owner encoding");
        let request = value.request.restore()?;
        let envelope = value.envelope.restore()?;
        let (context_request, context_receipt) = value.context.restore()?;
        ensure!(request.run_id == record.run_id && request.snapshot.body_generation().get() == original.snapshot.generation,
            "canonical request differs from original admitted Objective");
        let attachment = value.attachment;
        ensure!(attachment.revision > 0, "original prepared attachment revision is missing");
        let attached_revision = attachment.revision;
        let run_snapshot = protocol_snapshot(&value.run);
        let context_attachment = crate::AgentContextAttachment {
            run_id: attachment.run.run_id, request_digest: attachment.run.request_digest,
            objective_digest: attachment.run.objective_digest, body_digest: attachment.run.body_digest,
            artifact_set_digest: attachment.run.artifact_set_digest, authority_epoch: attachment.run.authority_epoch,
            generation: attachment.run.generation, fence_digest: attachment.run.fence_digest,
            deadline_ms: attachment.run.deadline_ms, context_digest: attachment.context_digest,
            compilation_receipt_digest: attachment.compilation_receipt_digest,
        };
        let candidate_ids = request.legal_candidates.candidates.iter().map(|candidate| candidate.candidate_id.clone()).collect();
        let prepared = PreparedAgentdIntelligenceRunV1 { original_envelope: envelope.clone(), envelope,
            dispatch_proposal_digest: value.dispatch_proposal_digest.parse()?, snapshot: request.snapshot.clone(), request,
            candidate_ids, run_snapshot, context_attachment, context_request, context_receipt };
        validate_fields(&prepared)?;
        crate::canonical_queued_input::verify_admitted_record(original, &value.run)?;
        ensure!(value.run.generation == current_generation && value.run.deadline_ms > now_ms,
            "compiled canonical prepared generation or deadline is stale");
        let mut oracle = FileBackedFreshnessOracleV1::new(self.authority_file.clone(), self.authority_verifier.clone());
        validate_current_snapshot(&prepared.snapshot, &mut oracle)?;
        let materials = value.materials.into_iter().map(wire::Material::restore).collect::<Result<Vec<_>>>()?;
        let context = prepared.bind_native_context(materials)?;
        ensure!(context.context() == value.rendered_context && context.rendered_context_digest().to_string() == value.rendered_context_digest,
            "original canonical material or rendering changed");
        context.verify_run_snapshot(&value.run)?;
        // Re-read the signed authority file after bounded decoding/rendering.
        validate_current_snapshot(&prepared.snapshot, &mut oracle)?;
        Ok(RestoredCanonicalPreparationV1 { prepared, attached_revision, context })
    }
}

fn validate_fields(prepared: &PreparedAgentdIntelligenceRunV1) -> Result<()> {
    ensure!(prepared.envelope == prepared.original_envelope && prepared.snapshot == prepared.request.snapshot,
        "prepared envelope or snapshot differs from the original result");
    ensure!(prepared.candidate_ids == prepared.request.legal_candidates.candidates.iter().map(|value| value.candidate_id.clone()).collect::<Vec<_>>(),
        "prepared candidate identities changed");
    codex_hepta_intelligence::validate_retained_envelope_v1(&prepared.request, &prepared.original_envelope)?;
    codex_hepta_context_compiler::validate_retained_compilation_v1(&prepared.context_request, &prepared.context_receipt)?;
    let snapshot = &prepared.snapshot; let envelope = &prepared.original_envelope;
    let run = &prepared.run_snapshot;
    let mut body = b"hepta.agentd.intelligence-body.v1\0".to_vec();
    body.extend_from_slice(snapshot.digest().as_array());
    body.extend_from_slice(&snapshot.body_generation().get().to_be_bytes());
    ensure!(run.run_id == envelope.run_id.as_str() && run.request_digest == envelope.trace_digest.to_string()
        && run.objective_digest == envelope.objective_digest.to_string() && run.body_digest == Digest32::of_bytes(&body).to_string()
        && run.artifact_set_digest == snapshot.digest().to_string() && run.authority_epoch == snapshot.authority_epoch(),
        "compiled run differs from original canonical envelope");
    let mut proposal = b"hepta.agentd.intelligence-dispatch-proposal.v1\0".to_vec();
    proposal.extend_from_slice(envelope.envelope_digest.as_array());
    proposal.extend_from_slice(snapshot.revocation_frontier_digest().as_array());
    ensure!(Digest32::of_bytes(&proposal) == prepared.dispatch_proposal_digest, "canonical dispatch proposal changed");
    let attachment = &prepared.context_attachment;
    ensure!(attachment_snapshot(attachment) == internal_snapshot(run)
        && attachment.context_digest == prepared.context_receipt.context_digest.to_string()
        && attachment.compilation_receipt_digest == envelope.envelope_digest.to_string(), "canonical context attachment changed");
    Ok(())
}

fn attachment_snapshot(value: &crate::AgentContextAttachment) -> crate::RunSnapshot {
    crate::RunSnapshot { run_id: value.run_id.clone(), request_digest: value.request_digest.clone(), objective_digest: value.objective_digest.clone(),
        body_digest: value.body_digest.clone(), artifact_set_digest: value.artifact_set_digest.clone(), authority_epoch: value.authority_epoch,
        generation: value.generation, fence_digest: value.fence_digest.clone(), deadline_ms: value.deadline_ms }
}

fn internal_snapshot(value: &crate::AgentRunSnapshot) -> crate::RunSnapshot {
    crate::RunSnapshot { run_id: value.run_id.clone(), request_digest: value.request_digest.clone(), objective_digest: value.objective_digest.clone(),
        body_digest: value.body_digest.clone(), artifact_set_digest: value.artifact_set_digest.clone(), authority_epoch: value.authority_epoch,
        generation: value.generation, fence_digest: value.fence_digest.clone(), deadline_ms: value.deadline_ms }
}

fn protocol_snapshot(value: &crate::RunSnapshot) -> crate::AgentRunSnapshot {
    crate::AgentRunSnapshot { run_id: value.run_id.clone(), request_digest: value.request_digest.clone(), objective_digest: value.objective_digest.clone(),
        body_digest: value.body_digest.clone(), artifact_set_digest: value.artifact_set_digest.clone(), authority_epoch: value.authority_epoch,
        generation: value.generation, fence_digest: value.fence_digest.clone(), deadline_ms: value.deadline_ms }
}
