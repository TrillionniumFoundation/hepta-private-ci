//! Independent S purpose over actual pre-registration E and completed Root ACK.
//! These original Artifact selections authorize candidate loading, never native
//! activation or the distinct registered operational model-use purpose.
use super::*;
use codex_hepta_agent_components::intelligence_eval::*;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_neuron::NeuronGenerationMaterialV2;
use serde::Serialize;
use std::sync::Arc;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ParameterPreRegistrationEvaluationSourcesV1 {
    pub configuration: CpuProtectedSourceV1,
    pub report: CpuProtectedSourceV1,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ParameterPreRegisteredPredecessorV1 {
    pub evaluation: ParameterPreRegistrationEvaluationSourcesV1,
    pub registration: CpuProtectedSourceV1,
    pub head_manifest: ParameterRoleSourceV3,
    pub head_admission_digest: String,
    pub head_artifact_id: String,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ParameterPreRegisteredSelectorConfigV1 {
    pub schema: String,
    pub evaluation: ParameterPreRegistrationEvaluationSourcesV1,
    pub current_registration: CpuProtectedSourceV1,
    pub head_manifest: ParameterRoleSourceV3,
    pub head_admission_digest: String,
    pub head_artifact_id: String,
    pub candidate_predecessor: Option<ParameterPreRegisteredPredecessorV1>,
    pub artifact_public_trust: CpuProtectedSourceV1,
    pub selector_program: CpuProtectedSourceV1,
    pub selector: CpuIndependentRoleV1,
    pub authority_epoch: u64,
    pub workload_uid: u32,
    pub frozen_at_ms: u64,
    pub expires_at_ms: u64,
    pub inaccessible_paths: [std::path::PathBuf; 5],
}
#[derive(Clone, Debug, Deserialize, Serialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
struct Body {
    schema: String,
    configuration_digest: String,
    evaluation_digest: String,
    original_round: ParameterPreRegistrationRoundV1,
    purpose: ParameterPreRegistrationPurposeV1,
    candidate_id: String,
    subject: String,
    material_digest: String,
    model_generation: u64,
    execution_profile_digest: String,
    native_digest: String,
    body_digest: String,
    original_baseline_artifact: String,
    original_baseline_head: String,
    original_baseline_operation: String,
    artifact_ids: [String; 3],
    manifest_digests: [String; 3],
    payload_digests: [String; 3],
    current_registry_head: String,
    current_witness: String,
    current_trust: String,
    current_withdrawal_scope: String,
    publication_operation: String,
    head_artifact_id: String,
    head_manifest_digest: String,
    head_payload_digest: String,
    selector_id: String,
    selector_controller: String,
    selector_program_digest: String,
    selector_uid: u32,
    selector_gid: u32,
    authority_epoch: u64,
    issued_at_ms: u64,
    expires_at_ms: u64,
}
impl Body {
    fn signing_bytes(&self) -> HostResult<Vec<u8>> {
        let mut bytes =
            b"hepta.cpu-neuron.parameter-pre-registered-artifact-selection.v1\0".to_vec();
        bytes.extend_from_slice(&serde_json::to_vec(self)?);
        if bytes.len() > 32 * 1024 {
            return Err("bounded whole pre-registered S body".into());
        }
        Ok(bytes)
    }
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Selection {
    body: Body,
    signature_hex: String,
    artifact_signatures: [String; 4],
}
#[path = "initial_cpu_parameter_registration_policy_v1.rs"]
mod policy;
use policy::Inputs as RegistrationInputs;
#[path = "initial_cpu_parameter_registration_selection_v1.rs"]
mod operation;
pub use operation::VerifiedParameterPreRegisteredAdmissionV1;
pub use operation::inspect_parameter_pre_registered_admission_v1;
pub use operation::select_parameter_pre_registered_artifacts_v1;

fn material_bytes(material: &NeuronGenerationMaterialV2) -> HostResult<Vec<u8>> {
    Ok(codex_hepta_neuron::encode_neuron_generation_material_v2(
        material,
    )?)
}
