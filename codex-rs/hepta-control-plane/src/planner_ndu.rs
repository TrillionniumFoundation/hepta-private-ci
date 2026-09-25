//! Product composition port: execute the NDU owner implementation before sealing
//! a planning receipt. Owner observations must originate at the trusted host;
//! this adapter binds their scope but does not authenticate arbitrary callers.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

use codex_hepta_ndu::ContributionSet;
use codex_hepta_ndu::EvaluationDisposition;
use codex_hepta_ndu::EvaluationPolicyV1;
use codex_hepta_ndu::NduError;
use codex_hepta_ndu::NduEvaluationReceiptV2;
use codex_hepta_ndu::ScalarizationProfile;
use codex_hepta_ndu::UtilityProfile;
use codex_hepta_ndu::canonical_evaluation_policy_digest;
use codex_hepta_ndu::canonical_scalarization_digest;
use codex_hepta_ndu::canonical_utility_profile_digest;
use codex_hepta_ndu::evaluate_candidates_with_policy;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::FeasiblePlanReceiptV1;
use crate::GlobalStateSnapshotV1;
use crate::NduPlanEvaluationInputV1;
use crate::PlannerError;
use crate::PlanningEvaluationDispositionV1;
use crate::PreparedPlanInputV1;
use crate::bind_ndu_plan_evaluation_v1;
use crate::finalize_plan;

/// Frozen NDU profile and observed owner contributions, never a claimed result.
#[derive(Clone, Debug)]
pub struct NduPlanningInputV1 {
    pub contributions: ContributionSet,
    pub profile: UtilityProfile,
    pub policy: EvaluationPolicyV1,
    pub scalarization: Option<ScalarizationProfile>,
}

/// The original NDU evaluation and sealed, authority-free planning projection.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvaluatedPlanV1 {
    pub ndu_evaluation: NduEvaluationReceiptV2,
    pub plan: FeasiblePlanReceiptV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NduPlanningError {
    Planner(PlannerError),
    Ndu(NduError),
    CandidateCoverage,
    OwnerCoverage(StableId),
}

impl fmt::Display for NduPlanningError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for NduPlanningError {}

/// Freeze this digest in PlanningRequestV1 before preparing candidates. It binds
/// the full utility and optional scalarization profiles as well as NDU policy;
/// contribution observations are separately bound by the actual evaluation.
pub fn canonical_ndu_planning_policy_digest(
    input: &NduPlanningInputV1,
) -> Result<Digest32, NduError> {
    let mut bytes = b"hepta.control.ndu-planning-policy.v1\0".to_vec();
    bytes.extend_from_slice(canonical_utility_profile_digest(&input.profile)?.as_array());
    bytes.extend_from_slice(
        canonical_evaluation_policy_digest(&input.profile, &input.policy)?.as_array(),
    );
    match &input.scalarization {
        Some(profile) => {
            bytes.push(1);
            bytes.extend_from_slice(canonical_scalarization_digest(profile)?.as_array());
        }
        None => bytes.push(0),
    }
    Ok(Digest32::of_bytes(&bytes))
}

pub fn evaluate_prepared_plan_with_ndu(
    snapshot: &GlobalStateSnapshotV1,
    prepared: &PreparedPlanInputV1,
    input: NduPlanningInputV1,
    now_micros: u64,
) -> Result<EvaluatedPlanV1, NduPlanningError> {
    use NduPlanningError as E;
    if input.contributions.contributions.len() > 4096 {
        return Err(E::Ndu(NduError::ContributionLimitExceeded));
    }
    if input.contributions.objective_digest != prepared.objective_digest() {
        return Err(E::Planner(PlannerError::MixedObjective));
    }
    if input.contributions.generation != prepared.body_generation() {
        return Err(E::Planner(PlannerError::MixedBodyGeneration));
    }
    let policy_digest = canonical_ndu_planning_policy_digest(&input).map_err(E::Ndu)?;
    if policy_digest != prepared.evaluation_policy_digest() {
        return Err(E::Planner(PlannerError::EvaluationBindingMismatch));
    }
    let candidates: BTreeMap<_, _> = prepared
        .feasible_candidates()
        .iter()
        .map(|candidate| (candidate.candidate_id.clone(), candidate))
        .collect();
    let observed_owners: BTreeSet<_> = snapshot
        .owner_summaries()
        .iter()
        .map(|owner| owner.owner_id.clone())
        .collect();
    let mut contributed: BTreeMap<StableId, BTreeSet<StableId>> = BTreeMap::new();
    for contribution in &input.contributions.contributions {
        let Some(candidate) = candidates.get(&contribution.candidate_id) else {
            return Err(E::CandidateCoverage);
        };
        if !observed_owners.contains(&contribution.organ_id)
            || !candidate
                .required_owner_ids
                .contains(&contribution.organ_id)
        {
            return Err(E::OwnerCoverage(contribution.organ_id.clone()));
        }
        contributed
            .entry(contribution.candidate_id.clone())
            .or_default()
            .insert(contribution.organ_id.clone());
    }
    if contributed.len() != candidates.len() {
        return Err(E::CandidateCoverage);
    }
    for (candidate_id, candidate) in candidates {
        let required: BTreeSet<_> = candidate.required_owner_ids.iter().cloned().collect();
        if contributed.get(&candidate_id) != Some(&required) {
            return Err(E::OwnerCoverage(candidate_id));
        }
    }
    let evaluation = evaluate_candidates_with_policy(
        input.contributions,
        input.profile,
        input.scalarization,
        input.policy,
    )
    .map_err(E::Ndu)?;
    let base = &evaluation.base;
    let disposition = match base.disposition {
        EvaluationDisposition::InfeasibleExplicitAbstain => {
            PlanningEvaluationDispositionV1::InfeasibleExplicitAbstain
        }
        EvaluationDisposition::UniqueParetoRecommendation => {
            PlanningEvaluationDispositionV1::UniqueParetoRecommendation
        }
        EvaluationDisposition::ParetoSetRequiresSlowPath => {
            PlanningEvaluationDispositionV1::ParetoSetRequiresSlowPath
        }
        EvaluationDisposition::ScalarizedRecommendation => {
            PlanningEvaluationDispositionV1::ScalarizedRecommendation
        }
        EvaluationDisposition::ScalarizationTieRequiresSlowPath => {
            PlanningEvaluationDispositionV1::ScalarizationTieRequiresSlowPath
        }
    };
    // NDU's evaluation digest already commits every candidate uncertainty axis
    // and support digest. Domain separation makes the projection unambiguous.
    let mut uncertainty = b"hepta.control.ndu-uncertainty-projection.v1\0".to_vec();
    uncertainty.extend_from_slice(evaluation.evaluation_digest_v2.as_array());
    let binding = bind_ndu_plan_evaluation_v1(NduPlanEvaluationInputV1 {
        objective_digest: base.objective_digest,
        body_generation: base.generation,
        evaluation_policy_digest: policy_digest,
        evaluation_digest: evaluation.evaluation_digest_v2,
        evaluated_candidate_ids: base
            .evaluated_candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect(),
        rejected_candidate_ids: base
            .rejected_candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect(),
        pareto_candidate_ids: base
            .pareto_frontier
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect(),
        advisory_candidate_id: base.advisory_recommendation.clone(),
        uncertainty_digest: Digest32::of_bytes(&uncertainty),
        disposition,
    })
    .map_err(E::Planner)?;
    let plan = finalize_plan(snapshot, prepared, &binding, now_micros).map_err(E::Planner)?;
    Ok(EvaluatedPlanV1 {
        ndu_evaluation: evaluation,
        plan,
    })
}

#[cfg(test)]
#[path = "planner_ndu_tests.rs"]
mod tests;
