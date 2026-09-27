//! Public admission boundary for the deterministic planning kernel.
//!
//! Keep normalization behind validation: an input which is not a bounded,
//! unambiguous member of the declared contract must not be silently repaired.
//! The private kernel retains its existing algorithms and regression fixtures.

use std::collections::BTreeSet;

#[path = "planner_kernel.rs"]
mod kernel;

pub use kernel::FeasiblePlanReceiptV1;
pub use kernel::GlobalStateSnapshotV1;
pub use kernel::GrantRequestSetV1;
pub use kernel::GrantRequestV1;
pub use kernel::NduPlanEvaluationInputV1;
pub use kernel::NduPlanEvaluationV1;
pub use kernel::OwnerReadinessV1;
pub use kernel::OwnerSummaryV1;
pub use kernel::PlanCandidateV1;
pub use kernel::PlannerAxisValueV1;
pub use kernel::PlannerError;
pub use kernel::PlanningEvaluationDispositionV1;
pub use kernel::PlanningRequestV1;
pub use kernel::PreparedPlanInputV1;
pub use kernel::ResourceReservationV1;
pub use kernel::SearchDisclosureV1;
pub use kernel::SnapshotRequestV1;

const MAX_OWNERS: usize = 32;
const MAX_CANDIDATES: usize = 128;
const MAX_RESOURCE_AXES: usize = 32;
const MAX_PAYLOADS: usize = 64;

/// Admit exactly the declared owner set. Missing owners remain observable via
/// the kernel's explicit mask; undeclared owners are not optional owners.
/// `IncompleteSnapshot` also covers a summary outside this closed owner set.
pub fn collect_snapshot(
    request: SnapshotRequestV1,
    owner_summaries: Vec<OwnerSummaryV1>,
) -> Result<GlobalStateSnapshotV1, PlannerError> {
    if request.required_owner_ids.len() > MAX_OWNERS || owner_summaries.len() > MAX_OWNERS {
        return Err(PlannerError::LimitExceeded("owners"));
    }
    let required: BTreeSet<_> = request.required_owner_ids.iter().collect();
    if owner_summaries
        .iter()
        .any(|summary| !required.contains(&summary.owner_id))
    {
        return Err(PlannerError::IncompleteSnapshot);
    }
    kernel::collect_snapshot(request, owner_summaries)
}

/// Validate resource and payload collections before the kernel sorts them.
/// Repeated payloads are a noncanonical plan, not a request to deduplicate.
pub fn prepare_plan(
    snapshot: &GlobalStateSnapshotV1,
    request: PlanningRequestV1,
) -> Result<PreparedPlanInputV1, PlannerError> {
    validate_current_observations(snapshot, request.now_micros)?;
    if request.candidates.len() > MAX_CANDIDATES {
        return Err(PlannerError::LimitExceeded("plan candidates"));
    }
    for candidate in &request.candidates {
        if candidate.resource_costs.len() > MAX_RESOURCE_AXES {
            return Err(PlannerError::LimitExceeded("candidate resource axes"));
        }
        if candidate.final_payload_digests.len() > MAX_PAYLOADS {
            return Err(PlannerError::LimitExceeded("candidate payloads"));
        }
        let payloads: BTreeSet<_> = candidate.final_payload_digests.iter().collect();
        if payloads.len() != candidate.final_payload_digests.len()
            || (candidate.candidate_id.as_str() == "abstain" && !payloads.is_empty())
        {
            return Err(PlannerError::PreparedPlanMismatch);
        }
    }
    kernel::prepare_plan(snapshot, request)
}

/// Bound all owner-port collections before sorting, cloning or hashing them.
pub fn bind_ndu_plan_evaluation_v1(
    input: NduPlanEvaluationInputV1,
) -> Result<NduPlanEvaluationV1, PlannerError> {
    if input.evaluated_candidate_ids.len() > MAX_CANDIDATES
        || input.rejected_candidate_ids.len() > MAX_CANDIDATES
        || input.pareto_candidate_ids.len() > MAX_CANDIDATES
        || input.evaluated_candidate_ids.len() + input.rejected_candidate_ids.len()
            > MAX_CANDIDATES
    {
        return Err(PlannerError::LimitExceeded("NDU candidate projection"));
    }
    kernel::bind_ndu_plan_evaluation_v1(input)
}

pub fn finalize_plan(
    snapshot: &GlobalStateSnapshotV1,
    prepared: &PreparedPlanInputV1,
    evaluation: &NduPlanEvaluationV1,
    now_micros: u64,
) -> Result<FeasiblePlanReceiptV1, PlannerError> {
    validate_current_observations(snapshot, now_micros)?;
    kernel::finalize_plan(snapshot, prepared, evaluation, now_micros)
}

pub fn request_execution_grants(
    snapshot: &GlobalStateSnapshotV1,
    prepared: &PreparedPlanInputV1,
    receipt: &FeasiblePlanReceiptV1,
    now_micros: u64,
) -> Result<GrantRequestSetV1, PlannerError> {
    validate_current_observations(snapshot, now_micros)?;
    kernel::request_execution_grants(snapshot, prepared, receipt, now_micros)
}

/// Collection-time masks cannot prove freshness at a later point of use.
/// The host supplies a single monotonic domain; a clock value before the
/// collection point is rejected rather than extending a lease.
fn validate_current_observations(
    snapshot: &GlobalStateSnapshotV1,
    now_micros: u64,
) -> Result<(), PlannerError> {
    if now_micros < snapshot.collected_at_micros() {
        return Err(PlannerError::InvalidTime("clock precedes snapshot collection"));
    }
    for summary in snapshot.owner_summaries() {
        let age = now_micros
            .checked_sub(summary.observed_at_micros)
            .ok_or(PlannerError::InvalidTime("clock precedes owner observation"))?;
        if age > snapshot.maximum_owner_age_micros() || now_micros >= summary.expires_at_micros {
            return Err(PlannerError::SnapshotExpired);
        }
    }
    Ok(())
}

#[cfg(test)]
#[path = "planner_admission_tests.rs"]
mod tests;
