//! Candidate checkpoint digest invariants, without a writer or model.

use std::collections::BTreeSet;

use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_cognitive_types::hnmf::ModalityKindV1;
use codex_hepta_cognitive_types::hnmf_learning::EngramPopulationV1;
use codex_hepta_cognitive_types::memory_cell::MemoryCellManifestV1;
use codex_hepta_cognitive_types::memory_cell::MemoryCellRoleV1;
use codex_hepta_cognitive_types::memory_cell::MemoryCellTickInputV1;
use codex_hepta_types::Digest32;

use super::shadow_checkpoint_digest;

fn id(value: &str) -> ContractIdV1 {
    ContractIdV1::new(value).unwrap_or_else(|error| panic!("id: {error:?}"))
}

fn digest(value: &str) -> ContractDigestV1 {
    ContractDigestV1::from_digest(Digest32::of_bytes(value.as_bytes()))
        .unwrap_or_else(|error| panic!("digest: {error:?}"))
}

fn generation(value: u64) -> ContractGenerationV1 {
    ContractGenerationV1::new(value)
        .unwrap_or_else(|error| panic!("generation: {error:?}"))
}

fn manifest() -> MemoryCellManifestV1 {
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

fn input() -> MemoryCellTickInputV1 {
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

fn checkpoint(cell: &MemoryCellManifestV1, tick: &MemoryCellTickInputV1) -> ContractDigestV1 {
    shadow_checkpoint_digest(cell, tick, Digest32::of_bytes(b"generated-recall"))
        .unwrap_or_else(|error| panic!("checkpoint: {error:?}"))
}

#[test]
fn checkpoint_is_deterministic_and_binds_all_tick_inputs() {
    let manifest = manifest();
    let input = input();
    let original = checkpoint(&manifest, &input);
    assert_eq!(original, checkpoint(&manifest, &input));

    let mut changed = input.clone();
    changed.resource_budget_units += 1;
    assert_ne!(original, checkpoint(&manifest, &changed));

    let mut changed = input.clone();
    changed.ndu_state_digest = digest("next-ndu");
    assert_ne!(original, checkpoint(&manifest, &changed));

    let mut changed = input.clone();
    changed.predecessor_checkpoint_digest = Some(digest("prior"));
    assert_ne!(original, checkpoint(&manifest, &changed));
}

#[test]
fn checkpoint_binds_artifact_role_and_lineage() {
    let manifest = manifest();
    let input = input();
    let original = checkpoint(&manifest, &input);

    let mut changed = manifest.clone();
    changed.adapter_artifact_digest = digest("other-adapter");
    assert_ne!(original, checkpoint(&changed, &input));

    let mut changed = manifest.clone();
    changed.head_artifact_digest = digest("other-head");
    assert_ne!(original, checkpoint(&changed, &input));

    let mut changed = manifest.clone();
    changed.role = MemoryCellRoleV1::Semantic;
    assert_ne!(original, checkpoint(&changed, &input));

    let mut changed = manifest.clone();
    changed.parent_cell_id = Some(id("memory-cell:parent"));
    assert_ne!(original, checkpoint(&changed, &input));

    let mut changed = manifest.clone();
    changed.lineage_digest = digest("other-lineage");
    assert_ne!(original, checkpoint(&changed, &input));
}

#[test]
fn checkpoint_binds_population_modality_and_resource_limits() {
    let manifest = manifest();
    let input = input();
    let original = checkpoint(&manifest, &input);

    let mut changed = manifest.clone();
    changed.modalities.insert(ModalityKindV1::CodeAst);
    assert_ne!(original, checkpoint(&changed, &input));

    let mut changed = manifest.clone();
    changed.populations.insert(EngramPopulationV1::SemanticConcept);
    assert_ne!(original, checkpoint(&changed, &input));

    let mut changed = manifest.clone();
    changed.max_active_cells += 1;
    assert_ne!(original, checkpoint(&changed, &input));

    let mut changed = manifest.clone();
    changed.max_state_bytes += 1;
    assert_ne!(original, checkpoint(&changed, &input));
}
