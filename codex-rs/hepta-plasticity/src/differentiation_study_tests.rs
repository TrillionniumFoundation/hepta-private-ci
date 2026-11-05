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
    assert_eq!(receipt.candidate_artifact_digest(), study.candidate.artifact_digest);
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
        (ProposalStatus::RequiresIndependentAcceptance, AuthorityPosture::DENY_ALL)
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

