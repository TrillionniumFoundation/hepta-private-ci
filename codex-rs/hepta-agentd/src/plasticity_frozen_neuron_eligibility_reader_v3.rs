//! Retain the complete original acknowledged numerical input for one finite
//! purpose while validating its continued eligibility through the held owner.
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

use codex_hepta_agent_components::neuron::JournalAnchor;
use codex_hepta_agent_components::neuron::MAX_NEURON_GENERATION_MATERIAL_BYTES_V2;
use codex_hepta_agent_components::neuron::NeuronGenerationMaterialV2;
use codex_hepta_agent_components::neuron::SparseCheckpoint;
use codex_hepta_agent_components::neuron::decode_neuron_generation_material_v2;
use codex_hepta_agent_components::neuron::encode_neuron_generation_material_v2;
use codex_hepta_agent_components::types::Digest32;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdNeuronRuntimeV2Host;
use crate::AgentdSelfIterationRoundV1;
use crate::PlasticityNeuronEligibilityReaderV1;
use crate::PlasticityOwnerEvidenceErrorV1;
use crate::PreparedParameterCheckpointV1;

/// Independently pinned complete original Sources. This constructor receives
/// the same held owner; it opens no Neuron store, index, witness or worker.
pub struct FrozenParameterCheckpointSourcesV3<'a> {
    pub identity: &'a AgentdIdentity,
    pub round: &'a AgentdSelfIterationRoundV1,
    pub baseline_material: &'a NeuronGenerationMaterialV2,
    pub checkpoint_response_path: &'a Path,
    pub checkpoint_response_digest: Digest32,
    pub goal_material_path: &'a Path,
    pub goal_material_digest: Digest32,
}

pub struct PlasticityFrozenNeuronEligibilityReaderV3 {
    host: Arc<AgentdNeuronRuntimeV2Host>,
    prepared: PreparedParameterCheckpointV1,
    frozen: SparseCheckpoint,
    checkpoint_response_path: PathBuf,
    checkpoint_response_digest: Digest32,
    checkpoint_response_bytes: Vec<u8>,
    goal_material_path: PathBuf,
    goal_material_digest: Digest32,
    goal_material_bytes: Vec<u8>,
}

impl PlasticityFrozenNeuronEligibilityReaderV3 {
    pub fn from_protected_sources(
        host: Arc<AgentdNeuronRuntimeV2Host>,
        inputs: &FrozenParameterCheckpointSourcesV3<'_>,
    ) -> Result<Self, AgentdError> {
        let response_bytes = crate::plasticity_process_bootstrap::protected_context_bytes(
            inputs.checkpoint_response_path,
            inputs.checkpoint_response_digest,
            crate::MAX_CONTROL_FRAME_BYTES,
        )?;
        let goal_bytes = crate::plasticity_process_bootstrap::protected_context_bytes(
            inputs.goal_material_path,
            inputs.goal_material_digest,
            MAX_NEURON_GENERATION_MATERIAL_BYTES_V2 as u64,
        )?;
        let goal = decode_neuron_generation_material_v2(&goal_bytes)
            .map_err(|e| AgentdError::Invalid(e.to_string()))?;
        validate_parameter_goal_material_projection_v3(inputs.baseline_material, &goal)?;
        let (_, prepared) = crate::decode_prepared_parameter_checkpoint_response_v3(
            &response_bytes,
            &inputs.identity.agent_id,
            inputs.identity.spawn_generation,
            inputs.round,
            &goal,
        )?;
        if prepared.baseline_material_digest != inputs.goal_material_digest {
            return Err(AgentdError::Invalid(
                "frozen checkpoint whole Goal Source differs".into(),
            ));
        }
        let frozen = prepared.checkpoint(&goal)?;
        let reader = Self {
            host,
            prepared,
            frozen,
            checkpoint_response_path: inputs.checkpoint_response_path.to_path_buf(),
            checkpoint_response_digest: inputs.checkpoint_response_digest,
            checkpoint_response_bytes: response_bytes,
            goal_material_path: inputs.goal_material_path.to_path_buf(),
            goal_material_digest: inputs.goal_material_digest,
            goal_material_bytes: goal_bytes,
        };
        reader
            .read(reader.prepared.anchor)
            .map_err(|e| AgentdError::Invalid(e.to_string()))?;
        Ok(reader)
    }

    fn revalidate_sources(&self) -> Result<(), PlasticityOwnerEvidenceErrorV1> {
        if crate::plasticity_process_bootstrap::protected_context_bytes(
            &self.checkpoint_response_path,
            self.checkpoint_response_digest,
            crate::MAX_CONTROL_FRAME_BYTES,
        )
        .map_err(|_| PlasticityOwnerEvidenceErrorV1::Unavailable)?
            != self.checkpoint_response_bytes
            || crate::plasticity_process_bootstrap::protected_context_bytes(
                &self.goal_material_path,
                self.goal_material_digest,
                MAX_NEURON_GENERATION_MATERIAL_BYTES_V2 as u64,
            )
            .map_err(|_| PlasticityOwnerEvidenceErrorV1::Unavailable)?
                != self.goal_material_bytes
        {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
        }
        Ok(())
    }

    fn revalidate_serving(&self) -> Result<(), PlasticityOwnerEvidenceErrorV1> {
        let actual = self
            .host
            .parameter_serving_scope_observation()
            .map_err(|_| PlasticityOwnerEvidenceErrorV1::Unavailable)?;
        let p = &self.prepared;
        if actual
            != (
                p.neuron_generation,
                p.configuration_digest,
                p.body_bundle_digest,
                p.scope,
                p.goal_ordinal,
            )
        {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
        }
        Ok(())
    }
}

impl PlasticityNeuronEligibilityReaderV1 for PlasticityFrozenNeuronEligibilityReaderV3 {
    fn read(
        &self,
        required_anchor: JournalAnchor,
    ) -> Result<SparseCheckpoint, PlasticityOwnerEvidenceErrorV1> {
        if required_anchor != self.prepared.anchor {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
        }
        let before = finite_round_now(&self.prepared.round)?;
        self.revalidate_sources()?;
        self.revalidate_serving()?;
        // This original getter verifies the historical ACK in the SAME held
        // history plus the full actual latest checkpoint/index/witness. Its
        // returned latest numerics are eligibility validation only.
        self.host
            .current_sparse_checkpoint_v2(
                crate::neuron_runtime_v2::AgentdNeuronGenerationIdV2::new(
                    self.prepared.neuron_generation,
                )
                .map_err(|_| PlasticityOwnerEvidenceErrorV1::InvalidReceipt)?,
                self.prepared.configuration_digest,
                self.prepared.body_bundle_digest,
                self.prepared.scope,
                required_anchor,
            )
            .map_err(|_| PlasticityOwnerEvidenceErrorV1::Unavailable)?
            .ok_or(PlasticityOwnerEvidenceErrorV1::Missing)?;
        self.revalidate_sources()?;
        self.revalidate_serving()?;
        if finite_round_now(&self.prepared.round)? < before {
            return Err(PlasticityOwnerEvidenceErrorV1::Stale);
        }
        // These complete original Source numerics are explicitly frozen, never
        // described as the current live checkpoint.
        Ok(self.frozen.clone())
    }
}

fn finite_round_now(
    round: &AgentdSelfIterationRoundV1,
) -> Result<u64, PlasticityOwnerEvidenceErrorV1> {
    let now: u64 = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|_| PlasticityOwnerEvidenceErrorV1::Unavailable)?
        .as_millis()
        .try_into()
        .map_err(|_| PlasticityOwnerEvidenceErrorV1::Unavailable)?;
    if now < round.admitted_at_ms() || now >= round.deadline_ms() {
        return Err(PlasticityOwnerEvidenceErrorV1::Stale);
    }
    Ok(now)
}

/// The original Goal projection may change only scope and its three physical
/// namespaces. Every runtime/native/body/context limit remains whole-equal to
/// the independently registered training material.
pub fn validate_parameter_goal_material_projection_v3(
    baseline: &NeuronGenerationMaterialV2,
    goal: &NeuronGenerationMaterialV2,
) -> Result<(), AgentdError> {
    let baseline_bytes = encode_neuron_generation_material_v2(baseline)
        .map_err(|e| AgentdError::Invalid(e.to_string()))?;
    encode_neuron_generation_material_v2(goal).map_err(|e| AgentdError::Invalid(e.to_string()))?;
    let mut neutral = goal.clone();
    neutral.scope = baseline.scope;
    neutral.store_context.scope = baseline.scope;
    neutral.index_context.scope = baseline.scope;
    neutral.witness_context.scope = baseline.scope;
    neutral
        .generation_store
        .clone_from(&baseline.generation_store);
    neutral.runtime_index.clone_from(&baseline.runtime_index);
    neutral.witness.clone_from(&baseline.witness);
    if encode_neuron_generation_material_v2(&neutral)
        .map_err(|e| AgentdError::Invalid(e.to_string()))?
        != baseline_bytes
    {
        return Err(AgentdError::Invalid(
            "actual Goal projection changed whole training runtime/native/body".into(),
        ));
    }
    Ok(())
}

#[cfg(test)]
#[path = "plasticity_frozen_neuron_eligibility_reader_v3_tests.rs"]
mod tests;
