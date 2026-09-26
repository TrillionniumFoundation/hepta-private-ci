//! Current scorer-owned commitments for authenticated intuition decisions.
//!
//! Historical V1 commitments remain byte-stable for replay. V2 removes the
//! complete candidate-set digest from the scorer-owned surface because that
//! digest also contains assignment probabilities. The complete calibrated
//! request is still authenticated separately, so assignment changes require a
//! fresh runtime attestation without pretending that the scorer produced them.

use codex_hepta_types::Digest32;

use crate::calibrated::AssignmentModeV1;
use crate::calibrated::CalibratedDecisionRequestV1;
use crate::calibrated::CalibratedError;
use crate::calibrated::canonical_calibrated_request_digest_v1;
use crate::qualified::CanonicalPolicyProfileV1;
use crate::qualified::canonical_policy_profile_digest_v1;
use crate::runtime_commitment::AssignmentCommitmentV1;
use crate::runtime_commitment::RuntimeCommitmentError;

const MAX_CANDIDATES: usize = 128;

/// Current scorer-owned identity and output commitment.
///
/// Candidate identity and scorer outputs are bound by
/// `scored_outputs_digest`. Legality, completeness, assignment probabilities,
/// random-stream identity and the exact draw remain generator/assignment
/// concerns and are committed by the complete request and runtime payload.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ScoringCommitmentV2 {
    pub model_artifact_digest: Digest32,
    pub feature_snapshot_digest: Digest32,
    pub feature_schema_digest: Digest32,
    pub scorer_contract_digest: Digest32,
    pub scored_outputs_digest: Digest32,
    pub policy_digest: Digest32,
    pub policy_generation: u64,
}

/// Commit only the ordered candidate identities and scorer-produced outputs.
pub fn canonical_scored_outputs_digest_v2(
    request: &CalibratedDecisionRequestV1,
) -> Result<Digest32, RuntimeCommitmentError> {
    if !(1..=MAX_CANDIDATES).contains(&request.candidates.len()) {
        return Err(CalibratedError::CandidateCountOutOfRange.into());
    }
    let mut bytes = b"hepta.intuition.scored-outputs.v2\0".to_vec();
    let count = u32::try_from(request.candidates.len()).map_err(|_| CalibratedError::Arithmetic)?;
    bytes.extend_from_slice(&count.to_be_bytes());
    for candidate in &request.candidates {
        let id = candidate.candidate_id.as_str().as_bytes();
        let length = u32::try_from(id.len()).map_err(|_| CalibratedError::Arithmetic)?;
        bytes.extend_from_slice(&length.to_be_bytes());
        bytes.extend_from_slice(id);
        bytes.extend_from_slice(&candidate.utility.raw().to_be_bytes());
        bytes.extend_from_slice(&candidate.calibrated_confidence.raw().to_be_bytes());
        bytes.extend_from_slice(&candidate.ood_score.raw().to_be_bytes());
        bytes.extend_from_slice(candidate.support_digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

pub fn canonical_scoring_commitment_digest_v2(
    scoring: &ScoringCommitmentV2,
) -> Result<Digest32, RuntimeCommitmentError> {
    for (name, digest) in [
        ("model artifact", scoring.model_artifact_digest),
        ("feature snapshot", scoring.feature_snapshot_digest),
        ("feature schema", scoring.feature_schema_digest),
        ("scorer contract", scoring.scorer_contract_digest),
        ("scored outputs", scoring.scored_outputs_digest),
        ("policy", scoring.policy_digest),
    ] {
        if digest.is_zero() {
            return Err(RuntimeCommitmentError::EmptyDigest(name));
        }
    }
    let mut bytes = b"hepta.intuition.scoring-commitment.v2\0".to_vec();
    for digest in [
        scoring.model_artifact_digest,
        scoring.feature_snapshot_digest,
        scoring.feature_schema_digest,
        scoring.scorer_contract_digest,
        scoring.scored_outputs_digest,
        scoring.policy_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&scoring.policy_generation.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

fn validate_scoring(
    request: &CalibratedDecisionRequestV1,
    profile: &CanonicalPolicyProfileV1,
    scoring: &ScoringCommitmentV2,
) -> Result<(), RuntimeCommitmentError> {
    if scoring.model_artifact_digest != profile.scorer.model_digest {
        return Err(RuntimeCommitmentError::ScoringIdentityMismatch(
            "model artifact",
        ));
    }
    if scoring.feature_schema_digest != profile.scorer.feature_schema_digest {
        return Err(RuntimeCommitmentError::ScoringIdentityMismatch(
            "feature schema",
        ));
    }
    if scoring.scorer_contract_digest != profile.scorer.scorer_contract_digest {
        return Err(RuntimeCommitmentError::ScoringIdentityMismatch(
            "scorer contract",
        ));
    }
    if scoring.policy_digest != profile.policy_digest
        || scoring.policy_digest != request.policy_digest
    {
        return Err(RuntimeCommitmentError::ScoringIdentityMismatch("policy"));
    }
    if scoring.policy_generation != profile.generation
        || scoring.policy_generation != request.policy_generation
    {
        return Err(RuntimeCommitmentError::ScoringIdentityMismatch(
            "generation",
        ));
    }
    if scoring.scored_outputs_digest != canonical_scored_outputs_digest_v2(request)? {
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

/// Authenticate the scorer-owned commitment together with the complete request.
///
/// Assignment-only changes leave the scorer digest unchanged but alter the
/// complete request digest and therefore this payload.
pub fn canonical_runtime_commitment_payload_v2(
    request: &CalibratedDecisionRequestV1,
    profile: &CanonicalPolicyProfileV1,
    scoring: &ScoringCommitmentV2,
    assignment: &AssignmentCommitmentV1,
) -> Result<Vec<u8>, RuntimeCommitmentError> {
    let scoring_digest = canonical_scoring_commitment_digest_v2(scoring)?;
    validate_scoring(request, profile, scoring)?;
    validate_assignment(request, assignment)?;

    let request_digest = canonical_calibrated_request_digest_v1(request)?;
    let profile_digest = canonical_policy_profile_digest_v1(profile)?;
    let mut bytes = b"hepta.intuition.runtime-commitment.v2\0".to_vec();
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
    use std::error::Error;

    use codex_hepta_types::FixedQ32;
    use codex_hepta_types::ProbabilityQ32;
    use codex_hepta_types::StableId;

    use super::*;
    use crate::calibrated::CalibratedActionCandidateV1;
    use crate::calibrated::CalibrationArtifactV1;
    use crate::calibrated::CandidateSetCompletenessBindingV1;
    use crate::calibrated::OodArtifactV1;
    use crate::calibrated::RiskClass;
    use crate::calibrated::canonical_candidate_order_digest_v1;
    use crate::calibrated::canonical_candidate_set_digest_v1;
    use crate::qualified::CanonicalRiskRuleV1;
    use crate::qualified::LearnedScorerContractV1;
    use crate::runtime_commitment::canonical_scored_outputs_digest_v1;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn fixture() -> Result<(CalibratedDecisionRequestV1, CanonicalPolicyProfileV1), Box<dyn Error>>
    {
        let candidates = vec![CalibratedActionCandidateV1 {
            candidate_id: StableId::new("candidate:a")?,
            legal: true,
            hard_veto: false,
            utility: FixedQ32::ONE,
            calibrated_confidence: ProbabilityQ32::ONE,
            ood_score: ProbabilityQ32::ZERO,
            assignment_probability: ProbabilityQ32::ONE,
            support_digest: digest("support"),
        }];
        let candidate_set_digest = canonical_candidate_set_digest_v1(&candidates)?;
        let request = CalibratedDecisionRequestV1 {
            decision_id: StableId::new("decision")?,
            objective_digest: digest("objective"),
            objective_class_digest: digest("class"),
            state_digest: digest("state"),
            policy_digest: digest("policy"),
            policy_generation: 1,
            sequence: 1,
            minimum_confidence: ProbabilityQ32::ZERO,
            maximum_ece_ppm: 0,
            maximum_ood_false_acceptance_ppm: 0,
            risk_class: RiskClass::Low,
            completeness: CandidateSetCompletenessBindingV1 {
                receipt_digest: digest("complete"),
                generator_digest: digest("generator"),
                grammar_digest: digest("grammar"),
                hard_filter_digest: digest("filter"),
                truncation_digest: digest("truncation"),
                candidate_set_digest,
                canonical_order_digest: canonical_candidate_order_digest_v1(&candidates)?,
                candidate_count: 1,
                omitted_count_bound: 0,
            },
            calibration: CalibrationArtifactV1 {
                artifact_digest: digest("calibration"),
                policy_digest: digest("policy"),
                objective_class_digest: digest("class"),
                generation: 1,
                valid_from_sequence: 1,
                expires_after_sequence: 2,
                measured_ece_ppm: 0,
                subgroup_audit_digest: digest("audit"),
            },
            ood: OodArtifactV1 {
                artifact_digest: digest("ood"),
                policy_digest: digest("policy"),
                detector_digest: digest("detector"),
                support_digest: digest("ood-support"),
                generation: 1,
                valid_from_sequence: 1,
                expires_after_sequence: 2,
                maximum_in_domain_score: ProbabilityQ32::ONE,
                measured_false_acceptance_ppm: 0,
            },
            assignment: AssignmentModeV1::CounterBased {
                random_stream_digest: digest("stream"),
                draw: ProbabilityQ32::ZERO,
                abstain_probability: ProbabilityQ32::ZERO,
            },
            candidates,
        };
        let profile = CanonicalPolicyProfileV1 {
            profile_id: StableId::new("profile")?,
            policy_digest: digest("policy"),
            objective_class_digest: digest("class"),
            generation: 1,
            valid_from_sequence: 1,
            expires_after_sequence: 2,
            minimum_confidence: ProbabilityQ32::ZERO,
            maximum_ece_ppm: 0,
            maximum_ood_false_acceptance_ppm: 0,
            maximum_in_domain_score: ProbabilityQ32::ONE,
            risk_rule: CanonicalRiskRuleV1::HighOnlySlowPath,
            scorer: LearnedScorerContractV1 {
                model_digest: digest("model"),
                feature_schema_digest: digest("features"),
                output_schema_digest: digest("outputs"),
                score_semantics_digest: digest("semantics"),
                scorer_contract_digest: digest("scorer"),
            },
            calibration_dataset_digest: digest("cal-data"),
            ood_dataset_digest: digest("ood-data"),
            calibration_artifact_digest: digest("calibration"),
            ood_artifact_digest: digest("ood"),
        };
        Ok((request, profile))
    }

    #[test]
    fn assignment_change_preserves_scorer_digest_and_changes_runtime_payload()
    -> Result<(), Box<dyn Error>> {
        let (request, profile) = fixture()?;
        let scoring = ScoringCommitmentV2 {
            model_artifact_digest: profile.scorer.model_digest,
            feature_snapshot_digest: digest("feature-snapshot"),
            feature_schema_digest: profile.scorer.feature_schema_digest,
            scorer_contract_digest: profile.scorer.scorer_contract_digest,
            scored_outputs_digest: canonical_scored_outputs_digest_v2(&request)?,
            policy_digest: request.policy_digest,
            policy_generation: request.policy_generation,
        };
        let assignment = AssignmentCommitmentV1::CounterBased {
            rng_owner_digest: digest("rng-owner"),
            random_stream_digest: digest("stream"),
            counter: request.sequence,
            draw: ProbabilityQ32::ZERO,
        };
        let original_payload =
            canonical_runtime_commitment_payload_v2(&request, &profile, &scoring, &assignment)?;
        let legacy_digest = canonical_scored_outputs_digest_v1(&request)?;

        let mut changed = request;
        changed.candidates[0].assignment_probability = ProbabilityQ32::ZERO;
        if let AssignmentModeV1::CounterBased {
            abstain_probability,
            ..
        } = &mut changed.assignment
        {
            *abstain_probability = ProbabilityQ32::ONE;
        }
        changed.completeness.candidate_set_digest =
            canonical_candidate_set_digest_v1(&changed.candidates)?;

        assert_eq!(
            scoring.scored_outputs_digest,
            canonical_scored_outputs_digest_v2(&changed)?
        );
        assert_ne!(legacy_digest, canonical_scored_outputs_digest_v1(&changed)?);
        let changed_payload =
            canonical_runtime_commitment_payload_v2(&changed, &profile, &scoring, &assignment)?;
        assert_ne!(original_payload, changed_payload);
        Ok(())
    }
}
