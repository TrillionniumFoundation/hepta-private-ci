use super::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture identity")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn observation() -> (SnapshotRequestV1, OwnerSummaryV1) {
    let request = SnapshotRequestV1 {
        objective_digest: digest("objective"),
        body_generation: Generation::new(1).expect("generation"),
        configuration_digest: digest("configuration"),
        revocation_frontier_digest: digest("revocations"),
        snapshot_policy_digest: digest("snapshot-policy"),
        collected_at_micros: 100,
        maximum_owner_age_micros: 20,
        expires_at_micros: 1_000,
        required_owner_ids: vec![id("owner")],
    };
    let summary = OwnerSummaryV1 {
        owner_id: id("owner"),
        revision: Revision::new(1).expect("revision"),
        objective_digest: request.objective_digest,
        body_generation: request.body_generation,
        configuration_digest: request.configuration_digest,
        observed_at_micros: 90,
        expires_at_micros: 1_000,
        readiness: OwnerReadinessV1::Ready,
        source_frontier_digest: digest("frontier"),
        support_digest: digest("support"),
    };
    (request, summary)
}

fn planning() -> PlanningRequestV1 {
    PlanningRequestV1 {
        plan_id: id("plan"),
        now_micros: 100,
        deadline_micros: 1_000,
        evaluation_policy_digest: digest("evaluation-policy"),
        resource_profile_digest: digest("resources"),
        candidates: ["abstain", "work"]
            .into_iter()
            .map(|name| PlanCandidateV1 {
                candidate_id: id(name),
                operation_id: id(name),
                plan_digest: digest(name),
                required_owner_ids: vec![id("owner")],
                final_payload_digests: Vec::new(),
                resource_costs: vec![PlannerAxisValueV1 {
                    axis: id("budget"),
                    value: FixedQ32::ZERO,
                }],
            })
            .collect(),
        resource_reservations: vec![ResourceReservationV1 {
            axis: id("budget"),
            endowment: FixedQ32::ZERO,
            essential_floor: FixedQ32::ZERO,
        }],
    }
}

fn evaluation() -> NduPlanEvaluationInputV1 {
    NduPlanEvaluationInputV1 {
        objective_digest: digest("objective"),
        body_generation: Generation::new(1).expect("generation"),
        evaluation_policy_digest: digest("evaluation-policy"),
        evaluation_digest: digest("owner-evaluation"),
        evaluated_candidate_ids: vec![id("abstain"), id("work")],
        rejected_candidate_ids: Vec::new(),
        pareto_candidate_ids: vec![id("work")],
        advisory_candidate_id: Some(id("work")),
        uncertainty_digest: digest("uncertainty"),
        disposition: PlanningEvaluationDispositionV1::UniqueParetoRecommendation,
    }
}

#[test]
fn an_undeclared_owner_is_rejected_even_when_ready() {
    let (request, summary) = observation();
    let mut extra = summary.clone();
    extra.owner_id = id("undeclared");
    assert_eq!(
        collect_snapshot(request, vec![summary, extra]),
        Err(PlannerError::IncompleteSnapshot)
    );
}

#[test]
fn missing_required_owner_remains_an_explicit_observation() {
    let (request, _) = observation();
    let snapshot = collect_snapshot(request, Vec::new()).expect("observation");
    assert_eq!(snapshot.missing_owner_ids(), &[id("owner")]);
    assert!(prepare_plan(&snapshot, planning()).is_err());
}

#[test]
fn duplicate_payloads_are_not_silently_normalized() {
    let (request, summary) = observation();
    let snapshot = collect_snapshot(request, vec![summary]).expect("snapshot");
    let mut plan = planning();
    plan.candidates[1].final_payload_digests = vec![digest("payload"), digest("payload")];
    assert_eq!(
        prepare_plan(&snapshot, plan),
        Err(PlannerError::PreparedPlanMismatch)
    );
}

#[test]
fn abstention_cannot_request_an_effect() {
    let (request, summary) = observation();
    let snapshot = collect_snapshot(request, vec![summary]).expect("snapshot");
    let mut plan = planning();
    plan.candidates[0].final_payload_digests = vec![digest("effect")];
    assert_eq!(
        prepare_plan(&snapshot, plan),
        Err(PlannerError::PreparedPlanMismatch)
    );
}

#[test]
fn clock_regression_is_rejected_before_preparation() {
    let (request, summary) = observation();
    let snapshot = collect_snapshot(request, vec![summary]).expect("snapshot");
    let mut plan = planning();
    plan.now_micros = 99;
    assert!(matches!(prepare_plan(&snapshot, plan), Err(PlannerError::InvalidTime(_))));
}

#[test]
fn owner_age_is_rechecked_at_finalization_and_grant_request() {
    let (request, summary) = observation();
    let snapshot = collect_snapshot(request, vec![summary]).expect("snapshot");
    let prepared = prepare_plan(&snapshot, planning()).expect("prepared");
    let evaluated = bind_ndu_plan_evaluation_v1(evaluation()).expect("evaluation");
    let receipt = finalize_plan(&snapshot, &prepared, &evaluated, 110).expect("inclusive age");
    assert_eq!(
        finalize_plan(&snapshot, &prepared, &evaluated, 111),
        Err(PlannerError::SnapshotExpired)
    );
    assert_eq!(
        request_execution_grants(&snapshot, &prepared, &receipt, 111),
        Err(PlannerError::SnapshotExpired)
    );
}

#[test]
fn oversized_resource_axis_input_is_rejected_before_sorting() {
    let (request, summary) = observation();
    let snapshot = collect_snapshot(request, vec![summary]).expect("snapshot");
    let mut plan = planning();
    plan.candidates[1].resource_costs = vec![
        PlannerAxisValueV1 { axis: id("budget"), value: FixedQ32::ZERO };
        33
    ];
    assert!(matches!(prepare_plan(&snapshot, plan), Err(PlannerError::LimitExceeded(_))));
}

#[test]
fn oversized_ndu_projection_is_rejected_before_sorting() {
    let mut input = evaluation();
    input.evaluated_candidate_ids = (0..129).map(|n| id(&format!("candidate-{n}"))).collect();
    assert!(matches!(
        bind_ndu_plan_evaluation_v1(input),
        Err(PlannerError::LimitExceeded(_))
    ));
}
