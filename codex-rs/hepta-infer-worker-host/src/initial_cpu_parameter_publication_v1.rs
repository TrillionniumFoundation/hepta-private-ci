//! Finite E1-authorized publication through the existing Artifact Owner.
//! The original lease, writer, transaction recovery and CURRENT ACK remain sole.
use super::*;
use codex_hepta_agent_components::intelligence_eval::*;
use serde::Serialize;

#[path = "initial_cpu_parameter_publication_materials.rs"]
mod materials;
#[path = "initial_cpu_parameter_publication_observation.rs"]
mod observation;
#[path = "initial_cpu_parameter_publication_state.rs"]
mod retained;
pub use observation::observe_parameter_pre_registered_artifacts_v1;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ParameterPreRegistrationPublicationConfigV1 {
    pub schema: String,
    pub original_owner: CpuProtectedSourceV1,
    pub evaluation: ParameterPreRegistrationEvaluationSourcesV1,
    pub baseline_registration: CpuProtectedSourceV1,
    pub head_payload: ParameterRoleSourceV3,
    pub candidate_predecessor: Option<ParameterPreRegisteredPredecessorV1>,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ParameterPublishedArtifactV1 {
    pub artifact_id: String,
    pub manifest: CpuProtectedSourceV1,
    pub admission_digest: String,
    pub payload: CpuProtectedSourceV1,
    pub operation_id: String,
    pub current_head: String,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ParameterPreRegisteredPublicationV1 {
    pub schema: String,
    pub original_round: ParameterPreRegistrationRoundV1,
    pub purpose: ParameterPreRegistrationPurposeV1,
    pub candidate_id: String,
    pub material_digest: String,
    pub evaluation_digest: String,
    pub evaluation_sources: ParameterPreRegistrationEvaluationSourcesV1,
    pub baseline_registration: CpuProtectedSourceV1,
    pub pre_e1_registry_head: String,
    pub pre_e1_publication_operation: String,
    pub publications: [ParameterPublishedArtifactV1; 4],
    pub current_head: String,
    pub publication_operation_id: String,
    pub signed_current_head: CpuProtectedSourceV1,
    pub acknowledgement_state_digest: String,
}

pub(super) fn validate_retained_directory(profile: &Profile) -> HostResult<()> {
    retained::validate_directory(profile)
}
pub(super) fn retained_floor(
    inputs: &super::Inputs,
    binding: Digest32,
) -> HostResult<Option<SignedCurrentArtifactHeadV1>> {
    retained::floor(inputs, binding)
}

pub fn publish_parameter_pre_registered_artifacts_v1(
    path: &Path,
    pin: Digest32,
) -> HostResult<Value> {
    let source = Source {
        path: path.to_owned(),
        digest: pin.to_string(),
    };
    let bytes = source.read(64 * 1024)?;
    let config: ParameterPreRegistrationPublicationConfigV1 = serde_json::from_slice(&bytes)?;
    if config.schema != "hepta.cpu-neuron.parameter-pre-registration-publication-config.v1" {
        return Err("fixed E1 publication purpose".into());
    }
    let inputs = Inputs::read(
        &config.original_owner.path,
        digest(&config.original_owner.digest)?,
    )?;
    // This native purpose owns the original Root key; callers receive only
    // complete public facts. Reusing bootstrap does not replace its old lease.
    let key = role::actual_role(&inputs, &inputs.profile.owner)?;
    let recovering = retained::has_source(&inputs, &source)?;
    let evaluation = materials::evaluation(&config, recovering)?;
    let plans = materials::derive(&config, &inputs, &evaluation)?;
    let mut service = publication::open_original(&inputs, &key, inputs.profile.withdrawals()?)?;
    let binding = inputs.storage_binding();
    let mut receipts = Vec::new();
    for (index, (manifest, payload)) in plans.into_iter().enumerate() {
        let operation = materials::operation(&evaluation, &manifest)?;
        let existing = retained::read(&inputs, &operation)?;
        let historical = recovering || existing.is_some() || index > 0;
        let observed = materials::evaluation(&config, historical)?;
        if observed.authentication_digest() != evaluation.authentication_digest()
            || observed.round() != evaluation.round()
            || source.read(64 * 1024)? != bytes
        {
            return Err("whole original E1/round/publication source changed".into());
        }
        materials::revalidate(&observed, historical)?;
        let now = now_ms()?;
        let validated = validate_artifact_manifest_v2(manifest.clone(), now)?;
        let admission_path = inputs
            .profile
            .owner_root
            .join("admissions")
            .join(format!("{}.manifest", validated.manifest_digest));
        let admission = if admission_path.try_exists()? {
            let original = read_artifact_admission_by_manifest_digest(
                std::fs::File::open(&admission_path)?,
                validated.manifest_digest,
            )?;
            if original.validated_manifest != validated
                || original.withdrawal_scope_digest
                    != service
                        .withdrawal_registry()
                        .scope_digest()
                        .ok_or("scope")?
                || original.withdrawal_head_digest != service.withdrawal_registry().head_digest()
            {
                return Err("original completed E1 admission differs".into());
            }
            original
        } else {
            admit_manifest_at_withdrawal_head_v3(
                service.withdrawal_registry(),
                service.withdrawal_registry().head_digest(),
                manifest,
                now,
            )?
        };
        let preview = service.preview_registered_head(operation.clone(), admission.clone(), now)?;
        let signed = match existing {
            Some(original) => original.verify(&inputs, &source, &observed, &operation, binding)?,
            None => {
                if preview.original_signed_head.is_some() {
                    return Err("original E1 issuance disappeared".into());
                }
                let signed = retained::sign(
                    &inputs, &source, &observed, &operation, &preview, binding, &key,
                )?;
                retained::retain(&inputs, &operation, &signed.0)?;
                signed.1
            }
        };
        if signed.witness.head_digest != preview.head_digest
            || signed.witness.predecessor_head_digest != preview.predecessor
            || signed.witness.generation != preview.generation
            || preview
                .original_signed_head
                .as_ref()
                .is_some_and(|old| old != &signed)
        {
            return Err("retained E1 signed CURRENT head changed".into());
        }
        materials::revalidate(&observed, historical)?;
        let receipt = service.publish(LearningArtifactPublishRequestV1 {
            operation_id: operation.clone(),
            admission: admission.clone(),
            payload,
            signed_current_head: signed.clone(),
            expected_registry_predecessor_head: preview.predecessor,
            now: now_ms()?,
        })?;
        service.publish_root_read_frontier(now_ms()?)?;
        let manifest_bytes = read_root_review_input(&admission_path, 128 * 1024)?;
        let payload_path = inputs.profile.owner_root.join("payloads").join(format!(
            "{}-{}.bin",
            validated.manifest.artifact_id, validated.manifest.bytes_digest
        ));
        let actual_payload = read_root_review_input(&payload_path, 64 * 1024 * 1024)?;
        if actual_payload.len() as u64 != validated.manifest.encoded_size_bytes
            || Digest32::of_bytes(&actual_payload) != validated.manifest.bytes_digest
        {
            return Err("actual original published E1 payload differs".into());
        }
        receipts.push(ParameterPublishedArtifactV1 {
            artifact_id: validated.manifest.artifact_id.to_string(),
            manifest: CpuProtectedSourceV1 {
                path: admission_path,
                digest: Digest32::of_bytes(&manifest_bytes).to_string(),
            },
            admission_digest: admission.admission_digest.to_string(),
            payload: CpuProtectedSourceV1 {
                path: payload_path,
                digest: validated.manifest.bytes_digest.to_string(),
            },
            operation_id: receipt.operation_id.to_string(),
            current_head: signed.witness.head_digest.to_string(),
        });
    }
    publication::expose_original_public_artifacts(&inputs.profile.owner_root)?;
    let observed = materials::evaluation(&config, true)?;
    materials::revalidate(&observed, true)?;
    let owner = inputs.current()?;
    let current = owner.current_registry_view(now_ms()?)?;
    if source.read(64 * 1024)? != bytes
        || receipts
            .iter()
            .any(|p| id(&p.artifact_id).map_or(true, |artifact| !current.is_eligible(&artifact)))
    {
        return Err("actual E1 publication CURRENT/source/eligibility changed".into());
    }
    let last = receipts.last().ok_or("four E1 publications absent")?;
    let signed = owner.protected_current_head(now_ms()?)?;
    let acknowledgement = owner
        .acknowledged_publication(&id(&last.operation_id)?, &signed, now_ms()?)?
        .ok_or("actual original E1 terminal ACK absent")?;
    if signed.witness.head_digest != current.receipt().head_digest {
        return Err("actual E1 terminal ACK is not CURRENT".into());
    }
    let signed_path = inputs.profile.owner_root.join("heads").join(format!(
        "{}-{}.head",
        signed.witness.generation.get(),
        Digest32::of_bytes(&signed.signing_bytes())
    ));
    let signed_bytes = read_root_review_input(&signed_path, 16 * 1024)?;
    if signed_bytes != encode_untrusted_signed_artifact_head_v1(&signed) {
        return Err("whole actual E1 signed CURRENT Source changed".into());
    }
    let result = observation::packet(
        &config,
        &observed,
        receipts,
        &signed,
        CpuProtectedSourceV1 {
            path: signed_path,
            digest: Digest32::of_bytes(&signed_bytes).to_string(),
        },
        &acknowledgement,
    )?;
    Ok(serde_json::to_value(result)?)
}
