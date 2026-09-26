use std::collections::BTreeMap;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ContributionSet;
use crate::EvaluationPolicyV1;
use crate::NduError;
use crate::NduEvaluationReceiptV2;
use crate::ScalarizationProfile;
use crate::UtilityContribution;
use crate::UtilityProfile;
use crate::ValidatedScalarizationProfileV1;
use crate::canonical_evaluation_policy_digest;
use crate::canonical_utility_profile_digest;
use crate::evaluate_candidates_with_policy;

const MAX_CONTRIBUTIONS: usize = 4096;
const MAX_CANDIDATES: usize = 128;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum CandidateQuarantineReasonV1 {
    EnvelopeMismatch,
    EmptySupport,
    DuplicateOrgan,
    MissingRequiredOrgan,
    AxisContractViolation,
    AggregationConflict,
    ArithmeticFailure,
}

impl CandidateQuarantineReasonV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::EnvelopeMismatch => 0,
            Self::EmptySupport => 1,
            Self::DuplicateOrgan => 2,
            Self::MissingRequiredOrgan => 3,
            Self::AxisContractViolation => 4,
            Self::AggregationConflict => 5,
            Self::ArithmeticFailure => 6,
        }
    }
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct QuarantinedCandidateV1 {
    pub candidate_id: StableId,
    pub reason: CandidateQuarantineReasonV1,
    /// Digest of the stable error code, candidate identity and complete error
    /// text. Raw untrusted contributions are deliberately not echoed.
    pub detail_digest: Digest32,
}

/// V3 preserves the V2 decision receipt and separately binds every candidate
/// excluded before cross-candidate comparison.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduEvaluationReceiptV3 {
    pub evaluation: NduEvaluationReceiptV2,
    pub quarantined_candidates: Vec<QuarantinedCandidateV1>,
    pub evaluation_digest_v3: Digest32,
}

/// Evaluate a batch with candidate-local fault isolation.
///
/// Profile, policy, scalarization, batch capacity and the explicit `abstain`
/// candidate remain global fail-closed invariants. A malformed non-abstain
/// candidate is quarantined before Pareto/scalar comparison, so it cannot deny
/// service to unrelated valid candidates or influence their result.
pub fn evaluate_candidates_with_quarantine(
    contributions: ContributionSet,
    utility_profile: &UtilityProfile,
    evaluation_policy: &EvaluationPolicyV1,
    scalarization: Option<&ScalarizationProfile>,
) -> Result<NduEvaluationReceiptV3, NduError> {
    if contributions.contributions.is_empty() {
        return Err(NduError::EmptyContributions);
    }
    if contributions.contributions.len() > MAX_CONTRIBUTIONS {
        return Err(NduError::ContributionLimitExceeded);
    }
    canonical_utility_profile_digest(utility_profile)?;
    canonical_evaluation_policy_digest(utility_profile, evaluation_policy)?;
    if let Some(profile) = scalarization {
        ValidatedScalarizationProfileV1::try_new(utility_profile, profile.clone())?;
    }

    let mut groups: BTreeMap<StableId, Vec<UtilityContribution>> = BTreeMap::new();
    for contribution in contributions.contributions {
        groups
            .entry(contribution.candidate_id.clone())
            .or_default()
            .push(contribution);
    }
    if groups.len() > MAX_CANDIDATES {
        return Err(NduError::CandidateLimitExceeded);
    }
    let abstain_id = groups
        .keys()
        .find(|candidate| candidate.as_str() == "abstain")
        .cloned()
        .ok_or(NduError::MissingAbstainCandidate)?;
    let abstain = groups
        .get(&abstain_id)
        .cloned()
        .ok_or(NduError::MissingAbstainCandidate)?;

    // Validate global policy and the safety fallback first. Any defect in the
    // explicit fallback remains a global error rather than a quarantine.
    evaluate_candidates_with_policy(
        ContributionSet {
            objective_digest: contributions.objective_digest,
            generation: contributions.generation,
            contributions: abstain.clone(),
        },
        utility_profile.clone(),
        scalarization.cloned(),
        evaluation_policy.clone(),
    )?;

    let mut admitted = abstain.clone();
    let mut quarantined = Vec::new();
    for (candidate_id, candidate) in groups {
        if candidate_id == abstain_id {
            continue;
        }
        let mut probe = abstain.clone();
        probe.extend(candidate.iter().cloned());
        let result = evaluate_candidates_with_policy(
            ContributionSet {
                objective_digest: contributions.objective_digest,
                generation: contributions.generation,
                contributions: probe,
            },
            utility_profile.clone(),
            scalarization.cloned(),
            evaluation_policy.clone(),
        );
        match result {
            Ok(_) => admitted.extend(candidate),
            Err(error) => {
                let Some(reason) = quarantine_reason(&error) else {
                    return Err(error);
                };
                quarantined.push(QuarantinedCandidateV1 {
                    detail_digest: quarantine_detail_digest(&candidate_id, &error),
                    candidate_id,
                    reason,
                });
            }
        }
    }
    quarantined.sort();

    let evaluation = evaluate_candidates_with_policy(
        ContributionSet {
            objective_digest: contributions.objective_digest,
            generation: contributions.generation,
            contributions: admitted,
        },
        utility_profile.clone(),
        scalarization.cloned(),
        evaluation_policy.clone(),
    )?;
    let evaluation_digest_v3 = quarantine_receipt_digest(&evaluation, &quarantined);
    Ok(NduEvaluationReceiptV3 {
        evaluation,
        quarantined_candidates: quarantined,
        evaluation_digest_v3,
    })
}

fn quarantine_reason(error: &NduError) -> Option<CandidateQuarantineReasonV1> {
    match error {
        NduError::MixedObjective | NduError::MixedGeneration => {
            Some(CandidateQuarantineReasonV1::EnvelopeMismatch)
        }
        NduError::EmptySupportDigest { .. } => Some(CandidateQuarantineReasonV1::EmptySupport),
        NduError::DuplicateOrganContribution { .. } => {
            Some(CandidateQuarantineReasonV1::DuplicateOrgan)
        }
        NduError::MissingRequiredOrgan { .. } => {
            Some(CandidateQuarantineReasonV1::MissingRequiredOrgan)
        }
        NduError::MissingAxis { .. }
        | NduError::UnknownAxis(_)
        | NduError::DuplicateAxis(_) => {
            Some(CandidateQuarantineReasonV1::AxisContractViolation)
        }
        NduError::AggregationConflict(_) => {
            Some(CandidateQuarantineReasonV1::AggregationConflict)
        }
        NduError::Arithmetic => Some(CandidateQuarantineReasonV1::ArithmeticFailure),
        _ => None,
    }
}

fn quarantine_detail_digest(candidate_id: &StableId, error: &NduError) -> Digest32 {
    let rendered = error.to_string();
    Digest32::of_parts(&[
        b"hepta.ndu.candidate-quarantine-detail.v1\0",
        candidate_id.as_str().as_bytes(),
        b"\0",
        error.code().as_bytes(),
        b"\0",
        rendered.as_bytes(),
    ])
}

fn quarantine_receipt_digest(
    evaluation: &NduEvaluationReceiptV2,
    quarantined: &[QuarantinedCandidateV1],
) -> Digest32 {
    let mut bytes = b"hepta.ndu.evaluation-receipt.v3\0".to_vec();
    bytes.extend_from_slice(evaluation.evaluation_digest_v2.as_array());
    bytes.extend_from_slice(&u32::try_from(quarantined.len()).unwrap_or(u32::MAX).to_be_bytes());
    for candidate in quarantined {
        let id = candidate.candidate_id.as_str().as_bytes();
        bytes.extend_from_slice(&u32::try_from(id.len()).unwrap_or(u32::MAX).to_be_bytes());
        bytes.extend_from_slice(id);
        bytes.push(candidate.reason.tag());
        bytes.extend_from_slice(candidate.detail_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::FixedQ32;
    use codex_hepta_types::Generation;

    use super::*;
    use crate::AggregationOperator;
    use crate::AxisAggregationRule;
    use crate::AxisDirection;
    use crate::AxisValue;
    use crate::FeasibilityPosture;
    use crate::RequiredOrganSet;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    fn profile() -> UtilityProfile {
        UtilityProfile {
            profile_id: id("utility-v1"),
            axis_registry_digest: Digest32::of_bytes(b"axes"),
            normalization_manifest_digest: Digest32::of_bytes(b"normalization"),
            dimensions: vec![(id("success"), AxisDirection::Maximize)],
            risk_ceilings: Vec::new(),
            resource_ceilings: Vec::new(),
            required_organs: RequiredOrganSet {
                organ_ids: vec![id("planner")],
            },
        }
    }

    fn policy() -> EvaluationPolicyV1 {
        EvaluationPolicyV1 {
            policy_id: id("policy-v1"),
            utility_rules: vec![AxisAggregationRule {
                axis: id("success"),
                operator: AggregationOperator::Sum,
            }],
            risk_rules: Vec::new(),
            resource_rules: Vec::new(),
            uncertainty_rules: vec![AxisAggregationRule {
                axis: id("success"),
                operator: AggregationOperator::Maximum,
            }],
            pareto_absolute_tolerances: vec![AxisValue {
                axis: id("success"),
                value: FixedQ32::ZERO,
            }],
        }
    }

    fn contribution(candidate: &str, organ: &str, value: FixedQ32) -> UtilityContribution {
        UtilityContribution {
            candidate_id: id(candidate),
            organ_id: id(organ),
            objective_digest: Digest32::of_bytes(b"objective"),
            generation: Generation::new(1).expect("generation"),
            feasibility: FeasibilityPosture::Feasible,
            utility: vec![AxisValue {
                axis: id("success"),
                value,
            }],
            risk: Vec::new(),
            resource: Vec::new(),
            uncertainty: vec![AxisValue {
                axis: id("success"),
                value: FixedQ32::ZERO,
            }],
            support_digest: Digest32::of_bytes(format!("{candidate}-{organ}").as_bytes()),
        }
    }

    fn set(contributions: Vec<UtilityContribution>) -> ContributionSet {
        ContributionSet {
            objective_digest: Digest32::of_bytes(b"objective"),
            generation: Generation::new(1).expect("generation"),
            contributions,
        }
    }

    #[test]
    fn malformed_non_abstain_is_quarantined_without_hiding_valid_candidate() {
        let receipt = evaluate_candidates_with_quarantine(
            set(vec![
                contribution("abstain", "planner", FixedQ32::ZERO),
                contribution("good", "planner", FixedQ32::ONE),
                contribution("bad", "observer", FixedQ32::ONE),
            ]),
            &profile(),
            &policy(),
            None,
        )
        .expect("quarantine evaluation");
        assert_eq!(
            receipt.evaluation.base.advisory_recommendation,
            Some(id("good"))
        );
        assert_eq!(receipt.quarantined_candidates.len(), 1);
        assert_eq!(receipt.quarantined_candidates[0].candidate_id, id("bad"));
        assert_eq!(
            receipt.quarantined_candidates[0].reason,
            CandidateQuarantineReasonV1::MissingRequiredOrgan
        );
        assert!(!receipt.evaluation_digest_v3.is_zero());
    }

    #[test]
    fn malformed_abstain_remains_global_fail_closed() {
        assert!(matches!(
            evaluate_candidates_with_quarantine(
                set(vec![
                    contribution("abstain", "observer", FixedQ32::ZERO),
                    contribution("good", "planner", FixedQ32::ONE),
                ]),
                &profile(),
                &policy(),
                None,
            ),
            Err(NduError::MissingRequiredOrgan { candidate, .. }) if candidate == "abstain"
        ));
    }
}
