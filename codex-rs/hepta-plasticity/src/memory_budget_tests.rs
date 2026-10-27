//! Synthetic contract tests; these do not claim empirical structural benefit.

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::*;
use crate::ProposalStatus;
use crate::ProposalWindowV2;
use crate::TopologyCandidateKindV2;
use crate::TopologyChangeV2;

fn digest(value: &str) -> Digest32 { Digest32::of_bytes(value.as_bytes()) }
fn id(value: &str) -> StableId { StableId::new(value).expect("fixture identity") }

fn budget() -> MemoryStructureBudgetV1 {
    MemoryStructureBudgetV1 { required_fixed_shards: vec![1, 2, 4], max_artifact_bytes: 1_000_000,
        max_resident_payload_bytes: 1_000_000, forecast_queries: 100_000,
        max_retention_error_permyriad: 100, error_weight: 10_000, byte_weight: 1,
        wall_ns_weight: 1, communication_byte_weight: 1 }
}

fn measurement(name: &str, role: MemoryStructureRoleV1, shards: u8, errors: u64, reads: u64) -> MemoryStructureMeasurementV1 {
    MemoryStructureMeasurementV1 { artifact_digest: digest(name), source_cut_digest: digest("same-live-cut"),
        task_set_digest: digest("same-independent-queries"), training_profile_digest: digest("same-fitting-limits"),
        role, shards, queries: 100, errors, retention_queries: 100, retention_errors: 0, independent_evaluation: true,
        cost: MemoryStructureCostV1 { artifact_bytes: 1000, raw_cache_bytes: 800, resident_payload_bytes: 300,
            resident_metadata_bytes: 200, catalog_bytes: 80, route_bytes: 20, source_ledger_bytes: Some(4000),
            search_wall_ns: Some(100), training_wall_ns: Some(1000), replay_wall_ns: Some(200),
            read_compute_wall_ns: Some(reads), wake_wall_ns: Some(10), communication_wall_ns: Some(20), communication_bytes: Some(50) } }
}

fn measurements() -> Vec<MemoryStructureMeasurementV1> {
    vec![measurement("keep", MemoryStructureRoleV1::KeepFixed, 2, 10, 100),
        measurement("fixed-1", MemoryStructureRoleV1::Fixed, 1, 10, 100),
        measurement("fixed-2", MemoryStructureRoleV1::Fixed, 2, 10, 100),
        measurement("fixed-4", MemoryStructureRoleV1::Fixed, 4, 10, 100),
        measurement("split", MemoryStructureRoleV1::Split, 4, 0, 80)]
}

fn request(decision: &MemoryStructureDecisionV1) -> TopologyProposalRequestV2 {
    let evidence = decision.evidence_digest();
    TopologyProposalRequestV2 { proposal_id: id("memory:proposal"), proposer_id: id("memory:generator"),
        evaluator_id: id("memory:independent-evaluator"), selected_artifact_digest: digest("keep"),
        window: ProposalWindowV2 { window_id: id("memory:window"), window_digest: digest("window") },
        baseline_generation: Generation::new(2).expect("generation"), candidate_generation: Generation::new(3).expect("generation"),
        evaluation_digest: evidence, rollback_predecessor_digest: digest("keep"),
        changes: vec![TopologyChangeV2 { module_id: id("memory:semantic"), operation: TopologyOperationV2::Split,
            predecessor_digest: Some(digest("keep")), candidate_digest: Some(digest("split")),
            capability_typing_digest: digest("capability"), compatibility_plan_digest: digest("compatibility"),
            lesion_ablation_digest: digest("ablation"), resource_review_digest: evidence,
            security_review_digest: digest("security"), migration_digest: digest("migration"),
            rollback_digest: digest("rollback"), writer_handoff_digest: digest("handoff"), evidence_digest: evidence }] }
}

#[test]
fn unknown_costs_and_missing_independent_measurement_emit_only_no_change() {
    let mut measured = measurements();
    measured[4].cost.communication_wall_ns = None;
    let decision = evaluate_memory_structure_v1(&budget(), &measured).expect("bounded evaluation");
    assert_eq!(decision.reason(), MemoryStructureKeepReasonV1::MissingMeasurements);
    let proposal = propose_memory_structure_v1(request(&decision), &decision).expect("no change proposal");
    assert_eq!(proposal.candidates.len(), 1);
    assert_eq!(proposal.candidates[0].kind, TopologyCandidateKindV2::NoChange);
    assert!(!proposal.authority.grants_any());
    measured[4].independent_evaluation = false;
    assert_eq!(evaluate_memory_structure_v1(&budget(), &measured).expect("diagnostic").reason(),
        MemoryStructureKeepReasonV1::MissingIndependentEvaluation);
}

#[test]
fn strongest_fixed_and_all_candidate_search_cost_prevent_false_structural_wins() {
    for axis in 0..4 {
        let mut invalid = budget();
        match axis {
            0 => invalid.error_weight = 0,
            1 => invalid.byte_weight = 0,
            2 => invalid.wall_ns_weight = 0,
            _ => invalid.communication_byte_weight = 0,
        }
        assert_eq!(evaluate_memory_structure_v1(&invalid, &measurements()), Err(MemoryStructureBudgetErrorV1::InvalidInventory));
    }
    let mut measured = measurements();
    measured[3].errors = 0;
    measured[3].cost.read_compute_wall_ns = Some(1);
    let decision = evaluate_memory_structure_v1(&budget(), &measured).expect("full comparison");
    assert_eq!(decision.best_fixed_digest(), Some(digest("fixed-4")));
    assert_eq!(decision.proposed_digest(), None);
    assert_eq!(decision.reason(), MemoryStructureKeepReasonV1::NoPositiveNetBenefit);
    let mut measured = measurements();
    measured[1].cost.search_wall_ns = Some(1_000_000_000);
    assert_eq!(evaluate_memory_structure_v1(&budget(), &measured).expect("charge losing candidate").proposed_digest(), None);
    measured.pop();
    measured.retain(|item| item.shards != 4);
    assert_eq!(evaluate_memory_structure_v1(&budget(), &measured), Err(MemoryStructureBudgetErrorV1::InvalidInventory));
}

#[test]
fn positive_synthetic_gate_still_preserves_no_change_and_independent_authority() {
    let measured = measurements();
    let decision = evaluate_memory_structure_v1(&budget(), &measured).expect("contract example");
    assert_eq!(decision.proposed_digest(), Some(digest("split")));
    assert!(decision.full_search_score() < decision.best_fixed_score());
    let proposal = propose_memory_structure_v1(request(&decision), &decision).expect("bounded split proposal");
    assert_eq!(proposal.status, ProposalStatus::RequiresIndependentAcceptance);
    assert!(!proposal.authority.grants_any());
    assert_eq!(proposal.candidates.iter().filter(|candidate| candidate.kind == TopologyCandidateKindV2::NoChange).count(), 1);
    let mut mismatched = measured;
    mismatched[4].source_cut_digest = digest("different-cut");
    assert_eq!(evaluate_memory_structure_v1(&budget(), &mismatched), Err(MemoryStructureBudgetErrorV1::IncomparableData));
    let mut wrong = request(&decision);
    wrong.changes[0].candidate_digest = Some(digest("unmeasured"));
    assert_eq!(propose_memory_structure_v1(wrong, &decision), Err(MemoryStructureBudgetErrorV1::ProposalBinding));
}
