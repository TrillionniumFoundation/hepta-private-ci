use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AxisDirection;
use crate::AxisLimit;
use crate::AxisValue;
use crate::CandidateRejectionReason;
use crate::CandidateUtility;
use crate::EvaluationDisposition;
use crate::RejectedCandidate;
use crate::UtilityProfile;

const PROFILE_DIGEST_DOMAIN: &[u8] = b"hepta.ndu.utility-profile.v1";
const EVALUATION_DIGEST_DOMAIN: &[u8] = b"hepta.ndu.evaluation.v1";

pub(crate) struct EvaluationDigestInput<'a> {
    pub(crate) objective_digest: Digest32,
    pub(crate) generation: u64,
    pub(crate) disposition: EvaluationDisposition,
    pub(crate) evaluated: &'a [CandidateUtility],
    pub(crate) rejected: &'a [RejectedCandidate],
    pub(crate) frontier: &'a [CandidateUtility],
    pub(crate) advisory: Option<&'a StableId>,
    pub(crate) utility_profile_digest: Digest32,
    pub(crate) scalarization_digest: Option<Digest32>,
}

pub(crate) fn digest_evaluation(input: EvaluationDigestInput<'_>) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(EVALUATION_DIGEST_DOMAIN);
    bytes.extend_from_slice(input.objective_digest.as_array());
    bytes.extend_from_slice(input.utility_profile_digest.as_array());
    push_optional_digest(&mut bytes, input.scalarization_digest);
    bytes.extend_from_slice(&input.generation.to_be_bytes());
    bytes.push(disposition_tag(input.disposition));
    push_len(&mut bytes, input.evaluated.len());
    for candidate in input.evaluated {
        push_candidate(&mut bytes, candidate);
    }
    push_len(&mut bytes, input.rejected.len());
    for candidate in input.rejected {
        push_id(&mut bytes, &candidate.candidate_id);
        push_len(&mut bytes, candidate.reasons.len());
        for reason in &candidate.reasons {
            bytes.push(rejection_reason_tag(*reason));
        }
    }
    push_len(&mut bytes, input.frontier.len());
    for candidate in input.frontier {
        push_candidate(&mut bytes, candidate);
    }
    if let Some(candidate) = input.advisory {
        bytes.push(1);
        push_id(&mut bytes, candidate);
    } else {
        bytes.push(0);
    }
    Digest32::of_bytes(&bytes)
}

pub(crate) fn digest_profile(profile: &UtilityProfile) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(PROFILE_DIGEST_DOMAIN);
    push_id(&mut bytes, &profile.profile_id);
    push_len(&mut bytes, profile.dimensions.len());
    for (axis, direction) in &profile.dimensions {
        push_id(&mut bytes, axis);
        bytes.push(match direction {
            AxisDirection::Maximize => 0,
            AxisDirection::Minimize => 1,
        });
    }
    push_limits(&mut bytes, &profile.risk_ceilings);
    push_limits(&mut bytes, &profile.resource_ceilings);
    push_len(&mut bytes, profile.required_organs.organ_ids.len());
    for organ in &profile.required_organs.organ_ids {
        push_id(&mut bytes, organ);
    }
    Digest32::of_bytes(&bytes)
}

fn push_candidate(bytes: &mut Vec<u8>, candidate: &CandidateUtility) {
    push_id(bytes, &candidate.candidate_id);
    push_axis_values(bytes, &candidate.utility);
    push_axis_values(bytes, &candidate.risk);
    push_axis_values(bytes, &candidate.resource);
    push_axis_values(bytes, &candidate.uncertainty);
    bytes.extend_from_slice(candidate.support_digest.as_array());
    if let Some(score) = candidate.scalar_score {
        bytes.push(1);
        bytes.extend_from_slice(&score.raw().to_be_bytes());
    } else {
        bytes.push(0);
    }
}

pub(crate) fn push_axis_values(bytes: &mut Vec<u8>, values: &[AxisValue]) {
    push_len(bytes, values.len());
    for value in values {
        push_id(bytes, &value.axis);
        bytes.extend_from_slice(&value.value.raw().to_be_bytes());
    }
}

fn push_limits(bytes: &mut Vec<u8>, values: &[AxisLimit]) {
    push_len(bytes, values.len());
    for value in values {
        push_id(bytes, &value.axis);
        bytes.extend_from_slice(&value.maximum.raw().to_be_bytes());
    }
}

fn push_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    if let Some(digest) = value {
        bytes.push(1);
        bytes.extend_from_slice(digest.as_array());
    } else {
        bytes.push(0);
    }
}

fn disposition_tag(value: EvaluationDisposition) -> u8 {
    match value {
        EvaluationDisposition::InfeasibleExplicitAbstain => 0,
        EvaluationDisposition::UniqueParetoRecommendation => 1,
        EvaluationDisposition::ParetoSetRequiresSlowPath => 2,
        EvaluationDisposition::ScalarizedRecommendation => 3,
        EvaluationDisposition::ScalarizationTieRequiresSlowPath => 4,
    }
}

fn rejection_reason_tag(value: CandidateRejectionReason) -> u8 {
    match value {
        CandidateRejectionReason::HardConstraintViolation => 0,
        CandidateRejectionReason::RiskCeilingExceeded => 1,
        CandidateRejectionReason::ResourceCeilingExceeded => 2,
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    let converted = u32::try_from(value).unwrap_or(u32::MAX);
    bytes.extend_from_slice(&converted.to_be_bytes());
}
