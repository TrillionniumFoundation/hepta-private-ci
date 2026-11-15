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

use codex_hepta_cognitive_types::Citation;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_cognitive_types::memory_cell::MemoryCellStatusV1;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::EngramDynamicsPolicyV1;
use crate::EngramNodeV1;
use crate::EngramPopulationV1 as RuntimeEngramPopulationV1;
use crate::EngramSnapshotV1;
use crate::EngramSupportV1;
use crate::GeneratedCandidateInputV1;
use crate::MemoryCellRuntimeErrorV1;
use crate::MemoryCellShadowTickV1;
use crate::MemoryCueV1;
use crate::RecallDispositionV1;
use crate::RetrievalChannelCandidateV1;
use crate::RetrievalChannelV1;
use crate::RetrievalChannelWeightV1;
use crate::RetrievalGeneratorBatchV1;
use crate::RetrievalGeneratorOwnerV1;
use crate::RetrievalGeneratorReceiptV1;
use crate::RetrievalPolicyV1;
use crate::RetrievalSourceCompletenessV1;
use crate::compile_cue;

fn id(value: &str) -> ContractIdV1 {
    ContractIdV1::new(value).unwrap_or_else(|error| panic!("id: {error:?}"))
}

fn digest(value: &str) -> ContractDigestV1 {
    ContractDigestV1::from_digest(Digest32::of_bytes(value.as_bytes()))
        .unwrap_or_else(|error| panic!("digest: {error:?}"))
}

fn generation(value: u64) -> ContractGenerationV1 {
    ContractGenerationV1::new(value).unwrap_or_else(|error| panic!("generation: {error:?}"))
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
    changed
        .populations
        .insert(EngramPopulationV1::SemanticConcept);
    assert_ne!(original, checkpoint(&changed, &input));

    let mut changed = manifest.clone();
    changed.max_active_cells += 1;
    assert_ne!(original, checkpoint(&changed, &input));

    let mut changed = manifest.clone();
    changed.max_state_bytes += 1;
    assert_ne!(original, checkpoint(&changed, &input));
}

fn stable_id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("stable id: {error:?}"))
}

fn runtime_generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("generation: {error:?}"))
}

fn revision(value: u64) -> Revision {
    Revision::new(value).unwrap_or_else(|error| panic!("revision: {error:?}"))
}

fn snapshot_key() -> CognitiveSnapshotKeyV1 {
    CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: stable_id("scope:memory-cell-fixture"),
        purpose_id: stable_id("purpose:recall"),
        memory_ledger_frontier: 10,
        knowledge_fact_frontier: 8,
        tombstone_frontier: 4,
        source_ledger_frontier: 11,
        knowledge_graph_generation: runtime_generation(2),
        compact_checkpoint_generation: runtime_generation(1),
        prompt_registry_revision: revision(3),
        retrieval_profile_digest: Digest32::of_bytes(b"retrieval-profile"),
        encoder_preprocessor_digest: Digest32::of_bytes(b"encoder-profile"),
        authority_epoch: 5,
        model_digest: Digest32::of_bytes(b"model"),
        tokenizer_digest: Digest32::of_bytes(b"tokenizer"),
        template_digest: Digest32::of_bytes(b"template"),
        tool_schema_digest: Digest32::of_bytes(b"tool-schema"),
    })
    .unwrap_or_else(|error| panic!("snapshot key: {error:?}"))
}

struct ShadowFixture {
    manifest: MemoryCellManifestV1,
    input: MemoryCellTickInputV1,
    cue: MemoryCueV1,
    policy: RetrievalPolicyV1,
    generated: GeneratedCandidateInputV1,
    snapshot: EngramSnapshotV1,
    dynamics: EngramDynamicsPolicyV1,
}

fn shadow_fixture(with_candidate: bool) -> ShadowFixture {
    let cue = compile_cue(
        stable_id("cue:memory-cell"),
        Digest32::of_bytes(b"objective"),
        Digest32::of_bytes(b"approved-context"),
        Digest32::of_bytes(b"request"),
        snapshot_key(),
        Digest32::of_bytes(b"cue-profile"),
    )
    .unwrap_or_else(|error| panic!("cue: {error:?}"));
    let policy = RetrievalPolicyV1 {
        policy_id: stable_id("policy:memory-cell"),
        channel_weights: vec![RetrievalChannelWeightV1 {
            channel: RetrievalChannelV1::Lexical,
            weight: FixedQ32::ONE,
            maximum_candidates: 16,
        }],
        maximum_results: 8,
        minimum_total_score: FixedQ32::ZERO,
        maximum_ood: ProbabilityQ32::ONE,
        minimum_distinct_channels: 1,
        abstain_on_contradiction: true,
    };
    let record = MemoryRecord {
        record_id: stable_id("memory:cell-fixture"),
        revision: revision(1),
        kind: MemoryKind::Fact,
        content_digest: Digest32::of_bytes(b"memory-content"),
        predecessor_digest: None,
        citations: vec![Citation {
            source_id: stable_id("source:memory-cell"),
            source_digest: Digest32::of_bytes(b"source-record"),
        }],
        state: RecordState::Live,
    };
    let candidate = RetrievalChannelCandidateV1 {
        record: record.clone(),
        channel: RetrievalChannelV1::Lexical,
        channel_rank: 1,
        normalized_score: FixedQ32::ONE,
        ood: ProbabilityQ32::ZERO,
        support_digest: Digest32::of_bytes(b"candidate-support"),
        contradiction_group_digest: None,
        generation_vector_digest: cue.snapshot_key.vector_digest,
    };
    let candidates = if with_candidate {
        vec![candidate]
    } else {
        Vec::new()
    };
    let receipt = RetrievalGeneratorReceiptV1::new(
        RetrievalGeneratorOwnerV1::CognitiveLexical,
        cue.snapshot_key.vector_digest,
        Digest32::of_bytes(b"lexical-owner-generation"),
        u32::try_from(candidates.len()).unwrap_or(u32::MAX),
        RetrievalSourceCompletenessV1::Exhausted,
    )
    .unwrap_or_else(|error| panic!("generator receipt: {error:?}"));
    let generated = GeneratedCandidateInputV1::new(vec![RetrievalGeneratorBatchV1 {
        receipt,
        candidates,
    }])
    .unwrap_or_else(|error| panic!("generated input: {error:?}"));
    let snapshot = EngramSnapshotV1::new(
        cue.snapshot_key.vector_digest,
        Digest32::of_bytes(b"engram-generation"),
        vec![EngramNodeV1 {
            node_id: stable_id("node:episodic"),
            population: RuntimeEngramPopulationV1::EpisodicBinding,
            support: vec![EngramSupportV1 {
                record_id: record.record_id,
                record_revision: record.revision,
            }],
            threshold: FixedQ32::ZERO,
            confidence: ProbabilityQ32::ONE,
            generation_vector_digest: cue.snapshot_key.vector_digest,
        }],
        Vec::new(),
    )
    .unwrap_or_else(|error| panic!("engram snapshot: {error:?}"));
    let dynamics = EngramDynamicsPolicyV1::product_default()
        .unwrap_or_else(|error| panic!("dynamics: {error:?}"));
    let mut input = input();
    input.cue_digest = ContractDigestV1::from_digest(cue.digest())
        .unwrap_or_else(|error| panic!("cue digest: {error:?}"));
    input.snapshot_digest = ContractDigestV1::from_digest(snapshot.snapshot_digest)
        .unwrap_or_else(|error| panic!("snapshot digest: {error:?}"));
    ShadowFixture {
        manifest: manifest(),
        input,
        cue,
        policy,
        generated,
        snapshot,
        dynamics,
    }
}

fn execute(fixture: &ShadowFixture) -> Result<MemoryCellShadowTickV1, MemoryCellRuntimeErrorV1> {
    super::run_memory_cell_tick(
        &fixture.manifest,
        &fixture.input,
        &fixture.cue,
        &fixture.policy,
        &fixture.generated,
        &fixture.snapshot,
        &fixture.dynamics,
    )
}

#[test]
fn shadow_runtime_selected_tick_is_deterministic() {
    let fixture = shadow_fixture(true);
    let first = execute(&fixture).unwrap_or_else(|error| panic!("selected tick: {error:?}"));
    assert_eq!(
        first,
        execute(&fixture).unwrap_or_else(|error| panic!("replay: {error:?}"))
    );
    assert_eq!(first.receipt.status, MemoryCellStatusV1::Selected);
    assert_eq!(
        first.recall.packet.disposition,
        RecallDispositionV1::Recalled
    );
    assert!(first.receipt.recall_packet_digest.is_some());
    assert!(first.receipt.successor_checkpoint_digest.is_some());
}

#[test]
fn shadow_runtime_abstains_without_candidate_support() {
    let fixture = shadow_fixture(false);
    let result = execute(&fixture).unwrap_or_else(|error| panic!("empty tick: {error:?}"));
    assert_eq!(result.receipt.status, MemoryCellStatusV1::Abstained);
    assert!(result.receipt.recall_packet_digest.is_none());
    assert!(result.receipt.successor_checkpoint_digest.is_none());
    assert!(matches!(
        result.recall.packet.disposition,
        RecallDispositionV1::Abstained(_)
    ));
}

#[test]
fn shadow_runtime_rejects_wrong_frontier_cue_and_snapshot() {
    let mut fixture = shadow_fixture(true);
    fixture.input.forget_frontier_digest = digest("stale-forget");
    assert!(matches!(
        execute(&fixture),
        Err(MemoryCellRuntimeErrorV1::Binding("forget_frontier_digest"))
    ));

    let mut fixture = shadow_fixture(true);
    fixture.input.cue_digest = digest("wrong-cue");
    assert!(matches!(
        execute(&fixture),
        Err(MemoryCellRuntimeErrorV1::Binding("cue_digest"))
    ));

    let mut fixture = shadow_fixture(true);
    fixture.input.snapshot_digest = digest("wrong-snapshot");
    assert!(matches!(
        execute(&fixture),
        Err(MemoryCellRuntimeErrorV1::Binding("snapshot_digest"))
    ));

    let mut fixture = shadow_fixture(true);
    fixture.input.graph_generation = generation(2);
    assert!(matches!(
        execute(&fixture),
        Err(MemoryCellRuntimeErrorV1::Binding("graph_generation"))
    ));
}

#[test]
fn shadow_runtime_preserves_ood_evidence_on_abstention() {
    let mut fixture = shadow_fixture(true);
    fixture.policy.maximum_ood = ProbabilityQ32::ZERO;
    fixture.generated.batches[0].candidates[0].ood = ProbabilityQ32::ONE;
    let result = execute(&fixture).unwrap_or_else(|error| panic!("ood tick: {error:?}"));
    assert_eq!(result.receipt.status, MemoryCellStatusV1::Abstained);
    assert_eq!(result.receipt.ood_ppm, 1_000_000);
    assert!(result.receipt.successor_checkpoint_digest.is_none());
}
