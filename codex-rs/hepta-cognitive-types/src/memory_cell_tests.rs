use std::collections::BTreeSet;

use codex_hepta_types::Digest32;

use super::{
    MemoryCellManifestV1, MemoryCellRoleV1, MemoryCellStatusV1, MemoryCellTickInputV1,
    MemoryCellTickReceiptV1, MAX_MEMORY_CELL_STATE_BYTES,
};
use crate::hnmf::ContractDigestV1;
use crate::hnmf::ContractGenerationV1;
use crate::hnmf::ContractIdV1;
use crate::hnmf::HnmfContractError;
use crate::hnmf::ModalityKindV1;
use crate::hnmf_learning::EngramPopulationV1;

fn id(value: &str) -> ContractIdV1 {
    ContractIdV1::new(value).unwrap_or_else(|error| panic!("valid id: {error:?}"))
}

fn digest(value: &str) -> ContractDigestV1 {
    ContractDigestV1::from_digest(Digest32::of_bytes(value.as_bytes()))
        .unwrap_or_else(|error| panic!("valid digest: {error:?}"))
}

fn generation(value: u64) -> ContractGenerationV1 {
    ContractGenerationV1::new(value)
        .unwrap_or_else(|error| panic!("valid generation: {error:?}"))
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
