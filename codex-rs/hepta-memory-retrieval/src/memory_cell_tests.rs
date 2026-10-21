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

fn meta_policy(
    fixture: &ShadowFixture,
) -> codex_hepta_cognitive_types::memory_meta_network::MemoryMetaNetworkPolicyV1 {
    use codex_hepta_cognitive_types::memory_meta_network::MemoryMetaNetworkPolicyV1;

    MemoryMetaNetworkPolicyV1 {
        schema_version: 1,
        shared_base_digest: fixture.manifest.shared_base_digest,
        encoder_digest: fixture.manifest.encoder_digest,
        encoder_feature_digest: digest("shared-feature"),
        evidence_ledger_digest: digest("evidence-ledger"),
        snapshot_digest: ContractDigestV1::from_digest(fixture.snapshot.snapshot_digest)
            .unwrap_or_else(|error| panic!("snapshot: {error:?}")),
        source_frontier_digest: fixture.manifest.source_frontier_digest,
        forget_frontier_digest: fixture.manifest.forget_frontier_digest,
        graph_generation: fixture.manifest.graph_generation,
        model_generation: fixture.manifest.model_generation,
        maximum_selected_cells: 2,
        maximum_compute_units: 100,
        minimum_relevance_ppm: 100_000,
        minimum_confidence_ppm: 500_000,
        maximum_ood_ppm: 200_000,
    }
}

fn meta_spec(fixture: &ShadowFixture) -> crate::MemoryMetaCellTickSpecV1 {
    crate::MemoryMetaCellTickSpecV1 {
        manifest: fixture.manifest.clone(),
        tick_input: fixture.input.clone(),
        generated_input: fixture.generated.clone(),
        evidence_ledger_digest: digest("evidence-ledger"),
        encoder_feature_digest: digest("shared-feature"),
        support_digest: Some(digest("source-citation")),
        independent_assessment_digest: digest("independent-assessor"),
        relevance_ppm: 850_000,
        resource_cost_units: 20,
        association_group_digest: None,
        contradiction_group_digest: None,
    }
}

#[test]
fn multi_cell_shadow_recall_uses_one_snapshot_and_returns_grounded_route() {
    use codex_hepta_cognitive_types::memory_meta_network::MemoryMetaRouteDispositionV1;

    let fixture = shadow_fixture(true);
    let first = meta_spec(&fixture);
    let mut second = meta_spec(&fixture);
    second.manifest.cell_id = id("memory-cell:semantic:2");
    second.manifest.role = MemoryCellRoleV1::Semantic;
    second.tick_input.cell_id = second.manifest.cell_id.clone();

    let result = crate::run_memory_meta_batch_shadow_v1(
        &meta_policy(&fixture),
        &fixture.cue,
        &fixture.policy,
        &fixture.snapshot,
        &fixture.dynamics,
        &[second, first],
    )
    .unwrap_or_else(|error| panic!("meta shadow batch: {error:?}"));

    assert_eq!(result.cell_ticks.len(), 2);
    assert!(result.cell_ticks.iter().all(|tick| {
        tick.receipt.status == MemoryCellStatusV1::Selected
    }));
    assert_eq!(result.routing.receipt.resource_used_units, 40);
    assert!(result.routing.receipt.decisions.iter().all(|decision| {
        decision.disposition == MemoryMetaRouteDispositionV1::Selected
    }));
    assert!(!result.routing.receipt.production_activation_allowed);
    assert!(!result.routing.authority.grants_any());
    assert!(result.routing.receipt.validate().is_ok());
}

#[test]
fn multi_cell_shadow_recall_abstains_on_empty_retrieval() {
    let fixture = shadow_fixture(false);
    let result = crate::run_memory_meta_batch_shadow_v1(
        &meta_policy(&fixture),
        &fixture.cue,
        &fixture.policy,
        &fixture.snapshot,
        &fixture.dynamics,
        &[meta_spec(&fixture)],
    )
    .unwrap_or_else(|error| panic!("empty meta batch: {error:?}"));

    assert_eq!(result.cell_ticks[0].receipt.status, MemoryCellStatusV1::Abstained);
    assert!(result.routing.receipt.abstained);
    assert_eq!(result.routing.receipt.resource_used_units, 0);
}

#[test]
fn multi_cell_shadow_preflight_rejects_stale_frontier_and_duplicates() {
    let fixture = shadow_fixture(true);
    let mut spec = meta_spec(&fixture);
    spec.manifest.forget_frontier_digest = digest("old-forget");
    spec.tick_input.forget_frontier_digest = digest("old-forget");

    let rejected = crate::run_memory_meta_batch_shadow_v1(
        &meta_policy(&fixture),
        &fixture.cue,
        &fixture.policy,
        &fixture.snapshot,
        &fixture.dynamics,
        &[spec],
    );
    assert!(matches!(
        rejected,
        Err(crate::MemoryMetaBatchErrorV1::Contract(
            codex_hepta_cognitive_types::hnmf::HnmfContractError::Conflict(
                "memory meta evidence or generation drift"
            )
        ))
    ));

    let spec = meta_spec(&fixture);
    let rejected = crate::run_memory_meta_batch_shadow_v1(
        &meta_policy(&fixture),
        &fixture.cue,
        &fixture.policy,
        &fixture.snapshot,
        &fixture.dynamics,
        &[spec, meta_spec(&fixture)],
    );
    assert!(matches!(
        rejected,
        Err(crate::MemoryMetaBatchErrorV1::Contract(
            codex_hepta_cognitive_types::hnmf::HnmfContractError::DuplicateIdentity(
                "memory meta cell"
            )
        ))
    ));
}

#[test]
fn multi_cell_shadow_preflight_rejects_late_invalid_tick_before_first_retrieval() {
    let fixture = shadow_fixture(true);
    let mut first = meta_spec(&fixture);
    // If the first tick ran, its empty generated source would fail as a Tick error.
    first.generated_input.batches.clear();

    let mut second = meta_spec(&fixture);
    second.manifest.cell_id = id("memory-cell:semantic:2");
    second.manifest.role = MemoryCellRoleV1::Semantic;
    second.tick_input.cell_id = second.manifest.cell_id.clone();
    second.tick_input.logical_sequence = 0;

    let rejected = crate::run_memory_meta_batch_shadow_v1(
        &meta_policy(&fixture),
        &fixture.cue,
        &fixture.policy,
        &fixture.snapshot,
        &fixture.dynamics,
        &[first, second],
    );
    assert!(matches!(
        rejected,
        Err(crate::MemoryMetaBatchErrorV1::Contract(
            codex_hepta_cognitive_types::hnmf::HnmfContractError::ZeroValue("logicalSequence")
        ))
    ));
}

#[test]
fn multi_cell_shadow_preflight_rejects_late_generation_and_cost_before_first_tick() {
    let fixture = shadow_fixture(true);
    let mut first = meta_spec(&fixture);
    first.generated_input.batches.clear();

    let mut second = meta_spec(&fixture);
    second.manifest.cell_id = id("memory-cell:semantic:2");
    second.manifest.role = MemoryCellRoleV1::Semantic;
    second.tick_input.cell_id = second.manifest.cell_id.clone();
    second.tick_input.model_generation = generation(2);
    let rejected = crate::run_memory_meta_batch_shadow_v1(
        &meta_policy(&fixture),
        &fixture.cue,
        &fixture.policy,
        &fixture.snapshot,
        &fixture.dynamics,
        &[first, second.clone()],
    );
    assert!(matches!(
        rejected,
        Err(crate::MemoryMetaBatchErrorV1::Contract(
            codex_hepta_cognitive_types::hnmf::HnmfContractError::Conflict(
                "memory meta tick binding"
            )
        ))
    ));

    second.tick_input.model_generation = second.manifest.model_generation;
    second.resource_cost_units = 0;
    let rejected = crate::run_memory_meta_batch_shadow_v1(
        &meta_policy(&fixture),
        &fixture.cue,
        &fixture.policy,
        &fixture.snapshot,
        &fixture.dynamics,
        &[meta_spec(&fixture), second.clone()],
    );
    assert!(matches!(
        rejected,
        Err(crate::MemoryMetaBatchErrorV1::Contract(
            codex_hepta_cognitive_types::hnmf::HnmfContractError::Invalid(
                "memory meta candidate cost"
            )
        ))
    ));

    second.resource_cost_units = 20;
    second.relevance_ppm = 1_000_001;
    let rejected = crate::run_memory_meta_batch_shadow_v1(
        &meta_policy(&fixture),
        &fixture.cue,
        &fixture.policy,
        &fixture.snapshot,
        &fixture.dynamics,
        &[meta_spec(&fixture), second],
    );
    assert!(matches!(
        rejected,
        Err(crate::MemoryMetaBatchErrorV1::Contract(
            codex_hepta_cognitive_types::hnmf::HnmfContractError::Invalid(
                "memory meta candidate relevance"
            )
        ))
    ));
}

#[test]
fn multi_cell_shadow_preflight_rejects_late_forged_cue_and_objective_before_any_tick() {
    let fixture = shadow_fixture(true);
    let mut first = meta_spec(&fixture);
    // No early tick may run: the first Cell has an invalid generated source.
    first.generated_input.batches.clear();
    let mut second = meta_spec(&fixture);
    second.manifest.cell_id = id("memory-cell:semantic:2");
    second.manifest.role = MemoryCellRoleV1::Semantic;
    second.tick_input.cell_id = second.manifest.cell_id.clone();

    second.tick_input.cue_digest = digest("forged-late-cue");
    let forged_cue = crate::run_memory_meta_batch_shadow_v1(
        &meta_policy(&fixture),
        &fixture.cue,
        &fixture.policy,
        &fixture.snapshot,
        &fixture.dynamics,
        &[first.clone(), second.clone()],
    );
    assert!(matches!(
        forged_cue,
        Err(crate::MemoryMetaBatchErrorV1::Contract(
            codex_hepta_cognitive_types::hnmf::HnmfContractError::Conflict(
                "memory meta pre-tick cue or objective"
            )
        ))
    ));

    second.tick_input.cue_digest = meta_spec(&fixture).tick_input.cue_digest;
    second.tick_input.objective_digest = digest("forged-late-objective");
    let forged_objective = crate::run_memory_meta_batch_shadow_v1(
        &meta_policy(&fixture),
        &fixture.cue,
        &fixture.policy,
        &fixture.snapshot,
        &fixture.dynamics,
        &[first, second],
    );
    assert!(matches!(
        forged_objective,
        Err(crate::MemoryMetaBatchErrorV1::Contract(
            codex_hepta_cognitive_types::hnmf::HnmfContractError::Conflict(
                "memory meta pre-tick cue or objective"
            )
        ))
    ));
}

#[test]
fn pre_tick_shadow_skips_non_admitted_cell_execution_and_is_order_independent() {
    let fixture = shadow_fixture(true);
    let first = meta_spec(&fixture);
    let mut second = meta_spec(&fixture);
    second.manifest.cell_id = id("memory-cell:semantic:2");
    second.manifest.role = MemoryCellRoleV1::Semantic;
    second.tick_input.cell_id = second.manifest.cell_id.clone();
    second.relevance_ppm = 700_000;
    // This generated candidate set cannot pass a tick, so success proves
    // that the deferred Cell was not executed.
    second.generated_input.batches.clear();

    let mut policy = meta_policy(&fixture);
    policy.maximum_selected_cells = 1;
    let plan_a = crate::plan_memory_meta_pre_ticks_shadow_v1(
        &policy,
        &fixture.cue,
        &fixture.snapshot,
        &[first.clone(), second.clone()],
    )
    .unwrap_or_else(|error| panic!("pre-tick plan: {error:?}"));
    let plan_b = crate::plan_memory_meta_pre_ticks_shadow_v1(
        &policy,
        &fixture.cue,
        &fixture.snapshot,
        &[second.clone(), first.clone()],
    )
    .unwrap_or_else(|error| panic!("reverse plan: {error:?}"));
    assert_eq!(plan_a, plan_b);
    assert_eq!(plan_a.admitted_cell_ids, vec![first.manifest.cell_id.clone()]);
    assert_eq!(plan_a.deferred_cell_ids, vec![second.manifest.cell_id.clone()]);
    assert_eq!(plan_a.reserved_compute_units, 20);
    assert!(plan_a.current_snapshot_immutable);
    assert!(!plan_a.production_activation_allowed);

    let outcome = crate::run_memory_meta_preselected_shadow_v1(
        &policy,
        &fixture.cue,
        &fixture.policy,
        &fixture.snapshot,
        &fixture.dynamics,
        &[second.clone(), first],
    )
    .unwrap_or_else(|error| panic!("preselected tick: {error:?}"));
    assert_eq!(outcome.pre_tick_plan, plan_a);
    assert_eq!(outcome.batch.cell_ticks.len(), 1);
    assert_eq!(outcome.batch.routing.receipt.decisions.len(), 1);
    assert_eq!(outcome.batch.routing.receipt.resource_used_units, 20);
    assert!(!outcome.batch.routing.authority.grants_any());

    let mut changed = second;
    changed.relevance_ppm += 1;
    let changed_plan = crate::plan_memory_meta_pre_ticks_shadow_v1(
        &policy,
        &fixture.cue,
        &fixture.snapshot,
        &[meta_spec(&fixture), changed],
    )
    .unwrap_or_else(|error| panic!("changed metadata: {error:?}"));
    assert_ne!(plan_b.admission_input_digest, changed_plan.admission_input_digest);
    assert_ne!(plan_b.admission_plan_digest, changed_plan.admission_plan_digest);
}

#[test]
fn pre_tick_shadow_suppresses_conflicted_cells_without_running_their_tics() {
    let fixture = shadow_fixture(true);
    let mut first = meta_spec(&fixture);
    let mut second = meta_spec(&fixture);
    second.manifest.cell_id = id("memory-cell:semantic:2");
    second.manifest.role = MemoryCellRoleV1::Semantic;
    second.tick_input.cell_id = second.manifest.cell_id.clone();
    first.contradiction_group_digest = Some(digest("unresolved-dispute"));
    second.contradiction_group_digest = first.contradiction_group_digest;
    first.generated_input.batches.clear();
    second.generated_input.batches.clear();

    let outcome = crate::run_memory_meta_preselected_shadow_v1(
        &meta_policy(&fixture),
        &fixture.cue,
        &fixture.policy,
        &fixture.snapshot,
        &fixture.dynamics,
        &[second, first],
    )
    .unwrap_or_else(|error| panic!("conflict suppression: {error:?}"));
    assert!(outcome.pre_tick_plan.admitted_cell_ids.is_empty());
    assert_eq!(outcome.pre_tick_plan.deferred_cell_ids.len(), 2);
    assert_eq!(outcome.pre_tick_plan.reserved_compute_units, 0);
    assert!(outcome.batch.cell_ticks.is_empty());
    assert!(outcome.batch.routing.receipt.abstained);
    assert!(!outcome.batch.routing.authority.grants_any());
}

#[test]
fn pre_tick_shadow_rejects_invalid_non_admitted_cue_and_stale_forget_frontier() {
    let fixture = shadow_fixture(true);
    let first = meta_spec(&fixture);
    let mut second = meta_spec(&fixture);
    second.manifest.cell_id = id("memory-cell:semantic:2");
    second.tick_input.cell_id = second.manifest.cell_id.clone();
    second.relevance_ppm = 1;
    second.tick_input.cue_digest = digest("forged-cue");

    let rejected = crate::plan_memory_meta_pre_ticks_shadow_v1(
        &meta_policy(&fixture),
        &fixture.cue,
        &fixture.snapshot,
        &[first.clone(), second.clone()],
    );
    assert!(matches!(
        rejected,
        Err(crate::MemoryMetaBatchErrorV1::Contract(
            codex_hepta_cognitive_types::hnmf::HnmfContractError::Conflict(
                "memory meta pre-tick cue or objective"
            )
        ))
    ));

    second.tick_input.cue_digest = first.tick_input.cue_digest;
    second.manifest.forget_frontier_digest = digest("stale-forget");
    second.tick_input.forget_frontier_digest = digest("stale-forget");
    let rejected = crate::plan_memory_meta_pre_ticks_shadow_v1(
        &meta_policy(&fixture),
        &fixture.cue,
        &fixture.snapshot,
        &[first, second],
    );
    assert!(matches!(
        rejected,
        Err(crate::MemoryMetaBatchErrorV1::Contract(
            codex_hepta_cognitive_types::hnmf::HnmfContractError::Conflict(
                "memory meta evidence or generation drift"
            )
        ))
    ));
}

#[test]
fn checked_pre_tick_rejects_late_ledger_denial_before_any_tick() {
    let fixture = shadow_fixture(true);
    let first = meta_spec(&fixture);
    let mut second = meta_spec(&fixture);
    second.manifest.cell_id = id("memory-cell:semantic:2");
    second.manifest.role = MemoryCellRoleV1::Semantic;
    second.tick_input.cell_id = second.manifest.cell_id.clone();
    // If this second Cell reaches a tick it fails as an unrelated retrieval
    // error. The external denial must reject the *whole* batch first.
    second.generated_input.batches.clear();
    let denied_id = second.manifest.cell_id.clone();
    let first_id = first.manifest.cell_id.clone();
    let mut checked = Vec::new();

    let rejected = crate::run_memory_meta_preselected_evidence_checked_shadow_v1(
        &meta_policy(&fixture),
        &fixture.cue,
        &fixture.policy,
        &fixture.snapshot,
        &fixture.dynamics,
        &[first, second],
        |lookup| {
            checked.push(lookup.cell_id.clone());
            lookup.cell_id != denied_id
        },
    );
    assert!(matches!(
        rejected,
        Err(crate::MemoryMetaBatchErrorV1::Contract(
            codex_hepta_cognitive_types::hnmf::HnmfContractError::Conflict(
                "memory meta external evidence rejected"
            )
        ))
    ));
    // Ranked admission order must be deterministic, and no ticks have run.
    assert_eq!(checked, vec![first_id, denied_id]);
}

#[test]
fn checked_pre_tick_binds_exact_ledger_snapshot_and_forget_frontier() {
    let fixture = shadow_fixture(true);
    let policy = meta_policy(&fixture);
    let spec = meta_spec(&fixture);
    let mut verified = 0_usize;

    let result = crate::run_memory_meta_preselected_evidence_checked_shadow_v1(
        &policy,
        &fixture.cue,
        &fixture.policy,
        &fixture.snapshot,
        &fixture.dynamics,
        &[spec.clone()],
        |lookup| {
            verified += 1;
            lookup.cell_id == spec.manifest.cell_id
                && Some(lookup.support_digest) == spec.support_digest
                && lookup.evidence_ledger_digest == policy.evidence_ledger_digest
                && lookup.snapshot_digest == policy.snapshot_digest
                && lookup.source_frontier_digest == policy.source_frontier_digest
                && lookup.forget_frontier_digest == policy.forget_frontier_digest
        },
    )
    .unwrap_or_else(|error| panic!("evidence-checked batch: {error:?}"));
    assert_eq!(verified, 1);
    assert_eq!(result.batch.cell_ticks.len(), 1);
    assert_eq!(result.batch.routing.receipt.resource_used_units, 20);
    assert!(!result.batch.routing.authority.grants_any());
    assert!(!result.pre_tick_plan.production_activation_allowed);
}

#[test]
fn checked_pre_tick_does_not_claim_unverified_deferred_support() {
    let fixture = shadow_fixture(true);
    let mut cell = meta_spec(&fixture);
    cell.support_digest = None;
    cell.generated_input.batches.clear();
    let mut verified = 0_usize;
    let result = crate::run_memory_meta_preselected_evidence_checked_shadow_v1(
        &meta_policy(&fixture),
        &fixture.cue,
        &fixture.policy,
        &fixture.snapshot,
        &fixture.dynamics,
        &[cell],
        |_| {
            verified += 1;
            true
        },
    )
    .unwrap_or_else(|error| panic!("deferred evidence-checked batch: {error:?}"));
    assert_eq!(verified, 0);
    assert!(result.pre_tick_plan.admitted_cell_ids.is_empty());
    assert_eq!(result.batch.cell_ticks.len(), 0);
    assert!(result.batch.routing.receipt.abstained);
}

#[test]
fn pre_tick_shadow_rejects_local_budget_overcommit_on_deferred_cell() {
    let fixture = shadow_fixture(true);
    let mut first = meta_spec(&fixture);
    // A first tick would fail due to empty generated input; the later
    // local-budget mismatch must surface before retrieval starts.
    first.generated_input.batches.clear();
    let mut second = meta_spec(&fixture);
    second.manifest.cell_id = id("memory-cell:semantic:2");
    second.tick_input.cell_id = second.manifest.cell_id.clone();
    second.relevance_ppm = 1;
    second.resource_cost_units = second.tick_input.resource_budget_units + 1;

    let rejected = crate::run_memory_meta_batch_shadow_v1(
        &meta_policy(&fixture),
        &fixture.cue,
        &fixture.policy,
        &fixture.snapshot,
        &fixture.dynamics,
        &[first, second],
    );
    assert!(matches!(
        rejected,
        Err(crate::MemoryMetaBatchErrorV1::Contract(
            codex_hepta_cognitive_types::hnmf::HnmfContractError::Conflict(
                "memory meta local tick budget"
            )
        ))
    ));
}
