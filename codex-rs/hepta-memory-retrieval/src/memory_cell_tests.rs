use super::*;

use std::collections::BTreeSet;

use codex_hepta_cognitive_types::Citation;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_cognitive_types::hnmf::ModalityKindV1;
use codex_hepta_cognitive_types::hnmf_learning::EngramPopulationV1 as ContractPopulationV1;
use codex_hepta_cognitive_types::memory_cell::MemoryCellRoleV1;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::EngramNodeV1;
use crate::EngramPopulationV1;
use crate::EngramSupportV1;
use crate::RetrievalChannelCandidateV1;
use crate::RetrievalChannelV1;
use crate::RetrievalChannelWeightV1;
use crate::RetrievalGeneratorBatchV1;
use crate::RetrievalGeneratorOwnerV1;
use crate::RetrievalGeneratorReceiptV1;
use crate::RetrievalSourceCompletenessV1;
use crate::compile_cue;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn contract_digest(value: Digest32) -> ContractDigestV1 {
    ContractDigestV1::from_digest(value)
        .unwrap_or_else(|error| panic!("valid contract digest: {error:?}"))
}

fn contract_id(value: &str) -> ContractIdV1 {
    ContractIdV1::new(value).unwrap_or_else(|error| panic!("valid contract id: {error:?}"))
}

fn model_generation(value: u64) -> ContractGenerationV1 {
    ContractGenerationV1::new(value)
        .unwrap_or_else(|error| panic!("valid contract generation: {error:?}"))
}

fn revision(value: u64) -> Revision {
    Revision::new(value).unwrap_or_else(|error| panic!("valid revision: {error}"))
}

fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("valid generation: {error}"))
}

struct Fixture {
    manifest: MemoryCellManifestV1,
    input: MemoryCellTickInputV1,
    cue: MemoryCueV1,
    policy: RetrievalPolicyV1,
    candidates: GeneratedCandidateInputV1,
    engram: EngramSnapshotV1,
    dynamics: EngramDynamicsPolicyV1,
}

fn fixture() -> Fixture {
    let key = CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:memory-cell-shadow"),
        purpose_id: id("purpose:recall"),
        memory_ledger_frontier: 10,
        knowledge_fact_frontier: 8,
        tombstone_frontier: 4,
        source_ledger_frontier: 11,
        knowledge_graph_generation: generation(2),
        compact_checkpoint_generation: generation(1),
        prompt_registry_revision: revision(3),
        retrieval_profile_digest: digest("retrieval-profile"),
        encoder_preprocessor_digest: digest("encoder-profile"),
        authority_epoch: 5,
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
    })
    .unwrap_or_else(|error| panic!("valid generation vector: {error}"));
    let cue = compile_cue(
        id("cue:memory-cell-shadow"),
        digest("objective"),
        digest("approved-context"),
        digest("request"),
        key,
        digest("cue-profile"),
    )
    .unwrap_or_else(|error| panic!("valid cue: {error}"));
    let record = MemoryRecord {
        record_id: id("memory:1"),
        revision: revision(1),
        kind: MemoryKind::Fact,
        content_digest: digest("content:1"),
        predecessor_digest: None,
        citations: vec![Citation {
            source_id: id("source:1"),
            source_digest: digest("source:1"),
        }],
        state: RecordState::Live,
    };
    let candidate = RetrievalChannelCandidateV1 {
        record,
        channel: RetrievalChannelV1::Lexical,
        channel_rank: 1,
        normalized_score: FixedQ32::ONE,
        ood: ProbabilityQ32::ZERO,
        support_digest: digest("candidate:support"),
        contradiction_group_digest: None,
        generation_vector_digest: cue.snapshot_key.vector_digest,
    };
    let receipt = RetrievalGeneratorReceiptV1::new(
        RetrievalGeneratorOwnerV1::CognitiveLexical,
        cue.snapshot_key.vector_digest,
        digest("owner-generation"),
        1,
        RetrievalSourceCompletenessV1::Exhausted,
    )
    .unwrap_or_else(|error| panic!("valid generator receipt: {error:?}"));
    let candidates = GeneratedCandidateInputV1::new(vec![RetrievalGeneratorBatchV1 {
        receipt,
        candidates: vec![candidate],
    }])
    .unwrap_or_else(|error| panic!("valid candidates: {error:?}"));
    let policy = RetrievalPolicyV1 {
        policy_id: id("policy:memory-cell-shadow"),
        channel_weights: vec![RetrievalChannelWeightV1 {
            channel: RetrievalChannelV1::Lexical,
            weight: FixedQ32::ONE,
            maximum_candidates: 4,
        }],
        maximum_results: 1,
        minimum_total_score: FixedQ32::from_raw(1),
        maximum_ood: ProbabilityQ32::ONE,
        minimum_distinct_channels: 1,
        abstain_on_contradiction: true,
    };
    let engram = EngramSnapshotV1::new(
        cue.snapshot_key.vector_digest,
        digest("engram-generation"),
        vec![EngramNodeV1 {
            node_id: id("node:episodic"),
            population: EngramPopulationV1::EpisodicBinding,
            support: vec![EngramSupportV1 {
                record_id: id("memory:1"),
                record_revision: revision(1),
            }],
            threshold: FixedQ32::ZERO,
            confidence: ProbabilityQ32::ONE,
            generation_vector_digest: cue.snapshot_key.vector_digest,
        }],
        Vec::new(),
    )
    .unwrap_or_else(|error| panic!("valid engram: {error:?}"));
    let dynamics = EngramDynamicsPolicyV1::product_default()
        .unwrap_or_else(|error| panic!("valid engram dynamics: {error:?}"));
    let manifest = MemoryCellManifestV1 {
        schema_version: 1,
        cell_id: contract_id("memory-cell:episodic:shadow-fixture"),
        role: MemoryCellRoleV1::Episodic,
        parent_cell_id: None,
        shared_base_digest: contract_digest(digest("base")),
        encoder_digest: contract_digest(digest("encoder")),
        adapter_artifact_digest: contract_digest(digest("adapter")),
        head_artifact_digest: contract_digest(digest("head")),
        state_schema_digest: contract_digest(digest("state")),
        source_frontier_digest: contract_digest(digest("source-frontier")),
        forget_frontier_digest: contract_digest(digest("forget-frontier")),
        lineage_digest: contract_digest(digest("lineage")),
        modalities: BTreeSet::from([ModalityKindV1::Text]),
        populations: BTreeSet::from([ContractPopulationV1::EpisodicBinding]),
        graph_generation: model_generation(1),
        model_generation: model_generation(1),
        max_active_cells: 8,
        max_state_bytes: 65_536,
    };
    let input = MemoryCellTickInputV1 {
        schema_version: 1,
        cell_id: manifest.cell_id.clone(),
        graph_generation: manifest.graph_generation,
        model_generation: manifest.model_generation,
        logical_sequence: 1,
        predecessor_checkpoint_digest: None,
        input_digest: contract_digest(digest("input")),
        cue_digest: contract_digest(cue.digest()),
        snapshot_digest: contract_digest(engram.snapshot_digest),
        source_frontier_digest: manifest.source_frontier_digest.clone(),
        forget_frontier_digest: manifest.forget_frontier_digest.clone(),
        objective_digest: contract_digest(cue.objective_digest),
        ndu_state_digest: contract_digest(digest("ndu")),
        resource_budget_units: 100,
    };
    Fixture { manifest, input, cue, policy, candidates, engram, dynamics }
}

fn tick(f: &Fixture) -> Result<MemoryCellShadowTickV1, MemoryCellRuntimeErrorV1> {
    run_memory_cell_tick(
        &f.manifest,
        &f.input,
        &f.cue,
        &f.policy,
        &f.candidates,
        &f.engram,
        &f.dynamics,
    )
}

fn successful_tick(f: &Fixture) -> MemoryCellShadowTickV1 {
    tick(f).unwrap_or_else(|error| panic!("valid shadow tick: {error:?}"))
}

fn rejected_tick(f: &Fixture) -> MemoryCellRuntimeErrorV1 {
    match tick(f) {
        Ok(_) => panic!("the altered binding must be rejected"),
        Err(error) => error,
    }
}

#[test]
fn selected_tick_has_stable_non_authoritative_receipts() {
    let f = fixture();
    let first = successful_tick(&f);
    let second = successful_tick(&f);
    assert_eq!(first, second);
    assert_eq!(first.receipt.status, MemoryCellStatusV1::Selected);
    assert!(first.receipt.recall_packet_digest.is_some());
    assert!(first.receipt.successor_checkpoint_digest.is_some());
    assert!(first.receipt.validate().is_ok());
    assert_eq!(first.receipt.resident_bytes, 0);
    assert_eq!(first.receipt.transient_bytes, 0);
}

#[test]
fn ood_abstention_retains_input_telemetry_without_successor() {
    let mut f = fixture();
    f.candidates.batches[0].candidates[0].ood = ProbabilityQ32::ONE;
    f.policy.maximum_ood = ProbabilityQ32::ZERO;
    let result = successful_tick(&f);
    assert_eq!(result.receipt.status, MemoryCellStatusV1::Abstained);
    assert_eq!(result.receipt.ood_ppm, 1_000_000);
    assert!(result.receipt.successor_checkpoint_digest.is_none());
    assert!(result.receipt.recall_packet_digest.is_none());
    assert!(result.receipt.candidate_digest.is_some());
}

#[test]
fn mismatched_frontiers_generations_and_snapshot_fail_closed() {
    let mut f = fixture();
    f.input.graph_generation = model_generation(2);
    assert_eq!(rejected_tick(&f), MemoryCellRuntimeErrorV1::Binding("graph_generation"));

    let mut f = fixture();
    f.input.source_frontier_digest = contract_digest(digest("stale-source"));
    assert_eq!(rejected_tick(&f), MemoryCellRuntimeErrorV1::Binding("source_frontier_digest"));

    let mut f = fixture();
    f.input.forget_frontier_digest = contract_digest(digest("stale-forget"));
    assert_eq!(rejected_tick(&f), MemoryCellRuntimeErrorV1::Binding("forget_frontier_digest"));

    let mut f = fixture();
    f.input.snapshot_digest = contract_digest(digest("different-snapshot"));
    assert_eq!(rejected_tick(&f), MemoryCellRuntimeErrorV1::Binding("snapshot_digest"));

    let mut f = fixture();
    f.input.cue_digest = contract_digest(digest("different-cue"));
    assert_eq!(rejected_tick(&f), MemoryCellRuntimeErrorV1::Binding("cue_digest"));
}

#[test]
fn candidate_checkpoint_binds_budget_input_ndu_and_predecessor() {
    let baseline = successful_tick(&fixture()).receipt.successor_checkpoint_digest;

    let mut f = fixture();
    f.input.resource_budget_units += 1;
    assert_ne!(baseline, successful_tick(&f).receipt.successor_checkpoint_digest);

    let mut f = fixture();
    f.input.ndu_state_digest = contract_digest(digest("different-ndu"));
    assert_ne!(baseline, successful_tick(&f).receipt.successor_checkpoint_digest);

    let mut f = fixture();
    f.input.input_digest = contract_digest(digest("different-input"));
    assert_ne!(baseline, successful_tick(&f).receipt.successor_checkpoint_digest);

    let mut f = fixture();
    f.input.predecessor_checkpoint_digest = Some(contract_digest(digest("previous-checkpoint")));
    assert_ne!(baseline, successful_tick(&f).receipt.successor_checkpoint_digest);
}
