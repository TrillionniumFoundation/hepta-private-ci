//! Pure shadow execution for one typed Memory Cell tick.
//!
//! The adapter binds the Memory Cell manifest and tick input to the existing
//! generation-bound retrieval and HNMF engram core. It emits a receipt and
//! deterministic candidate checkpoint digest; it owns no source writer, model
//! invocation, selector, trainer, promotion or topology authority.

use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::memory_cell::MemoryCellManifestV1;
use codex_hepta_cognitive_types::memory_cell::MemoryCellResourceUsageV1;
use codex_hepta_cognitive_types::memory_cell::MemoryCellRoleV1;
use codex_hepta_cognitive_types::memory_cell::MemoryCellStatusV1;
use codex_hepta_cognitive_types::memory_cell::MemoryCellTickInputV1;
use codex_hepta_cognitive_types::memory_cell::MemoryCellTickReceiptV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;

use crate::EngramDynamicsPolicyV1;
use crate::EngramSnapshotV1;
use crate::GeneratedCandidateInputV1;
use crate::GeneratedRecallV1;
use crate::GeneratorErrorV1;
use crate::MemoryCueV1;
use crate::RecallDispositionV1;
use crate::RetrievalPolicyV1;

/// Errors raised while binding a Memory Cell tick to the pure retrieval core.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum MemoryCellRuntimeErrorV1 {
    /// The typed contract itself is invalid.
    Contract(String),
    /// A digest, generation or frontier did not match the declared cell.
    Binding(&'static str),
    /// Candidate generation or HNMF recall rejected the input.
    Retrieval(GeneratorErrorV1),
}

impl std::fmt::Display for MemoryCellRuntimeErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for MemoryCellRuntimeErrorV1 {}

/// One deterministic, authority-free result of a Memory Cell shadow tick.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryCellShadowTickV1 {
    /// The status and evidence binding emitted for this tick.
    pub receipt: MemoryCellTickReceiptV1,
    /// The retrieval packet and source completeness evidence used to build it.
    pub recall: GeneratedRecallV1,
}

/// Execute one Memory Cell tick against immutable generated candidates and an
/// immutable engram snapshot.
///
/// The function deliberately treats a successful recall as a candidate
/// successor checkpoint. Persisting that checkpoint, writing source facts,
/// changing model weights or activating a split remains outside this adapter.
pub fn run_memory_cell_tick(
    manifest: &MemoryCellManifestV1,
    input: &MemoryCellTickInputV1,
    cue: &MemoryCueV1,
    retrieval_policy: &RetrievalPolicyV1,
    generated_input: &GeneratedCandidateInputV1,
    engram_snapshot: &EngramSnapshotV1,
    dynamics_policy: &EngramDynamicsPolicyV1,
) -> Result<MemoryCellShadowTickV1, MemoryCellRuntimeErrorV1> {
    manifest
        .validate()
        .map_err(|error| MemoryCellRuntimeErrorV1::Contract(format!("{error:?}")))?;
    input
        .validate()
        .map_err(|error| MemoryCellRuntimeErrorV1::Contract(format!("{error:?}")))?;
    cue.validate()
        .map_err(|error| MemoryCellRuntimeErrorV1::Retrieval(GeneratorErrorV1::Recall(error)))?;
    retrieval_policy
        .validate()
        .map_err(|error| MemoryCellRuntimeErrorV1::Retrieval(GeneratorErrorV1::Recall(error)))?;
    engram_snapshot.validate().map_err(|error| {
        MemoryCellRuntimeErrorV1::Retrieval(GeneratorErrorV1::Engram(error.to_string()))
    })?;
    dynamics_policy.validate().map_err(|error| {
        MemoryCellRuntimeErrorV1::Retrieval(GeneratorErrorV1::Engram(error.to_string()))
    })?;

    if input.cell_id != manifest.cell_id {
        return Err(MemoryCellRuntimeErrorV1::Binding("cell_id"));
    }
    if input.graph_generation != manifest.graph_generation {
        return Err(MemoryCellRuntimeErrorV1::Binding("graph_generation"));
    }
    if input.model_generation != manifest.model_generation {
        return Err(MemoryCellRuntimeErrorV1::Binding("model_generation"));
    }
    if input.source_frontier_digest != manifest.source_frontier_digest {
        return Err(MemoryCellRuntimeErrorV1::Binding("source_frontier_digest"));
    }
    if input.forget_frontier_digest != manifest.forget_frontier_digest {
        return Err(MemoryCellRuntimeErrorV1::Binding("forget_frontier_digest"));
    }
    if input.cue_digest.digest() != cue.digest() {
        return Err(MemoryCellRuntimeErrorV1::Binding("cue_digest"));
    }
    if input.objective_digest.digest() != cue.objective_digest {
        return Err(MemoryCellRuntimeErrorV1::Binding("objective_digest"));
    }
    if input.snapshot_digest.digest() != engram_snapshot.snapshot_digest {
        return Err(MemoryCellRuntimeErrorV1::Binding("snapshot_digest"));
    }
    if engram_snapshot.generation_vector_digest != cue.snapshot_key.vector_digest {
        return Err(MemoryCellRuntimeErrorV1::Binding(
            "generation_vector_digest",
        ));
    }

    let generated_union =
        crate::build_candidate_union_from_generated(cue, retrieval_policy, generated_input)
            .map_err(MemoryCellRuntimeErrorV1::Retrieval)?;
    let input_ood_ppm = generated_union
        .union
        .entries
        .iter()
        .map(|entry| probability_ppm(entry.maximum_ood))
        .max()
        .unwrap_or(0);

    let recall = crate::recall_generated_with_engram(
        cue,
        retrieval_policy,
        generated_input,
        engram_snapshot,
        dynamics_policy,
    )
    .map_err(MemoryCellRuntimeErrorV1::Retrieval)?;
    let selected = matches!(recall.packet.disposition, RecallDispositionV1::Recalled);
    let status = if selected {
        MemoryCellStatusV1::Selected
    } else {
        MemoryCellStatusV1::Abstained
    };
    let recall_packet_digest = selected
        .then(|| contract_digest(recall.packet.packet_digest))
        .transpose()?;
    let candidate_digest = contract_digest(recall.receipt_digest)?;
    let successor_checkpoint_digest = selected
        .then(|| shadow_checkpoint_digest(manifest, input, recall.receipt_digest))
        .transpose()?;

    let (coverage_ppm, confidence_ppm) = recall
        .packet
        .engram
        .as_ref()
        .map(|engram| {
            (
                probability_ppm(engram.coverage),
                probability_ppm(engram.confidence),
            )
        })
        .unwrap_or((0, 0));
    let ood_ppm = input_ood_ppm;

    let receipt = MemoryCellTickReceiptV1 {
        schema_version: 1,
        cell_id: input.cell_id.clone(),
        graph_generation: input.graph_generation,
        model_generation: input.model_generation,
        logical_sequence: input.logical_sequence,
        status,
        predecessor_checkpoint_digest: input.predecessor_checkpoint_digest.clone(),
        successor_checkpoint_digest,
        recall_packet_digest,
        candidate_digest: Some(candidate_digest),
        coverage_ppm,
        confidence_ppm,
        ood_ppm,
        resource_usage: MemoryCellResourceUsageV1::Unavailable {},
    };
    receipt
        .validate()
        .map_err(|error| MemoryCellRuntimeErrorV1::Contract(format!("{error:?}")))?;
    Ok(MemoryCellShadowTickV1 { receipt, recall })
}

fn contract_digest(value: Digest32) -> Result<ContractDigestV1, MemoryCellRuntimeErrorV1> {
    ContractDigestV1::from_digest(value)
        .map_err(|error| MemoryCellRuntimeErrorV1::Contract(format!("{error:?}")))
}

fn shadow_checkpoint_digest(
    manifest: &MemoryCellManifestV1,
    input: &MemoryCellTickInputV1,
    recall_receipt_digest: Digest32,
) -> Result<ContractDigestV1, MemoryCellRuntimeErrorV1> {
    // v2 also commits to the cell's artifact identity, declared roles and
    // budgets. This remains a candidate digest, never a persisted checkpoint.
    let mut bytes = b"hepta.memory-cell.shadow-checkpoint.v2".to_vec();
    push_shadow_frame(&mut bytes, input.cell_id.as_str().as_bytes());
    bytes.extend_from_slice(&input.logical_sequence.to_be_bytes());
    bytes.extend_from_slice(&input.graph_generation.get().to_be_bytes());
    bytes.extend_from_slice(&input.model_generation.get().to_be_bytes());
    bytes.extend_from_slice(&input.resource_budget_units.to_be_bytes());
    bytes.extend_from_slice(&manifest.max_active_cells.to_be_bytes());
    bytes.extend_from_slice(&manifest.max_state_bytes.to_be_bytes());
    bytes.push(match manifest.role {
        MemoryCellRoleV1::Episodic => 1,
        MemoryCellRoleV1::Semantic => 2,
        MemoryCellRoleV1::Procedural => 3,
        MemoryCellRoleV1::Predictive => 4,
        MemoryCellRoleV1::CrossModal => 5,
        MemoryCellRoleV1::MetaMemory => 6,
        MemoryCellRoleV1::Utility => 7,
    });
    bytes.push(u8::from(manifest.parent_cell_id.is_some()));
    if let Some(parent_id) = &manifest.parent_cell_id {
        push_shadow_frame(&mut bytes, parent_id.as_str().as_bytes());
    }
    for digest in [
        manifest.shared_base_digest.digest(),
        manifest.encoder_digest.digest(),
        manifest.adapter_artifact_digest.digest(),
        manifest.head_artifact_digest.digest(),
        manifest.state_schema_digest.digest(),
        manifest.lineage_digest.digest(),
        manifest.source_frontier_digest.digest(),
        manifest.forget_frontier_digest.digest(),
        input.input_digest.digest(),
        input.ndu_state_digest.digest(),
        input.cue_digest.digest(),
        input.snapshot_digest.digest(),
        input.source_frontier_digest.digest(),
        input.forget_frontier_digest.digest(),
        input.objective_digest.digest(),
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(
        &u64::try_from(manifest.modalities.len())
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    for modality in &manifest.modalities {
        push_shadow_frame(&mut bytes, modality.as_str().as_bytes());
    }
    bytes.extend_from_slice(
        &u64::try_from(manifest.populations.len())
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    for population in &manifest.populations {
        push_shadow_frame(&mut bytes, population.as_str().as_bytes());
    }
    bytes.push(u8::from(input.predecessor_checkpoint_digest.is_some()));
    if let Some(predecessor) = &input.predecessor_checkpoint_digest {
        bytes.extend_from_slice(predecessor.digest().as_array());
    }
    bytes.extend_from_slice(recall_receipt_digest.as_array());
    contract_digest(Digest32::of_bytes(&bytes))
}

fn push_shadow_frame(bytes: &mut Vec<u8>, value: &[u8]) {
    bytes.extend_from_slice(&u64::try_from(value.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(value);
}

fn probability_ppm(value: ProbabilityQ32) -> u32 {
    let scaled = u128::from(value.raw())
        .saturating_mul(1_000_000)
        .checked_div(u128::from(ProbabilityQ32::ONE.raw()))
        .unwrap_or(1_000_000);
    u32::try_from(scaled.min(1_000_000)).unwrap_or(1_000_000)
}

#[cfg(test)]
#[path = "memory_cell_tests.rs"]
mod tests;
