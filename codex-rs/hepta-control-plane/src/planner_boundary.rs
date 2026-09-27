//! Public planner boundary validation. The deterministic kernel stays private.

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
    summaries: Vec<OwnerSummaryV1>,
) -> Result<GlobalStateSnapshotV1, PlannerError> {
    if request.required_owner_ids.len() > 32 || summaries.len() > 32 {
        return Err(PlannerError::LimitExceeded("owners"));
    }
    let required: BTreeSet<_> = request.required_owner_ids.iter().collect();
    if summaries
        .iter()
        .any(|summary| !required.contains(&summary.owner_id))
    {
        // Missing owners remain observable masks. Extra owners may not change
        // expiry, readiness or the meaning of the required-owner cut.
        return Err(PlannerError::PreparedPlanMismatch);
    }
    crate::planner::collect_snapshot(request, summaries)
}

pub fn prepare_plan(
    snapshot: &GlobalStateSnapshotV1,
    request: PlanningRequestV1,
) -> Result<PreparedPlanInputV1, PlannerError> {
    validate_time(snapshot, request.now_micros)?;
    if request.candidates.len() > 128 {
        return Err(PlannerError::LimitExceeded("plan candidates"));
    }
    for candidate in &request.candidates {
        if candidate.resource_costs.len() > 32 {
            return Err(PlannerError::LimitExceeded("candidate resource axes"));
        }
        if candidate.final_payload_digests.len() > 64 {
            return Err(PlannerError::LimitExceeded("candidate payloads"));
        }
        let payloads: BTreeSet<_> = candidate.final_payload_digests.iter().collect();
        if payloads.len() != candidate.final_payload_digests.len() {
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
    validate_time(snapshot, now_micros)?;
    crate::planner::finalize_plan(snapshot, prepared, evaluation, now_micros)
}

pub fn request_execution_grants(
    snapshot: &GlobalStateSnapshotV1,
    prepared: &PreparedPlanInputV1,
    receipt: &FeasiblePlanReceiptV1,
    now_micros: u64,
) -> Result<GrantRequestSetV1, PlannerError> {
    validate_time(snapshot, now_micros)?;
    crate::planner::request_execution_grants(snapshot, prepared, receipt, now_micros)
}

fn validate_time(snapshot: &GlobalStateSnapshotV1, now: u64) -> Result<(), PlannerError> {
    if now < snapshot.collected_at_micros() {
        return Err(PlannerError::InvalidTime("clock before snapshot collection"));
    }
    for summary in snapshot.owner_summaries() {
        let age = now
            .checked_sub(summary.observed_at_micros)
            .ok_or(PlannerError::InvalidTime("clock before owner observation"))?;
        if age > snapshot.maximum_owner_age_micros() {
            return Err(PlannerError::SnapshotExpired);
        }
    }
    Ok(())
}
