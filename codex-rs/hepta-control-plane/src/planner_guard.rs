//! Public fail-closed guards around the owner-local planner implementation.
//!
//! The native planner keeps its deterministic core intentionally small.  This
//! boundary rejects ambiguous inputs before they enter that core so product
//! callers cannot smuggle non-required owners into a coherent snapshot or rely
//! on silent payload de-duplication.

use std::collections::BTreeSet;

use crate::planner;
use crate::planner::GlobalStateSnapshotV1;
use crate::planner::OwnerSummaryV1;
use crate::planner::PlannerError;
use crate::planner::PlanningRequestV1;
use crate::planner::PreparedPlanInputV1;
use crate::planner::SnapshotRequestV1;

/// Collect exactly the owner set named by the request.
///
/// The legacy kernel already reports missing required owners.  The public
/// boundary additionally rejects extra summaries instead of allowing an
/// unrelated stale or unavailable owner to shorten expiry or poison readiness
/// masks.  `DuplicateOwner` is retained as the V1 wire-compatible error class;
/// its message is domain-prefixed so callers can distinguish this case.
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
            "unexpected-owner:{}",
            unexpected.owner_id
        )));
    }
    planner::collect_snapshot(request, owner_summaries)
}

/// Prepare a plan only when every final payload digest is unique per candidate.
///
/// The native kernel canonicalizes ordering.  Product callers must not depend
/// on canonicalization to erase a duplicated effect request, because doing so
/// hides an upstream construction fault and makes cardinality accounting
/// ambiguous.
pub fn prepare_plan(
    snapshot: &GlobalStateSnapshotV1,
    request: PlanningRequestV1,
) -> Result<PreparedPlanInputV1, PlannerError> {
    for candidate in &request.candidates {
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
        let snapshot = collect_snapshot(request(), vec![summary("planner")])
            .expect("coherent snapshot");
        let duplicated = digest("payload");
        let error = prepare_plan(
            &snapshot,
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
                        final_payload_digests: vec![duplicated, duplicated],
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
            },
        )
        .expect_err("duplicate payload must fail closed");
        assert_eq!(
            error,
            PlannerError::DuplicateCandidate("duplicate-final-payload:work".to_string())
        );
    }
}
