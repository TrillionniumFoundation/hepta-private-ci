//! Construct four complete manifests from the original authenticated E1 material.
//! Calibration/OOD payloads are the actual new runtime's sole original codecs.
use super::*;
use codex_hepta_neuron::encode_neuron_generation_material_v2;

pub(super) fn evaluation(
    config: &ParameterPreRegistrationPublicationConfigV1,
    historical: bool,
) -> HostResult<VerifiedParameterPreRegistrationEvaluationV1> {
    let sources = &config.evaluation;
    if historical {
        inspect_parameter_pre_registration_history_v1(
            &sources.configuration.path,
            digest(&sources.configuration.digest)?,
            &sources.report.path,
            digest(&sources.report.digest)?,
        )
    } else {
        inspect_parameter_pre_registration_evaluation_v1(
            &sources.configuration.path,
            digest(&sources.configuration.digest)?,
            &sources.report.path,
            digest(&sources.report.digest)?,
        )
    }
}
pub(super) fn revalidate(
    evaluation: &VerifiedParameterPreRegistrationEvaluationV1,
    historical: bool,
) -> HostResult<()> {
    if historical {
        evaluation.revalidate_after_registration()
    } else {
        evaluation.revalidate_before_registration()
    }
}
fn raw(source: &ParameterRoleSourceV3, maximum: u64) -> HostResult<Vec<u8>> {
    Source {
        path: source.path.clone(),
        digest: source.digest.clone(),
    }
    .read(maximum)
}
pub(super) fn operation(
    evaluation: &VerifiedParameterPreRegistrationEvaluationV1,
    manifest: &LearningArtifactManifestV2,
) -> HostResult<StableId> {
    let full = validate_artifact_manifest_v2(manifest.clone(), now_ms()?)?;
    id(&format!(
        "parameter.publish:{}",
        Digest32::of_parts(&[
            b"hepta.original-artifact-owner.parameter-e1-publication.v1",
            evaluation.authentication_digest().as_array(),
            full.manifest_digest.as_array(),
            digest(&evaluation.round().round_digest)?.as_array(),
        ])
    ))
}
pub(super) fn derive(
    config: &ParameterPreRegistrationPublicationConfigV1,
    inputs: &super::super::Inputs,
    evaluation: &VerifiedParameterPreRegistrationEvaluationV1,
) -> HostResult<[(LearningArtifactManifestV2, Vec<u8>); 4]> {
    let raw_config: FixedParameterPreRegistrationConfigV1 = serde_json::from_slice(&raw(
        &ParameterRoleSourceV3 {
            path: config.evaluation.configuration.path.clone(),
            digest: config.evaluation.configuration.digest.clone(),
        },
        64 * 1024,
    )?)?;
    if config.baseline_registration.path != raw_config.baseline_registration.path
        || config.baseline_registration.digest != raw_config.baseline_registration.digest
        || raw_config.subject != evaluation.subject().as_str()
    {
        return Err("original signed E1 baseline Source/subject changed".into());
    }
    let mut predecessor_model = evaluation.baseline_artifact_id().clone();
    let mut predecessor_head = evaluation.baseline_head_artifact_id().clone();
    match (evaluation.purpose(), &config.candidate_predecessor) {
        (ParameterPreRegistrationPurposeV1::Candidate, None) => (),
        (ParameterPreRegistrationPurposeV1::ExactRollback, Some(previous)) => {
            let prior = inspect_parameter_pre_registration_history_v1(
                &previous.evaluation.configuration.path,
                digest(&previous.evaluation.configuration.digest)?,
                &previous.evaluation.report.path,
                digest(&previous.evaluation.report.digest)?,
            )?;
            if prior.purpose() != ParameterPreRegistrationPurposeV1::Candidate
                || prior.round() != evaluation.round()
                || prior.subject() != evaluation.subject()
                || prior.candidate_id() != evaluation.candidate_id()
                || prior.baseline_artifact_id() != evaluation.baseline_artifact_id()
                || prior.baseline_head_artifact_id() != evaluation.baseline_head_artifact_id()
                || prior
                    .material()
                    .ok_or("candidate E1 material absent")?
                    .runtime
                    .generation
                    .next()?
                    != evaluation
                        .material()
                        .ok_or("rollback E1 material absent")?
                        .runtime
                        .generation
            {
                return Err(
                    "rollback must follow the exact same completed candidate/E1 round".into(),
                );
            }
            let prior_plans = manifests(
                inputs,
                &prior,
                &config.head_payload,
                prior.baseline_artifact_id(),
                prior.baseline_head_artifact_id(),
            )?;
            let current = inputs.current()?.current_registry_view(now_ms()?)?;
            for (manifest, _) in &prior_plans {
                let expected = validate_artifact_manifest_v2(manifest.clone(), now_ms()?)?;
                let sidecar = inputs
                    .profile
                    .owner_root
                    .join("admissions")
                    .join(format!("{}.manifest", expected.manifest_digest));
                let actual = read_artifact_admission_by_manifest_digest(
                    std::fs::File::open(sidecar)?,
                    expected.manifest_digest,
                )?;
                let eligible = current
                    .eligible_manifest(&manifest.artifact_id)
                    .ok_or("original candidate publication is not CURRENT eligible")?;
                if actual.validated_manifest != expected
                    || eligible.support_digest != expected.manifest_digest
                    || eligible.content_digest != manifest.bytes_digest
                    || eligible.generation != manifest.generation
                {
                    return Err("actual whole candidate publication differs before rollback".into());
                }
            }
            predecessor_model = prior_plans[0].0.artifact_id.clone();
            predecessor_head = prior_plans[3].0.artifact_id.clone();
            if previous.head_artifact_id != predecessor_head.as_str() {
                return Err("actual candidate numeric-head predecessor changed".into());
            }
            prior.revalidate_after_registration()?;
        }
        _ => return Err("publication candidate/rollback predecessor purpose".into()),
    }
    manifests(
        inputs,
        evaluation,
        &config.head_payload,
        &predecessor_model,
        &predecessor_head,
    )
}
fn manifests(
    inputs: &super::super::Inputs,
    evaluation: &VerifiedParameterPreRegistrationEvaluationV1,
    head: &ParameterRoleSourceV3,
    predecessor_model: &StableId,
    predecessor_head: &StableId,
) -> HostResult<[(LearningArtifactManifestV2, Vec<u8>); 4]> {
    let material = evaluation
        .material()
        .ok_or("actual E1 did not qualify update/rollback material")?;
    let weights = inputs.profile.weights.read(16 * 1024 * 1024)?;
    let head_bytes = raw(head, 16 * 1024 * 1024)?;
    if Digest32::of_bytes(&head_bytes) != material.runtime.head_digest
        || material.native.model_digest != material.runtime.head_digest
        || inputs.runtime.weights_digest != material.runtime.weights_digest
        || Digest32::of_bytes(&weights) != material.runtime.weights_digest
    {
        return Err(
            "actual E1 native head and unchanged model weights must be separately pinned".into(),
        );
    }
    let payloads = [
        weights,
        material.runtime.calibration_evidence_payload_v1()?,
        material.runtime.ood_evidence_payload_v1()?,
        head_bytes,
    ];
    if Digest32::of_bytes(&payloads[1]) != material.runtime.calibration.calibration_artifact_digest
        || Digest32::of_bytes(&payloads[2]) != material.runtime.calibration.ood_artifact_digest
    {
        return Err("E1 must supply its freshly measured calibration/OOD identities".into());
    }
    let profile = material.runtime.execution_profile_digest_v1()?;
    let material_digest = Digest32::of_bytes(&encode_neuron_generation_material_v2(material)?);
    let now = now_ms()?;
    let created = evaluation.measured_at_ms();
    let expires = evaluation.expires_at().min(inputs.profile.expires_at_ms);
    let mut result = Vec::new();
    for (index, payload) in payloads.into_iter().enumerate() {
        let identity = Digest32::of_parts(&[
            b"hepta.original-artifact-owner.parameter-e1-artifact.v1",
            evaluation.authentication_digest().as_array(),
            material_digest.as_array(),
            &[index as u8],
        ]);
        let manifest = LearningArtifactManifestV2 {
            artifact_id: id(&format!("parameter.artifact:{identity}"))?,
            kind: match index {
                0 => ArtifactKind::Model,
                3 => ArtifactKind::Parameters,
                _ => ArtifactKind::Policy,
            },
            generation: material.runtime.generation,
            provenance_mode: ProvenanceModeV1::DatasetDerived,
            source_dataset_digests: evaluation.source_dataset_digests().to_vec(),
            lineage_digests: vec![
                evaluation.evaluation_publication_digest(),
                evaluation.authentication_digest(),
                material_digest,
                material.runtime.model_manifest_digest,
            ],
            predecessor_ids: match index {
                0 => vec![predecessor_model.clone()],
                3 => vec![predecessor_head.clone()],
                _ => Vec::new(),
            },
            rollback_predecessor: (evaluation.purpose()
                == ParameterPreRegistrationPurposeV1::ExactRollback
                && matches!(index, 0 | 3))
            .then(|| {
                if index == 3 {
                    predecessor_head.clone()
                } else {
                    predecessor_model.clone()
                }
            }),
            bytes_digest: Digest32::of_bytes(&payload),
            encoded_size_bytes: payload.len() as u64,
            training_code_digest: Digest32::of_bytes(
                &inputs.profile.training_code.read(1024 * 1024)?,
            ),
            runtime_tuple_digest: profile,
            device_profile_digest: material.runtime.device_digest,
            objective_class_digest: material.scope.objective_digest,
            compatibility_digest: profile,
            schema_profile_digest: Digest32::of_bytes(b"hepta.cpu-neuron.parameter-e1-artifact.v1"),
            normalization_digest: material.runtime.normalization_digest,
            producer_id: id(&inputs.profile.owner.id)?,
            created_at: created,
            expires_at: expires,
        };
        validate_artifact_manifest_v2(manifest.clone(), now)?;
        result.push((manifest, payload));
    }
    result
        .try_into()
        .map_err(|_| "four full E1 artifact plans".into())
}
