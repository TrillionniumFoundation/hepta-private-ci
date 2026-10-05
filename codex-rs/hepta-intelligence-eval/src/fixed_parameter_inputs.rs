//! Public finite request bytes grant no Root custody or E authority.
use crate::fixed_parameter_no_change::HostResult;
use crate::fixed_parameter_no_change::hex;
use crate::fixed_parameter_no_change_host::Inputs;
use crate::*;
use codex_hepta_learning_ledger::ReviewEvidenceWireV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_plasticity::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterEvaluationRoundBindingV1 {
    pub round_identity_digest: Digest32,
    pub round_payload_digest: Digest32,
    pub canonical_policy_digest: Digest32,
    pub execution_envelope_digest: Digest32,
    pub admitted_at_ms: u64,
    pub deadline_ms: u64,
}
pub fn encode_fixed_parameter_evaluator_config_v1(
    config: &FixedParameterEvaluatorConfigV1,
) -> HostResult<Vec<u8>> {
    if ![
        "hepta.fixed-parameter-no-change-config.v1",
        "hepta.fixed-parameter-preparation-config.v1",
    ]
    .contains(&config.schema.as_str())
        || config.uid == 0
        || config.gid == 0
        || config.distribution_generation == 0
        || config.authority_epoch == 0
        || config.inaccessible_paths.len() != 5
    {
        return Err("fixed E enrolled configuration".into());
    }
    let bytes = serde_json::to_vec(config)?;
    if bytes.len() > 32 * 1024 {
        return Err("complete fixed E configuration bound".into());
    }
    Ok(bytes)
}
/// None selects no-update; Some selects the exact generated Update for review.
pub fn encode_fixed_parameter_role_inputs_v1(
    round: &ParameterEvaluationRoundBindingV1,
    profile: &ParameterGeneratorProfileV3,
    admission: &PlasticityAdmissionEvidenceV1,
    generator: &SignedLearningEvidenceV1,
    observer: &SignedLearningEvidenceV1,
    candidate: Option<&StableId>,
) -> HostResult<Vec<u8>> {
    encode_inputs(
        round, profile, admission, generator, observer, candidate, None,
    )
}
pub fn encode_fixed_parameter_preparation_inputs_v1(
    round: &ParameterEvaluationRoundBindingV1,
    profile: &ParameterGeneratorProfileV3,
    admission: &PlasticityAdmissionEvidenceV1,
    generator: &SignedLearningEvidenceV1,
    observer: &SignedLearningEvidenceV1,
    reviews: &[FixedParameterCompletedReviewSourceV1],
) -> HostResult<Vec<u8>> {
    encode_inputs(
        round,
        profile,
        admission,
        generator,
        observer,
        None,
        Some(reviews),
    )
}
fn encode_inputs(
    round: &ParameterEvaluationRoundBindingV1,
    profile: &ParameterGeneratorProfileV3,
    admission: &PlasticityAdmissionEvidenceV1,
    generator: &SignedLearningEvidenceV1,
    observer: &SignedLearningEvidenceV1,
    candidate: Option<&StableId>,
    reviews: Option<&[FixedParameterCompletedReviewSourceV1]>,
) -> HostResult<Vec<u8>> {
    if [
        round.round_identity_digest,
        round.round_payload_digest,
        round.canonical_policy_digest,
        round.execution_envelope_digest,
    ]
    .iter()
    .any(|digest| digest.is_zero())
        || round.admitted_at_ms == 0
        || round.deadline_ms <= round.admitted_at_ms
    {
        return Err("original E round request binding".into());
    }
    let generated = generate_parameter_candidates_v3(profile.clone())?;
    validate_parameter_admission_binding_v1(profile, &generated, admission)?;
    let schema = if reviews.is_some() {
        "hepta.parameter-preparation-inputs.v1"
    } else if candidate.is_some() {
        "hepta.parameter-review-inputs.v1"
    } else {
        "hepta.parameter-no-change-inputs.v1"
    };
    let updates = generated
        .candidates
        .iter()
        .filter(|c| c.kind == ParameterCandidateKindV2::Update);
    if let Some(candidate) = candidate {
        if !updates.clone().any(|c| &c.candidate_id == candidate) {
            return Err("actual Update candidate".into());
        }
    } else if let Some(reviews) = reviews {
        if reviews.is_empty() || reviews.len() != updates.count() || reviews.len() > 32 {
            return Err("whole measured candidate completion inputs".into());
        }
    } else if updates.count() != 0 {
        return Err("no-change request cannot contain an actual Update".into());
    }
    let bytes = serde_json::to_vec(&Inputs {
        schema: schema.to_owned(),
        profile_hex: hex(&encode_untrusted_parameter_generator_profile_v3(profile)?),
        admission_hex: hex(&encode_untrusted_plasticity_admission_v1(admission)?),
        generator_evidence: ReviewEvidenceWireV1::from_native(generator),
        observer_evidence: ReviewEvidenceWireV1::from_native(observer),
        round_identity_digest: round.round_identity_digest.to_string(),
        round_payload_digest: round.round_payload_digest.to_string(),
        canonical_policy_digest: round.canonical_policy_digest.to_string(),
        execution_envelope_digest: round.execution_envelope_digest.to_string(),
        admitted_at_ms: round.admitted_at_ms,
        deadline_ms: round.deadline_ms,
        candidate_id: candidate.map(ToString::to_string),
        completed_reviews: reviews.unwrap_or_default().to_vec(),
    })?;
    if bytes.len() > 4 * MAX_PARAMETER_ROLE_MATERIAL_BYTES_V1 + 32 * 1024 {
        return Err("whole fixed parameter E inputs bound".into());
    }
    Ok(bytes)
}
