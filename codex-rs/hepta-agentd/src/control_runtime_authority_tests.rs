use codex_hepta_control_plane::ExecutionGrantBindingV1;
use codex_hepta_control_plane::NduPlanEvaluationInputV1;
use codex_hepta_control_plane::OwnerReadinessV1;
use codex_hepta_control_plane::OwnerSummaryV1;
use codex_hepta_control_plane::PlanCandidateV1;
use codex_hepta_control_plane::PlannerAxisValueV1;
use codex_hepta_control_plane::PlanningEvaluationDispositionV1;
use codex_hepta_control_plane::PlanningRequestV1;
use codex_hepta_control_plane::ResourceReservationV1;
use codex_hepta_control_plane::SnapshotRequestV1;
use codex_hepta_control_plane::bind_ndu_plan_evaluation_v1;
use codex_hepta_control_plane::canonical_resource_profile_digest;
use codex_hepta_control_plane::collect_snapshot;
use codex_hepta_control_plane::finalize_plan;
use codex_hepta_control_plane::prepare_plan;
use codex_hepta_control_plane::request_execution_grants;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use super::AgentdControlRuntimeAuthorityHost;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn q32(value: i64) -> FixedQ32 {
    FixedQ32::from_raw(value << 32)
}

fn grant_request() -> codex_hepta_control_plane::GrantRequestV1 {
    let generation = Generation::new(1).expect("generation");
    let snapshot = collect_snapshot(
        SnapshotRequestV1 {
            objective_digest: digest("objective"),
            body_generation: generation,
            configuration_digest: digest("configuration"),
            revocation_frontier_digest: digest("revocations"),
            snapshot_policy_digest: digest("snapshot-policy"),
            collected_at_micros: 100,
            maximum_owner_age_micros: 50,
            expires_at_micros: 500,
            required_owner_ids: vec![id("fleet-owner")],
        },
        vec![OwnerSummaryV1 {
            owner_id: id("fleet-owner"),
            revision: Revision::new(1).expect("revision"),
            objective_digest: digest("objective"),
            body_generation: generation,
            configuration_digest: digest("configuration"),
            observed_at_micros: 90,
            expires_at_micros: 500,
            readiness: OwnerReadinessV1::Ready,
            source_frontier_digest: digest("fleet-frontier"),
            support_digest: digest("fleet-support"),
        }],
    )
    .expect("snapshot");
    let reservations = vec![ResourceReservationV1 {
        axis: id("compute"),
        endowment: q32(10),
        essential_floor: q32(2),
    }];
    let prepared = prepare_plan(
        &snapshot,
        PlanningRequestV1 {
            plan_id: id("global-plan"),
            now_micros: 100,
            deadline_micros: 400,
            evaluation_policy_digest: digest("evaluation-policy"),
            resource_profile_digest: canonical_resource_profile_digest(&reservations)
                .expect("resource digest"),
            candidates: vec![
                PlanCandidateV1 {
                    candidate_id: id("abstain"),
                    operation_id: id("no-effect"),
                    plan_digest: digest("abstain-plan"),
                    execution_binding: None,
                    required_owner_ids: vec![id("fleet-owner")],
                    final_payload_digests: vec![],
                    resource_costs: vec![PlannerAxisValueV1 {
                        axis: id("compute"),
                        value: FixedQ32::ZERO,
                    }],
                },
                PlanCandidateV1 {
                    candidate_id: id("work"),
                    operation_id: id("provider-send"),
                    plan_digest: digest("work-plan"),
                    execution_binding: Some(ExecutionGrantBindingV1 {
                        subject_id: id("agent-alpha"),
                        destination_id: id("provider-primary"),
                        scope_digest: digest("provider-send-scope"),
                    }),
                    required_owner_ids: vec![id("fleet-owner")],
                    final_payload_digests: vec![digest("exact-final-payload")],
                    resource_costs: vec![PlannerAxisValueV1 {
                        axis: id("compute"),
                        value: q32(1),
                    }],
                },
            ],
            resource_reservations: reservations,
        },
    )
    .expect("prepared");
    let evaluation = bind_ndu_plan_evaluation_v1(NduPlanEvaluationInputV1 {
        objective_digest: digest("objective"),
        body_generation: generation,
        evaluation_policy_digest: digest("evaluation-policy"),
        evaluation_digest: digest("ndu-evaluation"),
        evaluated_candidate_ids: vec![id("abstain"), id("work")],
        rejected_candidate_ids: vec![],
        pareto_candidate_ids: vec![id("work")],
        advisory_candidate_id: Some(id("work")),
        uncertainty_digest: digest("uncertainty"),
        disposition: PlanningEvaluationDispositionV1::UniqueParetoRecommendation,
    })
    .expect("evaluation");
    let receipt = finalize_plan(&snapshot, &prepared, &evaluation, 110).expect("final plan");
    let requests =
        request_execution_grants(&snapshot, &prepared, &receipt, 120).expect("grant requests");
    requests.requests()[0].clone()
}

#[test]
fn sealed_control_request_maps_exactly_to_final_use_binding() {
    let request = grant_request();
    let binding = AgentdControlRuntimeAuthorityHost::binding(&request).expect("binding");
    assert_eq!(binding.subject_id, "agent-alpha");
    assert_eq!(binding.destination_id, "provider-primary");
    assert_eq!(binding.request_sha256, *request.request_digest().as_array());
    assert_eq!(binding.scope_sha256, *request.scope_digest.as_array());
    assert_eq!(binding.payload_sha256, *request.final_payload_digest.as_array());
}

#[test]
fn request_field_drift_is_rejected_before_authority_claim() {
    let mut request = grant_request();
    request.scope_digest = digest("substituted-scope");
    assert_eq!(
        AgentdControlRuntimeAuthorityHost::binding(&request)
            .expect_err("tampered request must reject"),
        codex_hepta_contracts::FinalUseError::BindingMismatch
    );
}
