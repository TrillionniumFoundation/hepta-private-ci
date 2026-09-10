use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::NduPlanEvaluationInputV1;
use super::OwnerReadinessV1;
use super::OwnerSummaryV1;
use super::PlanCandidateV1;
use super::PlannerAxisValueV1;
use super::PlannerError;
use super::PlanningEvaluationDispositionV1;
use super::PlanningRequestV1;
use super::PreparedPlanInputV1;
use super::ResourceReservationV1;
use super::SnapshotRequestV1;
use super::bind_ndu_plan_evaluation_v1;
use super::collect_snapshot;
use super::finalize_plan;
use super::prepare_plan;
use super::request_execution_grants;

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

fn summary(readiness: OwnerReadinessV1, observed: u64, expires: u64) -> OwnerSummaryV1 {
    OwnerSummaryV1 {
        owner_id: id("planner"),
        revision: must(Revision::new(3)),
        objective_digest: digest("objective"),
        body_generation: must(Generation::new(7)),
        configuration_digest: digest("configuration"),
        observed_at_micros: observed,
        expires_at_micros: expires,
        readiness,
        source_frontier_digest: digest("frontier"),
        support_digest: digest("support"),
    }
}

fn snapshot_request() -> SnapshotRequestV1 {
    SnapshotRequestV1 {
        objective_digest: digest("objective"),
        body_generation: must(Generation::new(7)),
        configuration_digest: digest("configuration"),
        revocation_frontier_digest: digest("revocations"),
        collected_at_micros: 1_000,
        maximum_owner_age_micros: 100,
        expires_at_micros: 2_000,
        required_owner_ids: vec![id("planner")],
    }
}

fn candidate(name: &str, resource: i64) -> PlanCandidateV1 {
    PlanCandidateV1 {
        candidate_id: id(name),
        operation_id: id(&format!("operation-{name}")),
        plan_digest: digest(&format!("plan:{name}")),
        required_owner_ids: vec![id("planner")],
        final_payload_digests: (name != "abstain")
            .then(|| digest(&format!("payload:{name}")))
            .into_iter()
            .collect(),
        resource_costs: vec![PlannerAxisValueV1 {
            axis: id("compute"),
            value: q32(resource),
        }],
    }
}

fn planning_request(work_resource: i64) -> PlanningRequestV1 {
    PlanningRequestV1 {
        plan_id: id("plan-run-1"),
        now_micros: 1_000,
        deadline_micros: 1_900,
        candidates: vec![candidate("abstain", 0), candidate("work", work_resource)],
        resource_reservations: vec![ResourceReservationV1 {
            axis: id("compute"),
            endowment: q32(10),
            essential_floor: FixedQ32::ZERO,
        }],
    }
}

fn evaluation(
    prepared: &PreparedPlanInputV1,
    disposition: PlanningEvaluationDispositionV1,
    pareto: Vec<StableId>,
    advisory: Option<StableId>,
) -> super::NduPlanEvaluationV1 {
    must(bind_ndu_plan_evaluation_v1(NduPlanEvaluationInputV1 {
        objective_digest: prepared.objective_digest,
        body_generation: prepared.body_generation,
        evaluation_policy_digest: digest("policy"),
        evaluation_digest: digest("ndu-evaluation"),
        evaluated_candidate_ids: prepared
            .feasible_candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect(),
        rejected_candidate_ids: Vec::new(),
        pareto_candidate_ids: pareto,
        advisory_candidate_id: advisory,
        uncertainty_digest: digest("uncertainty"),
        disposition,
    }))
}

#[test]
fn coherent_snapshot_prepares_finalizes_and_emits_authority_free_grant_requests() {
    let snapshot = must(collect_snapshot(
        snapshot_request(),
        vec![summary(OwnerReadinessV1::Ready, 950, 1_800)],
    ));
    let prepared = must(prepare_plan(&snapshot, planning_request(1)));
    let ndu = evaluation(
        &prepared,
        PlanningEvaluationDispositionV1::UniqueParetoRecommendation,
        vec![id("work")],
        Some(id("work")),
    );
    let receipt = must(finalize_plan(&snapshot, &prepared, &ndu, 1_100));

    assert_eq!(receipt.chosen_candidate_id, Some(id("work")));
    assert_eq!(receipt.chosen_plan_digest, Some(digest("plan:work")));
    assert!(!receipt.receipt_digest.is_zero());
    assert!(!receipt.authority.grants_any());
    assert_eq!(receipt.ndu_evaluation_digest, ndu.evaluation_digest);

    let grants = must(request_execution_grants(
        &snapshot, &prepared, &receipt, 1_200,
    ));
    assert_eq!(grants.requests.len(), 1);
    assert_eq!(
        grants.requests[0].final_payload_digest,
        digest("payload:work")
    );
    assert!(!grants.authority.grants_any());
}

#[test]
fn missing_or_stale_required_owner_blocks_global_planning() {
    let missing = must(collect_snapshot(snapshot_request(), Vec::new()));
    assert_eq!(
        must_err(prepare_plan(&missing, planning_request(1))),
        PlannerError::IncompleteSnapshot
    );

    let stale = must(collect_snapshot(
        snapshot_request(),
        vec![summary(OwnerReadinessV1::Ready, 800, 1_800)],
    ));
    assert_eq!(stale.stale_owner_ids, vec![id("planner")]);
    assert_eq!(
        must_err(prepare_plan(&stale, planning_request(1))),
        PlannerError::IncompleteSnapshot
    );
}

#[test]
fn essential_floor_survives_overload_before_ndu_evaluation() {
    let snapshot = must(collect_snapshot(
        snapshot_request(),
        vec![summary(OwnerReadinessV1::Ready, 950, 1_800)],
    ));
    let mut request = planning_request(9);
    request.resource_reservations[0].essential_floor = q32(2);
    let prepared = must(prepare_plan(&snapshot, request));

    assert_eq!(prepared.resource_rejected_candidate_ids, vec![id("work")]);
    assert_eq!(prepared.feasible_candidates.len(), 1);
    assert_eq!(prepared.feasible_candidates[0].candidate_id, id("abstain"));

    let ndu = evaluation(
        &prepared,
        PlanningEvaluationDispositionV1::InfeasibleExplicitAbstain,
        vec![id("abstain")],
        Some(id("abstain")),
    );
    let receipt = must(finalize_plan(&snapshot, &prepared, &ndu, 1_100));
    assert_eq!(receipt.chosen_candidate_id, Some(id("abstain")));
    assert_eq!(receipt.chosen_plan_digest, Some(digest("plan:abstain")));
}

#[test]
fn changed_configuration_invalidates_prepared_plan() {
    let snapshot = must(collect_snapshot(
        snapshot_request(),
        vec![summary(OwnerReadinessV1::Ready, 950, 1_800)],
    ));
    let prepared = must(prepare_plan(&snapshot, planning_request(1)));
    let ndu = evaluation(
        &prepared,
        PlanningEvaluationDispositionV1::UniqueParetoRecommendation,
        vec![id("work")],
        Some(id("work")),
    );
    let receipt = must(finalize_plan(&snapshot, &prepared, &ndu, 1_100));

    let mut changed_request = snapshot_request();
    changed_request.configuration_digest = digest("changed-configuration");
    let mut changed_summary = summary(OwnerReadinessV1::Ready, 950, 1_800);
    changed_summary.configuration_digest = digest("changed-configuration");
    let changed = must(collect_snapshot(changed_request, vec![changed_summary]));

    assert_eq!(
        must_err(request_execution_grants(
            &changed, &prepared, &receipt, 1_200,
        )),
        PlannerError::PreparedPlanMismatch
    );
}

#[test]
fn evaluation_must_cover_exact_prepared_candidate_set() {
    let snapshot = must(collect_snapshot(
        snapshot_request(),
        vec![summary(OwnerReadinessV1::Ready, 950, 1_800)],
    ));
    let prepared = must(prepare_plan(&snapshot, planning_request(1)));
    let ndu = must(bind_ndu_plan_evaluation_v1(NduPlanEvaluationInputV1 {
        objective_digest: prepared.objective_digest,
        body_generation: prepared.body_generation,
        evaluation_policy_digest: digest("policy"),
        evaluation_digest: digest("ndu-evaluation"),
        evaluated_candidate_ids: vec![id("abstain")],
        rejected_candidate_ids: Vec::new(),
        pareto_candidate_ids: vec![id("abstain")],
        advisory_candidate_id: Some(id("abstain")),
        uncertainty_digest: digest("uncertainty"),
        disposition: PlanningEvaluationDispositionV1::InfeasibleExplicitAbstain,
    }));

    assert_eq!(
        must_err(finalize_plan(&snapshot, &prepared, &ndu, 1_100)),
        PlannerError::EvaluationCandidateSetMismatch
    );
}

#[test]
fn tampered_ndu_binding_is_rejected() {
    let snapshot = must(collect_snapshot(
        snapshot_request(),
        vec![summary(OwnerReadinessV1::Ready, 950, 1_800)],
    ));
    let prepared = must(prepare_plan(&snapshot, planning_request(1)));
    let mut ndu = evaluation(
        &prepared,
        PlanningEvaluationDispositionV1::UniqueParetoRecommendation,
        vec![id("work")],
        Some(id("work")),
    );
    ndu.uncertainty_digest = digest("tampered");

    assert_eq!(
        must_err(finalize_plan(&snapshot, &prepared, &ndu, 1_100)),
        PlannerError::EvaluationBindingMismatch
    );
}

#[test]
fn missing_resource_axis_is_unavailable_not_zero_cost() {
    let snapshot = must(collect_snapshot(
        snapshot_request(),
        vec![summary(OwnerReadinessV1::Ready, 950, 1_800)],
    ));
    let mut request = planning_request(1);
    request.candidates[1].resource_costs.clear();

    assert_eq!(
        must_err(prepare_plan(&snapshot, request)),
        PlannerError::MissingResourceAxis {
            candidate: "work".to_string(),
            axis: "compute".to_string(),
        }
    );
}
