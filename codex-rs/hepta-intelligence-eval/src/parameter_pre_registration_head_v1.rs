//! Native numeric head is a real registered artifact, distinct from model weights.
use crate::fixed_parameter_generator_v3::ParameterRoleSourceV3;
use crate::initial_neuron_operational_source::HostResult;
use crate::operational_registered_model_v3::RegisteredArtifactCurrentFactsV3;
use crate::parameter_pre_registration_policy_v1::BaselineFactsV1;
use crate::parameter_pre_registration_v1::FixedParameterPreRegistrationConfigV1;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ValidatedArtifactManifestV2;
use codex_hepta_learning_artifacts::read_artifact_admission_by_digest;
use codex_hepta_learning_artifacts::validate_artifact_manifest_v2;
use codex_hepta_learning_ledger::open_root_review_input;
use codex_hepta_learning_ledger::read_root_review_input;
use codex_hepta_neuron::NeuronGenerationMaterialV2;
use codex_hepta_plasticity::PlasticityAdmissionEvidenceV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

pub(super) fn inspect_head(
    config: &FixedParameterPreRegistrationConfigV1,
    facts: &BaselineFactsV1,
    material: &NeuronGenerationMaterialV2,
    admission: &PlasticityAdmissionEvidenceV1,
    now: u64,
) -> HostResult<ValidatedArtifactManifestV2> {
    inspect_parameter_head(
        &config.baseline_head_manifest,
        config.baseline_head_admission_digest.parse()?,
        facts.current_view(),
        facts.current_head().withdrawal_scope_digest,
        facts.artifact_root(),
        material,
        &admission.baseline_id,
        admission.objective_digest,
        now,
    )
}

/// Inspect a real Root-registered numeric-head payload through the same complete
/// current owner facts. Decoded metadata alone cannot authorize this purpose.
pub fn inspect_registered_parameter_head_material_v1(
    source: &ParameterRoleSourceV3,
    admission_digest: Digest32,
    facts: &RegisteredArtifactCurrentFactsV3,
    material: &NeuronGenerationMaterialV2,
    head_id: &StableId,
    now: u64,
) -> HostResult<ValidatedArtifactManifestV2> {
    inspect_parameter_head(
        source,
        admission_digest,
        facts.current_view(),
        facts.current_head().withdrawal_scope_digest,
        facts.artifact_root(),
        material,
        head_id,
        material.scope.objective_digest,
        now,
    )
}

fn inspect_parameter_head(
    source: &ParameterRoleSourceV3,
    admission_digest: Digest32,
    view: &codex_hepta_learning_artifacts::VerifiedCurrentRegistryViewV1,
    withdrawal_scope: Digest32,
    artifact_root: &std::path::Path,
    material: &NeuronGenerationMaterialV2,
    head_id: &StableId,
    objective: Digest32,
    now: u64,
) -> HostResult<ValidatedArtifactManifestV2> {
    let bytes = source.read(128 * 1024)?;
    let packet =
        read_artifact_admission_by_digest(open_root_review_input(&source.path)?, admission_digest)?;
    let full = validate_artifact_manifest_v2(packet.validated_manifest.manifest, now)?;
    let manifest = &full.manifest;
    let current = view
        .eligible_manifest(head_id)
        .ok_or("actual native head is not independently CURRENT eligible")?;
    let profile = material.runtime.execution_profile_digest_v1()?;
    if packet.withdrawal_scope_digest != withdrawal_scope
        || &manifest.artifact_id != head_id
        || !matches!(
            manifest.kind,
            ArtifactKind::Parameters | ArtifactKind::Model
        )
        || manifest.bytes_digest != material.native.model_digest
        || manifest.bytes_digest != material.runtime.head_digest
        || manifest.generation != material.runtime.generation
        || manifest.objective_class_digest != objective
        || manifest.runtime_tuple_digest != profile
        || manifest.compatibility_digest != profile
        || manifest.device_profile_digest != material.runtime.device_digest
        || manifest.normalization_digest != material.runtime.normalization_digest
        || current.kind != manifest.kind
        || current.generation != manifest.generation
        || current.content_digest != manifest.bytes_digest
        || current.support_digest != full.manifest_digest
        || current.compatibility_digest != profile
        || current.objective_digest != manifest.objective_class_digest
        || current.encoded_size_bytes != manifest.encoded_size_bytes
        || current.producer_id != manifest.producer_id
        || manifest
            .source_dataset_digests
            .iter()
            .any(|cut| !view.supports_dataset(current, *cut))
    {
        return Err(
            "actual native-head/current/full manifest tuple differs from original O admission"
                .into(),
        );
    }
    let payload = read_root_review_input(
        &artifact_root.join("payloads").join(format!(
            "{}-{}.bin",
            manifest.artifact_id, manifest.bytes_digest
        )),
        16 * 1024 * 1024,
    )?;
    if payload.len() as u64 != manifest.encoded_size_bytes
        || Digest32::of_bytes(&payload) != manifest.bytes_digest
        || source.read(128 * 1024)? != bytes
    {
        return Err("original native-head payload or full manifest changed".into());
    }
    Ok(full)
}
