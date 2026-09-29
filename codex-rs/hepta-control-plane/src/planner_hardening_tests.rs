use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use super::super::planner::OwnerReadinessV1;
use super::super::planner::OwnerSummaryV1;
use super::super::planner::PlanCandidateV1;
use super::super::planner::PlannerAxisValueV1;
use super::super::planner::PlannerError;
use super::super::planner::PlanningRequestV1;
use super::super::planner::ResourceReservationV1;
use super::super::planner::SnapshotRequestV1;
use super::collect_snapshot;
use super::prepare_plan;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn must_err<T: Debug, E>(result: Result<T, E>) -> E {
    match result {
        Err(error) => error,
        Ok(value) => panic!("expected error, received value: {value:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn q32(value: i64) -> FixedQ32 {
    FixedQ32::from_raw(value << 32)
}

fn snapshot_request() -> SnapshotRequestV1 {
    SnapshotRequestV1 {
        objective_digest: digest("objective"),
        body_generation: must(Generation::new(7)),
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
        revision: must(Revision::new(3)),
        objective_digest: digest("objective"),
        body_generation: must(Generation::new(7)),
        configuration_digest: digest("configuration"),
        observed_at_micros: 950,
        expires_at_micros: 1_800,
        readiness: OwnerReadinessV1::Ready,
        source_frontier_digest: digest("frontier"),
        support_digest: digest("support"),
    }
}

fn candidate(name: &str, payloads: Vec<Digest32>) -> PlanCandidateV1 {
    PlanCandidateV1 {
        candidate_id: id(name),
        operation_id: id(&format!("operation-{name}")),
        plan_digest: digest(&format!("plan:{name}")),
        required_owner_ids: vec![id("planner")],
        final_payload_digests: payloads,
        resource_costs: vec![PlannerAxisValueV1 {
            axis: id("compute"),
            value: q32(i64::from(name != "abstain")),
        }],
    }
}

fn planning_request(now_micros: u64, candidates: Vec<PlanCandidateV1>) -> PlanningRequestV1 {
    PlanningRequestV1 {
        plan_id: id("plan-run-1"),
        now_micros,
        deadline_micros: 1_900,
        evaluation_policy_digest: digest("policy"),
        resource_profile_digest: digest("resource-profile"),
        candidates,
        resource_reservations: vec![ResourceReservationV1 {
            axis: id("compute"),
            endowment: q32(10),
            essential_floor: FixedQ32::ZERO,
        }],
    }
}

#[test]
fn supplied_owner_must_belong_to_the_exact_required_set() {
    let error = must_err(collect_snapshot(
        snapshot_request(),
        vec![summary("planner"), summary("injected-owner")],
    ));
    assert!(matches!(
        error,
        PlannerError::DuplicateOwner(message) if message.contains("unexpected owner")
    ));
}

#[test]
fn duplicate_final_payload_is_rejected_instead_of_repaired() {
    let snapshot = must(collect_snapshot(
        snapshot_request(),
        vec![summary("planner")],
    ));
    let repeated = digest("payload:work");
    let error = must_err(prepare_plan(
        &snapshot,
        planning_request(
            1_000,
            vec![
                candidate("abstain", Vec::new()),
                candidate("work", vec![repeated, repeated]),
            ],
        ),
    ));
    assert!(matches!(
        error,
        PlannerError::DuplicateCandidate(message) if message.contains("repeats a final payload")
    ));
}

#[test]
fn planning_time_cannot_precede_snapshot_collection() {
    let snapshot = must(collect_snapshot(
        snapshot_request(),
        vec![summary("planner")],
    ));
    let error = must_err(prepare_plan(
        &snapshot,
        planning_request(999, vec![candidate("abstain", Vec::new())]),
    ));
    assert_eq!(
        error,
        PlannerError::InvalidTime("planning time before snapshot collection")
    );
}

#[test]
fn owner_age_is_rechecked_at_plan_use() {
    let snapshot = must(collect_snapshot(
        snapshot_request(),
        vec![summary("planner")],
    ));
    let error = must_err(prepare_plan(
        &snapshot,
        planning_request(1_051, vec![candidate("abstain", Vec::new())]),
    ));
    assert_eq!(error, PlannerError::SnapshotExpired);
}

#[test]
fn abstain_cannot_carry_an_effect_payload() {
    let snapshot = must(collect_snapshot(
        snapshot_request(),
        vec![summary("planner")],
    ));
    let error = must_err(prepare_plan(
        &snapshot,
        planning_request(
            1_000,
            vec![candidate("abstain", vec![digest("must-not-execute")])],
        ),
    ));
    assert_eq!(error, PlannerError::AbstainUnavailable);
}
