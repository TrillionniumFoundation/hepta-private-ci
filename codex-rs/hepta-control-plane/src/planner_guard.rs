//! Public fail-closed guards around the owner-local planner implementation.
//!
//! Check raw collection lengths before allocating sets or normalizing inputs.
//! A hash-valid snapshot must also be current in the caller's monotonic domain.

use std::collections::BTreeSet;

use crate::planner;
use crate::planner::GlobalStateSnapshotV1;
use crate::planner::OwnerSummaryV1;
use crate::planner::PlannerError;
use crate::planner::PlanningRequestV1;
use crate::planner::PreparedPlanInputV1;
use crate::planner::SnapshotRequestV1;

const MAX_OWNERS: usize = 32;
const MAX_CANDIDATES: usize = 128;
const MAX_PAYLOADS: usize = 64;
const MAX_RESOURCE_AXES: usize = 32;

/// Collect exactly the owner set named by the request.
///
/// Missing required owners remain observable through the kernel's explicit
/// masks. Extra owners reject instead of poisoning those masks or expiry.
/// The V1 error class remains compatible with the existing caller mapping.
pub fn collect_snapshot(
    request: SnapshotRequestV1,
    owner_summaries: Vec<OwnerSummaryV1>,
) -> Result<GlobalStateSnapshotV1, PlannerError> {
    if request.required_owner_ids.len() > MAX_OWNERS || owner_summaries.len() > MAX_OWNERS {
        return Err(PlannerError::LimitExceeded("owners"));
    }
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
            "unexpected-owner:{}",
            unexpected.owner_id
        )));
    }
    planner::collect_snapshot(request, owner_summaries)
}

/// Prepare only bounded, unambiguous inputs against a current owner snapshot.
///
/// Bounds precede sorting, hashing, set allocation and duplicate detection.
/// Counting only normalized values would admit arbitrarily large raw inputs.
/// An intrinsic abstention must not hide an effect payload behind its name.
pub fn prepare_plan(
    snapshot: &GlobalStateSnapshotV1,
    request: PlanningRequestV1,
) -> Result<PreparedPlanInputV1, PlannerError> {
    if request.candidates.is_empty() || request.candidates.len() > MAX_CANDIDATES {
        return Err(PlannerError::LimitExceeded("plan candidates"));
    }
    if request.resource_reservations.is_empty()
        || request.resource_reservations.len() > MAX_RESOURCE_AXES
    {
        return Err(PlannerError::LimitExceeded("resource reservations"));
    }
    validate_current_snapshot(snapshot, request.now_micros)?;
    for candidate in &request.candidates {
        if candidate.required_owner_ids.len() > MAX_OWNERS {
            return Err(PlannerError::LimitExceeded("candidate required owners"));
        }
        if candidate.final_payload_digests.len() > MAX_PAYLOADS {
            return Err(PlannerError::LimitExceeded("candidate payloads"));
        }
        if candidate.resource_costs.len() > MAX_RESOURCE_AXES {
            return Err(PlannerError::LimitExceeded("candidate resource axes"));
        }
        if candidate.candidate_id.as_str() == "abstain"
            && !candidate.final_payload_digests.is_empty()
        {
            return Err(PlannerError::AbstainUnavailable);
        }
        let mut payloads = BTreeSet::new();
        for payload in &candidate.final_payload_digests {
            if !payloads.insert(*payload) {
                return Err(PlannerError::DuplicateCandidate(format!(
                    "duplicate-final-payload:{}",
                    candidate.candidate_id
                )));
            }
        }
    }
    planner::prepare_plan(snapshot, request)
}

/// Owner-age policy remains effective after collection, not merely at collection.
/// This check supplements, rather than replaces, the kernel's digest, mask and
/// expiry checks. A backward clock must never make an old snapshot look fresh.
pub(crate) fn validate_current_snapshot(
    snapshot: &GlobalStateSnapshotV1,
    now_micros: u64,
) -> Result<(), PlannerError> {
    if now_micros < snapshot.collected_at_micros() {
        return Err(PlannerError::InvalidTime("snapshot clock rollback"));
    }
    for owner in snapshot.owner_summaries() {
        let age = now_micros
            .checked_sub(owner.observed_at_micros)
            .ok_or(PlannerError::InvalidTime("owner clock rollback"))?;
        if age > snapshot.maximum_owner_age_micros() || now_micros >= owner.expires_at_micros {
            return Err(PlannerError::SnapshotExpired);
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::Digest32;
    use codex_hepta_types::FixedQ32;
    use codex_hepta_types::Generation;
    use codex_hepta_types::Revision;
    use codex_hepta_types::StableId;

    use super::collect_snapshot;
    use super::prepare_plan;
    use crate::OwnerReadinessV1;
    use crate::OwnerSummaryV1;
    use crate::PlanCandidateV1;
    use crate::PlannerAxisValueV1;
    use crate::PlannerError;
    use crate::PlanningRequestV1;
    use crate::ResourceReservationV1;
    use crate::SnapshotRequestV1;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn q32(value: i64) -> FixedQ32 {
        FixedQ32::from_raw(value << 32)
    }

    fn request() -> SnapshotRequestV1 {
        SnapshotRequestV1 {
            objective_digest: digest("objective"),
            body_generation: Generation::new(7).expect("generation"),
            configuration_digest: digest("configuration"),
            revocation_frontier_digest: digest("revocations"),
            snapshot_policy_digest: digest("snapshot-policy"),
            collected_at_micros: 1_000,
            maximum_owner_age_micros: 100,
            expires_at_micros: 2_000,
            required_owner_ids: vec![id("planner")],
        }
    }

    fn summary(owner: &str) -> OwnerSummaryV1 {
        OwnerSummaryV1 {
            owner_id: id(owner),
            revision: Revision::new(3).expect("revision"),
            objective_digest: digest("objective"),
            body_generation: Generation::new(7).expect("generation"),
            configuration_digest: digest("configuration"),
            observed_at_micros: 950,
            expires_at_micros: 1_800,
            readiness: OwnerReadinessV1::Ready,
            source_frontier_digest: digest("frontier"),
            support_digest: digest("support"),
        }
    }

    fn planning_request() -> PlanningRequestV1 {
        PlanningRequestV1 {
            plan_id: id("plan"),
            now_micros: 1_000,
            deadline_micros: 1_700,
            evaluation_policy_digest: digest("policy"),
            resource_profile_digest: digest("resources"),
            candidates: vec![
                PlanCandidateV1 {
                    candidate_id: id("abstain"),
                    operation_id: id("abstain"),
                    plan_digest: digest("abstain-plan"),
                    required_owner_ids: vec![id("planner")],
                    final_payload_digests: Vec::new(),
                    resource_costs: vec![PlannerAxisValueV1 {
                        axis: id("compute"),
                        value: FixedQ32::ZERO,
                    }],
                },
                PlanCandidateV1 {
                    candidate_id: id("work"),
                    operation_id: id("operation-work"),
                    plan_digest: digest("work-plan"),
                    required_owner_ids: vec![id("planner")],
                    final_payload_digests: vec![digest("payload")],
                    resource_costs: vec![PlannerAxisValueV1 {
                        axis: id("compute"),
                        value: q32(1),
                    }],
                },
            ],
            resource_reservations: vec![ResourceReservationV1 {
                axis: id("compute"),
                endowment: q32(10),
                essential_floor: FixedQ32::ZERO,
            }],
        }
    }

    #[test]
    fn non_required_owner_is_rejected_before_snapshot_masks_or_expiry_change() {
        let error = collect_snapshot(request(), vec![summary("planner"), summary("intruder")])
            .expect_err("unexpected owner must fail closed");
        assert_eq!(
            error,
            PlannerError::DuplicateOwner("unexpected-owner:intruder".to_string())
        );
    }

    #[test]
    fn duplicate_final_payload_is_rejected_instead_of_silently_deduplicated() {
        let snapshot =
            collect_snapshot(request(), vec![summary("planner")]).expect("coherent snapshot");
        let mut planning = planning_request();
        planning.candidates[1].final_payload_digests = vec![digest("payload"); 2];
        assert_eq!(
            prepare_plan(&snapshot, planning),
            Err(PlannerError::DuplicateCandidate(
                "duplicate-final-payload:work".to_string()
            ))
        );
    }

    #[test]
    fn owner_count_is_rejected_before_set_construction_or_duplicate_detection() {
        let mut input = request();
        input.required_owner_ids = vec![id("planner"); 33];
        assert_eq!(
            collect_snapshot(input, vec![summary("planner")]),
            Err(PlannerError::LimitExceeded("owners"))
        );
        assert_eq!(
            collect_snapshot(request(), vec![summary("planner"); 33]),
            Err(PlannerError::LimitExceeded("owners"))
        );
    }

    #[test]
    fn raw_candidate_axis_and_payload_limits_precede_normalization() {
        let snapshot =
            collect_snapshot(request(), vec![summary("planner")]).expect("coherent snapshot");
        let mut planning = planning_request();
        planning.candidates = vec![planning.candidates[0].clone(); 129];
        assert_eq!(
            prepare_plan(&snapshot, planning),
            Err(PlannerError::LimitExceeded("plan candidates"))
        );
        let mut planning = planning_request();
        planning.candidates[1].resource_costs =
            vec![planning.candidates[1].resource_costs[0].clone(); 33];
        assert_eq!(
            prepare_plan(&snapshot, planning),
            Err(PlannerError::LimitExceeded("candidate resource axes"))
        );
        let mut planning = planning_request();
        planning.candidates[1].final_payload_digests = vec![digest("payload"); 65];
        assert_eq!(
            prepare_plan(&snapshot, planning),
            Err(PlannerError::LimitExceeded("candidate payloads"))
        );
    }

    #[test]
    fn owner_age_is_rechecked_after_collection_and_clock_rollback_rejects() {
        let snapshot =
            collect_snapshot(request(), vec![summary("planner")]).expect("coherent snapshot");
        let mut planning = planning_request();
        planning.now_micros = 1_050;
        assert!(prepare_plan(&snapshot, planning.clone()).is_ok());
        planning.now_micros = 1_051;
        assert_eq!(
            prepare_plan(&snapshot, planning.clone()),
            Err(PlannerError::SnapshotExpired)
        );
        planning.now_micros = 999;
        assert_eq!(
            prepare_plan(&snapshot, planning),
            Err(PlannerError::InvalidTime("snapshot clock rollback"))
        );
    }

    #[test]
    fn abstain_cannot_smuggle_an_effect_payload() {
        let snapshot =
            collect_snapshot(request(), vec![summary("planner")]).expect("coherent snapshot");
        let mut planning = planning_request();
        planning.candidates[0].final_payload_digests.push(digest("effect"));
        assert_eq!(
            prepare_plan(&snapshot, planning),
            Err(PlannerError::AbstainUnavailable)
        );
    }
}
