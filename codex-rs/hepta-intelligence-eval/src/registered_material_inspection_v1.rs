//! Original whole manifest validation shared by live and historical facts.
use super::*;
#[derive(Clone, Copy)]
pub(super) enum MaterialHeadV1<'a> {
    Current,
    Historical(&'a SignedCurrentArtifactHeadV1),
}
pub(super) fn manifests(
    registration: &Registration,
    plan: &NeuronGenerationMaterialV2,
    view: &VerifiedCurrentRegistryViewV1,
    head: &SignedCurrentArtifactHeadV1,
    predecessor: &Option<StableId>,
    now: u64,
) -> HostResult<(Vec<ValidatedArtifactManifestV2>, u64)> {
    let profile = plan.runtime.execution_profile_digest_v1()?;
    let material_digest = Digest32::of_bytes(&encode_neuron_generation_material_v2(plan)?);
    let expected = [
        (ArtifactKind::Model, plan.runtime.weights_digest),
        (
            ArtifactKind::Policy,
            plan.runtime.calibration.calibration_artifact_digest,
        ),
        (
            ArtifactKind::Policy,
            plan.runtime.calibration.ood_artifact_digest,
        ),
    ];
    let mut manifests: Vec<ValidatedArtifactManifestV2> = Vec::new();
    let mut expiry = head.witness.expires_at;
    for (source, (kind, payload)) in registration.manifests.iter().zip(expected) {
        source.source.read(128 * 1024)?;
        let admission = read_artifact_admission_by_digest(
            codex_hepta_learning_ledger::open_root_review_input(&source.source.path)?,
            source.admission_digest.parse()?,
        )?;
        let full = validate_artifact_manifest_v2(admission.validated_manifest.manifest, now)?;
        let manifest = &full.manifest;
        let current = view
            .eligible_manifest(&manifest.artifact_id)
            .ok_or("registered three-artifact CURRENT eligibility")?;
        if admission.withdrawal_scope_digest != head.withdrawal_scope_digest
            || manifest.kind != kind
            || manifest.generation != plan.runtime.generation
            || manifest.bytes_digest != payload
            || manifest.runtime_tuple_digest != profile
            || manifest.compatibility_digest != profile
            || manifest.device_profile_digest != plan.runtime.device_digest
            || manifest.normalization_digest != plan.runtime.normalization_digest
            || manifest.objective_class_digest != plan.scope.objective_digest
            || current.kind != kind
            || current.generation != manifest.generation
            || current.content_digest != payload
            || current.encoded_size_bytes != manifest.encoded_size_bytes
            || current.support_digest != full.manifest_digest
            || current.compatibility_digest != profile
            || current.objective_digest != manifest.objective_class_digest
            || current.producer_id != manifest.producer_id
            || current.predecessor_id.as_ref() != manifest.predecessor_ids.first()
            || manifest.predecessor_ids.len()
                != usize::from(kind == ArtifactKind::Model && predecessor.is_some())
            || manifests
                .iter()
                .any(|m| m.manifest.artifact_id == manifest.artifact_id)
            || manifest
                .source_dataset_digests
                .iter()
                .any(|dataset| !view.supports_dataset(current, *dataset))
        {
            return Err(
                "full independently current registered manifest/runtime/source tuple".into(),
            );
        }
        if kind == ArtifactKind::Model
            && (manifest.predecessor_ids.first() != predecessor.as_ref()
                || !manifest
                    .lineage_digests
                    .contains(&plan.runtime.model_manifest_digest)
                || (plan.runtime.generation.get() > 1
                    && !manifest.lineage_digests.contains(&material_digest)))
        {
            return Err("actual model predecessor/whole model source".into());
        }
        source.source.read(128 * 1024)?;
        expiry = expiry.min(manifest.expires_at);
        manifests.push(full);
    }
    Ok((manifests, expiry))
}
