//! A distinct, pre-registration E purpose. Whole facts grant no activation.
use crate::fixed_parameter_generator_v3::ParameterRoleSourceV3;
use crate::initial_neuron_operational_source::HostResult;
use codex_hepta_learning_ledger::ReviewEvidenceWireV1;
use codex_hepta_neuron::NeuronGenerationMaterialV2;
use codex_hepta_neuron::encode_neuron_generation_material_v2;
use codex_hepta_neuron::validate_neuron_generation_material_v2;
use codex_hepta_plasticity::GeneratedParameterCandidateSetV3;
use codex_hepta_plasticity::ParameterCandidateKindV2;
use codex_hepta_plasticity::PlasticityAdmissionEvidenceV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use std::path::PathBuf;

pub const MAX_PARAMETER_PRE_REGISTRATION_REPORT_BYTES_V1: usize =
    2 * codex_hepta_neuron::MAX_NEURON_GENERATION_MATERIAL_BYTES_V2 + 64 * 1024;
pub const PARAMETER_PRE_REGISTRATION_CLAIM_V1: &str = "parameter-pre-registration;training-source-reused;no-unseen-holdout;no-primary-superiority;cpu-abstention-only";

#[derive(Clone, Copy, Debug, Deserialize, Serialize, Eq, PartialEq)]
pub enum ParameterPreRegistrationPurposeV1 {
    Candidate,
    ExactRollback,
}
#[derive(Clone, Debug, Deserialize, Serialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct ParameterPreRegistrationRoundV1 {
    pub round_digest: String,
    pub canonical_policy_digest: String,
    pub execution_digest: String,
    pub round_payload_digest: String,
    pub admitted_at_ms: u64,
    pub deadline_ms: u64,
}
impl ParameterPreRegistrationRoundV1 {
    pub(super) fn validate(&self, now: u64) -> HostResult<()> {
        for pin in [
            &self.round_digest,
            &self.canonical_policy_digest,
            &self.execution_digest,
            &self.round_payload_digest,
        ] {
            let actual: Digest32 = pin.parse()?;
            if actual.is_zero() || actual.to_string() != *pin {
                return Err("whole original admitted Round digest".into());
            }
        }
        if self.admitted_at_ms == 0 || self.admitted_at_ms > now || now >= self.deadline_ms {
            return Err("original pre-registration Round admission/deadline".into());
        }
        Ok(())
    }
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FixedParameterPreRegistrationConfigV1 {
    pub schema: String,
    pub uid: u32,
    pub gid: u32,
    pub program_digest: String,
    pub private_key_path: PathBuf,
    pub reviewer_id: String,
    pub root_verifying_key_hex: String,
    pub source_configuration: ParameterRoleSourceV3,
    pub current_learning_trust: ParameterRoleSourceV3,
    pub baseline_material: ParameterRoleSourceV3,
    pub baseline_registration: ParameterRoleSourceV3,
    pub baseline_head_manifest: ParameterRoleSourceV3,
    pub baseline_head_admission_digest: String,
    pub prospective_material: ParameterRoleSourceV3,
    pub profile: ParameterRoleSourceV3,
    pub admission: ParameterRoleSourceV3,
    pub generator_evidence: ReviewEvidenceWireV1,
    pub observer_evidence: ReviewEvidenceWireV1,
    pub subject: String,
    pub candidate_id: String,
    pub purpose: ParameterPreRegistrationPurposeV1,
    pub round: ParameterPreRegistrationRoundV1,
    pub maximum_resident_bytes: u64,
    pub inaccessible_paths: Vec<PathBuf>,
}

/// The shared original sparse rules determine all eight allowed parameters.
/// No process, physical store, signing key or current capability is opened.
pub fn validate_parameter_pre_registration_material_v1(
    baseline: &NeuronGenerationMaterialV2,
    prospective: &NeuronGenerationMaterialV2,
    generated: &GeneratedParameterCandidateSetV3,
    admission: &PlasticityAdmissionEvidenceV1,
    candidate_id: &StableId,
    purpose: ParameterPreRegistrationPurposeV1,
) -> HostResult<()> {
    validate_neuron_generation_material_v2(baseline)?;
    validate_neuron_generation_material_v2(prospective)?;
    let candidate = generated
        .candidates
        .iter()
        .find(|candidate| {
            candidate.kind == ParameterCandidateKindV2::Update
                && &candidate.candidate_id == candidate_id
        })
        .ok_or("pre-registration candidate is not an original generated Update")?;
    let expected_native = match purpose {
        ParameterPreRegistrationPurposeV1::Candidate => {
            codex_hepta_neuron::apply_sparse_parameter_deltas_v1(
                &baseline.native,
                admission.candidate_generation,
                &candidate.parameter_deltas,
            )?
        }
        ParameterPreRegistrationPurposeV1::ExactRollback => {
            let mut original = baseline.native.clone();
            original.generation = admission.candidate_generation.next()?;
            original
        }
    };
    if prospective.native != expected_native
        || baseline.runtime.generation != admission.baseline_generation
        || baseline.native.model_digest != admission.selected_artifact_digest
        || baseline.scope != prospective.scope
        || prospective.scope.objective_digest != admission.objective_digest
        || prospective.model_manifest != baseline.model_manifest
        || prospective.model_manifest_digest != baseline.model_manifest_digest
    {
        return Err("pre-registration whole sparse delta/baseline/lineage/purpose".into());
    }
    let mut normalized = prospective.runtime.clone();
    normalized.config_id = baseline.runtime.config_id.clone();
    normalized.generation = baseline.runtime.generation;
    normalized.native_config_digest = baseline.runtime.native_config_digest;
    normalized.calibration.generation = baseline.runtime.calibration.generation;
    normalized.calibration.calibration_artifact_digest =
        baseline.runtime.calibration.calibration_artifact_digest;
    normalized.calibration.ood_artifact_digest = baseline.runtime.calibration.ood_artifact_digest;
    normalized.calibration.measured_ece_ppm = baseline.runtime.calibration.measured_ece_ppm;
    normalized.calibration.measured_false_acceptance_ppm =
        baseline.runtime.calibration.measured_false_acceptance_ppm;
    let mut body = prospective.body.clone();
    body.body_generation = baseline.body.body_generation;
    body.effective_parameter_digest = baseline.body.effective_parameter_digest;
    let mut store = prospective.store_context.clone();
    store.generation = baseline.store_context.generation;
    store.runtime_config_digest = baseline.store_context.runtime_config_digest;
    store.body_bundle_digest = baseline.store_context.body_bundle_digest;
    let mut index = prospective.index_context.clone();
    index.generation = baseline.index_context.generation;
    index.runtime_config_digest = baseline.index_context.runtime_config_digest;
    index.body_bundle_digest = baseline.index_context.body_bundle_digest;
    let mut witness = prospective.witness_context.clone();
    witness.generation = baseline.witness_context.generation;
    if normalized != baseline.runtime
        || body != baseline.body
        || store != baseline.store_context
        || index != baseline.index_context
        || witness != baseline.witness_context
        || [
            &prospective.generation_store,
            &prospective.runtime_index,
            &prospective.witness,
        ]
        .iter()
        .any(|path| {
            [
                &baseline.generation_store,
                &baseline.runtime_index,
                &baseline.witness,
            ]
            .contains(path)
        })
    {
        return Err(
            "pre-registration changed frozen head/body/policy/limits or reused stores".into(),
        );
    }
    Ok(())
}

/// Freeze actual measured calibration values using the original non-circular
/// artifact payloads. This computation alone is not evaluator evidence.
pub fn finalize_parameter_pre_registration_material_v1(
    prospective: &NeuronGenerationMaterialV2,
    measured_ece_ppm: u32,
    measured_false_acceptance_ppm: u32,
) -> HostResult<NeuronGenerationMaterialV2> {
    let mut material = prospective.clone();
    material.runtime.calibration.measured_ece_ppm = measured_ece_ppm;
    material.runtime.calibration.measured_false_acceptance_ppm = measured_false_acceptance_ppm;
    material.runtime.calibration.calibration_artifact_digest =
        Digest32::of_bytes(&material.runtime.calibration_evidence_payload_v1()?);
    material.runtime.calibration.ood_artifact_digest =
        Digest32::of_bytes(&material.runtime.ood_evidence_payload_v1()?);
    material.body.effective_parameter_digest = material.runtime.execution_profile_digest_v1()?;
    let runtime = material.runtime.semantic_digest()?;
    let body = material.body.semantic_digest()?;
    material.store_context.runtime_config_digest = runtime;
    material.store_context.body_bundle_digest = body;
    material.index_context.runtime_config_digest = runtime;
    material.index_context.body_bundle_digest = body;
    validate_neuron_generation_material_v2(&material)?;
    encode_neuron_generation_material_v2(&material)?;
    Ok(material)
}

#[cfg(test)]
#[path = "parameter_pre_registration_tests_v1.rs"]
mod tests;
