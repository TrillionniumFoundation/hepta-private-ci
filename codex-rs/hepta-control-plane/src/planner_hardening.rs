//! Public planner admission hardening.
//!
//! The native planner keeps canonicalization and digest construction in one
//! place. This facade rejects ambiguous input before that canonicalization so
//! callers cannot rely on silent repair of owner or payload identity.

use std::collections::BTreeSet;

use crate::planner::FeasiblePlanReceiptV1;
use crate::planner::GlobalStateSnapshotV1;
use crate::planner::GrantRequestSetV1;
use crate::planner::NduPlanEvaluationInputV1;
use crate::planner::NduPlanEvaluationV1;
use crate::planner::OwnerSummaryV1;
use crate::planner::PlannerError;
use crate::planner::PlanningRequestV1;
use crate::planner::PreparedPlanInputV1;
use crate::planner::SnapshotRequestV1;

/// Collect an exact required-owner snapshot.
///
/// The lower-level collector intentionally records missing required owners, but
/// a supplied owner that was not requested is an input-shape error. Rejecting
/// it here prevents optional or injected state from shortening expiry or
/// poisoning readiness masks for the required set.
pub fn collect_snapshot(
    request: SnapshotRequestV1,
    owner_summaries: Vec<OwnerSummaryV1>,
) -> Result<GlobalStateSnapshotV1, PlannerError> {
    let required = request
        .required_owner_ids
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>();
    if let Some(summary) = owner_summaries
        .iter()
        .find(|summary| !required.contains(&summary.owner_id))
    {
        return Err(PlannerError::DuplicateOwner(format!(
            "unexpected owner {} outside required owner set",
            summary.owner_id
        )));
    }
    crate::planner::collect_snapshot(request, owner_summaries)
}

/// Prepare a plan only from an unambiguous candidate envelope.
///
/// The canonical planner sorts payload digests. The public boundary rejects
/// duplicate payload identities instead of silently deduplicating them, so an
/// upstream construction bug cannot be hidden by normalization.
pub fn prepare_plan(
    snapshot: &GlobalStateSnapshotV1,
    request: PlanningRequestV1,
) -> Result<PreparedPlanInputV1, PlannerError> {
    for candidate in &request.candidates {
        let mut payloads = BTreeSet::new();
        if candidate
            .final_payload_digests
            .iter()
            .any(|digest| !payloads.insert(*digest))
        {
            return Err(PlannerError::DuplicateCandidate(format!(
                "candidate {} repeats a final payload digest",
                candidate.candidate_id
            )));
        }
    }
    crate::planner::prepare_plan(snapshot, request)
}

/// Bind the exact projection returned by the NDU owner.
pub fn bind_ndu_plan_evaluation_v1(
    input: NduPlanEvaluationInputV1,
) -> Result<NduPlanEvaluationV1, PlannerError> {
    crate::planner::bind_ndu_plan_evaluation_v1(input)
}

/// Finalize one prepared bounded plan without changing NDU semantics.
pub fn finalize_plan(
    snapshot: &GlobalStateSnapshotV1,
    prepared: &PreparedPlanInputV1,
    evaluation: &NduPlanEvaluationV1,
    now_micros: u64,
) -> Result<FeasiblePlanReceiptV1, PlannerError> {
    crate::planner::finalize_plan(snapshot, prepared, evaluation, now_micros)
}

/// Construct authority-free requests after revalidating the sealed plan.
pub fn request_execution_grants(
    snapshot: &GlobalStateSnapshotV1,
    prepared: &PreparedPlanInputV1,
    receipt: &FeasiblePlanReceiptV1,
    now_micros: u64,
) -> Result<GrantRequestSetV1, PlannerError> {
    crate::planner::request_execution_grants(snapshot, prepared, receipt, now_micros)
}

#[cfg(test)]
#[path = "planner_hardening_tests.rs"]
mod tests;
