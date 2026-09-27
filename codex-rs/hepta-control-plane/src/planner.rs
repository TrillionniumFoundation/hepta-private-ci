//! Public hardening layer for the bounded control planner.
//!
//! The original deterministic kernel remains in `planner_core.rs`.  This layer
//! adds closed-world admission checks that must run before any public caller can
//! construct a snapshot or prepared plan.

use std::collections::BTreeSet;

#[path = "planner_core.rs"]
mod core;

pub use core::{
    FeasiblePlanReceiptV1, GlobalStateSnapshotV1, GrantRequestSetV1, GrantRequestV1,
    NduPlanEvaluationInputV1, NduPlanEvaluationV1, OwnerReadinessV1, OwnerSummaryV1,
    PlanCandidateV1, PlannerAxisValueV1, PlannerError, PlanningEvaluationDispositionV1,
    PlanningRequestV1, PreparedPlanInputV1, ResourceReservationV1, SearchDisclosureV1,
    SnapshotRequestV1, bind_ndu_plan_evaluation_v1, finalize_plan, request_execution_grants,
};

/// Collect exactly the declared owner set.  Extra summaries are rejected rather
/// than being allowed to shorten expiry or poison readiness masks for owners the
/// caller did not require.
pub fn collect_snapshot(
    request: SnapshotRequestV1,
    owner_summaries: Vec<OwnerSummaryV1>,
) -> Result<GlobalStateSnapshotV1, PlannerError> {
    let required: BTreeSet<_> = request.required_owner_ids.iter().cloned().collect();
    if let Some(summary) = owner_summaries
        .iter()
        .find(|summary| !required.contains(&summary.owner_id))
    {
        return Err(PlannerError::DuplicateOwner(format!(
            "unexpected owner summary outside required-owner set: {}",
            summary.owner_id
        )));
    }
    core::collect_snapshot(request, owner_summaries)
}

/// Prepare a plan only after rejecting duplicate final-payload identities.
/// Duplicate payloads are an upstream construction error and must not be
/// silently canonicalized away at an authority-sensitive boundary.
pub fn prepare_plan(
    snapshot: &GlobalStateSnapshotV1,
    request: PlanningRequestV1,
) -> Result<PreparedPlanInputV1, PlannerError> {
    for candidate in &request.candidates {
        let mut payloads = BTreeSet::new();
        for payload in &candidate.final_payload_digests {
            if !payloads.insert(*payload) {
                return Err(PlannerError::DuplicateCandidate(format!(
                    "candidate {} contains a duplicate final payload digest",
                    candidate.candidate_id
                )));
            }
        }
    }
    core::prepare_plan(snapshot, request)
}

#[cfg(test)]
mod hardening_tests {
    use codex_hepta_types::Digest32;
    use codex_hepta_types::Generation;
    use codex_hepta_types::Revision;
    use codex_hepta_types::StableId;

    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).unwrap()
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn request(required_owner_ids: Vec<StableId>) -> SnapshotRequestV1 {
        SnapshotRequestV1 {
            objective_digest: digest("objective"),
            body_generation: Generation::new(1).unwrap(),
            configuration_digest: digest("configuration"),
            revocation_frontier_digest: digest("revocation"),
            snapshot_policy_digest: digest("snapshot-policy"),
            collected_at_micros: 10,
            maximum_owner_age_micros: 10,
            expires_at_micros: 20,
            required_owner_ids,
        }
    }

    fn owner(owner_id: StableId) -> OwnerSummaryV1 {
        OwnerSummaryV1 {
            owner_id,
            revision: Revision::new(1).unwrap(),
            objective_digest: digest("objective"),
            body_generation: Generation::new(1).unwrap(),
            configuration_digest: digest("configuration"),
            observed_at_micros: 10,
            expires_at_micros: 20,
            readiness: OwnerReadinessV1::Ready,
            source_frontier_digest: digest("source"),
            support_digest: digest("support"),
        }
    }

    #[test]
    fn extra_owner_summary_is_rejected_before_snapshot_digesting() {
        let required = id("required-owner");
        let extra = id("extra-owner");
        let error = collect_snapshot(
            request(vec![required.clone()]),
            vec![owner(required), owner(extra)],
        )
        .unwrap_err();
        assert!(matches!(error, PlannerError::DuplicateOwner(_)));
    }

    #[test]
    fn duplicate_final_payload_is_rejected_before_canonicalization() {
        let required = id("required-owner");
        let snapshot = collect_snapshot(
            request(vec![required.clone()]),
            vec![owner(required.clone())],
        )
        .unwrap();
        let payload = digest("payload");
        let error = prepare_plan(
            &snapshot,
            PlanningRequestV1 {
                plan_id: id("plan"),
                now_micros: 10,
                deadline_micros: 19,
                evaluation_policy_digest: digest("evaluation-policy"),
                resource_profile_digest: digest("resource-profile"),
                candidates: vec![PlanCandidateV1 {
                    candidate_id: id("abstain"),
                    operation_id: id("abstain"),
                    plan_digest: digest("abstain-plan"),
                    required_owner_ids: vec![required],
                    final_payload_digests: vec![payload, payload],
                    resource_costs: vec![PlannerAxisValueV1 {
                        axis: id("bytes"),
                        value: codex_hepta_types::FixedQ32::ZERO,
                    }],
                }],
                resource_reservations: vec![ResourceReservationV1 {
                    axis: id("bytes"),
                    endowment: codex_hepta_types::FixedQ32::ZERO,
                    essential_floor: codex_hepta_types::FixedQ32::ZERO,
                }],
            },
        )
        .unwrap_err();
        assert!(matches!(error, PlannerError::DuplicateCandidate(_)));
    }
}
