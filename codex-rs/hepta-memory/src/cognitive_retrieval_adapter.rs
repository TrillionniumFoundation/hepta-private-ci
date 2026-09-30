//! SQLite-owner adaptation with explicit multi-proposition semantic admission.
//! The predecessor core remains unchanged; proposition evidence is observed in
//! the same owner transaction and bound transitively into every candidate's
//! support digest. This module never invents a source assertion or polarity.

#[path = "cognitive_retrieval_adapter_core.rs"]
mod core;

pub use core::OwnerRetrievalExecutionV1;
pub use core::RetrievalExecutionContextV1;
pub use core::sqlite_owner_cue_profile_digest;
pub use core::sqlite_owner_retrieval_policy_v1;

use std::collections::BTreeSet;

use codex_hepta_memory_retrieval::RecallAbstentionReasonV1;
use codex_hepta_memory_retrieval::RecallDispositionV1;
use codex_hepta_memory_retrieval::build_candidate_union_from_generated;
use codex_hepta_memory_retrieval::compile_cue;
use codex_hepta_memory_retrieval::observe_retrieval_assignment;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::CognitiveStoreError;
use crate::DurableCognitiveSnapshot;
use crate::RetrievalObservation;

/// Migration alias retained for source compatibility, but it no longer creates
/// unlimited work control. Every caller must provide the host-owned control.
#[deprecated(note = "use execute_owner_observation_controlled with explicit work control")]
pub fn execute_owner_observation(
    observation: &RetrievalObservation,
    cut: &DurableCognitiveSnapshot,
    context: &RetrievalExecutionContextV1,
    request_digest: Digest32,
    acquired_at_unix_ms: u64,
    lease_expires_unix_ms: u64,
    work: &codex_hepta_memory_retrieval::RecallWorkControlV1,
) -> Result<OwnerRetrievalExecutionV1, CognitiveStoreError> {
    execute_owner_observation_inner(
        observation,
        cut,
        context,
        request_digest,
        acquired_at_unix_ms,
        lease_expires_unix_ms,
        work,
    )
}

/// Execute against the same owner cut with cancellation and a host deadline.
pub fn execute_owner_observation_controlled(
    observation: &RetrievalObservation,
    cut: &DurableCognitiveSnapshot,
    context: &RetrievalExecutionContextV1,
    request_digest: Digest32,
    acquired_at_unix_ms: u64,
    lease_expires_unix_ms: u64,
    work: &codex_hepta_memory_retrieval::RecallWorkControlV1,
) -> Result<OwnerRetrievalExecutionV1, CognitiveStoreError> {
    execute_owner_observation_inner(
        observation,
        cut,
        context,
        request_digest,
        acquired_at_unix_ms,
        lease_expires_unix_ms,
        work,
    )
}

fn execute_owner_observation_inner(
    observation: &RetrievalObservation,
    cut: &DurableCognitiveSnapshot,
    context: &RetrievalExecutionContextV1,
    request_digest: Digest32,
    acquired_at_unix_ms: u64,
    lease_expires_unix_ms: u64,
    work: &codex_hepta_memory_retrieval::RecallWorkControlV1,
) -> Result<OwnerRetrievalExecutionV1, CognitiveStoreError> {
    work.checkpoint()
        .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?;
    let mut execution = core::execute_owner_observation_controlled(
        observation,
        cut,
        context,
        request_digest,
        acquired_at_unix_ms,
        lease_expires_unix_ms,
        work,
    )?;
    // Reconstruct the exact bounded union using the same cue identity. This
    // deliberately favors one verifiable algorithm over an approximate score
    // shortcut. It may be fused with the core after differential qualification.
    let authoritative = cut
        .bind_context(
            context.generation_vector.clone(),
            acquired_at_unix_ms,
            lease_expires_unix_ms,
        )
        .map_err(|error| CognitiveStoreError::Conflict(error.to_string()))?;
    let generated = core::generated_input_from_owner_observation(
        observation,
        authoritative.snapshot_key(),
        authoritative.snapshot(),
    )?;
    let mut cue_bytes = b"hepta.owner-retrieval-cue.v1".to_vec();
    cue_bytes.extend_from_slice(request_digest.as_array());
    cue_bytes.extend_from_slice(authoritative.snapshot_key().vector_digest.as_array());
    let cue = compile_cue(
        StableId::new(format!("cue:{}", Digest32::of_bytes(&cue_bytes)))
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
        context.objective_digest,
        context.approved_context_digest,
        request_digest,
        authoritative.snapshot_key().clone(),
        context.cue_profile_digest,
    )
    .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
    let union = build_candidate_union_from_generated(&cue, &context.retrieval_policy, &generated)
        .map_err(|error| CognitiveStoreError::Conflict(error.to_string()))?;
    let admitted = union
        .union
        .entries
        .iter()
        .filter(|entry| {
            entry.weighted_score > FixedQ32::ZERO
                && entry.weighted_score >= context.retrieval_policy.minimum_total_score
        })
        .map(|entry| (entry.record.record_id.clone(), entry.record.revision))
        .collect::<BTreeSet<_>>();
    let conflicts = observation.admitted_proposition_conflicts(&admitted)?;
    if !conflicts.is_empty()
        && (context.retrieval_policy.abstain_on_contradiction
            || context.dynamics_policy.contradiction_forces_abstention)
    {
        let packet = &mut execution.recall.packet;
        packet.disposition =
            RecallDispositionV1::Abstained(RecallAbstentionReasonV1::ContradictoryEvidence);
        packet.selections.clear();
        packet.omitted_count = 0;
        packet.packet_digest = packet.compute_packet_digest();
        execution.recall.receipt_digest = execution.recall.compute_receipt_digest();
        execution
            .recall
            .validate()
            .map_err(|error| CognitiveStoreError::Conflict(error.to_string()))?;
        execution.assignment = observe_retrieval_assignment(
            &cue,
            &context.retrieval_policy,
            &generated,
            &execution.recall,
        )
        .map_err(|error| CognitiveStoreError::Conflict(error.to_string()))?;
    }
    work.checkpoint()
        .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?;
    Ok(execution)
}

#[cfg(test)]
#[path = "cognitive_proposition_owner_tests.rs"]
mod proposition_tests;
