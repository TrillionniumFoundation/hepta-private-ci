use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use super::*;
use crate::OwnerReadinessV1;
use crate::PlanCandidateV1;
use crate::PlannerAxisValueV1;
use crate::ResourceReservationV1;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn request() -> SnapshotRequestV1 {
    SnapshotRequestV1 {
        objective_digest: digest("objective"),
        body_generation: must(Generation::new(1)),
        configuration_digest: digest("configuration"),
        revocation_frontier_digest: digest("revocation"),
        snapshot_policy_digest: digest("snapshot-policy"),
        collected_at_micros: 100,
        maximum_owner_age_micros: 10,
        expires_at_micros: 200,
        required_owner_ids: vec![id("required-owner")],
    }
}

fn summary(owner: &str) -> OwnerSummaryV1 {
    OwnerSummaryV1 {
        owner_id: id(owner),
        revision: must(Revision::new(1)),
        objective_digest: digest("objective"),
        body_generation: must(Generation::new(1)),
        configuration_digest: digest("configuration"),
        observed_at_micros: 100,
        expires_at_micros: 200,
        readiness: OwnerReadinessV1::Ready,
        source_frontier_digest: digest("source-frontier"),
        support_digest: digest("support"),
    }
}

#[test]
fn unexpected_owner_summary_is_rejected_before_it_can_poison_snapshot_state() {
    let error = collect_snapshot(
        request(),
        vec![summary("required-owner"), summary("unexpected-owner")],
    )
    .expect_err("extra owner must reject");
    assert!(matches!(error, PlannerError::DuplicateOwner(message) if message.contains("unexpected-owner")));
}

#[test]
fn duplicate_final_payload_digest_is_rejected_not_silently_normalized() {
    let snapshot = must(collect_snapshot(
        request(),
        vec![summary("required-owner")],
    ));
    let payload = digest("same-payload");
    let axis = id("compute");
    let error = prepare_plan(
        &snapshot,
        PlanningRequestV1 {
            plan_id: id("plan"),
            now_micros: 100,
            deadline_micros: 180,
            evaluation_policy_digest: digest("policy"),
            resource_profile_digest: digest("resource-profile"),
            candidates: vec![
                PlanCandidateV1 {
                    candidate_id: id("abstain"),
                    operation_id: id("abstain"),
                    plan_digest: digest("abstain-plan"),
                    required_owner_ids: vec![id("required-owner")],
                    final_payload_digests: vec![],
                    resource_costs: vec![PlannerAxisValueV1 {
                        axis: axis.clone(),
                        value: FixedQ32::ZERO,
                    }],
                },
                PlanCandidateV1 {
                    candidate_id: id("work"),
                    operation_id: id("work-operation"),
                    plan_digest: digest("work-plan"),
                    required_owner_ids: vec![id("required-owner")],
                    final_payload_digests: vec![payload, payload],
                    resource_costs: vec![PlannerAxisValueV1 {
                        axis: axis.clone(),
                        value: FixedQ32::ZERO,
                    }],
                },
            ],
            resource_reservations: vec![ResourceReservationV1 {
                axis,
                endowment: FixedQ32::ZERO,
                essential_floor: FixedQ32::ZERO,
            }],
        },
    )
    .expect_err("duplicate payload must reject");
    assert!(matches!(error, PlannerError::DuplicateCandidate(message) if message.contains("duplicate final payload")));
}
