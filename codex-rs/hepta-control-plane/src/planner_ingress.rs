//! Public ingress for the sealed planning kernel.
//!
//! The kernel remains private to this crate. These checks run before its
//! normalization/allocations, so an invalid caller input cannot be silently
//! repaired into a different admitted request. No authority is created here.

use std::collections::BTreeSet;

use crate::FeasiblePlanReceiptV1;
use crate::GlobalStateSnapshotV1;
use crate::GrantRequestSetV1;
use crate::NduPlanEvaluationInputV1;
use crate::NduPlanEvaluationV1;
use crate::OwnerSummaryV1;
use crate::PlannerError;
use crate::PlanningRequestV1;
use crate::PreparedPlanInputV1;
use crate::SnapshotRequestV1;

pub fn collect_snapshot(
    request: SnapshotRequestV1,
    owners: Vec<OwnerSummaryV1>,
) -> Result<GlobalStateSnapshotV1, PlannerError> {
    if request.required_owner_ids.len() > 32 || owners.len() > 32 {
        return Err(PlannerError::LimitExceeded("owners"));
    }
    let required: BTreeSet<_> = request.required_owner_ids.iter().collect();
    if owners.iter().any(|owner| !required.contains(&owner.owner_id)) {
        // V1 admits exactly the required set; it has no implicit optional-owner
        // semantics. Missing owners remain representable as an observation.
        return Err(PlannerError::IncompleteSnapshot);
    }
    crate::planner::collect_snapshot(request, owners)
}

pub fn prepare_plan(
    snapshot: &GlobalStateSnapshotV1,
    request: PlanningRequestV1,
) -> Result<PreparedPlanInputV1, PlannerError> {
    validate_clock(snapshot, request.now_micros)?;
    if request.candidates.len() > 128 {
        return Err(PlannerError::LimitExceeded("plan candidates"));
    }
    for candidate in &request.candidates {
        if candidate.final_payload_digests.len() > 64 {
            return Err(PlannerError::LimitExceeded("candidate payloads"));
        }
        if candidate.resource_costs.len() > 32 {
            return Err(PlannerError::LimitExceeded("candidate resource axes"));
        }
        let payloads: BTreeSet<_> = candidate.final_payload_digests.iter().collect();
        if payloads.len() != candidate.final_payload_digests.len() {
            // Preserve the public V1 error surface. An ambiguous request is not
            // a sealed prepared input; the kernel must not deduplicate it.
            return Err(PlannerError::PreparedPlanMismatch);
        }
        if candidate.candidate_id.as_str() == "abstain"
            && !candidate.final_payload_digests.is_empty()
        {
            return Err(PlannerError::AbstainUnavailable);
        }
    }
    crate::planner::prepare_plan(snapshot, request)
}

pub fn bind_ndu_plan_evaluation_v1(
    input: NduPlanEvaluationInputV1,
) -> Result<NduPlanEvaluationV1, PlannerError> {
    if input.evaluated_candidate_ids.len() > 128
        || input.rejected_candidate_ids.len() > 128
        || input.pareto_candidate_ids.len() > 128
        || input.evaluated_candidate_ids.len() + input.rejected_candidate_ids.len() > 128
    {
        return Err(PlannerError::LimitExceeded("NDU candidate projection"));
    }
    crate::planner::bind_ndu_plan_evaluation_v1(input)
}

pub fn finalize_plan(
    snapshot: &GlobalStateSnapshotV1,
    prepared: &PreparedPlanInputV1,
    evaluation: &NduPlanEvaluationV1,
    now_micros: u64,
) -> Result<FeasiblePlanReceiptV1, PlannerError> {
    validate_clock(snapshot, now_micros)?;
    crate::planner::finalize_plan(snapshot, prepared, evaluation, now_micros)
}

pub fn request_execution_grants(
    snapshot: &GlobalStateSnapshotV1,
    prepared: &PreparedPlanInputV1,
    receipt: &FeasiblePlanReceiptV1,
    now_micros: u64,
) -> Result<GrantRequestSetV1, PlannerError> {
    validate_clock(snapshot, now_micros)?;
    crate::planner::request_execution_grants(snapshot, prepared, receipt, now_micros)
}

fn validate_clock(snapshot: &GlobalStateSnapshotV1, now: u64) -> Result<(), PlannerError> {
    if now < snapshot.collected_at_micros() {
        return Err(PlannerError::InvalidTime("clock precedes snapshot collection"));
    }
    Ok(())
}

#[cfg(test)]
#[path = "planner_ingress_tests.rs"]
mod tests;
