use codex_hepta_control_plane::GlobalStateSnapshotV1;
use codex_hepta_control_plane::NduPlanEvaluationInputV1;
use codex_hepta_control_plane::OwnerReadinessV1;
use codex_hepta_control_plane::OwnerSummaryV1;
use codex_hepta_control_plane::PlanCandidateV1;
use codex_hepta_control_plane::PlannerAxisValueV1;
use codex_hepta_control_plane::PlannerError;
use codex_hepta_control_plane::PlanningEvaluationDispositionV1;
use codex_hepta_control_plane::PlanningRequestV1;
use codex_hepta_control_plane::ResourceReservationV1;
use codex_hepta_control_plane::SnapshotRequestV1;
use codex_hepta_control_plane::bind_ndu_plan_evaluation_v1;
use codex_hepta_control_plane::collect_snapshot;
use codex_hepta_control_plane::prepare_plan;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn snapshot_request() -> SnapshotRequestV1 {
    SnapshotRequestV1 {
        objective_digest: digest("objective"),
        body_generation: Generation::new(1).unwrap(),
        configuration_digest: digest("configuration"),
        revocation_frontier_digest: digest("revocation"),
        snapshot_policy_digest: digest("snapshot-policy"),
        collected_at_micros: 100,
        maximum_owner_age_micros: 10,
        expires_at_micros: 1_000,
        required_owner_ids: vec![id("owner")],
    }
}

fn summary(owner: &str) -> OwnerSummaryV1 {
    OwnerSummaryV1 {
        owner_id: id(owner),
        revision: Revision::new(1).unwrap(),
        objective_digest: digest("objective"),
        body_generation: Generation::new(1).unwrap(),
        configuration_digest: digest("configuration"),
        observed_at_micros: 100,
        expires_at_micros: 1_000,
        readiness: OwnerReadinessV1::Ready,
        source_frontier_digest: digest("frontier"),
        support_digest: digest("support"),
    }
}

fn snapshot() -> GlobalStateSnapshotV1 {
    collect_snapshot(snapshot_request(), vec![summary("owner")]).unwrap()
}

fn planning_request() -> PlanningRequestV1 {
    PlanningRequestV1 {
        plan_id: id("plan"),
        now_micros: 100,
        deadline_micros: 500,
        evaluation_policy_digest: digest("ndu-policy"),
        resource_profile_digest: digest("resource-profile"),
        candidates: vec![PlanCandidateV1 {
            candidate_id: id("abstain"),
            operation_id: id("abstain"),
            plan_digest: digest("abstain"),
            required_owner_ids: vec![id("owner")],
            final_payload_digests: vec![],
            resource_costs: vec![PlannerAxisValueV1 {
                axis: id("bytes"),
                value: FixedQ32::ZERO,
            }],
        }],
        resource_reservations: vec![ResourceReservationV1 {
            axis: id("bytes"),
            endowment: FixedQ32::from_raw(10_i64 << 32),
            essential_floor: FixedQ32::ZERO,
        }],
    }
}

#[test]
fn extra_owner_rejects_instead_of_contaminating_the_required_cut() {
    assert!(matches!(
        collect_snapshot(snapshot_request(), vec![summary("owner"), summary("extra")]),
        Err(PlannerError::PreparedPlanMismatch)
    ));
    let missing = collect_snapshot(snapshot_request(), vec![]).unwrap();
    assert_eq!(missing.missing_owner_ids(), &[id("owner")]);
}

#[test]
fn duplicate_effect_payloads_are_not_silently_deduplicated() {
    let mut request = planning_request();
    let mut effect = request.candidates[0].clone();
    effect.candidate_id = id("effect");
    effect.operation_id = id("effect");
    effect.final_payload_digests = vec![digest("payload"), digest("payload")];
    request.candidates.push(effect);
    assert!(matches!(
        prepare_plan(&snapshot(), request),
        Err(PlannerError::PreparedPlanMismatch)
    ));
}

#[test]
fn abstain_may_not_smuggle_an_effect_payload() {
    let mut request = planning_request();
    request.candidates[0].final_payload_digests = vec![digest("effect")];
    assert!(matches!(
        prepare_plan(&snapshot(), request),
        Err(PlannerError::AbstainUnavailable)
    ));
}

#[test]
fn clock_reversal_and_owner_age_expiry_close_planning() {
    let current = snapshot();
    let mut request = planning_request();
    request.now_micros = 99;
    assert!(matches!(
        prepare_plan(&current, request),
        Err(PlannerError::InvalidTime(_))
    ));
    let mut request = planning_request();
    request.now_micros = 111;
    assert!(matches!(
        prepare_plan(&current, request),
        Err(PlannerError::SnapshotExpired)
    ));
    let mut request = planning_request();
    request.now_micros = 110;
    assert!(prepare_plan(&current, request).is_ok());
}

#[test]
fn resource_axis_and_ndu_projection_limits_precede_canonicalization() {
    let mut request = planning_request();
    request.candidates[0].resource_costs = (0..33)
        .map(|index| PlannerAxisValueV1 {
            axis: id(&format!("axis-{index}")),
            value: FixedQ32::ZERO,
        })
        .collect();
    assert!(matches!(
        prepare_plan(&snapshot(), request),
        Err(PlannerError::LimitExceeded("candidate resource axes"))
    ));
    let input = NduPlanEvaluationInputV1 {
        objective_digest: digest("objective"),
        body_generation: Generation::new(1).unwrap(),
        evaluation_policy_digest: digest("policy"),
        evaluation_digest: digest("evaluation"),
        evaluated_candidate_ids: (0..129).map(|index| id(&format!("candidate-{index}"))).collect(),
        rejected_candidate_ids: vec![],
        pareto_candidate_ids: vec![id("candidate-0")],
        advisory_candidate_id: Some(id("candidate-0")),
        uncertainty_digest: digest("uncertainty"),
        disposition: PlanningEvaluationDispositionV1::UniqueParetoRecommendation,
    };
    assert!(matches!(
        bind_ndu_plan_evaluation_v1(input),
        Err(PlannerError::LimitExceeded("NDU candidate projection"))
    ));
}
