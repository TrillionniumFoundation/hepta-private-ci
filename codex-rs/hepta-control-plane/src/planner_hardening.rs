//! Public planner admission hardening.
//!
//! The native planner keeps canonicalization and digest construction in one
//! place. This facade rejects ambiguous or stale input before normalization so
//! callers cannot rely on silent repair at an authority-sensitive boundary.

use std::collections::BTreeSet;

use super::planner::FeasiblePlanReceiptV1;
use super::planner::GlobalStateSnapshotV1;
use super::planner::GrantRequestSetV1;
use super::planner::NduPlanEvaluationInputV1;
use super::planner::NduPlanEvaluationV1;
use super::planner::OwnerSummaryV1;
use super::planner::PlannerError;
use super::planner::PlanningRequestV1;
use super::planner::PreparedPlanInputV1;
use super::planner::SnapshotRequestV1;

const MAX_OWNERS: usize = 32;
const MAX_CANDIDATES: usize = 128;
const MAX_REQUIRED_OWNERS_PER_CANDIDATE: usize = 32;
const MAX_PAYLOADS_PER_CANDIDATE: usize = 64;
const MAX_RESOURCE_AXES_PER_CANDIDATE: usize = 32;
const MAX_RESOURCE_RESERVATIONS: usize = 32;
const ABSTAIN_ID: &str = "abstain";

/// Collect an exact required-owner snapshot.
pub fn collect_snapshot(
    request: SnapshotRequestV1,
    owner_summaries: Vec<OwnerSummaryV1>,
) -> Result<GlobalStateSnapshotV1, PlannerError> {
    // Reject cardinality before building indexes or cloning identities.
    if request.required_owner_ids.len() > MAX_OWNERS || owner_summaries.len() > MAX_OWNERS {
        return Err(PlannerError::LimitExceeded("owners"));
    }
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
    super::planner::collect_snapshot(request, owner_summaries)
}

/// Prepare a plan only from a fresh snapshot and an unambiguous bounded
/// candidate envelope.
pub fn prepare_plan(
    snapshot: &GlobalStateSnapshotV1,
    request: PlanningRequestV1,
) -> Result<PreparedPlanInputV1, PlannerError> {
    validate_snapshot_freshness(snapshot, request.now_micros)?;
    if request.candidates.len() > MAX_CANDIDATES {
        return Err(PlannerError::LimitExceeded("plan candidates"));
    }
    if request.resource_reservations.len() > MAX_RESOURCE_RESERVATIONS {
        return Err(PlannerError::LimitExceeded("resource reservations"));
    }
    for candidate in &request.candidates {
        if candidate.required_owner_ids.len() > MAX_REQUIRED_OWNERS_PER_CANDIDATE {
            return Err(PlannerError::LimitExceeded("candidate required owners"));
        }
        if candidate.final_payload_digests.len() > MAX_PAYLOADS_PER_CANDIDATE {
            return Err(PlannerError::LimitExceeded("candidate payloads"));
        }
        if candidate.resource_costs.len() > MAX_RESOURCE_AXES_PER_CANDIDATE {
            return Err(PlannerError::LimitExceeded("candidate resource axes"));
        }
        if candidate.candidate_id.as_str() == ABSTAIN_ID
            && !candidate.final_payload_digests.is_empty()
        {
            return Err(PlannerError::AbstainUnavailable);
        }
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
    super::planner::prepare_plan(snapshot, request)
}

/// Bind the exact projection returned by the NDU owner.
pub fn bind_ndu_plan_evaluation_v1(
    input: NduPlanEvaluationInputV1,
) -> Result<NduPlanEvaluationV1, PlannerError> {
    super::planner::bind_ndu_plan_evaluation_v1(input)
}

/// Finalize only while the original snapshot and every owner observation remain
/// fresh at the supplied use time.
pub fn finalize_plan(
    snapshot: &GlobalStateSnapshotV1,
    prepared: &PreparedPlanInputV1,
    evaluation: &NduPlanEvaluationV1,
    now_micros: u64,
) -> Result<FeasiblePlanReceiptV1, PlannerError> {
    validate_snapshot_freshness(snapshot, now_micros)?;
    super::planner::finalize_plan(snapshot, prepared, evaluation, now_micros)
}

/// Construct authority-free requests after revalidating the sealed plan and
/// the freshness of each owner observation.
pub fn request_execution_grants(
    snapshot: &GlobalStateSnapshotV1,
    prepared: &PreparedPlanInputV1,
    receipt: &FeasiblePlanReceiptV1,
    now_micros: u64,
) -> Result<GrantRequestSetV1, PlannerError> {
    validate_snapshot_freshness(snapshot, now_micros)?;
    let requests =
        super::planner::request_execution_grants(snapshot, prepared, receipt, now_micros)?;
    if receipt
        .chosen_candidate_id()
        .is_some_and(|candidate| candidate.as_str() == ABSTAIN_ID)
        && !requests.requests().is_empty()
    {
        return Err(PlannerError::PreparedPlanMismatch);
    }
    Ok(requests)
}

fn validate_snapshot_freshness(
    snapshot: &GlobalStateSnapshotV1,
    now_micros: u64,
) -> Result<(), PlannerError> {
    if now_micros < snapshot.collected_at_micros() {
        return Err(PlannerError::InvalidTime(
            "planning time before snapshot collection",
        ));
    }
    if now_micros >= snapshot.expires_at_micros() {
        return Err(PlannerError::SnapshotExpired);
    }
    for summary in snapshot.owner_summaries() {
        if summary.observed_at_micros > now_micros {
            return Err(PlannerError::FutureOwnerSummary(
                summary.owner_id.to_string(),
            ));
        }
        let age = now_micros
            .checked_sub(summary.observed_at_micros)
            .ok_or(PlannerError::Arithmetic)?;
        if age > snapshot.maximum_owner_age_micros() || now_micros >= summary.expires_at_micros {
            return Err(PlannerError::SnapshotExpired);
        }
    }
    Ok(())
}

#[cfg(test)]
#[path = "planner_hardening_tests.rs"]
mod tests;
