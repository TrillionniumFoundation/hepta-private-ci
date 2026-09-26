//! Production-facing intuition policy contract.
//!
//! The historical V1/V2 request and receipt shapes remain available for replay
//! and qualification fixtures.  This module is the current product boundary: it
//! validates bounded scalar types, preserves the original request risk, exposes
//! an explicit policy-rule routing reason, and separates candidate identity,
//! scorer output and assignment commitments by owner.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::calibrated::AbstentionReasonV1;
use crate::calibrated::AssignmentModeV1;
use crate::calibrated::CalibratedActionCandidateV1;
use crate::calibrated::CalibratedDecisionRequestV1;
use crate::calibrated::CalibratedDispositionV1;
use crate::calibrated::RiskClass;
use crate::calibrated::SlowPathReasonV1;
use crate::calibrated::canonical_calibrated_request_digest_v1;
use crate::qualified::CanonicalPolicyProfileV1;
use crate::qualified::CanonicalRiskRuleV1;
use crate::qualified::QualifiedCalibratedError;
use crate::qualified::canonical_policy_profile_digest_v1;
use crate::qualified::decide_calibrated_v3;

pub const PPM_SCALE: u32 = 1_000_000;

/// A probability-like quantity represented in parts per million.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct Ppm(u32);

impl Ppm {
    pub fn new(value: u32) -> Result<Self, BoundedValueError> {
        if value <= PPM_SCALE {
            Ok(Self(value))
        } else {
            Err(BoundedValueError::PpmOutOfRange)
        }
    }

    #[must_use]
    pub const fn get(self) -> u32 {
        self.0
    }
}

impl TryFrom<u32> for Ppm {
    type Error = BoundedValueError;

    fn try_from(value: u32) -> Result<Self, Self::Error> {
        Self::new(value)
    }
}

impl From<Ppm> for u32 {
    fn from(value: Ppm) -> Self {
        value.get()
    }
}

/// A nonzero monotonically versioned policy generation.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct PolicyGeneration(u64);

impl PolicyGeneration {
    pub fn new(value: u64) -> Result<Self, BoundedValueError> {
        if value == 0 {
            Err(BoundedValueError::ZeroPolicyGeneration)
        } else {
            Ok(Self(value))
        }
    }

    #[must_use]
    pub const fn get(self) -> u64 {
        self.0
    }
}

impl TryFrom<u64> for PolicyGeneration {
    type Error = BoundedValueError;

    fn try_from(value: u64) -> Result<Self, Self::Error> {
        Self::new(value)
    }
}

impl From<PolicyGeneration> for u64 {
    fn from(value: PolicyGeneration) -> Self {
        value.get()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BoundedValueError {
    PpmOutOfRange,
    ZeroPolicyGeneration,
}

impl BoundedValueError {
    #[must_use]
    pub const fn code(self) -> &'static str {
        match self {
            Self::PpmOutOfRange => "intuition.policy.bound.ppm_out_of_range",
            Self::ZeroPolicyGeneration => "intuition.policy.bound.zero_generation",
        }
    }
}

impl fmt::Display for BoundedValueError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.code())
    }
}

impl StdError for BoundedValueError {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProductionSlowPathReasonV1 {
    RequestHighRisk,
    ProfileRiskRule,
    OutOfDistribution,
    LowConfidence,
    Unsupported,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProductionDispositionV1 {
    Selected(StableId),
    SlowPath(ProductionSlowPathReasonV1),
    Abstained(AbstentionReasonV1),
}

/// Current product receipt.  It does not expose dispatch or effect authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionIntuitionReceiptV1 {
    pub decision_id: StableId,
    pub original_risk_class: RiskClass,
    pub matched_risk_rule: CanonicalRiskRuleV1,
    pub disposition: ProductionDispositionV1,
    pub propensities: Vec<crate::calibrated::CalibratedCandidatePropensityV1>,
    pub abstain_probability: ProbabilityQ32,
    pub slow_path_probability: ProbabilityQ32,
    pub profile_digest: Digest32,
    pub legacy_receipt_digest: Digest32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ScoringCommitmentV2 {
    pub model_artifact_digest: Digest32,
    pub feature_snapshot_digest: Digest32,
    pub feature_schema_digest: Digest32,
    pub scorer_contract_digest: Digest32,
    pub candidate_identity_digest: Digest32,
    pub scored_outputs_digest: Digest32,
    pub policy_digest: Digest32,
    pub policy_generation: PolicyGeneration,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AssignmentCommitmentV2 {
    Deterministic {
        distribution_digest: Digest32,
    },
    CounterBased {
        rng_owner_digest: Digest32,
        random_stream_digest: Digest32,
        counter: u64,
        draw: ProbabilityQ32,
        distribution_digest: Digest32,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProductionPolicyError {
    Bounded {
        field: &'static str,
        source: BoundedValueError,
    },
    EmptyDigest(&'static str),
    Qualified(QualifiedCalibratedError),
    ScoringIdentityMismatch(&'static str),
    ScoringDigestMismatch,
    AssignmentModeMismatch,
    AssignmentStreamMismatch,
    AssignmentCounterMismatch,
    AssignmentDrawMismatch,
    AssignmentDistributionMismatch,
    Arithmetic,
}

impl ProductionPolicyError {
    #[must_use]
    pub const fn code(&self) -> &'static str {
        match self {
            Self::Bounded { source, .. } => source.code(),
            Self::EmptyDigest(_) => "intuition.policy.commitment.empty_digest",
            Self::Qualified(_) => "intuition.policy.qualification.rejected",
            Self::ScoringIdentityMismatch(_) => "intuition.policy.scoring.identity_mismatch",
            Self::ScoringDigestMismatch => "intuition.policy.scoring.digest_mismatch",
            Self::AssignmentModeMismatch => "intuition.policy.assignment.mode_mismatch",
            Self::AssignmentStreamMismatch => "intuition.policy.assignment.stream_mismatch",
            Self::AssignmentCounterMismatch => "intuition.policy.assignment.counter_mismatch",
            Self::AssignmentDrawMismatch => "intuition.policy.assignment.draw_mismatch",
            Self::AssignmentDistributionMismatch => {
                "intuition.policy.assignment.distribution_mismatch"
            }
            Self::Arithmetic => "intuition.policy.commitment.arithmetic",
        }
    }
}

impl fmt::Display for ProductionPolicyError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.code())
    }
}

impl StdError for ProductionPolicyError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Bounded { source, .. } => Some(source),
            Self::Qualified(source) => Some(source),
            _ => None,
        }
    }
}

impl From<QualifiedCalibratedError> for ProductionPolicyError {
    fn from(value: QualifiedCalibratedError) -> Self {
        Self::Qualified(value)
    }
}

/// Current product decision entrypoint.  It preserves compatibility with the
/// historical receipt kernel while exposing an unambiguous profile-rule reason.
pub fn decide_calibrated_v4(
    request: CalibratedDecisionRequestV1,
    profile: &CanonicalPolicyProfileV1,
) -> Result<ProductionIntuitionReceiptV1, ProductionPolicyError> {
    validate_bounded_request(&request, profile)?;

    let original_risk_class = request.risk_class;
    let matched_risk_rule = profile.risk_rule;
    let request_digest = canonical_calibrated_request_digest_v1(&request)
        .map_err(QualifiedCalibratedError::Policy)?;
    let profile_digest = canonical_policy_profile_digest_v1(profile)?;
    let forced_by_profile = risk_requires_slow_path(profile.risk_rule, request.risk_class);
    let legacy = decide_calibrated_v3(request, profile)?;

    let disposition = if forced_by_profile && original_risk_class != RiskClass::High {
        ProductionDispositionV1::SlowPath(ProductionSlowPathReasonV1::ProfileRiskRule)
    } else {
        map_disposition(&legacy.disposition)
    };

    let mut bytes = b"hepta.intuition.production-decision.v1\0".to_vec();
    bytes.extend_from_slice(request_digest.as_array());
    bytes.extend_from_slice(profile_digest.as_array());
    bytes.extend_from_slice(legacy.receipt_digest.as_array());
    bytes.push(risk_code(original_risk_class));
    bytes.push(risk_rule_code(matched_risk_rule));
    push_production_disposition(&mut bytes, &disposition)?;
    for propensity in &legacy.propensities {
        push_id(&mut bytes, &propensity.candidate_id)?;
        bytes.extend_from_slice(&propensity.probability.raw().to_be_bytes());
    }
    bytes.extend_from_slice(&legacy.abstain_probability.raw().to_be_bytes());
    bytes.extend_from_slice(&legacy.slow_path_probability.raw().to_be_bytes());

    Ok(ProductionIntuitionReceiptV1 {
        decision_id: legacy.decision_id,
        original_risk_class,
        matched_risk_rule,
        disposition,
        propensities: legacy.propensities,
        abstain_probability: legacy.abstain_probability,
        slow_path_probability: legacy.slow_path_probability,
        profile_digest,
        legacy_receipt_digest: legacy.receipt_digest,
        receipt_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

/// Candidate identity is owned by the generator.  It deliberately excludes
/// utility, confidence, OOD score and assignment probability.
pub fn canonical_candidate_identity_digest_v2(
    candidates: &[CalibratedActionCandidateV1],
) -> Result<Digest32, ProductionPolicyError> {
    let mut bytes = b"hepta.intuition.candidate-identity.v2\0".to_vec();
    push_len(&mut bytes, candidates.len())?;
    for candidate in candidates {
        push_id(&mut bytes, &candidate.candidate_id)?;
        bytes.push(u8::from(candidate.legal));
        bytes.push(u8::from(candidate.hard_veto));
        bytes.extend_from_slice(candidate.support_digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

/// Scorer-owned outputs.  Assignment probabilities and RNG material are absent.
pub fn canonical_scored_outputs_digest_v2(
    request: &CalibratedDecisionRequestV1,
) -> Result<Digest32, ProductionPolicyError> {
    let mut bytes = b"hepta.intuition.scored-outputs.v2\0".to_vec();
    bytes
        .extend_from_slice(canonical_candidate_identity_digest_v2(&request.candidates)?.as_array());
    push_len(&mut bytes, request.candidates.len())?;
    for candidate in &request.candidates {
        push_id(&mut bytes, &candidate.candidate_id)?;
        bytes.extend_from_slice(&candidate.utility.raw().to_be_bytes());
        bytes.extend_from_slice(&candidate.calibrated_confidence.raw().to_be_bytes());
        bytes.extend_from_slice(&candidate.ood_score.raw().to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

/// Assignment-owner distribution.  It excludes scorer outputs and binds only
/// ordered candidate identities, candidate mass and explicit abstain mass.
pub fn canonical_assignment_distribution_digest_v2(
    request: &CalibratedDecisionRequestV1,
) -> Result<Digest32, ProductionPolicyError> {
    let mut bytes = b"hepta.intuition.assignment-distribution.v2\0".to_vec();
    bytes
        .extend_from_slice(canonical_candidate_identity_digest_v2(&request.candidates)?.as_array());
    push_len(&mut bytes, request.candidates.len())?;
    for candidate in &request.candidates {
        push_id(&mut bytes, &candidate.candidate_id)?;
        bytes.extend_from_slice(&candidate.assignment_probability.raw().to_be_bytes());
    }
    match request.assignment {
        AssignmentModeV1::Deterministic => {
            bytes.push(0);
            bytes.extend_from_slice(&ProbabilityQ32::ZERO.raw().to_be_bytes());
        }
        AssignmentModeV1::CounterBased {
            abstain_probability,
            ..
        } => {
            bytes.push(1);
            bytes.extend_from_slice(&abstain_probability.raw().to_be_bytes());
        }
    }
    Ok(Digest32::of_bytes(&bytes))
}

pub fn canonical_scoring_commitment_digest_v2(
    scoring: &ScoringCommitmentV2,
) -> Result<Digest32, ProductionPolicyError> {
    require_digests(&[
        ("model artifact", scoring.model_artifact_digest),
        ("feature snapshot", scoring.feature_snapshot_digest),
        ("feature schema", scoring.feature_schema_digest),
        ("scorer contract", scoring.scorer_contract_digest),
        ("candidate identity", scoring.candidate_identity_digest),
        ("scored outputs", scoring.scored_outputs_digest),
        ("policy", scoring.policy_digest),
    ])?;
    let mut bytes = b"hepta.intuition.scoring-commitment.v2\0".to_vec();
    for digest in [
        scoring.model_artifact_digest,
        scoring.feature_snapshot_digest,
        scoring.feature_schema_digest,
        scoring.scorer_contract_digest,
        scoring.candidate_identity_digest,
        scoring.scored_outputs_digest,
        scoring.policy_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&scoring.policy_generation.get().to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

pub fn canonical_assignment_commitment_digest_v2(
    request: &CalibratedDecisionRequestV1,
    assignment: &AssignmentCommitmentV2,
) -> Result<Digest32, ProductionPolicyError> {
    validate_assignment(request, assignment)?;
    let mut bytes = b"hepta.intuition.assignment-commitment.v2\0".to_vec();
    match assignment {
        AssignmentCommitmentV2::Deterministic {
            distribution_digest,
        } => {
            bytes.push(0);
            bytes.extend_from_slice(distribution_digest.as_array());
        }
        AssignmentCommitmentV2::CounterBased {
            rng_owner_digest,
            random_stream_digest,
            counter,
            draw,
            distribution_digest,
        } => {
            bytes.push(1);
            bytes.extend_from_slice(rng_owner_digest.as_array());
            bytes.extend_from_slice(random_stream_digest.as_array());
            bytes.extend_from_slice(&counter.to_be_bytes());
            bytes.extend_from_slice(&draw.raw().to_be_bytes());
            bytes.extend_from_slice(distribution_digest.as_array());
        }
    }
    Ok(Digest32::of_bytes(&bytes))
}

/// Per-decision observer payload with non-overlapping generator, scorer and
/// assignment commitments.  The complete request digest remains the final
/// anti-substitution envelope; owner-specific digests are independently visible.
pub fn canonical_runtime_commitment_payload_v2(
    request: &CalibratedDecisionRequestV1,
    profile: &CanonicalPolicyProfileV1,
    scoring: &ScoringCommitmentV2,
    assignment: &AssignmentCommitmentV2,
) -> Result<Vec<u8>, ProductionPolicyError> {
    validate_bounded_request(request, profile)?;
    validate_scoring(request, profile, scoring)?;
    let assignment_digest = canonical_assignment_commitment_digest_v2(request, assignment)?;

    let request_digest = canonical_calibrated_request_digest_v1(request)
        .map_err(QualifiedCalibratedError::Policy)?;
    let profile_digest = canonical_policy_profile_digest_v1(profile)?;
    let scoring_digest = canonical_scoring_commitment_digest_v2(scoring)?;
    let candidate_identity_digest = canonical_candidate_identity_digest_v2(&request.candidates)?;
    let scored_outputs_digest = canonical_scored_outputs_digest_v2(request)?;
    let distribution_digest = canonical_assignment_distribution_digest_v2(request)?;

    let mut bytes = b"hepta.intuition.runtime-commitment.v2\0".to_vec();
    for digest in [
        request_digest,
        profile_digest,
        candidate_identity_digest,
        scored_outputs_digest,
        distribution_digest,
        scoring_digest,
        assignment_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(bytes)
}

fn validate_bounded_request(
    request: &CalibratedDecisionRequestV1,
    profile: &CanonicalPolicyProfileV1,
) -> Result<(), ProductionPolicyError> {
    bounded_generation("request policy generation", request.policy_generation)?;
    bounded_generation("calibration generation", request.calibration.generation)?;
    bounded_generation("ood generation", request.ood.generation)?;
    bounded_generation("profile generation", profile.generation)?;
    bounded_ppm("request maximum ece", request.maximum_ece_ppm)?;
    bounded_ppm(
        "request maximum ood false acceptance",
        request.maximum_ood_false_acceptance_ppm,
    )?;
    bounded_ppm(
        "calibration measured ece",
        request.calibration.measured_ece_ppm,
    )?;
    bounded_ppm(
        "ood measured false acceptance",
        request.ood.measured_false_acceptance_ppm,
    )?;
    bounded_ppm("profile maximum ece", profile.maximum_ece_ppm)?;
    bounded_ppm(
        "profile maximum ood false acceptance",
        profile.maximum_ood_false_acceptance_ppm,
    )?;
    Ok(())
}

fn validate_scoring(
    request: &CalibratedDecisionRequestV1,
    profile: &CanonicalPolicyProfileV1,
    scoring: &ScoringCommitmentV2,
) -> Result<(), ProductionPolicyError> {
    if scoring.model_artifact_digest != profile.scorer.model_digest {
        return Err(ProductionPolicyError::ScoringIdentityMismatch(
            "model artifact",
        ));
    }
    if scoring.feature_schema_digest != profile.scorer.feature_schema_digest {
        return Err(ProductionPolicyError::ScoringIdentityMismatch(
            "feature schema",
        ));
    }
    if scoring.scorer_contract_digest != profile.scorer.scorer_contract_digest {
        return Err(ProductionPolicyError::ScoringIdentityMismatch(
            "scorer contract",
        ));
    }
    if scoring.policy_digest != profile.policy_digest
        || scoring.policy_digest != request.policy_digest
    {
        return Err(ProductionPolicyError::ScoringIdentityMismatch("policy"));
    }
    if scoring.policy_generation.get() != profile.generation
        || scoring.policy_generation.get() != request.policy_generation
    {
        return Err(ProductionPolicyError::ScoringIdentityMismatch(
            "policy generation",
        ));
    }
    if scoring.candidate_identity_digest
        != canonical_candidate_identity_digest_v2(&request.candidates)?
    {
        return Err(ProductionPolicyError::ScoringIdentityMismatch(
            "candidate identity",
        ));
    }
    if scoring.scored_outputs_digest != canonical_scored_outputs_digest_v2(request)? {
        return Err(ProductionPolicyError::ScoringDigestMismatch);
    }
    Ok(())
}

fn validate_assignment(
    request: &CalibratedDecisionRequestV1,
    assignment: &AssignmentCommitmentV2,
) -> Result<(), ProductionPolicyError> {
    let expected_distribution = canonical_assignment_distribution_digest_v2(request)?;
    match (&request.assignment, assignment) {
        (
            AssignmentModeV1::Deterministic,
            AssignmentCommitmentV2::Deterministic {
                distribution_digest,
            },
        ) => {
            if distribution_digest.is_zero() {
                return Err(ProductionPolicyError::EmptyDigest(
                    "assignment distribution",
                ));
            }
            if *distribution_digest != expected_distribution {
                return Err(ProductionPolicyError::AssignmentDistributionMismatch);
            }
            Ok(())
        }
        (
            AssignmentModeV1::CounterBased {
                random_stream_digest,
                draw,
                ..
            },
            AssignmentCommitmentV2::CounterBased {
                rng_owner_digest,
                random_stream_digest: committed_stream,
                counter,
                draw: committed_draw,
                distribution_digest,
            },
        ) => {
            require_digests(&[
                ("rng owner", *rng_owner_digest),
                ("random stream", *committed_stream),
                ("assignment distribution", *distribution_digest),
            ])?;
            if random_stream_digest != committed_stream {
                return Err(ProductionPolicyError::AssignmentStreamMismatch);
            }
            if *counter != request.sequence {
                return Err(ProductionPolicyError::AssignmentCounterMismatch);
            }
            if draw != committed_draw {
                return Err(ProductionPolicyError::AssignmentDrawMismatch);
            }
            if *distribution_digest != expected_distribution {
                return Err(ProductionPolicyError::AssignmentDistributionMismatch);
            }
            Ok(())
        }
        _ => Err(ProductionPolicyError::AssignmentModeMismatch),
    }
}

fn bounded_ppm(field: &'static str, value: u32) -> Result<Ppm, ProductionPolicyError> {
    Ppm::new(value).map_err(|source| ProductionPolicyError::Bounded { field, source })
}

fn bounded_generation(
    field: &'static str,
    value: u64,
) -> Result<PolicyGeneration, ProductionPolicyError> {
    PolicyGeneration::new(value).map_err(|source| ProductionPolicyError::Bounded { field, source })
}

fn require_digests(values: &[(&'static str, Digest32)]) -> Result<(), ProductionPolicyError> {
    for (name, digest) in values {
        if digest.is_zero() {
            return Err(ProductionPolicyError::EmptyDigest(name));
        }
    }
    Ok(())
}

fn map_disposition(value: &CalibratedDispositionV1) -> ProductionDispositionV1 {
    match value {
        CalibratedDispositionV1::Selected(candidate_id) => {
            ProductionDispositionV1::Selected(candidate_id.clone())
        }
        CalibratedDispositionV1::SlowPath(reason) => {
            ProductionDispositionV1::SlowPath(match reason {
                SlowPathReasonV1::HighRisk => ProductionSlowPathReasonV1::RequestHighRisk,
                SlowPathReasonV1::OutOfDistribution => {
                    ProductionSlowPathReasonV1::OutOfDistribution
                }
                SlowPathReasonV1::LowConfidence => ProductionSlowPathReasonV1::LowConfidence,
                SlowPathReasonV1::Unsupported => ProductionSlowPathReasonV1::Unsupported,
            })
        }
        CalibratedDispositionV1::Abstained(reason) => ProductionDispositionV1::Abstained(*reason),
    }
}

const fn risk_requires_slow_path(rule: CanonicalRiskRuleV1, risk: RiskClass) -> bool {
    match rule {
        CanonicalRiskRuleV1::HighOnlySlowPath => matches!(risk, RiskClass::High),
        CanonicalRiskRuleV1::ElevatedAndHighSlowPath => {
            matches!(risk, RiskClass::Elevated | RiskClass::High)
        }
        CanonicalRiskRuleV1::AlwaysSlowPath => true,
    }
}

fn push_production_disposition(
    bytes: &mut Vec<u8>,
    disposition: &ProductionDispositionV1,
) -> Result<(), ProductionPolicyError> {
    match disposition {
        ProductionDispositionV1::Selected(candidate_id) => {
            bytes.push(0);
            push_id(bytes, candidate_id)?;
        }
        ProductionDispositionV1::SlowPath(reason) => {
            bytes.push(1);
            bytes.push(match reason {
                ProductionSlowPathReasonV1::RequestHighRisk => 0,
                ProductionSlowPathReasonV1::ProfileRiskRule => 1,
                ProductionSlowPathReasonV1::OutOfDistribution => 2,
                ProductionSlowPathReasonV1::LowConfidence => 3,
                ProductionSlowPathReasonV1::Unsupported => 4,
            });
        }
        ProductionDispositionV1::Abstained(reason) => {
            bytes.push(2);
            bytes.push(match reason {
                AbstentionReasonV1::NoLegalCandidate => 0,
                AbstentionReasonV1::RandomizedAbstain => 1,
            });
        }
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), ProductionPolicyError> {
    let raw = value.as_str().as_bytes();
    let len = u32::try_from(raw.len()).map_err(|_| ProductionPolicyError::Arithmetic)?;
    bytes.extend_from_slice(&len.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_len(bytes: &mut Vec<u8>, value: usize) -> Result<(), ProductionPolicyError> {
    let value = u32::try_from(value).map_err(|_| ProductionPolicyError::Arithmetic)?;
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

const fn risk_rule_code(value: CanonicalRiskRuleV1) -> u8 {
    match value {
        CanonicalRiskRuleV1::HighOnlySlowPath => 0,
        CanonicalRiskRuleV1::ElevatedAndHighSlowPath => 1,
        CanonicalRiskRuleV1::AlwaysSlowPath => 2,
    }
}

#[cfg(test)]
#[path = "production_tests.rs"]
mod tests;
