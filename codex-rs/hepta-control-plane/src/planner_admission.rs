use std::collections::BTreeSet;

use crate::GlobalStateSnapshotV1;
use crate::OwnerSummaryV1;
use crate::PlannerError;
use crate::PlanningRequestV1;
use crate::PreparedPlanInputV1;
use crate::SnapshotRequestV1;

/// Strict public snapshot admission. Every supplied summary must be requested;
/// callers cannot inject an optional stale/unavailable owner that shortens the
/// snapshot lifetime or poisons readiness masks.
pub fn collect_snapshot(
    request: SnapshotRequestV1,
    owner_summaries: Vec<OwnerSummaryV1>,
) -> Result<GlobalStateSnapshotV1, PlannerError> {
    let required = request
        .required_owner_ids
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>();
    if let Some(unexpected) = owner_summaries
        .iter()
        .find(|summary| !required.contains(&summary.owner_id))
    {
        return Err(PlannerError::DuplicateOwner(format!(
            "unexpected owner summary: {}",
            unexpected.owner_id
        )));
    }
    crate::planner::collect_snapshot(request, owner_summaries)
}

/// Strict public plan admission. Duplicate payload digests are malformed input,
/// not a normalization opportunity: silently deduplicating them would erase an
/// upstream construction error and change grant-request multiplicity.
pub fn prepare_plan(
    snapshot: &GlobalStateSnapshotV1,
    request: PlanningRequestV1,
) -> Result<PreparedPlanInputV1, PlannerError> {
    for candidate in &request.candidates {
        let mut payloads = candidate.final_payload_digests.clone();
        payloads.sort();
        if payloads.windows(2).any(|window| window[0] == window[1]) {
            return Err(PlannerError::DuplicateCandidate(format!(
                "{} contains duplicate final payload digest",
                candidate.candidate_id
            )));
        }
    }
    crate::planner::prepare_plan(snapshot, request)
}

#[cfg(test)]
#[path = "planner_admission_tests.rs"]
mod tests;
