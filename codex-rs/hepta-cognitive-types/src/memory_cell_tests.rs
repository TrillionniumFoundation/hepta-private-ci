use std::collections::BTreeSet;

use codex_hepta_types::Digest32;

use super::MAX_MEMORY_CELL_STATE_BYTES;
use super::MemoryCellManifestV1;
use super::MemoryCellRoleV1;
use super::MemoryCellSplitProposalV1;
use super::MemoryCellStatusV1;
use super::MemoryCellTickInputV1;
use super::MemoryCellTickReceiptV1;
use crate::hnmf::ContractDigestV1;
use crate::hnmf::ContractGenerationV1;
use crate::hnmf::ContractIdV1;
use crate::hnmf::HnmfContractError;
use crate::hnmf::ModalityKindV1;
use crate::hnmf_learning::EngramPopulationV1;
use crate::hnmf_learning::PlasticityBatchV1;
use crate::hnmf_learning::TopologyEdgeSpecV1;
use crate::hnmf_learning::TopologyNodeSpecV1;
use crate::hnmf_learning::TopologyOperationV1;
use crate::hnmf_learning::TopologyProposalStateV1;
use crate::hnmf_learning::TopologyProposalV1;
use crate::hnmf_learning::TopologyResourceDeltaV1;
use crate::hnmf_learning::TopologyTypedNodesEdgesV1;

fn id(value: &str) -> ContractIdV1 {
    ContractIdV1::new(value).unwrap_or_else(|error| panic!("valid id: {error:?}"))
}

fn digest(value: &str) -> ContractDigestV1 {
    ContractDigestV1::from_digest(Digest32::of_bytes(value.as_bytes()))
        .unwrap_or_else(|error| panic!("valid digest: {error:?}"))
}

fn generation(value: u64) -> ContractGenerationV1 {
    ContractGenerationV1::new(value).unwrap_or_else(|error| panic!("valid generation: {error:?}"))
}

fn valid_manifest() -> MemoryCellManifestV1 {
    MemoryCellManifestV1 {
        schema_version: 1,
        cell_id: id("memory-cell:episodic:1"),
        role: MemoryCellRoleV1::Episodic,
        parent_cell_id: None,
        shared_base_digest: digest("base"),
        encoder_digest: digest("encoder"),
        adapter_artifact_digest: digest("adapter"),
        head_artifact_digest: digest("head"),
        state_schema_digest: digest("state"),
        source_frontier_digest: digest("source"),
        forget_frontier_digest: digest("forget"),
        lineage_digest: digest("lineage"),
        modalities: BTreeSet::from([ModalityKindV1::Text]),
        populations: BTreeSet::from([EngramPopulationV1::EpisodicBinding]),
        graph_generation: generation(1),
        model_generation: generation(1),
        max_active_cells: 8,
        max_state_bytes: 65_536,
    }
}

fn valid_tick_input() -> MemoryCellTickInputV1 {
    MemoryCellTickInputV1 {
        schema_version: 1,
        cell_id: id("memory-cell:episodic:1"),
        graph_generation: generation(1),
        model_generation: generation(1),
        logical_sequence: 1,
        predecessor_checkpoint_digest: None,
        input_digest: digest("input"),
        cue_digest: digest("cue"),
        snapshot_digest: digest("snapshot"),
        source_frontier_digest: digest("source"),
        forget_frontier_digest: digest("forget"),
        objective_digest: digest("objective"),
        ndu_state_digest: digest("ndu"),
        resource_budget_units: 100,
    }
}

fn valid_receipt() -> MemoryCellTickReceiptV1 {
    MemoryCellTickReceiptV1 {
        schema_version: 1,
        cell_id: id("memory-cell:episodic:1"),
        graph_generation: generation(1),
        model_generation: generation(1),
        logical_sequence: 1,
        status: MemoryCellStatusV1::Selected,
        predecessor_checkpoint_digest: None,
        successor_checkpoint_digest: Some(digest("successor")),
        recall_packet_digest: Some(digest("recall")),
        candidate_digest: Some(digest("candidate")),
        coverage_ppm: 900_000,
        confidence_ppm: 800_000,
        ood_ppm: 10_000,
        resident_bytes: 4_096,
        transient_bytes: 8_192,
    }
}

#[test]
fn manifest_accepts_bounded_projection_identity() {
    assert!(valid_manifest().validate().is_ok());
}

#[test]
fn manifest_rejects_self_parent_and_zero_state_budget() {
    let mut manifest = valid_manifest();
    manifest.parent_cell_id = Some(manifest.cell_id.clone());
    assert!(matches!(
        manifest.validate(),
        Err(HnmfContractError::Conflict("memory cell self-parent"))
    ));

    let mut manifest = valid_manifest();
    manifest.max_state_bytes = 0;
    assert!(matches!(
        manifest.validate(),
        Err(HnmfContractError::LimitExceeded {
            field: "maxStateBytes",
            ..
        })
    ));
    assert!(usize::try_from(MAX_MEMORY_CELL_STATE_BYTES).is_ok());
}

#[test]
fn tick_input_requires_progress_and_budget() {
    assert!(valid_tick_input().validate().is_ok());

    let mut input = valid_tick_input();
    input.logical_sequence = 0;
    assert!(matches!(
        input.validate(),
        Err(HnmfContractError::ZeroValue("logicalSequence"))
    ));

    let mut input = valid_tick_input();
    input.resource_budget_units = 0;
    assert!(matches!(
        input.validate(),
        Err(HnmfContractError::ZeroValue("resourceBudgetUnits"))
    ));
}

#[test]
fn receipt_binds_selected_output_and_rejects_invalid_abstain() {
    assert!(valid_receipt().validate().is_ok());

    let mut receipt = valid_receipt();
    receipt.recall_packet_digest = None;
    assert!(matches!(
        receipt.validate(),
        Err(HnmfContractError::Missing(
            "selected memory cell receipt successor"
        ))
    ));

    let mut receipt = valid_receipt();
    receipt.status = MemoryCellStatusV1::Abstained;
    assert!(matches!(
        receipt.validate(),
        Err(HnmfContractError::Conflict(
            "abstained memory cell receipt output"
        ))
    ));
}

#[test]
fn selected_receipt_requires_candidate_evidence_and_global_budget() {
    let mut receipt = valid_receipt();
    receipt.candidate_digest = None;
    assert!(matches!(
        receipt.validate(),
        Err(HnmfContractError::Missing(
            "selected memory cell receipt successor"
        ))
    ));

    let mut receipt = valid_receipt();
    receipt.resident_bytes = MAX_MEMORY_CELL_STATE_BYTES + 1;
    assert!(matches!(
        receipt.validate(),
        Err(HnmfContractError::LimitExceeded {
            field: "residentBytes",
            ..
        })
    ));
}

#[test]
fn receipt_rejects_cross_generation_and_over_budget_bindings() {
    let manifest = valid_manifest();
    let input = valid_tick_input();
    assert!(valid_receipt()
        .validate_against_manifest_and_input(&manifest, &input)
        .is_ok());

    let mut receipt = valid_receipt();
    receipt.logical_sequence += 1;
    assert!(matches!(
        receipt.validate_against_manifest_and_input(&manifest, &input),
        Err(HnmfContractError::Conflict(
            "memory cell receipt/input binding"
        ))
    ));

    let mut receipt = valid_receipt();
    receipt.predecessor_checkpoint_digest = Some(digest("wrong-predecessor"));
    assert!(matches!(
        receipt.validate_against_manifest_and_input(&manifest, &input),
        Err(HnmfContractError::Conflict(
            "memory cell receipt/input binding"
        ))
    ));

    let mut stale_input = input.clone();
    stale_input.forget_frontier_digest = digest("stale-forget");
    assert!(matches!(
        valid_receipt().validate_against_manifest_and_input(&manifest, &stale_input),
        Err(HnmfContractError::Conflict(
            "memory cell manifest/input binding"
        ))
    ));

    let mut receipt = valid_receipt();
    receipt.resident_bytes = manifest.max_state_bytes + 1;
    assert!(matches!(
        receipt.validate_against_manifest_and_input(&manifest, &input),
        Err(HnmfContractError::LimitExceeded {
            field: "residentBytes",
            ..
        })
    ));
}

fn valid_split() -> MemoryCellSplitProposalV1 {
    let topology = TopologyProposalV1 {
        proposal_id: id("topology:split:1"),
        predecessor_topology_digest: digest("topology-before"),
        operation: TopologyOperationV1::Split,
        typed_nodes_edges: TopologyTypedNodesEdgesV1 {
            nodes: vec![
                TopologyNodeSpecV1 {
                    node_id: id("node:child-a"),
                    population: EngramPopulationV1::EpisodicBinding,
                    label: "child-a".to_string(),
                },
                TopologyNodeSpecV1 {
                    node_id: id("node:child-b"),
                    population: EngramPopulationV1::SemanticConcept,
                    label: "child-b".to_string(),
                },
            ],
            edges: Vec::<TopologyEdgeSpecV1>::new(),
        },
        compatibility_plan_digest: digest("compatibility"),
        resource_delta: TopologyResourceDeltaV1 {
            node_delta: 1,
            edge_delta: 0,
            resident_bytes_upper_bound_delta: 1024,
        },
        security_review_digest: digest("security"),
        lesion_plan_digest: digest("lesion"),
        rollback_plan_digest: digest("rollback"),
        state: TopologyProposalStateV1::Proposed,
    };
    MemoryCellSplitProposalV1 {
        schema_version: 1,
        proposal_id: id("topology:split:1"),
        parent_cell_id: id("memory-cell:episodic:parent"),
        child_cell_ids: vec![
            id("memory-cell:episodic:child-a"),
            id("memory-cell:episodic:child-b"),
        ],
        parent_manifest_digest: digest("parent-manifest"),
        child_manifest_digests: vec![digest("child-a-manifest"), digest("child-b-manifest")],
        partition_digest: digest("partition"),
        state_transform_digest: digest("state-transform"),
        replay_snapshot_digest: digest("replay"),
        source_frontier_digest: digest("source"),
        forget_frontier_digest: digest("forget"),
        predecessor_graph_generation: generation(1),
        next_graph_generation: generation(2),
        predecessor_model_generation: generation(1),
        next_model_generation: generation(2),
        topology,
        plasticity: PlasticityBatchV1 {
            predecessor_generation: generation(1),
            next_generation: generation(2),
            outcome_signal_digest: digest("outcome"),
            weight_proposals: Vec::new(),
            threshold_proposals: Vec::new(),
            current_snapshot_immutable: true,
            production_activation_allowed: false,
        },
        independent_evaluation_digest: digest("evaluation"),
    }
}

#[test]
fn split_proposal_requires_governed_binary_candidate() {
    assert!(valid_split().validate().is_ok());

    let mut proposal = valid_split();
    proposal.topology.operation = TopologyOperationV1::Add;
    assert!(matches!(
        proposal.validate(),
        Err(HnmfContractError::Conflict("memory cell split topology"))
    ));

    let mut proposal = valid_split();
    proposal.child_cell_ids[1] = proposal.child_cell_ids[0].clone();
    assert!(matches!(
        proposal.validate(),
        Err(HnmfContractError::Conflict("memory cell split identity"))
    ));

    let mut proposal = valid_split();
    proposal.plasticity.production_activation_allowed = true;
    assert!(matches!(
        proposal.validate(),
        Err(HnmfContractError::Conflict(
            "plasticity generation/authority"
        ))
    ));
}
