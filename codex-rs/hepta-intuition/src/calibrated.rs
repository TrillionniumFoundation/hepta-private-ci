//! Explicit calibrated/OOD intuition profile.
//!
//! This module is deliberately separate from the legacy deterministic baseline.
//! It validates candidate completeness, calibration and OOD artifacts before
//! emitting an advisory decision. The host must authenticate calibration/OOD
//! measurements and supply a correctly generated random draw; nonzero digests
//! alone establish neither fact. It grants no dispatch or effect authority.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

#[path = "calibrated_binding.rs"]
mod binding;

pub use binding::canonical_calibrated_request_digest_v1;
pub use binding::decide_calibrated_v2;

const MAX_CANDIDATES: usize = 128;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RiskClass {
    Low,
    Elevated,
    High,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CandidateSetCompletenessBindingV1 {
    pub receipt_digest: Digest32,
    pub generator_digest: Digest32,
    pub grammar_digest: Digest32,
    pub hard_filter_digest: Digest32,
    pub truncation_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub canonical_order_digest: Digest32,
    pub candidate_count: u32,
    pub omitted_count_bound: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CalibrationArtifactV1 {
    pub artifact_digest: Digest32,
    pub policy_digest: Digest32,
    pub objective_class_digest: Digest32,
    pub generation: u64,
    pub valid_from_sequence: u64,
    pub expires_after_sequence: u64,
    pub measured_ece_ppm: u32,
    pub subgroup_audit_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OodArtifactV1 {
    pub artifact_digest: Digest32,
    pub policy_digest: Digest32,
    pub detector_digest: Digest32,
    pub support_digest: Digest32,
    pub generation: u64,
    pub valid_from_sequence: u64,
    pub expires_after_sequence: u64,
    pub maximum_in_domain_score: ProbabilityQ32,
    pub measured_false_acceptance_ppm: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CalibratedActionCandidateV1 {
    pub candidate_id: StableId,
    pub legal: bool,
    pub hard_veto: bool,
    pub utility: FixedQ32,
    pub calibrated_confidence: ProbabilityQ32,
    pub ood_score: ProbabilityQ32,
    pub assignment_probability: ProbabilityQ32,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AssignmentModeV1 {
    Deterministic,
    CounterBased {
        random_stream_digest: Digest32,
        draw: ProbabilityQ32,
        abstain_probability: ProbabilityQ32,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CalibratedDecisionRequestV1 {
    pub decision_id: StableId,
    pub objective_digest: Digest32,
    pub objective_class_digest: Digest32,
    pub state_digest: Digest32,
    pub policy_digest: Digest32,
    pub policy_generation: u64,
    pub sequence: u64,
    pub minimum_confidence: ProbabilityQ32,
    pub maximum_ece_ppm: u32,
    pub maximum_ood_false_acceptance_ppm: u32,
    pub risk_class: RiskClass,
    pub completeness: CandidateSetCompletenessBindingV1,
    pub calibration: CalibrationArtifactV1,
    pub ood: OodArtifactV1,
    pub assignment: AssignmentModeV1,
    pub candidates: Vec<CalibratedActionCandidateV1>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SlowPathReasonV1 {
    HighRisk,
    OutOfDistribution,
    LowConfidence,
    Unsupported,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AbstentionReasonV1 {
    NoLegalCandidate,
    RandomizedAbstain,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CalibratedDispositionV1 {
    Selected(StableId),
    SlowPath(SlowPathReasonV1),
    Abstained(AbstentionReasonV1),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CalibratedCandidatePropensityV1 {
    pub candidate_id: StableId,
    pub probability: ProbabilityQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CalibratedIntuitionReceiptV1 {
    pub decision_id: StableId,
    pub disposition: CalibratedDispositionV1,
    pub propensities: Vec<CalibratedCandidatePropensityV1>,
    pub abstain_probability: ProbabilityQ32,
    pub slow_path_probability: ProbabilityQ32,
    pub completeness_receipt_digest: Digest32,
    pub calibration_artifact_digest: Digest32,
    pub ood_artifact_digest: Digest32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CalibratedError {
    CandidateCountOutOfRange,
    DuplicateCandidate(String),
    EmptyDigest(&'static str),
    CandidateSetMismatch,
    CandidateOrderDigestMismatch,
    CandidateCountMismatch,
    NonCanonicalCandidateOrder,
    ArtifactPolicyMismatch,
    ArtifactObjectiveMismatch,
    ArtifactGenerationMismatch,
    ArtifactWindowInvalid,
    ArtifactExpired,
    CalibrationQualityInsufficient,
    OodQualityInsufficient,
    ProbabilityForIneligibleCandidate(String),
    ProbabilityNotNormalized,
    RandomDrawOutOfRange,
    Arithmetic,
}

impl fmt::Display for CalibratedError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CalibratedError {}

pub fn decide_calibrated(
    request: CalibratedDecisionRequestV1,
) -> Result<CalibratedIntuitionReceiptV1, CalibratedError> {
    validate_request(&request)?;

    let mut legal_count = 0usize;
    let mut ood_count = 0usize;
    let mut low_confidence_count = 0usize;
    let mut eligible: Vec<&CalibratedActionCandidateV1> = Vec::new();

    for candidate in &request.candidates {
        if !candidate.legal || candidate.hard_veto {
            continue;
        }
        legal_count += 1;
        if candidate.ood_score > request.ood.maximum_in_domain_score {
            ood_count += 1;
            continue;
        }
        if candidate.calibrated_confidence < request.minimum_confidence {
            low_confidence_count += 1;
            continue;
        }
        eligible.push(candidate);
    }

    validate_assignment(&request, &eligible)?;

    let disposition = if request.risk_class == RiskClass::High {
        CalibratedDispositionV1::SlowPath(SlowPathReasonV1::HighRisk)
    } else if legal_count == 0 {
        CalibratedDispositionV1::Abstained(AbstentionReasonV1::NoLegalCandidate)
    } else if eligible.is_empty() && ood_count > 0 {
        CalibratedDispositionV1::SlowPath(SlowPathReasonV1::OutOfDistribution)
    } else if eligible.is_empty() && low_confidence_count > 0 {
        CalibratedDispositionV1::SlowPath(SlowPathReasonV1::LowConfidence)
    } else if eligible.is_empty() {
        CalibratedDispositionV1::SlowPath(SlowPathReasonV1::Unsupported)
    } else {
        select(&request, &eligible)?
    };

    let (propensities, abstain_probability, slow_path_probability) =
        output_distribution(&request, &disposition)?;
    let receipt_digest = digest_receipt(
        &request,
        &disposition,
        &propensities,
        abstain_probability,
        slow_path_probability,
    )?;

    Ok(CalibratedIntuitionReceiptV1 {
        decision_id: request.decision_id,
        disposition,
        propensities,
        abstain_probability,
        slow_path_probability,
        completeness_receipt_digest: request.completeness.receipt_digest,
        calibration_artifact_digest: request.calibration.artifact_digest,
        ood_artifact_digest: request.ood.artifact_digest,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_request(request: &CalibratedDecisionRequestV1) -> Result<(), CalibratedError> {
    if !(1..=MAX_CANDIDATES).contains(&request.candidates.len()) {
        return Err(CalibratedError::CandidateCountOutOfRange);
    }
    for (name, digest) in [
        ("objective", request.objective_digest),
        ("objective class", request.objective_class_digest),
        ("state", request.state_digest),
        ("policy", request.policy_digest),
        ("completeness receipt", request.completeness.receipt_digest),
        ("generator", request.completeness.generator_digest),
        ("grammar", request.completeness.grammar_digest),
        ("hard filter", request.completeness.hard_filter_digest),
        ("truncation", request.completeness.truncation_digest),
        ("candidate set", request.completeness.candidate_set_digest),
        (
            "candidate order",
            request.completeness.canonical_order_digest,
        ),
        ("calibration artifact", request.calibration.artifact_digest),
        (
            "calibration subgroup audit",
            request.calibration.subgroup_audit_digest,
        ),
        ("ood artifact", request.ood.artifact_digest),
        ("ood detector", request.ood.detector_digest),
        ("ood support", request.ood.support_digest),
    ] {
        if digest.is_zero() {
            return Err(CalibratedError::EmptyDigest(name));
        }
    }
    if request.completeness.candidate_set_digest
        != canonical_candidate_set_digest_v1(&request.candidates)?
    {
        return Err(CalibratedError::CandidateSetMismatch);
    }
    if request.completeness.canonical_order_digest
        != canonical_candidate_order_digest_v1(&request.candidates)?
    {
        return Err(CalibratedError::CandidateOrderDigestMismatch);
    }
    if usize::try_from(request.completeness.candidate_count).ok() != Some(request.candidates.len())
    {
        return Err(CalibratedError::CandidateCountMismatch);
    }
    if request.calibration.policy_digest != request.policy_digest
        || request.ood.policy_digest != request.policy_digest
    {
        return Err(CalibratedError::ArtifactPolicyMismatch);
    }
    if request.calibration.objective_class_digest != request.objective_class_digest {
        return Err(CalibratedError::ArtifactObjectiveMismatch);
    }
    if request.calibration.generation != request.policy_generation
        || request.ood.generation != request.policy_generation
    {
        return Err(CalibratedError::ArtifactGenerationMismatch);
    }
    if request.calibration.valid_from_sequence > request.calibration.expires_after_sequence
        || request.ood.valid_from_sequence > request.ood.expires_after_sequence
    {
        return Err(CalibratedError::ArtifactWindowInvalid);
    }
    if request.sequence < request.calibration.valid_from_sequence
        || request.sequence > request.calibration.expires_after_sequence
        || request.sequence < request.ood.valid_from_sequence
        || request.sequence > request.ood.expires_after_sequence
    {
        return Err(CalibratedError::ArtifactExpired);
    }
    if request.calibration.measured_ece_ppm > request.maximum_ece_ppm {
        return Err(CalibratedError::CalibrationQualityInsufficient);
    }
    if request.ood.measured_false_acceptance_ppm > request.maximum_ood_false_acceptance_ppm {
        return Err(CalibratedError::OodQualityInsufficient);
    }

    let mut previous: Option<&StableId> = None;
    let mut seen = BTreeSet::new();
    for candidate in &request.candidates {
        if let Some(prior) = previous
            && prior >= &candidate.candidate_id
        {
            return Err(CalibratedError::NonCanonicalCandidateOrder);
        }
        previous = Some(&candidate.candidate_id);
        if !seen.insert(candidate.candidate_id.clone()) {
            return Err(CalibratedError::DuplicateCandidate(
                candidate.candidate_id.to_string(),
            ));
        }
        if candidate.support_digest.is_zero() {
            return Err(CalibratedError::EmptyDigest("candidate support"));
        }
    }
    Ok(())
}

fn validate_assignment(
    request: &CalibratedDecisionRequestV1,
    eligible: &[&CalibratedActionCandidateV1],
) -> Result<(), CalibratedError> {
    let AssignmentModeV1::CounterBased {
        random_stream_digest,
        draw,
        abstain_probability,
    } = &request.assignment
    else {
        return Ok(());
    };

    if random_stream_digest.is_zero() {
        return Err(CalibratedError::EmptyDigest("random stream"));
    }
    if *draw == ProbabilityQ32::ONE {
        return Err(CalibratedError::RandomDrawOutOfRange);
    }
    let eligible_ids = eligible
        .iter()
        .map(|candidate| candidate.candidate_id.clone())
        .collect::<BTreeSet<_>>();
    let mut total = u128::from(abstain_probability.raw());
    for candidate in &request.candidates {
        if !eligible_ids.contains(&candidate.candidate_id)
            && candidate.assignment_probability != ProbabilityQ32::ZERO
        {
            return Err(CalibratedError::ProbabilityForIneligibleCandidate(
                candidate.candidate_id.to_string(),
            ));
        }
        total = total
            .checked_add(u128::from(candidate.assignment_probability.raw()))
            .ok_or(CalibratedError::Arithmetic)?;
    }
    if total != u128::from(ProbabilityQ32::ONE.raw()) {
        return Err(CalibratedError::ProbabilityNotNormalized);
    }
    Ok(())
}

fn select(
    request: &CalibratedDecisionRequestV1,
    eligible: &[&CalibratedActionCandidateV1],
) -> Result<CalibratedDispositionV1, CalibratedError> {
    match &request.assignment {
        AssignmentModeV1::Deterministic => {
            let selected = eligible
                .iter()
                .copied()
                .max_by(|left, right| {
                    left.utility
                        .cmp(&right.utility)
                        .then_with(|| left.calibrated_confidence.cmp(&right.calibrated_confidence))
                        .then_with(|| right.candidate_id.cmp(&left.candidate_id))
                })
                .ok_or(CalibratedError::Arithmetic)?;
            Ok(CalibratedDispositionV1::Selected(
                selected.candidate_id.clone(),
            ))
        }
        AssignmentModeV1::CounterBased { draw, .. } => {
            // The complete assignment was checked before any disposition was
            // chosen. Selection only traverses that validated distribution.
            let target = u128::from(draw.raw());
            let mut cumulative = 0u128;
            for candidate in &request.candidates {
                cumulative = cumulative
                    .checked_add(u128::from(candidate.assignment_probability.raw()))
                    .ok_or(CalibratedError::Arithmetic)?;
                if target < cumulative {
                    return Ok(CalibratedDispositionV1::Selected(
                        candidate.candidate_id.clone(),
                    ));
                }
            }
            Ok(CalibratedDispositionV1::Abstained(
                AbstentionReasonV1::RandomizedAbstain,
            ))
        }
    }
}

fn output_distribution(
    request: &CalibratedDecisionRequestV1,
    disposition: &CalibratedDispositionV1,
) -> Result<
    (
        Vec<CalibratedCandidatePropensityV1>,
        ProbabilityQ32,
        ProbabilityQ32,
    ),
    CalibratedError,
> {
    let slow_path = matches!(disposition, CalibratedDispositionV1::SlowPath(_));
    let propensities = request
        .candidates
        .iter()
        .map(|candidate| CalibratedCandidatePropensityV1 {
            candidate_id: candidate.candidate_id.clone(),
            probability: if slow_path {
                ProbabilityQ32::ZERO
            } else {
                match &request.assignment {
                    AssignmentModeV1::Deterministic => match disposition {
                        CalibratedDispositionV1::Selected(selected)
                            if selected == &candidate.candidate_id =>
                        {
                            ProbabilityQ32::ONE
                        }
                        _ => ProbabilityQ32::ZERO,
                    },
                    AssignmentModeV1::CounterBased { .. } => candidate.assignment_probability,
                }
            },
        })
        .collect::<Vec<_>>();

    let abstain_probability = if slow_path {
        ProbabilityQ32::ZERO
    } else {
        match &request.assignment {
            AssignmentModeV1::Deterministic => {
                if matches!(disposition, CalibratedDispositionV1::Abstained(_)) {
                    ProbabilityQ32::ONE
                } else {
                    ProbabilityQ32::ZERO
                }
            }
            AssignmentModeV1::CounterBased {
                abstain_probability,
                ..
            } => *abstain_probability,
        }
    };
    let slow_path_probability = if slow_path {
        ProbabilityQ32::ONE
    } else {
        ProbabilityQ32::ZERO
    };
    Ok((propensities, abstain_probability, slow_path_probability))
}

/// Compute the canonical digest consumed by
/// [`CandidateSetCompletenessBindingV1::candidate_set_digest`].
pub fn canonical_candidate_set_digest_v1(
    candidates: &[CalibratedActionCandidateV1],
) -> Result<Digest32, CalibratedError> {
    let mut bytes = b"hepta.intuition.calibrated-candidate-set.v1".to_vec();
    push_len(&mut bytes, candidates.len())?;
    for candidate in candidates {
        push_id(&mut bytes, &candidate.candidate_id)?;
        bytes.push(u8::from(candidate.legal));
        bytes.push(u8::from(candidate.hard_veto));
        bytes.extend_from_slice(&candidate.utility.raw().to_be_bytes());
        bytes.extend_from_slice(&candidate.calibrated_confidence.raw().to_be_bytes());
        bytes.extend_from_slice(&candidate.ood_score.raw().to_be_bytes());
        bytes.extend_from_slice(&candidate.assignment_probability.raw().to_be_bytes());
        bytes.extend_from_slice(candidate.support_digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

/// Compute the exact candidate-order digest. Candidate order remains separately
/// bound so a completeness receipt cannot be replayed over a reordered set.
pub fn canonical_candidate_order_digest_v1(
    candidates: &[CalibratedActionCandidateV1],
) -> Result<Digest32, CalibratedError> {
    let mut bytes = b"hepta.intuition.calibrated-candidate-order.v1".to_vec();
    push_len(&mut bytes, candidates.len())?;
    for candidate in candidates {
        push_id(&mut bytes, &candidate.candidate_id)?;
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_receipt(
    request: &CalibratedDecisionRequestV1,
    disposition: &CalibratedDispositionV1,
    propensities: &[CalibratedCandidatePropensityV1],
    abstain_probability: ProbabilityQ32,
    slow_path_probability: ProbabilityQ32,
) -> Result<Digest32, CalibratedError> {
    let mut bytes = b"hepta.intuition.calibrated-decision.v1".to_vec();
    push_id(&mut bytes, &request.decision_id)?;
    for digest in [
        request.objective_digest,
        request.objective_class_digest,
        request.state_digest,
        request.policy_digest,
        request.completeness.receipt_digest,
        request.calibration.artifact_digest,
        request.ood.artifact_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&request.policy_generation.to_be_bytes());
    bytes.extend_from_slice(&request.sequence.to_be_bytes());
    bytes.extend_from_slice(&request.minimum_confidence.raw().to_be_bytes());
    bytes.extend_from_slice(&request.maximum_ece_ppm.to_be_bytes());
    bytes.extend_from_slice(&request.maximum_ood_false_acceptance_ppm.to_be_bytes());
    bytes.push(risk_code(request.risk_class));
    match disposition {
        CalibratedDispositionV1::Selected(candidate_id) => {
            bytes.push(0);
            push_id(&mut bytes, candidate_id)?;
        }
        CalibratedDispositionV1::SlowPath(reason) => {
            bytes.push(1);
            bytes.push(slow_path_code(*reason));
        }
        CalibratedDispositionV1::Abstained(reason) => {
            bytes.push(2);
            bytes.push(abstention_code(*reason));
        }
    }
    push_len(&mut bytes, propensities.len())?;
    for propensity in propensities {
        push_id(&mut bytes, &propensity.candidate_id)?;
        bytes.extend_from_slice(&propensity.probability.raw().to_be_bytes());
    }
    bytes.extend_from_slice(&abstain_probability.raw().to_be_bytes());
    bytes.extend_from_slice(&slow_path_probability.raw().to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), CalibratedError> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| CalibratedError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_len(bytes: &mut Vec<u8>, value: usize) -> Result<(), CalibratedError> {
    let value = u32::try_from(value).map_err(|_| CalibratedError::Arithmetic)?;
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(())
}

const fn risk_code(value: RiskClass) -> u8 {
    match value {
        RiskClass::Low => 0,
        RiskClass::Elevated => 1,
        RiskClass::High => 2,
    }
}

const fn slow_path_code(value: SlowPathReasonV1) -> u8 {
    match value {
        SlowPathReasonV1::HighRisk => 0,
        SlowPathReasonV1::OutOfDistribution => 1,
        SlowPathReasonV1::LowConfidence => 2,
        SlowPathReasonV1::Unsupported => 3,
    }
}

const fn abstention_code(value: AbstentionReasonV1) -> u8 {
    match value {
        AbstentionReasonV1::NoLegalCandidate => 0,
        AbstentionReasonV1::RandomizedAbstain => 1,
    }
}

#[cfg(test)]
#[path = "calibrated_tests.rs"]
mod tests;
