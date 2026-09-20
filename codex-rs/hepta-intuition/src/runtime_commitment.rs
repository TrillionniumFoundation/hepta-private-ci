//! Per-decision commitments for learned scoring and assignment provenance.
//!
//! Qualification of a model/profile is intentionally longer-lived than one
//! decision. This module binds the exact scored candidate set and the exact
//! owner-supplied assignment draw to the calibrated request so a caller cannot
//! substitute scores or choose a favorable random draw after qualification.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;

use crate::calibrated::AssignmentModeV1;
use crate::calibrated::CalibratedDecisionRequestV1;
use crate::calibrated::CalibratedError;
use crate::calibrated::canonical_calibrated_request_digest_v1;
use crate::calibrated::canonical_candidate_set_digest_v1;
use crate::qualified::CanonicalPolicyProfileV1;
use crate::qualified::QualifiedCalibratedError;
use crate::qualified::canonical_policy_profile_digest_v1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ScoringCommitmentV1 {
    pub model_artifact_digest: Digest32,
    pub feature_snapshot_digest: Digest32,
    pub feature_schema_digest: Digest32,
    pub scorer_contract_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub scored_outputs_digest: Digest32,
    pub policy_digest: Digest32,
    pub policy_generation: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AssignmentCommitmentV1 {
    Deterministic,
    CounterBased {
        /// Stable identity of the owner/authority that emitted this draw.
        rng_owner_digest: Digest32,
        random_stream_digest: Digest32,
        /// Canonical counter. Current V1 requires it to equal request.sequence.
        counter: u64,
        draw: ProbabilityQ32,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RuntimeCommitmentError {
    Policy(CalibratedError),
    Profile(QualifiedCalibratedError),
    EmptyDigest(&'static str),
    ScoringIdentityMismatch(&'static str),
    ScoringDigestMismatch,
    AssignmentModeMismatch,
    AssignmentStreamMismatch,
    AssignmentCounterMismatch,
    AssignmentDrawMismatch,
}

impl fmt::Display for RuntimeCommitmentError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for RuntimeCommitmentError {}

impl From<CalibratedError> for RuntimeCommitmentError {
    fn from(value: CalibratedError) -> Self {
        Self::Policy(value)
    }
}

impl From<QualifiedCalibratedError> for RuntimeCommitmentError {
    fn from(value: QualifiedCalibratedError) -> Self {
        Self::Profile(value)
    }
}

/// Bind only the scorer-produced fields. Candidate-set identity is committed
/// separately so assignment probabilities can remain an assignment concern.
pub fn canonical_scored_outputs_digest_v1(
    request: &CalibratedDecisionRequestV1,
) -> Result<Digest32, RuntimeCommitmentError> {
    let mut bytes = b"hepta.intuition.scored-outputs.v1\0".to_vec();
    bytes.extend_from_slice(canonical_candidate_set_digest_v1(&request.candidates)?.as_array());
    for candidate in &request.candidates {
        let id = candidate.candidate_id.as_str().as_bytes();
        let len = u32::try_from(id.len()).map_err(|_| CalibratedError::Arithmetic)?;
        bytes.extend_from_slice(&len.to_be_bytes());
        bytes.extend_from_slice(id);
        bytes.extend_from_slice(&candidate.utility.raw().to_be_bytes());
        bytes.extend_from_slice(&candidate.calibrated_confidence.raw().to_be_bytes());
        bytes.extend_from_slice(&candidate.ood_score.raw().to_be_bytes());
        bytes.extend_from_slice(candidate.support_digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

pub fn canonical_scoring_commitment_digest_v1(
    scoring: &ScoringCommitmentV1,
) -> Result<Digest32, RuntimeCommitmentError> {
    for (name, digest) in [
        ("model artifact", scoring.model_artifact_digest),
        ("feature snapshot", scoring.feature_snapshot_digest),
        ("feature schema", scoring.feature_schema_digest),
        ("scorer contract", scoring.scorer_contract_digest),
        ("candidate set", scoring.candidate_set_digest),
        ("scored outputs", scoring.scored_outputs_digest),
        ("policy", scoring.policy_digest),
    ] {
        if digest.is_zero() {
            return Err(RuntimeCommitmentError::EmptyDigest(name));
        }
    }
    let mut bytes = b"hepta.intuition.scoring-commitment.v1\0".to_vec();
    for digest in [
        scoring.model_artifact_digest,
        scoring.feature_snapshot_digest,
        scoring.feature_schema_digest,
        scoring.scorer_contract_digest,
        scoring.candidate_set_digest,
        scoring.scored_outputs_digest,
        scoring.policy_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&scoring.policy_generation.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

/// Long-lived evaluator qualification payload. It binds the canonical profile,
/// model/scorer lineage, frozen qualification datasets and accepted artifacts,
/// but deliberately does not require a new evaluator signature for each request.
pub fn canonical_profile_qualification_payload_v1(
    profile: &CanonicalPolicyProfileV1,
) -> Result<Vec<u8>, RuntimeCommitmentError> {
    let mut bytes = b"hepta.intuition.profile-qualification.v1\0".to_vec();
    bytes.extend_from_slice(canonical_policy_profile_digest_v1(profile)?.as_array());
    bytes.extend_from_slice(profile.scorer.model_digest.as_array());
    bytes.extend_from_slice(profile.scorer.feature_schema_digest.as_array());
    bytes.extend_from_slice(profile.scorer.output_schema_digest.as_array());
    bytes.extend_from_slice(profile.scorer.score_semantics_digest.as_array());
    bytes.extend_from_slice(profile.scorer.scorer_contract_digest.as_array());
    bytes.extend_from_slice(profile.calibration_dataset_digest.as_array());
    bytes.extend_from_slice(profile.ood_dataset_digest.as_array());
    bytes.extend_from_slice(profile.calibration_artifact_digest.as_array());
    bytes.extend_from_slice(profile.ood_artifact_digest.as_array());
    Ok(bytes)
}

fn validate_scoring(
    request: &CalibratedDecisionRequestV1,
    profile: &CanonicalPolicyProfileV1,
    scoring: &ScoringCommitmentV1,
) -> Result<(), RuntimeCommitmentError> {
    if scoring.model_artifact_digest != profile.scorer.model_digest {
        return Err(RuntimeCommitmentError::ScoringIdentityMismatch("model artifact"));
    }
    if scoring.feature_schema_digest != profile.scorer.feature_schema_digest {
        return Err(RuntimeCommitmentError::ScoringIdentityMismatch("feature schema"));
    }
    if scoring.scorer_contract_digest != profile.scorer.scorer_contract_digest {
        return Err(RuntimeCommitmentError::ScoringIdentityMismatch("scorer contract"));
    }
    if scoring.policy_digest != profile.policy_digest || scoring.policy_digest != request.policy_digest {
        return Err(RuntimeCommitmentError::ScoringIdentityMismatch("policy"));
    }
    if scoring.policy_generation != profile.generation
        || scoring.policy_generation != request.policy_generation
    {
        return Err(RuntimeCommitmentError::ScoringIdentityMismatch("generation"));
    }
    let candidate_set_digest = canonical_candidate_set_digest_v1(&request.candidates)?;
    if scoring.candidate_set_digest != candidate_set_digest
        || scoring.candidate_set_digest != request.completeness.candidate_set_digest
    {
        return Err(RuntimeCommitmentError::ScoringIdentityMismatch("candidate set"));
    }
    if scoring.scored_outputs_digest != canonical_scored_outputs_digest_v1(request)? {
        return Err(RuntimeCommitmentError::ScoringDigestMismatch);
    }
    Ok(())
}

fn validate_assignment(
    request: &CalibratedDecisionRequestV1,
    assignment: &AssignmentCommitmentV1,
) -> Result<(), RuntimeCommitmentError> {
    match (&request.assignment, assignment) {
        (AssignmentModeV1::Deterministic, AssignmentCommitmentV1::Deterministic) => Ok(()),
        (
            AssignmentModeV1::CounterBased {
                random_stream_digest,
                draw,
                ..
            },
            AssignmentCommitmentV1::CounterBased {
                rng_owner_digest,
                random_stream_digest: committed_stream,
                counter,
                draw: committed_draw,
            },
        ) => {
            if rng_owner_digest.is_zero() {
                return Err(RuntimeCommitmentError::EmptyDigest("rng owner"));
            }
            if random_stream_digest != committed_stream {
                return Err(RuntimeCommitmentError::AssignmentStreamMismatch);
            }
            if *counter != request.sequence {
                return Err(RuntimeCommitmentError::AssignmentCounterMismatch);
            }
            if draw != committed_draw {
                return Err(RuntimeCommitmentError::AssignmentDrawMismatch);
            }
            Ok(())
        }
        _ => Err(RuntimeCommitmentError::AssignmentModeMismatch),
    }
}

/// Per-decision observer payload. This is the authenticated bridge from a
/// qualified profile to the exact request: model scores, candidate-set identity,
/// assignment stream owner/counter/draw and every request field are committed.
pub fn canonical_runtime_commitment_payload_v1(
    request: &CalibratedDecisionRequestV1,
    profile: &CanonicalPolicyProfileV1,
    scoring: &ScoringCommitmentV1,
    assignment: &AssignmentCommitmentV1,
) -> Result<Vec<u8>, RuntimeCommitmentError> {
    validate_scoring(request, profile, scoring)?;
    validate_assignment(request, assignment)?;

    let request_digest = canonical_calibrated_request_digest_v1(request)?;
    let profile_digest = canonical_policy_profile_digest_v1(profile)?;
    let scoring_digest = canonical_scoring_commitment_digest_v1(scoring)?;

    let mut bytes = b"hepta.intuition.runtime-commitment.v1\0".to_vec();
    bytes.extend_from_slice(request_digest.as_array());
    bytes.extend_from_slice(profile_digest.as_array());
    bytes.extend_from_slice(scoring_digest.as_array());
    match assignment {
        AssignmentCommitmentV1::Deterministic => bytes.push(0),
        AssignmentCommitmentV1::CounterBased {
            rng_owner_digest,
            random_stream_digest,
            counter,
            draw,
        } => {
            bytes.push(1);
            bytes.extend_from_slice(rng_owner_digest.as_array());
            bytes.extend_from_slice(random_stream_digest.as_array());
            bytes.extend_from_slice(&counter.to_be_bytes());
            bytes.extend_from_slice(&draw.raw().to_be_bytes());
        }
    }
    Ok(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::calibrated::{
        CalibratedActionCandidateV1, CalibrationArtifactV1,
        CandidateSetCompletenessBindingV1, OodArtifactV1, RiskClass,
        canonical_candidate_order_digest_v1,
    };
    use crate::qualified::{CanonicalRiskRuleV1, LearnedScorerContractV1};
    use codex_hepta_types::{FixedQ32, StableId};

    fn d(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn fixture() -> (CalibratedDecisionRequestV1, CanonicalPolicyProfileV1) {
        let candidates = vec![CalibratedActionCandidateV1 {
            candidate_id: id("candidate:a"),
            legal: true,
            hard_veto: false,
            utility: FixedQ32::from_raw(1),
            calibrated_confidence: ProbabilityQ32::ONE,
            ood_score: ProbabilityQ32::ZERO,
            assignment_probability: ProbabilityQ32::ONE,
            support_digest: d("support"),
        }];
        let set = canonical_candidate_set_digest_v1(&candidates).expect("set");
        let request = CalibratedDecisionRequestV1 {
            decision_id: id("decision"),
            objective_digest: d("objective"),
            objective_class_digest: d("class"),
            state_digest: d("state"),
            policy_digest: d("policy"),
            policy_generation: 7,
            sequence: 11,
            minimum_confidence: ProbabilityQ32::ZERO,
            maximum_ece_ppm: 50_000,
            maximum_ood_false_acceptance_ppm: 5_000,
            risk_class: RiskClass::Low,
            completeness: CandidateSetCompletenessBindingV1 {
                receipt_digest: d("complete"),
                generator_digest: d("generator"),
                grammar_digest: d("grammar"),
                hard_filter_digest: d("filter"),
                truncation_digest: d("truncation"),
                candidate_set_digest: set,
                canonical_order_digest: canonical_candidate_order_digest_v1(&candidates).expect("order"),
                candidate_count: 1,
                omitted_count_bound: 0,
            },
            calibration: CalibrationArtifactV1 {
                artifact_digest: d("calibration"),
                policy_digest: d("policy"),
                objective_class_digest: d("class"),
                generation: 7,
                valid_from_sequence: 1,
                expires_after_sequence: 20,
                measured_ece_ppm: 1,
                subgroup_audit_digest: d("audit"),
            },
            ood: OodArtifactV1 {
                artifact_digest: d("ood"),
                policy_digest: d("policy"),
                detector_digest: d("detector"),
                support_digest: d("ood-support"),
                generation: 7,
                valid_from_sequence: 1,
                expires_after_sequence: 20,
                maximum_in_domain_score: ProbabilityQ32::ONE,
                measured_false_acceptance_ppm: 1,
            },
            assignment: AssignmentModeV1::CounterBased {
                random_stream_digest: d("stream"),
                draw: ProbabilityQ32::ZERO,
                abstain_probability: ProbabilityQ32::ZERO,
            },
            candidates,
        };
        let profile = CanonicalPolicyProfileV1 {
            profile_id: id("profile"),
            policy_digest: d("policy"),
            objective_class_digest: d("class"),
            generation: 7,
            valid_from_sequence: 1,
            expires_after_sequence: 20,
            minimum_confidence: ProbabilityQ32::ZERO,
            maximum_ece_ppm: 50_000,
            maximum_ood_false_acceptance_ppm: 5_000,
            maximum_in_domain_score: ProbabilityQ32::ONE,
            risk_rule: CanonicalRiskRuleV1::HighOnlySlowPath,
            scorer: LearnedScorerContractV1 {
                model_digest: d("model"),
                feature_schema_digest: d("features"),
                output_schema_digest: d("outputs"),
                score_semantics_digest: d("semantics"),
                scorer_contract_digest: d("scorer"),
            },
            calibration_dataset_digest: d("cal-data"),
            ood_dataset_digest: d("ood-data"),
            calibration_artifact_digest: d("calibration"),
            ood_artifact_digest: d("ood"),
        };
        (request, profile)
    }

    #[test]
    fn runtime_commitment_binds_scores_and_rng_owner_counter_draw() {
        let (request, profile) = fixture();
        let scoring = ScoringCommitmentV1 {
            model_artifact_digest: profile.scorer.model_digest,
            feature_snapshot_digest: d("feature-snapshot"),
            feature_schema_digest: profile.scorer.feature_schema_digest,
            scorer_contract_digest: profile.scorer.scorer_contract_digest,
            candidate_set_digest: request.completeness.candidate_set_digest,
            scored_outputs_digest: canonical_scored_outputs_digest_v1(&request).expect("scores"),
            policy_digest: request.policy_digest,
            policy_generation: request.policy_generation,
        };
        let assignment = AssignmentCommitmentV1::CounterBased {
            rng_owner_digest: d("rng-owner"),
            random_stream_digest: d("stream"),
            counter: request.sequence,
            draw: ProbabilityQ32::ZERO,
        };
        let original = canonical_runtime_commitment_payload_v1(
            &request,
            &profile,
            &scoring,
            &assignment,
        )
        .expect("runtime");

        let mut changed = assignment.clone();
        if let AssignmentCommitmentV1::CounterBased { counter, .. } = &mut changed {
            *counter += 1;
        }
        assert_eq!(
            canonical_runtime_commitment_payload_v1(&request, &profile, &scoring, &changed),
            Err(RuntimeCommitmentError::AssignmentCounterMismatch)
        );

        let mut tampered = request;
        tampered.candidates[0].utility = FixedQ32::from_raw(2);
        assert_eq!(
            canonical_runtime_commitment_payload_v1(&tampered, &profile, &scoring, &assignment),
            Err(RuntimeCommitmentError::ScoringIdentityMismatch("candidate set"))
        );
        assert!(!original.is_empty());
    }
}
