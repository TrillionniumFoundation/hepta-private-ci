//! Exact frozen Circuit/Cell protocol with one declared model substitution.
//! This code compares declarations and original reads; it cannot construct a
//! PublishedTask, inference permit, Root grant, worker or writable Cell.

use codex_hepta_automation::BoundedCircuitDefinitionV2;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use codex_hepta_learning_ledger::RunStartRecordV1;

use super::Error;
use super::OriginalCircuitOnPolicyCohortConfigV1;
use super::contract::push_bytes;
use super::contract::push_id;
use crate::CircuitCellBindingV1;
use crate::CircuitCellRegistryV1;
use crate::CircuitTaskSourcePublicationV1;
use crate::CellQ24FeatureWorkerV1;
use crate::circuit_cell_route_policy_digest_v1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCircuitOnPolicyProtocolV1 {
    pub circuit: BoundedCircuitDefinitionV2,
    pub binding: CircuitCellBindingV1,
    pub admission: OriginalCircuitOnPolicyAdmissionV1,
    pub objective_semantic_bytes: Vec<u8>,
    pub objective_function_v1_bytes: Vec<u8>,
}

impl OriginalCircuitOnPolicyProtocolV1 {
    pub fn canonical_digest(&self) -> Result<Digest32, Error> {
        let _ = CircuitCellRegistryV1::new(self.circuit.clone(), vec![self.binding.clone()])
            .map_err(|_| Error::Binding("complete frozen original Circuit/Cell protocol"))?;
        if self.objective_semantic_bytes.is_empty()
            || self.objective_semantic_bytes.len() > 65_536
            || self.objective_function_v1_bytes.is_empty()
            || self.objective_function_v1_bytes.len() > 65_536
        {
            return Err(Error::Binding("complete original objective protocol"));
        }
        let mut bytes = b"hepta.circuit.original-on-policy-protocol.v1\0".to_vec();
        let circuit = serde_json::to_vec(&self.circuit)
            .map_err(|_| Error::Binding("canonical original Circuit protocol"))?;
        push_bytes(&mut bytes, &circuit);
        bytes.extend_from_slice(self.binding.cell.semantic_digest()
            .map_err(|_| Error::Binding("frozen original Cell protocol"))?.as_array());
        push_bytes(&mut bytes, &self.objective_semantic_bytes);
        push_bytes(&mut bytes, &self.objective_function_v1_bytes);
        self.admission.commit(&mut bytes)?;
        bytes.push(0); // Existing Q24 reset-only / actual FreshEmpty profile.
        Ok(Digest32::of_bytes(&bytes))
    }

    pub(super) fn require_objective(&self, objective: Digest32) -> Result<(), Error> {
        self.canonical_digest()?;
        if Digest32::of_bytes(&self.objective_semantic_bytes) != objective {
            return Err(Error::Binding("frozen original objective semantic bytes"));
        }
        Ok(())
    }

    pub(super) fn require_publication(&self, actual: &CircuitTaskSourcePublicationV1)
        -> Result<(), Error>
    {
        self.admission.require_original(actual.original_record())?;
        if actual.original_record().objective_semantic_bytes != self.objective_semantic_bytes
            || actual.original_record().objective_function_v1_bytes != self.objective_function_v1_bytes
        {
            return Err(Error::Binding("exact original arm objective protocol"));
        }
        Ok(())
    }
}

/// Fill the sole candidate model slot from the original T's opaque material.
/// This is deterministic: the actual signed T bundle is the only candidate,
/// and no B row, reward, model output, or new capability enters the substitution.
pub(super) fn candidate_definition(
    config: &OriginalCircuitOnPolicyCohortConfigV1,
) -> Result<BoundedCircuitDefinitionV2, Error> {
    let protocol = &config.rule.protocol;
    let baseline = &config.training.request.selected_bundle;
    let selected = baseline.digest()
        .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?;
    let original = &protocol.binding.cell;
    let runtime = &original.runtime;
    let components = &baseline.components;
    if original.bundle_digest != selected
        || original.state_schema_digest != components.state_schema
        || runtime.model_id != baseline.artifact_id
        || runtime.model_manifest_digest != selected
        || runtime.generation != baseline.generation
        || runtime.encoder_digest != components.encoder
        || runtime.head_digest != components.heads
        || runtime.tokenizer_digest != components.tokenizer
        || runtime.preprocessor_digest != components.normalizer
        || runtime.normalization_digest != components.normalizer
        || runtime.quantization_digest != components.numeric_profile
        || runtime.runtime_digest != CellQ24FeatureWorkerV1::runtime_profile_digest()
        || runtime.input_feature_dimension != config.candidate.model().input_width()
        || runtime.state_width != config.candidate.model().output_width()
    {
        return Err(Error::Binding("frozen baseline and unchanged Q24 protocol"));
    }
    let bundle = config.candidate.bundle();
    let digest = bundle.digest()
        .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?;
    let mut binding = protocol.binding.clone();
    binding.cell.bundle_digest = digest;
    binding.cell.runtime.model_id = bundle.artifact_id.clone();
    binding.cell.runtime.model_manifest_digest = digest;
    binding.cell.runtime.generation = bundle.generation;
    binding.cell.runtime.head_digest = bundle.components.heads;
    binding.cell.runtime.weights_digest = config.candidate.model().effective_weights_digest();
    let mut circuit = protocol.circuit.clone();
    circuit.parameter_bundle_digest = Sha256Digest::parse(digest.to_string())
        .map_err(|_| Error::Binding("original candidate bundle identity"))?;
    circuit.route_policy_digest = circuit_cell_route_policy_digest_v1(&[binding.clone()])
        .map_err(|_| Error::Binding("same frozen route with original candidate model"))?;
    let registry = CircuitCellRegistryV1::new(circuit, vec![binding])
        .map_err(|_| Error::Binding("actual candidate protocol substitution"))?;
    Ok(registry.definition().clone())
}


/// Frozen original outer RunStart semantics. Its model tuple is the original
/// authenticated task snapshot, not a value rewritten from a candidate model.
/// Each arm still needs its own actual admission and existing execution grant.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCircuitOnPolicyAdmissionV1 {
    pub profile_id: StableId,
    pub profile_revision: u64,
    pub profile_digest: Digest32,
    pub hard_constraint_digest: Digest32,
    pub preference_state_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub prompt_registry_digest: Digest32,
    pub artifact_set_digest: Digest32,
    pub authority_epoch: u64,
    pub generation: u64,
    pub fence_digest: Digest32,
}

impl OriginalCircuitOnPolicyAdmissionV1 {
    fn commit(&self, bytes: &mut Vec<u8>) -> Result<(), Error> {
        if self.profile_revision == 0 || self.generation == 0 || self.profile_digest.is_zero() {
            return Err(Error::Binding("complete original admission protocol"));
        }
        push_id(bytes, &self.profile_id);
        for value in [self.profile_revision, self.authority_epoch, self.generation] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        for digest in [
            self.profile_digest, self.hard_constraint_digest, self.preference_state_digest,
            self.model_tuple_digest, self.prompt_registry_digest, self.artifact_set_digest,
            self.fence_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        Ok(())
    }

    fn require_original(&self, record: &RunStartRecordV1) -> Result<(), Error> {
        let snapshot = &record.snapshot;
        if record.admission.profile_id != self.profile_id
            || record.admission.profile_revision != self.profile_revision
            || record.admission.profile_digest != self.profile_digest
            || snapshot.hard_constraint_digest != self.hard_constraint_digest
            || snapshot.preference_state_digest != self.preference_state_digest
            || snapshot.model_tuple_digest != self.model_tuple_digest
            || snapshot.prompt_registry_digest != self.prompt_registry_digest
            || snapshot.artifact_set_digest != self.artifact_set_digest
            || snapshot.authority_epoch != self.authority_epoch
            || snapshot.generation != self.generation
            || snapshot.fence_digest != self.fence_digest
        {
            return Err(Error::Binding("all original RunStart protocol fields equal the preregistration"));
        }
        Ok(())
    }
}
