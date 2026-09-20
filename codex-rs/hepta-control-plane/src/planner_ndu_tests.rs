use codex_hepta_ndu::AxisDirection;
use codex_hepta_ndu::AxisValue;
use codex_hepta_ndu::FeasibilityPosture;
use codex_hepta_ndu::RequiredOrganSet;
use codex_hepta_ndu::UtilityContribution;
use codex_hepta_ndu::legacy_evaluation_policy;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use pretty_assertions::assert_eq;

use super::*;
use crate::OwnerReadinessV1;
use crate::OwnerSummaryV1;
use crate::PlanCandidateV1;
use crate::PlannerAxisValueV1;
use crate::PlanningRequestV1;
use crate::ResourceReservationV1;
use crate::SnapshotRequestV1;
use crate::collect_snapshot;
use crate::prepare_plan;
use crate::request_execution_grants;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid identifier")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn fixture() -> (
    GlobalStateSnapshotV1,
    PreparedPlanInputV1,
    NduPlanningInputV1,
) {
    let generation = Generation::new(1).expect("valid generation");
    let snapshot = collect_snapshot(
        SnapshotRequestV1 {
            objective_digest: digest("objective"),
            body_generation: generation,
            configuration_digest: digest("configuration"),
            revocation_frontier_digest: digest("revocation-frontier"),
            snapshot_policy_digest: digest("snapshot-policy"),
            collected_at_micros: 100,
            maximum_owner_age_micros: 10,
            expires_at_micros: 200,
            required_owner_ids: vec![id("state-reader")],
        },
        vec![OwnerSummaryV1 {
            owner_id: id("state-reader"),
            revision: Revision::new(1).expect("valid revision"),
            objective_digest: digest("objective"),
            body_generation: generation,
            configuration_digest: digest("configuration"),
            observed_at_micros: 99,
            expires_at_micros: 200,
            readiness: OwnerReadinessV1::Ready,
            source_frontier_digest: digest("observed-state"),
            support_digest: digest("read-evidence"),
        }],
    )
    .expect("coherent snapshot");
    let profile = UtilityProfile {
        profile_id: id("available-context"),
        dimensions: vec![(id("coverage"), AxisDirection::Maximize)],
        risk_ceilings: vec![],
        resource_ceilings: vec![],
        required_organs: RequiredOrganSet {
            organ_ids: vec![id("state-reader")],
        },
    };
    let input = NduPlanningInputV1 {
        policy: legacy_evaluation_policy(&profile).expect("valid policy"),
        profile,
        scalarization: None,
        contributions: ContributionSet {
            objective_digest: digest("objective"),
            generation,
            contributions: ["abstain", "read-context"]
                .into_iter()
                .map(|candidate| UtilityContribution {
                    candidate_id: id(candidate),
                    organ_id: id("state-reader"),
                    objective_digest: digest("objective"),
                    generation,
                    feasibility: FeasibilityPosture::Feasible,
                    utility: vec![AxisValue {
                        axis: id("coverage"),
                        value: if candidate == "abstain" {
                            FixedQ32::ZERO
                        } else {
                            FixedQ32::ONE
                        },
                    }],
                    risk: vec![],
                    resource: vec![],
                    uncertainty: vec![AxisValue {
                        axis: id("coverage"),
                        value: FixedQ32::ZERO,
                    }],
                    support_digest: digest(candidate),
                })
                .collect(),
        },
    };
    let prepared = prepare_plan(
        &snapshot,
        PlanningRequestV1 {
            plan_id: id("read-plan"),
            now_micros: 100,
            deadline_micros: 190,
            evaluation_policy_digest: canonical_ndu_planning_policy_digest(&input)
                .expect("policy binding"),
            resource_profile_digest: digest("bounded-context-read"),
            candidates: ["abstain", "read-context"]
                .into_iter()
                .map(|name| PlanCandidateV1 {
                    candidate_id: id(name),
                    operation_id: id(&format!("operation-{name}")),
                    plan_digest: digest(name),
                    required_owner_ids: vec![id("state-reader")],
                    final_payload_digests: vec![],
                    resource_costs: vec![PlannerAxisValueV1 {
                        axis: id("context-read"),
                        value: if name == "abstain" {
                            FixedQ32::ZERO
                        } else {
                            FixedQ32::ONE
                        },
                    }],
                })
                .collect(),
            resource_reservations: vec![ResourceReservationV1 {
                axis: id("context-read"),
                endowment: FixedQ32::ONE,
                essential_floor: FixedQ32::ZERO,
            }],
        },
    )
    .expect("prepared plan");
    (snapshot, prepared, input)
}

#[test]
fn owner_evaluation_composes_into_real_planner_without_self_reported_selection() {
    let (snapshot, prepared, input) = fixture();
    let result = evaluate_prepared_plan_with_ndu(&snapshot, &prepared, input, 110)
        .expect("actual NDU computation");
    assert_eq!(result.plan.chosen_candidate_id(), Some(&id("read-context")));
    assert_eq!(
        result.plan.ndu_evaluation_digest(),
        result.ndu_evaluation.evaluation_digest_v2
    );
    assert!(!result.plan.authority().grants_any());
    let requests = request_execution_grants(&snapshot, &prepared, &result.plan, 110)
        .expect("read-only candidate");
    assert!(requests.requests().is_empty());
}

#[test]
fn policy_mutations_after_preparation_are_rejected() {
    let (snapshot, prepared, input) = fixture();
    let mut direction = input.clone();
    direction.profile.dimensions[0].1 = AxisDirection::Minimize;
    let mut scalarization = input.clone();
    scalarization.scalarization = Some(ScalarizationProfile {
        profile_id: id("new-weights"),
        weights: vec![AxisValue {
            axis: id("coverage"),
            value: FixedQ32::ONE,
        }],
    });
    let mut tolerance = input;
    tolerance.policy.pareto_absolute_tolerances[0].value = FixedQ32::ONE;
    for changed in [direction, scalarization, tolerance] {
        assert_eq!(
            evaluate_prepared_plan_with_ndu(&snapshot, &prepared, changed, 110),
            Err(NduPlanningError::Planner(
                PlannerError::EvaluationBindingMismatch
            )),
        );
    }
}

#[test]
fn omitted_candidate_or_foreign_owner_cannot_supply_a_planning_result() {
    let (snapshot, prepared, input) = fixture();
    let mut omitted = input.clone();
    omitted.contributions.contributions.pop();
    assert_eq!(
        evaluate_prepared_plan_with_ndu(&snapshot, &prepared, omitted, 110),
        Err(NduPlanningError::CandidateCoverage),
    );
    let mut foreign = input;
    foreign.contributions.contributions[0].organ_id = id("unobserved-owner");
    assert_eq!(
        evaluate_prepared_plan_with_ndu(&snapshot, &prepared, foreign, 110),
        Err(NduPlanningError::OwnerCoverage(id("unobserved-owner"))),
    );
}

#[test]
fn expired_snapshot_cannot_become_a_plan_despite_valid_ndu_scores() {
    let (snapshot, prepared, input) = fixture();
    assert_eq!(
        evaluate_prepared_plan_with_ndu(&snapshot, &prepared, input, 201),
        Err(NduPlanningError::Planner(PlannerError::SnapshotExpired)),
    );
}
