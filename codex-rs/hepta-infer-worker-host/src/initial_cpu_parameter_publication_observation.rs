//! Completed-only recovery from the same immutable Owner facts. No signer,
//! writer lease, repair, frontier publication or native-purpose redispatch.
use super::*;

pub fn observe_parameter_pre_registered_artifacts_v1(
    path: &Path,
    pin: Digest32,
) -> HostResult<Option<ParameterPreRegisteredPublicationV1>> {
    let source = Source {
        path: path.to_owned(),
        digest: pin.to_string(),
    };
    let bytes = source.read(64 * 1024)?;
    let initial = now_ms()?;
    let config: ParameterPreRegistrationPublicationConfigV1 = serde_json::from_slice(&bytes)?;
    if config.schema != "hepta.cpu-neuron.parameter-pre-registration-publication-config.v1" {
        return Err("fixed read-only E1 publication observation purpose".into());
    }
    let inputs = super::super::Inputs::read(
        &config.original_owner.path,
        digest(&config.original_owner.digest)?,
    )?;
    if !retained::has_source(&inputs, &source)? {
        return Ok(None);
    }
    let evaluation = materials::evaluation(&config, true)?;
    let plans = materials::derive(&config, &inputs, &evaluation)?;
    let owner = inputs.current()?;
    let current = owner.current_registry_view(now_ms()?)?;
    let mut receipts = Vec::new();
    let mut last = None;
    let mut sources = Vec::new();
    let mut previous = None;
    let mut acknowledgements = Vec::new();
    for (manifest, expected_payload) in plans {
        let now = now_ms()?;
        let validated = validate_artifact_manifest_v2(manifest, now)?;
        let operation = materials::operation(&evaluation, &validated.manifest)?;
        let Some(original) = retained::read(&inputs, &operation)? else {
            return Ok(None);
        };
        let signed = original.verify(
            &inputs,
            &source,
            &evaluation,
            &operation,
            inputs.storage_binding(),
        )?;
        validate_chain(previous, &signed)?;
        let sidecar_path = inputs
            .profile
            .owner_root
            .join("admissions")
            .join(format!("{}.manifest", validated.manifest_digest));
        let Some(manifest_bytes) = existing(&sidecar_path, 128 * 1024)? else {
            return Ok(None);
        };
        let admission = read_artifact_admission_by_manifest_digest(
            std::fs::File::open(&sidecar_path)?,
            validated.manifest_digest,
        )?;
        if admission.validated_manifest != validated {
            return Err("whole original completed E1 admission differs".into());
        }
        let Some(ack) = owner.acknowledged_publication(&operation, &signed, now)? else {
            return Ok(None);
        };
        validate_complete_tuple(&operation, &signed, &admission, &ack)?;
        let eligible = current
            .eligible_manifest(&validated.manifest.artifact_id)
            .ok_or("completed original E1 artifact no longer eligible")?;
        if eligible.support_digest != validated.manifest_digest
            || eligible.content_digest != validated.manifest.bytes_digest
            || eligible.generation != validated.manifest.generation
        {
            return Err("actual current E1 admission differs from completed original".into());
        }
        let payload_path = inputs.profile.owner_root.join("payloads").join(format!(
            "{}-{}.bin",
            validated.manifest.artifact_id, validated.manifest.bytes_digest
        ));
        let Some(payload) = existing(&payload_path, 64 * 1024 * 1024)? else {
            return Ok(None);
        };
        if payload != expected_payload
            || payload.len() as u64 != validated.manifest.encoded_size_bytes
            || Digest32::of_bytes(&payload) != validated.manifest.bytes_digest
        {
            return Err("actual original completed E1 payload differs".into());
        }
        let signed_path = inputs.profile.owner_root.join("heads").join(format!(
            "{}-{}.head",
            signed.witness.generation.get(),
            Digest32::of_bytes(&signed.signing_bytes())
        ));
        let Some(signed_bytes) = existing(&signed_path, 16 * 1024)? else {
            return Ok(None);
        };
        if signed_bytes != encode_untrusted_signed_artifact_head_v1(&signed) {
            return Err("actual immutable E1 signed head differs".into());
        }
        receipts.push(ParameterPublishedArtifactV1 {
            artifact_id: validated.manifest.artifact_id.to_string(),
            manifest: CpuProtectedSourceV1 {
                path: sidecar_path.clone(),
                digest: Digest32::of_bytes(&manifest_bytes).to_string(),
            },
            admission_digest: admission.admission_digest.to_string(),
            payload: CpuProtectedSourceV1 {
                path: payload_path.clone(),
                digest: validated.manifest.bytes_digest.to_string(),
            },
            operation_id: operation.to_string(),
            current_head: signed.witness.head_digest.to_string(),
        });
        previous = Some((signed.witness.head_digest, signed.witness.generation));
        acknowledgements.push((operation.clone(), signed.clone(), ack.clone()));
        let head_source = Source {
            path: signed_path.clone(),
            digest: Digest32::of_bytes(&signed_bytes).to_string(),
        };
        sources.extend([
            (sidecar_path, manifest_bytes, 128 * 1024),
            (payload_path, payload, 64 * 1024 * 1024),
            (signed_path, signed_bytes, 16 * 1024),
        ]);
        last = Some((signed, head_source, ack));
    }
    materials::revalidate(&evaluation, true)?;
    inputs.revalidate()?;
    for (path, expected, max) in sources {
        if read_root_review_input(&path, max)? != expected {
            return Err("whole completed E1 publication Source changed".into());
        }
    }
    let final_now = now_ms()?;
    for (operation, signed, ack) in acknowledgements {
        let Some(original) = retained::read(&inputs, &operation)? else {
            return Err("completed original issuance disappeared".into());
        };
        if original.verify(
            &inputs,
            &source,
            &evaluation,
            &operation,
            inputs.storage_binding(),
        )? != signed
            || owner.acknowledged_publication(&operation, &signed, final_now)? != Some(ack)
        {
            return Err("complete original E1 terminal issuance/ACK changed".into());
        }
    }
    let latest = owner.current_registry_view(final_now)?;
    if source.read(64 * 1024)? != bytes
        || latest.receipt() != current.receipt()
        || final_now < initial
        || final_now >= evaluation.expires_at()
    {
        return Err("completed E1 original source/current/window changed".into());
    }
    let (signed, head_source, ack) = last.ok_or("four completed E1 publications absent")?;
    // Hc/op/ACK are the original terminal tuple. The independently observed H'
    // only establishes current eligibility; it never rewrites the old receipt.
    let result = packet(&config, &evaluation, receipts, &signed, head_source, &ack)?;
    let settled = now_ms()?;
    if settled < final_now
        || settled >= evaluation.expires_at()
        || settled >= evaluation.round().deadline_ms
    {
        return Err("completed E1 expired or clock rolled back during final observation".into());
    }
    Ok(Some(result))
}
fn existing(path: &Path, maximum: u64) -> HostResult<Option<Vec<u8>>> {
    match std::fs::symlink_metadata(path) {
        Ok(_) => Ok(Some(read_root_review_input(path, maximum)?)),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(error.into()),
    }
}
fn validate_chain(
    previous: Option<(Digest32, Generation)>,
    signed: &SignedCurrentArtifactHeadV1,
) -> HostResult<()> {
    if let Some((head, generation)) = previous
        && (signed.witness.predecessor_head_digest != head
            || signed.witness.generation != generation.next()?)
    {
        return Err("whole four original E1 publication chain differs".into());
    }
    Ok(())
}
fn validate_complete_tuple(
    operation: &StableId,
    signed: &SignedCurrentArtifactHeadV1,
    admission: &WithdrawalBoundArtifactAdmissionV3,
    ack: &ArtifactOwnerPublicationCheckpointV1,
) -> HostResult<()> {
    if ack.operation_id != *operation
        || ack.phase != ArtifactPublicationPhaseV1::Acknowledged
        || ack.admission_digest != admission.admission_digest
        || ack.withdrawal_scope_digest != admission.withdrawal_scope_digest
        || ack.withdrawal_head_digest != admission.withdrawal_head_digest
        || ack.expected_registry_predecessor_head != signed.witness.predecessor_head_digest
        || ack.registry_receipt.is_none_or(|receipt| {
            receipt.head_digest != signed.witness.head_digest || receipt.binding != signed.binding
        })
        || ack.acknowledged_at.is_none()
        || ack.authority.grants_any()
    {
        return Err("actual original terminal operation/admission/head/ACK tuple differs".into());
    }
    Ok(())
}
pub(super) fn packet(
    config: &ParameterPreRegistrationPublicationConfigV1,
    evaluation: &VerifiedParameterPreRegistrationEvaluationV1,
    receipts: Vec<ParameterPublishedArtifactV1>,
    signed: &SignedCurrentArtifactHeadV1,
    head_source: CpuProtectedSourceV1,
    acknowledgement: &ArtifactOwnerPublicationCheckpointV1,
) -> HostResult<ParameterPreRegisteredPublicationV1> {
    let last = receipts.last().ok_or("four E1 publications absent")?;
    if last.operation_id != acknowledgement.operation_id.as_str()
        || last.current_head != signed.witness.head_digest.to_string()
        || acknowledgement.registry_receipt.is_none_or(|r| {
            r.head_digest != signed.witness.head_digest || r.binding != signed.binding
        })
        || acknowledgement.phase != ArtifactPublicationPhaseV1::Acknowledged
        || acknowledgement.acknowledged_at.is_none()
    {
        return Err("original whole E1 terminal receipt is not self-consistent".into());
    }
    Ok(ParameterPreRegisteredPublicationV1 {
        schema: "hepta.cpu-neuron.parameter-pre-registered-publication.v1".into(),
        original_round: evaluation.round().clone(),
        purpose: evaluation.purpose(),
        candidate_id: evaluation.candidate_id().to_string(),
        material_digest: Digest32::of_bytes(
            &codex_hepta_neuron::encode_neuron_generation_material_v2(
                evaluation.material().ok_or("qualified material absent")?,
            )?,
        )
        .to_string(),
        evaluation_digest: evaluation.authentication_digest().to_string(),
        evaluation_sources: config.evaluation.clone(),
        baseline_registration: config.baseline_registration.clone(),
        pre_e1_registry_head: evaluation.baseline_registry_head().to_string(),
        pre_e1_publication_operation: evaluation.baseline_publication_operation().to_string(),
        current_head: signed.witness.head_digest.to_string(),
        publication_operation_id: acknowledgement.operation_id.to_string(),
        signed_current_head: head_source,
        acknowledgement_state_digest: acknowledgement.state_digest.to_string(),
        publications: receipts
            .try_into()
            .map_err(|_| "exact four E1 publications")?,
    })
}

#[cfg(test)]
#[path = "initial_cpu_parameter_publication_observation_tests.rs"]
mod tests;
