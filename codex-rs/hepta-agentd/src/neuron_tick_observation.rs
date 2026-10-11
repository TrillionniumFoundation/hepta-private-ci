//! Digest-only observation of one ACTUALLY COMMITTED Agentd Neuron tick.
//!
//! Agentd constructs this only after inference.control -> NeuronRuntime::tick
//! succeeded and the independent Journal witness acknowledges the checkpoint.
//! Inputs are never copied into the output; there are no labels, outcomes,
//! selected-route claims, NDU gains or execution authority here.

use codex_hepta_neuron::NeuronLocalCheckpointBindingV1;
use codex_hepta_neuron::NeuronRuntimeError;
use codex_hepta_neuron::NeuronRuntimeOutputV1;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const DOMAIN: &[u8] = b"hepta.agentd.neuron.tick-observation.diagnostic.v1\0";
const OUTPUT_DOMAIN: &[u8] = b"hepta.agentd.neuron.real-tick-output.v1\0";
const PPM: u32 = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdNeuronTickObservationV1 {
    pub tick_id: StableId,
    /// Digest of the original feature-bearing input, without its Q24 bytes.
    pub input_digest: Digest32,
    pub input_feature_digest: Digest32,
    pub scope_digest: Digest32,
    pub objective_digest: Digest32,
    pub ndu_snapshot_digest: Digest32,
    pub generation: Generation,
    pub logical_sequence: u64,
    pub checkpoint_before: Digest32,
    pub checkpoint_after: Digest32,
    /// Includes complete local model config and independently acknowledged state.
    pub local_checkpoint_binding_digest: Digest32,
    /// Recomputed from the real returned runtime/model tuple, not caller metadata.
    pub model_runtime_digest: Digest32,
    /// Commits every returned sparse-tick field and full signal vector.
    pub observed_output_digest: Digest32,
    pub execution_micros: u64,
    pub queue_age_micros: u64,
    pub observed_memory_bytes: u64,
    pub transient_allocation_bytes: u64,
    pub confidence_ppm: u32,
    pub ood_ppm: u32,
    pub abstain: bool,
    pub diagnostic_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl AgentdNeuronTickObservationV1 {
    #[must_use]
    pub fn computed_digest(&self) -> Digest32 {
        let mut b = DOMAIN.to_vec();
        push_id(&mut b, &self.tick_id);
        for digest in [
            self.input_digest,
            self.input_feature_digest,
            self.scope_digest,
            self.objective_digest,
            self.ndu_snapshot_digest,
        ] {
            b.extend_from_slice(digest.as_array());
        }
        for number in [self.generation.get(), self.logical_sequence] {
            b.extend_from_slice(&number.to_be_bytes());
        }
        for digest in [
            self.checkpoint_before,
            self.checkpoint_after,
            self.local_checkpoint_binding_digest,
            self.model_runtime_digest,
            self.observed_output_digest,
        ] {
            b.extend_from_slice(digest.as_array());
        }
        for number in [
            self.execution_micros,
            self.queue_age_micros,
            self.observed_memory_bytes,
            self.transient_allocation_bytes,
        ] {
            b.extend_from_slice(&number.to_be_bytes());
        }
        b.extend_from_slice(&self.confidence_ppm.to_be_bytes());
        b.extend_from_slice(&self.ood_ppm.to_be_bytes());
        b.push(u8::from(self.abstain));
        Digest32::of_bytes(&b)
    }

    /// Self-consistency, NOT an independent signature. Historical no-change
    /// proof requires this receipt to be stored by a trusted independent owner,
    /// joined to an actual Ledger Decision and a current selected production route.
    #[must_use]
    pub fn validate_integrity(&self) -> bool {
        self.authority == AuthorityPosture::DENY_ALL
            && self.logical_sequence > 0
            && !self.input_digest.is_zero()
            && !self.input_feature_digest.is_zero()
            && !self.scope_digest.is_zero()
            && !self.objective_digest.is_zero()
            && !self.ndu_snapshot_digest.is_zero()
            && !self.checkpoint_after.is_zero()
            && !self.local_checkpoint_binding_digest.is_zero()
            && !self.model_runtime_digest.is_zero()
            && !self.observed_output_digest.is_zero()
            && self.confidence_ppm <= PPM
            && self.ood_ppm <= PPM
            && self.diagnostic_digest == self.computed_digest()
    }
}

pub(crate) fn from_actual_committed_tick(
    input: &NeuronTickInputV1,
    input_digest: Digest32,
    output: &NeuronRuntimeOutputV1,
    witnessed: &NeuronLocalCheckpointBindingV1,
) -> Result<AgentdNeuronTickObservationV1, NeuronRuntimeError> {
    if !witnessed.validate_integrity()
        || output.tick.tick_id != input.tick_id
        || output.signal.signal_set_id != input.tick_id
        || output.tick.checkpoint_before != input.checkpoint_digest
        || output.tick.checkpoint_after != witnessed.anchor.checkpoint_digest
        || witnessed.anchor.sequence != input.logical_sequence
        || input
            .body_generation
            .is_some_and(|generation| generation != witnessed.config.generation.get())
        || witnessed.scope.objective_digest != input.objective_digest
        || output.model_runtime.model_id != witnessed.config.model_id
        || output.model_runtime.weights_digest != witnessed.config.weights_digest
        || output.tick.ood_ppm != output.signal.ood_ppm
        || output.tick.abstain != output.signal.abstain
        || output.tick.sparsity_ppm != output.signal.activation_sparsity_ppm
        || output.signal.authority != AuthorityPosture::DENY_ALL
    {
        return Err(NeuronRuntimeError::ModelBindingMismatch);
    }
    let model_runtime_digest = output.model_runtime.semantic_digest()?;
    let observed_output_digest = canonical_observed_output_digest(output)?;
    let mut diagnostic = AgentdNeuronTickObservationV1 {
        tick_id: input.tick_id.clone(),
        input_digest,
        input_feature_digest: input.input_feature_digest,
        scope_digest: witnessed.scope.scope_digest,
        objective_digest: input.objective_digest,
        ndu_snapshot_digest: input.ndu_snapshot_digest,
        generation: witnessed.config.generation,
        logical_sequence: input.logical_sequence,
        checkpoint_before: input.checkpoint_digest,
        checkpoint_after: output.tick.checkpoint_after,
        local_checkpoint_binding_digest: witnessed.binding_digest,
        model_runtime_digest,
        observed_output_digest,
        execution_micros: output.tick.resource_receipt.execution_micros,
        queue_age_micros: output.tick.resource_receipt.queue_age_micros,
        observed_memory_bytes: output.model_runtime.resident_bytes,
        transient_allocation_bytes: output.tick.resource_receipt.transient_allocation_bytes,
        confidence_ppm: output.tick.confidence_ppm,
        ood_ppm: output.tick.ood_ppm,
        abstain: output.tick.abstain,
        diagnostic_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    diagnostic.diagnostic_digest = diagnostic.computed_digest();
    if !diagnostic.validate_integrity() {
        return Err(NeuronRuntimeError::ModelBindingMismatch);
    }
    Ok(diagnostic)
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    let raw = id.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn canonical_observed_output_digest(
    output: &NeuronRuntimeOutputV1,
) -> Result<Digest32, NeuronRuntimeError> {
    if output.signal.authority != AuthorityPosture::DENY_ALL
        || output.signal.signal_set_id != output.tick.tick_id
        || output.tick.abstain != output.signal.abstain
        || output.tick.ood_ppm != output.signal.ood_ppm
        || output.tick.sparsity_ppm != output.signal.activation_sparsity_ppm
    {
        return Err(NeuronRuntimeError::ModelOutputMismatch);
    }
    let mut bytes = OUTPUT_DOMAIN.to_vec();
    push_id(&mut bytes, &output.tick.tick_id);
    for digest in [
        output.tick.checkpoint_before,
        output.tick.checkpoint_after,
        output.tick.activation_digest,
        output.tick.threshold_digest,
        output.tick.eligibility_digest,
        output.signal.model_runtime_digest,
        output.signal.temporal_state_digest,
        output.model_runtime.semantic_digest()?,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&(output.tick.active_indices.len() as u64).to_be_bytes());
    for index in &output.tick.active_indices {
        bytes.extend_from_slice(&index.to_be_bytes());
    }
    for number in [
        output.tick.sparsity_ppm,
        output.tick.confidence_ppm,
        output.tick.ood_ppm,
    ] {
        bytes.extend_from_slice(&number.to_be_bytes());
    }
    bytes.extend_from_slice(&output.tick.prediction_error_q24.to_be_bytes());
    bytes.push(u8::from(output.tick.abstain));
    let resource = &output.tick.resource_receipt;
    for number in [
        resource.execution_micros,
        resource.transient_allocation_bytes,
        resource.checkpoint_bytes,
        resource.journal_bytes_written,
        resource.queue_age_micros,
    ] {
        bytes.extend_from_slice(&number.to_be_bytes());
    }
    for number in [resource.write_amplification_ppm, resource.saturation_count] {
        bytes.extend_from_slice(&number.to_be_bytes());
    }
    bytes.extend_from_slice(&(output.signal.signals_q24.len() as u64).to_be_bytes());
    for value in &output.signal.signals_q24 {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}
