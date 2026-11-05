use super::*;
use crate::ProposalStatus;
use crate::ProposalWindowV2;
use crate::TopologyCandidateKindV2;
use crate::TopologyChangeV2;
use crate::TopologyOperationV2;
use crate::TopologyProposalRequestV2;
use crate::differentiation_demand::assess_differentiation_demand_v1;
use crate::differentiation_observations::*;
use crate::differentiation_plan::freeze_differentiation_plan_v1;
use crate::differentiation_test_support::*;
use crate::differentiation_topology::propose_differentiation_topology_v1;
use crate::differentiation_topology::validate_differentiation_topology_binding_v1;

fn outcomes(
    plan: &DifferentiationPlanV1,
    label: &str,
    new_score: u32,
) -> Vec<DifferentiationTaskObservationV1> {
    plan.task_ids()
        .into_iter()
        .map(|task_id| {
            let score_ppm = if plan.request.new_task_ids.contains(&task_id) {
                new_score
            } else {
                900_000
            };
            let evidence_digest = digest(&format!("{label}:{task_id}"));
            DifferentiationTaskObservationV1 {
                task_id,
                status: DifferentiationTaskStatusV1::Completed,
                score_ppm,
                evidence_digest,
            }
        })
        .collect()
}

fn reading(label: &str, category: &str) -> DifferentiationCostReadingV1 {
    DifferentiationCostReadingV1 {
        units: 1,
        evidence_digest: digest(&format!("cost:{label}:{category}")),
    }
}

fn fixture() -> (
    DifferentiationPlanV1,
    DifferentiationDemandAssessmentV1,
    DifferentiationStudyObservationV1,
) {
    let plan = freeze_differentiation_plan_v1(request()).expect("plan");
    let demand = assess_differentiation_demand_v1(&plan, &windows(&plan)).expect("demand");
    let candidate = DifferentiationCandidateV1 {
        parent_artifact_digest: plan.request.parent.artifact_digest,
        parent_generation: plan.request.parent.generation,
        artifact_digest: digest("trained-child"),
        topology_digest: digest("child-topology"),
        generation: plan.request.parent.generation.next().expect("generation"),
        capability_digest: plan.request.parent.capability_digest,
        state_schema_digest: plan.request.parent.state_schema_digest,
        namespace: plan.request.candidate_namespace.clone(),
        training_started_at_ms: 50,
        training_finished_at_ms: 60,
        training_task_ids: vec![id("training:1"), id("training:2")],
        training_evidence_digest: digest("isolated-training"),
    };
    let arms = ARMS
        .into_iter()
        .map(|arm| {
            let label = format!("arm:{arm:?}");
            let artifact_digest = match arm {
                DifferentiationArmV1::UnchangedParent => plan.request.parent.artifact_digest,
                DifferentiationArmV1::Candidate => candidate.artifact_digest,
                DifferentiationArmV1::ContinueParent
                | DifferentiationArmV1::ExpandedSingleModel
                | DifferentiationArmV1::FixedExperts
                | DifferentiationArmV1::RandomGrouping => digest(&label),
            };
            let new_score = if arm == DifferentiationArmV1::Candidate {
                900_000
            } else {
                500_000
            };
            DifferentiationArmObservationV1 {
                arm,
                protocol_digest: plan.request.arm_protocols[&arm],
                parent_artifact_digest: plan.request.parent.artifact_digest,
                artifact_digest,
                outcomes: outcomes(&plan, &label, new_score),
                evidence_digest: digest(&format!("summary:{label}")),
                costs: DifferentiationCostsV1 {
                    training: reading(&label, "training"),
                    evaluation: reading(&label, "evaluation"),
                    inference: reading(&label, "inference"),
                    routing: reading(&label, "routing"),
                    storage: reading(&label, "storage"),
                    migration: reading(&label, "migration"),
                },
            }
        })
        .collect();
    let observation = DifferentiationStudyObservationV1 {
        plan_digest: plan.digest(),
        demand_digest: demand.digest(),
        cost_profile_digest: plan.request.study.cost_profile_digest,
        outcome_protocol_digest: plan.request.study.outcome_protocol_digest,
        actors: plan.request.actors.clone(),
        arms,
        started_at_ms: 80,
        finished_at_ms: 90,
        migration: DifferentiationMigrationObservationV1 {
            candidate_artifact_digest: candidate.artifact_digest,
            migration_plan_digest: plan.request.migration_plan_digest,
            rollback_plan_digest: plan.request.rollback_plan_digest,
            predecessor_checkpoint_digest: plan.request.parent.checkpoint_digest,
            restored_checkpoint_digest: plan.request.parent.checkpoint_digest,
            remaining_predecessor_writers: 0,
            unresolved_effects: 0,
            replayed_external_effects: 0,
            outcomes: outcomes(&plan, "migration", /*new_score*/ 900_000),
            evidence_digest: digest("migration-observation"),
        },
        candidate,
    };
    (plan, demand, observation)
}

fn proposal(
    plan: &DifferentiationPlanV1,
    receipt: &DifferentiationStudyReceiptV1,
) -> TopologyProposalRequestV2 {
    let r = &plan.request;
    TopologyProposalRequestV2 {
        proposal_id: r.study_id.clone(),
        proposer_id: r.actors.generator.principal.clone(),
        evaluator_id: r.actors.evaluator.principal.clone(),
        selected_artifact_digest: r.parent.artifact_digest,
        window: ProposalWindowV2 {
            window_id: r.study_id.clone(),
            window_digest: plan.digest(),
        },
        baseline_generation: r.parent.generation,
        candidate_generation: r.parent.generation.next().expect("next"),
        evaluation_digest: receipt.digest(),
        rollback_predecessor_digest: r.parent.artifact_digest,
        changes: vec![TopologyChangeV2 {
            module_id: r.module_id.clone(),
            operation: TopologyOperationV2::Split,
            predecessor_digest: Some(r.parent.topology_digest),
            candidate_digest: Some(receipt.candidate_topology_digest),
            capability_typing_digest: r.parent.capability_digest,
            compatibility_plan_digest: r.compatibility_plan_digest,
            lesion_ablation_digest: receipt.digest(),
            resource_review_digest: receipt.digest(),
            security_review_digest: digest("security-review"),
            migration_digest: r.migration_plan_digest,
            rollback_digest: r.rollback_plan_digest,
            writer_handoff_digest: digest("owner-handoff"),
            evidence_digest: receipt.digest(),
        }],
    }
}

#[test]
fn six_arm_study_recommends_only_owner_review_and_enters_existing_proposal_owner() {
    let (plan, demand, mut study) = fixture();
    let receipt =
        evaluate_differentiation_study_v1(&plan, &demand, &study).expect("measured study");
    assert_eq!(
        receipt.conclusion(),
        DifferentiationConclusionV1::RecommendForOwnerReview
    );
    assert_eq!(receipt.authority(), AuthorityPosture::DENY_ALL);
    assert_eq!(
        receipt.candidate_artifact_digest(),
        study.candidate.artifact_digest
    );
    study.arms.reverse();
    study.candidate.training_task_ids.reverse();
    for arm in &mut study.arms {
        arm.outcomes.reverse();
    }
    study.migration.outcomes.reverse();
    assert_eq!(
        evaluate_differentiation_study_v1(&plan, &demand, &study),
        Ok(receipt.clone())
    );
    let proposed =
        propose_differentiation_topology_v1(&plan, &receipt, proposal(&plan, &receipt))
            .expect("proposal");
    assert_eq!(
        (proposed.status, proposed.authority),
        (
            ProposalStatus::RequiresIndependentAcceptance,
            AuthorityPosture::DENY_ALL
        )
    );
    assert_eq!(
        proposed
            .candidates
            .iter()
            .filter(|c| c.kind == TopologyCandidateKindV2::NoChange)
            .count(),
        1
    );
}

#[test]
fn every_required_comparator_must_be_present_and_be_beaten() {
    for arm in ARMS
        .into_iter()
        .filter(|a| *a != DifferentiationArmV1::Candidate)
    {
        let (plan, demand, mut study) = fixture();
        study.arms.retain(|a| a.arm != arm);
        assert_eq!(
            evaluate_differentiation_study_v1(&plan, &demand, &study),
            Err(DifferentiationErrorV1::MissingComparator)
        );
        let (plan, demand, mut study) = fixture();
        for row in &mut study
            .arms
            .iter_mut()
            .find(|a| a.arm == arm)
            .expect("arm")
            .outcomes
        {
            if plan.request.new_task_ids.contains(&row.task_id) {
                row.score_ppm = 900_000;
            }
        }
        assert_eq!(
            evaluate_differentiation_study_v1(&plan, &demand, &study)
                .expect("comparison")
                .conclusion(),
            DifferentiationConclusionV1::Hold(DifferentiationHoldReasonV1::NoMeasuredNetGain)
        );
    }
}

#[test]
fn failed_requests_stay_in_the_denominator_and_pending_is_not_failure_or_success() {
    let (plan, demand, mut study) = fixture();
    let candidate = study
        .arms
        .iter_mut()
        .find(|a| a.arm == DifferentiationArmV1::Candidate)
        .expect("candidate");
    candidate.outcomes[0].status = DifferentiationTaskStatusV1::Failed;
    candidate.outcomes[0].score_ppm = 0;
    study.migration.outcomes[0].status = DifferentiationTaskStatusV1::Failed;
    study.migration.outcomes[0].score_ppm = 0;
    assert_eq!(
        evaluate_differentiation_study_v1(&plan, &demand, &study)
            .expect("failed request")
            .conclusion(),
        DifferentiationConclusionV1::Hold(DifferentiationHoldReasonV1::NoMeasuredNetGain)
    );
    let candidate = study
        .arms
        .iter_mut()
        .find(|a| a.arm == DifferentiationArmV1::Candidate)
        .expect("candidate");
    candidate.outcomes[0].status = DifferentiationTaskStatusV1::Pending;
    assert_eq!(
        evaluate_differentiation_study_v1(&plan, &demand, &study)
            .expect("pending")
            .conclusion(),
        DifferentiationConclusionV1::Hold(DifferentiationHoldReasonV1::PendingOutcomes)
    );
    study.arms[0].outcomes.pop();
    assert_eq!(
        evaluate_differentiation_study_v1(&plan, &demand, &study),
        Err(DifferentiationErrorV1::Observation)
    );
}

#[test]
fn retention_is_against_the_frozen_parent_even_if_continued_training_also_forgets() {
    let (plan, demand, mut study) = fixture();
    for arm in &mut study.arms {
        if matches!(
            arm.arm,
            DifferentiationArmV1::Candidate | DifferentiationArmV1::ContinueParent
        ) {
            for row in &mut arm.outcomes {
                if row.task_id.as_str().starts_with("old:") {
                    row.score_ppm = 500_000;
                }
            }
        }
    }
    assert_eq!(
        evaluate_differentiation_study_v1(&plan, &demand, &study)
            .expect("retention")
            .conclusion(),
        DifferentiationConclusionV1::Hold(DifferentiationHoldReasonV1::RetentionRegression)
    );
}

#[test]
fn migration_cannot_erase_newly_learned_old_task_improvements() {
    let (plan, demand, mut study) = fixture();
    let original = study
        .arms
        .iter_mut()
        .find(|a| a.arm == DifferentiationArmV1::UnchangedParent)
        .expect("parent");
    for row in &mut original.outcomes {
        if row.task_id.as_str().starts_with("old:") {
            row.score_ppm = 600_000;
        }
    }
    for row in &mut study.migration.outcomes {
        if row.task_id.as_str().starts_with("old:") {
            row.score_ppm = 700_000;
        }
    }
    assert_eq!(
        evaluate_differentiation_study_v1(&plan, &demand, &study)
            .expect("migration regression")
            .conclusion(),
        DifferentiationConclusionV1::Hold(DifferentiationHoldReasonV1::MigrationUnverified)
    );
}

#[test]
fn every_cost_category_is_required_bounded_and_included_in_checked_arithmetic() {
    for category in 0..6 {
        let (plan, demand, mut study) = fixture();
        let cost = &mut study.arms[0].costs;
        let reading = match category {
            0 => &mut cost.training,
            1 => &mut cost.evaluation,
            2 => &mut cost.inference,
            3 => &mut cost.routing,
            4 => &mut cost.storage,
            _ => &mut cost.migration,
        };
        reading.units = 1_001;
        assert_eq!(
            evaluate_differentiation_study_v1(&plan, &demand, &study)
                .expect("budget")
                .conclusion(),
            DifferentiationConclusionV1::Hold(DifferentiationHoldReasonV1::BudgetExceeded)
        );
    }
    let (plan, demand, mut study) = fixture();
    study.arms[0].costs.training.units = u64::MAX;
    assert_eq!(
        evaluate_differentiation_study_v1(&plan, &demand, &study),
        Err(DifferentiationErrorV1::Arithmetic)
    );
    let (plan, demand, mut study) = fixture();
    study.arms[0].costs.storage.evidence_digest = Digest32::ZERO;
    assert_eq!(
        evaluate_differentiation_study_v1(&plan, &demand, &study),
        Err(DifferentiationErrorV1::EmptyEvidence)
    );
    let (old_plan, _, mut study) = fixture();
    let mut r = old_plan.request.clone();
    r.study.maximum_cost_per_arm = 10;
    r.study.maximum_total_study_cost = 35;
    let plan = freeze_differentiation_plan_v1(r).expect("aggregate budget");
    let demand = assess_differentiation_demand_v1(&plan, &windows(&plan)).expect("demand");
    study.plan_digest = plan.digest();
    study.demand_digest = demand.digest();
    assert_eq!(
        evaluate_differentiation_study_v1(&plan, &demand, &study)
            .expect("aggregate cost")
            .conclusion(),
        DifferentiationConclusionV1::Hold(DifferentiationHoldReasonV1::BudgetExceeded)
    );
}

#[test]
fn costs_inside_the_budget_can_still_remove_the_candidates_net_benefit() {
    let (old_plan, _, mut study) = fixture();
    let mut r = old_plan.request.clone();
    r.study.cost_penalty_ppm_per_unit = 50_000;
    let plan = freeze_differentiation_plan_v1(r).expect("cost-weighted policy");
    let demand = assess_differentiation_demand_v1(&plan, &windows(&plan)).expect("demand");
    study.plan_digest = plan.digest();
    study.demand_digest = demand.digest();
    let candidate = study
        .arms
        .iter_mut()
        .find(|a| a.arm == DifferentiationArmV1::Candidate)
        .expect("candidate");
    candidate.costs.training.units = 16; // Total 21; each control costs 6.
    assert_eq!(
        evaluate_differentiation_study_v1(&plan, &demand, &study)
            .expect("net comparison")
            .conclusion(),
        DifferentiationConclusionV1::Hold(DifferentiationHoldReasonV1::NoMeasuredNetGain)
    );
}

#[test]
fn one_source_record_cannot_impersonate_multiple_costs_outcomes_training_or_demand() {
    for mutation in 0..5 {
        let (plan, demand, mut study) = fixture();
        match mutation {
            0 => {
                study.arms[0].costs.routing.evidence_digest =
                    study.arms[0].costs.training.evidence_digest;
            }
            1 => {
                study.arms[1].costs.training.evidence_digest =
                    study.arms[0].costs.training.evidence_digest;
            }
            2 => {
                study.arms[0].costs.training.evidence_digest =
                    study.arms[0].outcomes[0].evidence_digest;
            }
            3 => {
                study.arms[0].outcomes[0].evidence_digest =
                    study.candidate.training_evidence_digest;
            }
            _ => {
                study.arms[0].outcomes[0].evidence_digest =
                    windows(&plan)[0].cases[0].observation_digest;
            }
        }
        assert_eq!(
            evaluate_differentiation_study_v1(&plan, &demand, &study),
            Err(DifferentiationErrorV1::DuplicateIdentity)
        );
    }
}

#[test]
fn parent_compatibility_isolation_and_chronology_cannot_be_changed_after_freeze() {
    for mutation in 0..7 {
        let (plan, demand, mut study) = fixture();
        let expected = match mutation {
            0 => {
                study.candidate.parent_artifact_digest = digest("other-parent");
                DifferentiationErrorV1::ParentBinding
            }
            1 => {
                study.candidate.namespace = plan.request.parent.namespace.clone();
                DifferentiationErrorV1::CandidateCompatibility
            }
            2 => {
                study.candidate.state_schema_digest = digest("other-schema");
                DifferentiationErrorV1::CandidateCompatibility
            }
            3 => {
                study.candidate.training_task_ids[0] = id("new:1");
                DifferentiationErrorV1::DataLeakage
            }
            4 => {
                study.candidate.training_started_at_ms = 49;
                DifferentiationErrorV1::Chronology
            }
            5 => {
                study.outcome_protocol_digest = digest("posthoc-outcome");
                DifferentiationErrorV1::PlanBinding
            }
            _ => {
                study.plan_digest = digest("other-plan");
                DifferentiationErrorV1::PlanBinding
            }
        };
        assert_eq!(
            evaluate_differentiation_study_v1(&plan, &demand, &study),
            Err(expected)
        );
    }
}

#[test]
fn migration_requires_quiescent_old_writers_known_effects_and_exact_rollback() {
    for mutation in 0..4 {
        let (plan, demand, mut study) = fixture();
        match mutation {
            0 => study.migration.remaining_predecessor_writers = 1,
            1 => study.migration.unresolved_effects = 1,
            2 => study.migration.replayed_external_effects = 1,
            _ => study.migration.restored_checkpoint_digest = digest("other-checkpoint"),
        }
        assert_eq!(
            evaluate_differentiation_study_v1(&plan, &demand, &study)
                .expect("migration")
                .conclusion(),
            DifferentiationConclusionV1::Hold(DifferentiationHoldReasonV1::MigrationUnverified)
        );
    }
}

#[test]
fn topology_bridge_rejects_parent_generation_actor_window_and_evidence_rebinding() {
    let (plan, demand, study) = fixture();
    let receipt = evaluate_differentiation_study_v1(&plan, &demand, &study).expect("study");
    for mutation in 0..9 {
        let mut r = proposal(&plan, &receipt);
        match mutation {
            0 => r.selected_artifact_digest = digest("other-parent"),
            1 => r.baseline_generation = r.baseline_generation.next().expect("next"),
            2 => r.candidate_generation = r.candidate_generation.next().expect("next"),
            3 => r.proposer_id = id("other-generator"),
            4 => r.evaluator_id = id("other-evaluator"),
            5 => r.window.window_digest = digest("other-plan"),
            6 => r.rollback_predecessor_digest = digest("other-rollback"),
            7 => r.changes[0].candidate_digest = Some(digest("other-topology")),
            _ => r.evaluation_digest = digest("other-evaluation"),
        }
        assert_eq!(
            propose_differentiation_topology_v1(&plan, &receipt, r),
            Err(DifferentiationErrorV1::TopologyBinding)
        );
    }
    assert_eq!(
        validate_differentiation_topology_binding_v1(
            &plan,
            &receipt,
            digest("other-weights"),
            &proposal(&plan, &receipt).changes[0],
        ),
        Err(DifferentiationErrorV1::TopologyBinding)
    );
}

#[test]
fn weak_demand_or_regressed_results_cannot_enter_the_topology_bridge() {
    let (plan, _, mut study) = fixture();
    let mut demand_rows = windows(&plan);
    demand_rows[0].cases.clear();
    let demand =
        assess_differentiation_demand_v1(&plan, &demand_rows).expect("insufficient demand");
    study.demand_digest = demand.digest();
    let receipt = evaluate_differentiation_study_v1(&plan, &demand, &study).expect("hold");
    assert_eq!(
        receipt.conclusion(),
        DifferentiationConclusionV1::Hold(
            DifferentiationHoldReasonV1::InsufficientPersistentDemand
        )
    );
    assert_eq!(
        propose_differentiation_topology_v1(&plan, &receipt, proposal(&plan, &receipt)),
        Err(DifferentiationErrorV1::TopologyBinding)
    );
}
