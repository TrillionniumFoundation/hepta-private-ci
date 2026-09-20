use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::collections::btree_map::Entry;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::AggregationOperator;
use crate::AxisAggregationRule;
use crate::AxisDirection;
use crate::AxisLimit;
use crate::AxisValue;
use crate::CandidateRejectionReason;
use crate::CandidateUtility;
use crate::ContributionSet;
use crate::EvaluationDisposition;
use crate::EvaluationPolicyV1;
use crate::FeasibilityPosture;
use crate::NduError;
use crate::NduEvaluationReceipt;
use crate::NduEvaluationReceiptV2;
use crate::RejectedCandidate;
use crate::ScalarizationProfile;
use crate::UtilityContribution;
use crate::UtilityProfile;
use crate::evaluation_digest::EvaluationDigestInput;
use crate::evaluation_digest::digest_evaluation;
use crate::evaluation_digest::digest_profile;
use crate::evaluation_digest::push_axis_values;
use crate::scoring::pareto_frontier;
use crate::scoring::score_frontier;

const MAX_CONTRIBUTIONS: usize = 4096;
const MAX_CANDIDATES: usize = 128;
const MAX_UTILITY_DIMENSIONS: usize = 8;
const MAX_RISK_RESOURCE_DIMENSIONS: usize = 32;
const MAX_REQUIRED_ORGANS: usize = 32;
const SCALARIZATION_DIGEST_DOMAIN: &[u8] = b"hepta.ndu.scalarization-profile.v1";
// V2 identifies non-deteriorating tolerant dominance. Historical V1 policies
// allowed a tolerated loss on other axes, which could create dominance cycles.
const EVALUATION_POLICY_DIGEST_DOMAIN: &[u8] = b"hepta.ndu.evaluation-policy.v2";
const EVALUATION_V2_DIGEST_DOMAIN: &[u8] = b"hepta.ndu.evaluation.v2";
const CONTRIBUTION_DIGEST_DOMAIN: &[u8] = b"hepta.ndu.contribution.v1";

#[derive(Default)]
struct CandidateAccumulator {
    organs: BTreeSet<StableId>,
    utility: BTreeMap<StableId, FixedQ32>,
    risk: BTreeMap<StableId, FixedQ32>,
    resource: BTreeMap<StableId, FixedQ32>,
    uncertainty: BTreeMap<StableId, FixedQ32>,
    support_digests: Vec<Digest32>,
    hard_violation: bool,
}

struct ValidatedEvaluationPolicy {
    utility: BTreeMap<StableId, AggregationOperator>,
    risk: BTreeMap<StableId, AggregationOperator>,
    resource: BTreeMap<StableId, AggregationOperator>,
    uncertainty: BTreeMap<StableId, AggregationOperator>,
    tolerances: BTreeMap<StableId, FixedQ32>,
}

/// Compatibility entry point. Its former implicit sum/sum/sum/max and exact
/// Pareto semantics are now materialized as a digestible policy.
pub fn evaluate_candidates(
    set: ContributionSet,
    profile: UtilityProfile,
    scalarization: Option<ScalarizationProfile>,
) -> Result<NduEvaluationReceipt, NduError> {
    let policy = legacy_evaluation_policy(&profile)?;
    Ok(evaluate_candidates_with_policy(set, profile, scalarization, policy)?.base)
}

/// Applies hard feasibility, complete profile-bound aggregation, tolerant
/// Pareto filtering and optional registered scalarization. Any recommendation
/// remains advisory and carries no selection or effect authority.
pub fn evaluate_candidates_with_policy(
    set: ContributionSet,
    mut profile: UtilityProfile,
    scalarization: Option<ScalarizationProfile>,
    mut policy: EvaluationPolicyV1,
) -> Result<NduEvaluationReceiptV2, NduError> {
    validate_profile(&mut profile)?;
    validate_contribution_envelope(&set)?;
    let validated_policy = validate_evaluation_policy(&profile, &mut policy)?;
    let evaluation_policy_digest = digest_evaluation_policy(&policy);
    let utility_profile_digest = digest_profile(&profile);

    let mut grouped: BTreeMap<StableId, CandidateAccumulator> = BTreeMap::new();
    for contribution in set.contributions {
        accumulate(&mut grouped, contribution, &profile, &validated_policy)?;
    }
    if grouped.len() > MAX_CANDIDATES {
        return Err(NduError::CandidateLimitExceeded);
    }
    let abstain = stable_id("abstain")?;
    if !grouped.contains_key(&abstain) {
        return Err(NduError::MissingAbstainCandidate);
    }

    let mut evaluated_candidates = Vec::new();
    let mut rejected_candidates = Vec::new();
    for (candidate_id, accumulator) in grouped {
        validate_required_organs(&candidate_id, &accumulator, &profile)?;
        let mut reasons = Vec::new();
        if accumulator.hard_violation {
            reasons.push(CandidateRejectionReason::HardConstraintViolation);
        }
        if exceeds_any(&candidate_id, &accumulator.risk, &profile.risk_ceilings)? {
            reasons.push(CandidateRejectionReason::RiskCeilingExceeded);
        }
        if exceeds_any(
            &candidate_id,
            &accumulator.resource,
            &profile.resource_ceilings,
        )? {
            reasons.push(CandidateRejectionReason::ResourceCeilingExceeded);
        }
        if reasons.is_empty() {
            evaluated_candidates.push(finalize_candidate(candidate_id, accumulator, &profile)?);
        } else {
            rejected_candidates.push(RejectedCandidate {
                candidate_id,
                reasons,
            });
        }
    }

    evaluated_candidates.sort_by(candidate_order);
    rejected_candidates.sort_by(rejected_order);
    if rejected_candidates
        .iter()
        .any(|candidate| candidate.candidate_id == abstain)
    {
        return Err(NduError::AbstainInfeasible);
    }

    let mut frontier = pareto_frontier(
        &evaluated_candidates,
        &profile.dimensions,
        &validated_policy.tolerances,
    );
    frontier.sort_by(candidate_order);
    let scalarization_profile_digest = scalarization
        .as_ref()
        .map(canonical_scalarization_digest)
        .transpose()?;
    let (disposition, advisory_recommendation) =
        if evaluated_candidates.len() == 1 && evaluated_candidates[0].candidate_id == abstain {
            (
                EvaluationDisposition::InfeasibleExplicitAbstain,
                Some(abstain),
            )
        } else if frontier.len() == 1 {
            (
                EvaluationDisposition::UniqueParetoRecommendation,
                Some(frontier[0].candidate_id.clone()),
            )
        } else if let Some(scalarization) = scalarization {
            score_frontier(&mut frontier, &profile, scalarization)?
        } else {
            (EvaluationDisposition::ParetoSetRequiresSlowPath, None)
        };

    let evaluation_digest = digest_evaluation(EvaluationDigestInput {
        objective_digest: set.objective_digest,
        generation: set.generation.get(),
        disposition,
        evaluated: &evaluated_candidates,
        rejected: &rejected_candidates,
        frontier: &frontier,
        advisory: advisory_recommendation.as_ref(),
        utility_profile_digest,
        scalarization_digest: scalarization_profile_digest,
    });
    let base = NduEvaluationReceipt {
        objective_digest: set.objective_digest,
        generation: set.generation,
        disposition,
        utility_profile_digest,
        scalarization_profile_digest,
        evaluated_candidates,
        rejected_candidates,
        pareto_frontier: frontier,
        advisory_recommendation,
        evaluation_digest,
    };
    let evaluation_digest_v2 = digest_evaluation_v2(&base, evaluation_policy_digest);
    Ok(NduEvaluationReceiptV2 {
        base,
        evaluation_policy_digest,
        evaluation_digest_v2,
    })
}

/// Returns the exact compatibility policy used by `evaluate_candidates`.
pub fn legacy_evaluation_policy(profile: &UtilityProfile) -> Result<EvaluationPolicyV1, NduError> {
    Ok(EvaluationPolicyV1 {
        policy_id: stable_id("legacy-sum-max-zero-tolerance-v1")?,
        utility_rules: profile
            .dimensions
            .iter()
            .map(|(axis, _)| AxisAggregationRule {
                axis: axis.clone(),
                operator: AggregationOperator::Sum,
            })
            .collect(),
        risk_rules: profile
            .risk_ceilings
            .iter()
            .map(|limit| AxisAggregationRule {
                axis: limit.axis.clone(),
                operator: AggregationOperator::Sum,
            })
            .collect(),
        resource_rules: profile
            .resource_ceilings
            .iter()
            .map(|limit| AxisAggregationRule {
                axis: limit.axis.clone(),
                operator: AggregationOperator::Sum,
            })
            .collect(),
        uncertainty_rules: profile
            .dimensions
            .iter()
            .map(|(axis, _)| AxisAggregationRule {
                axis: axis.clone(),
                operator: AggregationOperator::Maximum,
            })
            .collect(),
        pareto_absolute_tolerances: profile
            .dimensions
            .iter()
            .map(|(axis, _)| AxisValue {
                axis: axis.clone(),
                value: FixedQ32::ZERO,
            })
            .collect(),
    })
}

/// Binds all utility directions, feasibility ceilings and required organs.
pub fn canonical_utility_profile_digest(profile: &UtilityProfile) -> Result<Digest32, NduError> {
    let mut normalized = profile.clone();
    validate_profile(&mut normalized)?;
    Ok(digest_profile(&normalized))
}

pub fn canonical_evaluation_policy_digest(
    profile: &UtilityProfile,
    policy: &EvaluationPolicyV1,
) -> Result<Digest32, NduError> {
    let mut normalized_profile = profile.clone();
    let mut normalized_policy = policy.clone();
    validate_profile(&mut normalized_profile)?;
    validate_evaluation_policy(&normalized_profile, &mut normalized_policy)?;
    Ok(digest_evaluation_policy(&normalized_policy))
}

/// Returns the canonical digest of a scalarization profile after validating and
/// normalizing it. This does not register or authorize the profile.
pub fn canonical_scalarization_digest(
    profile: &ScalarizationProfile,
) -> Result<Digest32, NduError> {
    let mut normalized = profile.clone();
    normalize_axis_values(&mut normalized.weights)?;
    let mut bytes = Vec::new();
    bytes.extend_from_slice(SCALARIZATION_DIGEST_DOMAIN);
    push_id(&mut bytes, &normalized.profile_id);
    push_axis_values(&mut bytes, &normalized.weights);
    Ok(Digest32::of_bytes(&bytes))
}

fn validate_contribution_envelope(set: &ContributionSet) -> Result<(), NduError> {
    if set.objective_digest.is_zero() {
        return Err(NduError::EmptyObjectiveDigest);
    }
    if set.contributions.is_empty() {
        return Err(NduError::EmptyContributions);
    }
    if set.contributions.len() > MAX_CONTRIBUTIONS {
        return Err(NduError::ContributionLimitExceeded);
    }
    if set
        .contributions
        .iter()
        .any(|value| value.objective_digest != set.objective_digest)
    {
        return Err(NduError::MixedObjective);
    }
    if set
        .contributions
        .iter()
        .any(|value| value.generation != set.generation)
    {
        return Err(NduError::MixedGeneration);
    }
    Ok(())
}

fn validate_profile(profile: &mut UtilityProfile) -> Result<(), NduError> {
    if profile.dimensions.is_empty()
        || profile.dimensions.len() > MAX_UTILITY_DIMENSIONS
        || profile.risk_ceilings.len() > MAX_RISK_RESOURCE_DIMENSIONS
        || profile.resource_ceilings.len() > MAX_RISK_RESOURCE_DIMENSIONS
    {
        return Err(NduError::DimensionLimitExceeded);
    }
    if profile.required_organs.organ_ids.len() > MAX_REQUIRED_ORGANS {
        return Err(NduError::RequiredOrganLimitExceeded);
    }
    profile.dimensions.sort_by(dimension_order);
    profile.risk_ceilings.sort();
    profile.resource_ceilings.sort();
    profile.required_organs.organ_ids.sort();
    reject_duplicate_ids(profile.dimensions.iter().map(|value| &value.0))?;
    reject_duplicate_ids(profile.risk_ceilings.iter().map(|value| &value.axis))?;
    reject_duplicate_ids(profile.resource_ceilings.iter().map(|value| &value.axis))?;
    reject_duplicate_ids(profile.required_organs.organ_ids.iter())?;
    for limit in profile
        .risk_ceilings
        .iter()
        .chain(profile.resource_ceilings.iter())
    {
        if limit.maximum < FixedQ32::ZERO {
            return Err(NduError::NegativeCeiling(limit.axis.to_string()));
        }
    }
    Ok(())
}

fn validate_evaluation_policy(
    profile: &UtilityProfile,
    policy: &mut EvaluationPolicyV1,
) -> Result<ValidatedEvaluationPolicy, NduError> {
    policy.utility_rules.sort();
    policy.risk_rules.sort();
    policy.resource_rules.sort();
    policy.uncertainty_rules.sort();
    normalize_axis_values(&mut policy.pareto_absolute_tolerances)?;

    let utility = rule_map(&policy.utility_rules)?;
    let risk = rule_map(&policy.risk_rules)?;
    let resource = rule_map(&policy.resource_rules)?;
    let uncertainty = rule_map(&policy.uncertainty_rules)?;
    let tolerances: BTreeMap<_, _> = policy
        .pareto_absolute_tolerances
        .iter()
        .map(|value| (value.axis.clone(), value.value))
        .collect();

    let utility_axes: BTreeSet<_> = profile
        .dimensions
        .iter()
        .map(|(axis, _)| axis.clone())
        .collect();
    let risk_axes: BTreeSet<_> = profile
        .risk_ceilings
        .iter()
        .map(|value| value.axis.clone())
        .collect();
    let resource_axes: BTreeSet<_> = profile
        .resource_ceilings
        .iter()
        .map(|value| value.axis.clone())
        .collect();

    validate_rule_axes(&utility_axes, &utility)?;
    validate_rule_axes(&risk_axes, &risk)?;
    validate_rule_axes(&resource_axes, &resource)?;
    validate_rule_axes(&utility_axes, &uncertainty)?;
    validate_value_axes(&utility_axes, &tolerances)?;
    for (axis, tolerance) in &tolerances {
        if *tolerance < FixedQ32::ZERO {
            return Err(NduError::NegativeTolerance(axis.to_string()));
        }
    }

    Ok(ValidatedEvaluationPolicy {
        utility,
        risk,
        resource,
        uncertainty,
        tolerances,
    })
}

fn rule_map(
    rules: &[AxisAggregationRule],
) -> Result<BTreeMap<StableId, AggregationOperator>, NduError> {
    let mut result = BTreeMap::new();
    for rule in rules {
        if result.insert(rule.axis.clone(), rule.operator).is_some() {
            return Err(NduError::DuplicateAggregationRule(rule.axis.to_string()));
        }
    }
    Ok(result)
}

fn validate_rule_axes(
    expected: &BTreeSet<StableId>,
    actual: &BTreeMap<StableId, AggregationOperator>,
) -> Result<(), NduError> {
    for axis in expected {
        if !actual.contains_key(axis) {
            return Err(NduError::MissingAggregationRule(axis.to_string()));
        }
    }
    for axis in actual.keys() {
        if !expected.contains(axis) {
            return Err(NduError::AggregationAxisMismatch(axis.to_string()));
        }
    }
    Ok(())
}

fn validate_value_axes(
    expected: &BTreeSet<StableId>,
    actual: &BTreeMap<StableId, FixedQ32>,
) -> Result<(), NduError> {
    for axis in expected {
        if !actual.contains_key(axis) {
            return Err(NduError::MissingAggregationRule(axis.to_string()));
        }
    }
    for axis in actual.keys() {
        if !expected.contains(axis) {
            return Err(NduError::AggregationAxisMismatch(axis.to_string()));
        }
    }
    Ok(())
}

fn reject_duplicate_ids<'a>(values: impl Iterator<Item = &'a StableId>) -> Result<(), NduError> {
    let mut seen = BTreeSet::new();
    for value in values {
        if !seen.insert(value.clone()) {
            return Err(NduError::DuplicateAxis(value.to_string()));
        }
    }
    Ok(())
}

fn accumulate(
    grouped: &mut BTreeMap<StableId, CandidateAccumulator>,
    mut contribution: UtilityContribution,
    profile: &UtilityProfile,
    policy: &ValidatedEvaluationPolicy,
) -> Result<(), NduError> {
    if contribution.support_digest.is_zero() {
        return Err(NduError::EmptySupportDigest {
            candidate: contribution.candidate_id.to_string(),
            organ: contribution.organ_id.to_string(),
        });
    }
    validate_contribution_dimensions(&contribution)?;
    normalize_axis_values(&mut contribution.utility)?;
    normalize_axis_values(&mut contribution.risk)?;
    normalize_axis_values(&mut contribution.resource)?;
    normalize_axis_values(&mut contribution.uncertainty)?;
    validate_known_axes(&contribution, profile)?;
    let contribution_digest = digest_contribution(&contribution);
    let candidate_id = contribution.candidate_id.clone();
    let accumulator = grouped.entry(candidate_id.clone()).or_default();
    if !accumulator.organs.insert(contribution.organ_id.clone()) {
        return Err(NduError::DuplicateOrganContribution {
            candidate: candidate_id.to_string(),
            organ: contribution.organ_id.to_string(),
        });
    }
    accumulator.hard_violation |=
        contribution.feasibility == FeasibilityPosture::HardConstraintViolation;
    aggregate_values(
        &mut accumulator.utility,
        contribution.utility,
        &policy.utility,
    )?;
    aggregate_values(&mut accumulator.risk, contribution.risk, &policy.risk)?;
    aggregate_values(
        &mut accumulator.resource,
        contribution.resource,
        &policy.resource,
    )?;
    aggregate_values(
        &mut accumulator.uncertainty,
        contribution.uncertainty,
        &policy.uncertainty,
    )?;
    accumulator.support_digests.push(contribution_digest);
    Ok(())
}

fn aggregate_values(
    target: &mut BTreeMap<StableId, FixedQ32>,
    values: Vec<AxisValue>,
    rules: &BTreeMap<StableId, AggregationOperator>,
) -> Result<(), NduError> {
    for value in values {
        let operator = rules
            .get(&value.axis)
            .copied()
            .ok_or_else(|| NduError::MissingAggregationRule(value.axis.to_string()))?;
        match target.entry(value.axis.clone()) {
            Entry::Vacant(entry) => {
                entry.insert(value.value);
            }
            Entry::Occupied(mut entry) => {
                let current = *entry.get();
                let next = match operator {
                    AggregationOperator::Sum => current
                        .checked_add(value.value)
                        .map_err(|_| NduError::Arithmetic)?,
                    AggregationOperator::Maximum => current.max(value.value),
                    AggregationOperator::Minimum => current.min(value.value),
                    AggregationOperator::RequireEqual if current == value.value => current,
                    AggregationOperator::RequireEqual => {
                        return Err(NduError::AggregationConflict(value.axis.to_string()));
                    }
                };
                entry.insert(next);
            }
        }
    }
    Ok(())
}

fn validate_contribution_dimensions(contribution: &UtilityContribution) -> Result<(), NduError> {
    if contribution.utility.len() > MAX_UTILITY_DIMENSIONS
        || contribution.risk.len() > MAX_RISK_RESOURCE_DIMENSIONS
        || contribution.resource.len() > MAX_RISK_RESOURCE_DIMENSIONS
        || contribution.uncertainty.len() > MAX_UTILITY_DIMENSIONS
    {
        return Err(NduError::DimensionLimitExceeded);
    }
    Ok(())
}

pub(crate) fn normalize_axis_values(values: &mut [AxisValue]) -> Result<(), NduError> {
    values.sort();
    for window in values.windows(2) {
        if window[0].axis == window[1].axis {
            return Err(NduError::DuplicateAxis(window[0].axis.to_string()));
        }
    }
    Ok(())
}

fn validate_known_axes(
    contribution: &UtilityContribution,
    profile: &UtilityProfile,
) -> Result<(), NduError> {
    let utility: BTreeSet<_> = profile.dimensions.iter().map(|value| &value.0).collect();
    let risk: BTreeSet<_> = profile
        .risk_ceilings
        .iter()
        .map(|value| &value.axis)
        .collect();
    let resource: BTreeSet<_> = profile
        .resource_ceilings
        .iter()
        .map(|value| &value.axis)
        .collect();
    for value in contribution
        .utility
        .iter()
        .chain(contribution.uncertainty.iter())
    {
        if !utility.contains(&value.axis) {
            return Err(NduError::UnknownAxis(value.axis.to_string()));
        }
    }
    for value in &contribution.risk {
        if !risk.contains(&value.axis) {
            return Err(NduError::UnknownAxis(value.axis.to_string()));
        }
    }
    for value in &contribution.resource {
        if !resource.contains(&value.axis) {
            return Err(NduError::UnknownAxis(value.axis.to_string()));
        }
    }
    Ok(())
}

fn validate_required_organs(
    candidate_id: &StableId,
    accumulator: &CandidateAccumulator,
    profile: &UtilityProfile,
) -> Result<(), NduError> {
    for organ_id in &profile.required_organs.organ_ids {
        if !accumulator.organs.contains(organ_id) {
            return Err(NduError::MissingRequiredOrgan {
                candidate: candidate_id.to_string(),
                organ: organ_id.to_string(),
            });
        }
    }
    Ok(())
}

fn exceeds_any(
    candidate_id: &StableId,
    values: &BTreeMap<StableId, FixedQ32>,
    ceilings: &[AxisLimit],
) -> Result<bool, NduError> {
    for ceiling in ceilings {
        let value = values
            .get(&ceiling.axis)
            .ok_or_else(|| NduError::MissingAxis {
                candidate: candidate_id.to_string(),
                axis: ceiling.axis.to_string(),
            })?;
        if *value > ceiling.maximum {
            return Ok(true);
        }
    }
    Ok(false)
}

fn finalize_candidate(
    candidate_id: StableId,
    mut accumulator: CandidateAccumulator,
    profile: &UtilityProfile,
) -> Result<CandidateUtility, NduError> {
    for (axis, _) in &profile.dimensions {
        if !accumulator.utility.contains_key(axis) {
            return Err(NduError::MissingAxis {
                candidate: candidate_id.to_string(),
                axis: axis.to_string(),
            });
        }
        if !accumulator.uncertainty.contains_key(axis) {
            return Err(NduError::MissingAxis {
                candidate: candidate_id.to_string(),
                axis: format!("uncertainty:{axis}"),
            });
        }
    }
    accumulator.support_digests.sort();
    let mut support = Vec::with_capacity(accumulator.support_digests.len() * 32);
    for digest in accumulator.support_digests {
        support.extend_from_slice(digest.as_array());
    }
    Ok(CandidateUtility {
        candidate_id,
        utility: into_axis_values(accumulator.utility),
        risk: into_axis_values(accumulator.risk),
        resource: into_axis_values(accumulator.resource),
        uncertainty: into_axis_values(accumulator.uncertainty),
        support_digest: Digest32::of_bytes(&support),
        scalar_score: None,
    })
}

fn into_axis_values(values: BTreeMap<StableId, FixedQ32>) -> Vec<AxisValue> {
    values
        .into_iter()
        .map(|(axis, value)| AxisValue { axis, value })
        .collect()
}

fn digest_contribution(contribution: &UtilityContribution) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(CONTRIBUTION_DIGEST_DOMAIN);
    push_id(&mut bytes, &contribution.candidate_id);
    push_id(&mut bytes, &contribution.organ_id);
    bytes.extend_from_slice(contribution.objective_digest.as_array());
    bytes.extend_from_slice(&contribution.generation.get().to_be_bytes());
    bytes.push(match contribution.feasibility {
        FeasibilityPosture::Feasible => 0,
        FeasibilityPosture::HardConstraintViolation => 1,
    });
    push_axis_values(&mut bytes, &contribution.utility);
    push_axis_values(&mut bytes, &contribution.risk);
    push_axis_values(&mut bytes, &contribution.resource);
    push_axis_values(&mut bytes, &contribution.uncertainty);
    bytes.extend_from_slice(contribution.support_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn digest_evaluation_policy(policy: &EvaluationPolicyV1) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(EVALUATION_POLICY_DIGEST_DOMAIN);
    push_id(&mut bytes, &policy.policy_id);
    push_rules(&mut bytes, &policy.utility_rules);
    push_rules(&mut bytes, &policy.risk_rules);
    push_rules(&mut bytes, &policy.resource_rules);
    push_rules(&mut bytes, &policy.uncertainty_rules);
    push_axis_values(&mut bytes, &policy.pareto_absolute_tolerances);
    Digest32::of_bytes(&bytes)
}

fn digest_evaluation_v2(
    receipt: &NduEvaluationReceipt,
    evaluation_policy_digest: Digest32,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(EVALUATION_V2_DIGEST_DOMAIN);
    bytes.extend_from_slice(receipt.evaluation_digest.as_array());
    bytes.extend_from_slice(evaluation_policy_digest.as_array());
    bytes.push(receipt.disposition.tag());
    Digest32::of_bytes(&bytes)
}

fn push_rules(bytes: &mut Vec<u8>, rules: &[AxisAggregationRule]) {
    push_len(bytes, rules.len());
    for rule in rules {
        push_id(bytes, &rule.axis);
        bytes.push(rule.operator.tag());
    }
}

fn stable_id(value: &str) -> Result<StableId, NduError> {
    StableId::new(value).map_err(|_| NduError::Arithmetic)
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

fn dimension_order(
    left: &(StableId, AxisDirection),
    right: &(StableId, AxisDirection),
) -> std::cmp::Ordering {
    (&left.0, left.1).cmp(&(&right.0, right.1))
}

fn candidate_order(left: &CandidateUtility, right: &CandidateUtility) -> std::cmp::Ordering {
    left.candidate_id.cmp(&right.candidate_id)
}

fn rejected_order(left: &RejectedCandidate, right: &RejectedCandidate) -> std::cmp::Ordering {
    left.candidate_id.cmp(&right.candidate_id)
}

#[cfg(test)]
#[path = "evaluator_tests.rs"]
mod tests;
