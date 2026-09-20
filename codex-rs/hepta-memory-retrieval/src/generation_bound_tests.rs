use super::*;

use codex_hepta_cognitive_types::Citation;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf_learning::RecallAbstainReasonV1 as CanonicalRecallAbstainReasonV1;
use codex_hepta_cognitive_types::hnmf_learning::RecallResourceReceiptV1 as CanonicalRecallResourceReceiptV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::Generation;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn revision(value: u64) -> Revision {
    Revision::new(value).unwrap_or_else(|error| panic!("valid revision: {error}"))
}

fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("valid generation: {error}"))
}

fn probability(raw: u64) -> ProbabilityQ32 {
    ProbabilityQ32::from_raw(raw).unwrap_or_else(|error| panic!("valid probability: {error}"))
}

fn snapshot_key() -> CognitiveSnapshotKeyV1 {
    CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:retrieval"),
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
    .unwrap_or_else(|error| panic!("valid snapshot key: {error}"))
}

fn cue() -> MemoryCueV1 {
    MemoryCueV1 {
        cue_id: id("cue:1"),
        objective_digest: digest("objective"),
        approved_context_digest: digest("approved-context"),
        snapshot_key: snapshot_key(),
        cue_profile_digest: digest("cue-profile"),
    }
}

fn policy() -> RetrievalPolicyV1 {
    RetrievalPolicyV1 {
        policy_id: id("policy:1"),
        channel_weights: vec![
            RetrievalChannelWeightV1 {
                channel: RetrievalChannelV1::Lexical,
                weight: FixedQ32::from_raw(1_i64 << 31),
                maximum_candidates: 16,
            },
            RetrievalChannelWeightV1 {
                channel: RetrievalChannelV1::Entity,
                weight: FixedQ32::from_raw(1_i64 << 31),
                maximum_candidates: 16,
            },
            RetrievalChannelWeightV1 {
                channel: RetrievalChannelV1::ContradictionSupport,
                weight: FixedQ32::from_raw(1_i64 << 30),
                maximum_candidates: 16,
            },
        ],
        maximum_results: 8,
        minimum_total_score: FixedQ32::from_raw(1_i64 << 30),
        maximum_ood: probability(1_u64 << 30),
        minimum_distinct_channels: 2,
        abstain_on_contradiction: true,
    }
}

fn record(number: u64) -> MemoryRecord {
    MemoryRecord {
        record_id: id(&format!("memory:{number}")),
        revision: revision(1),
        kind: MemoryKind::Fact,
        content_digest: digest(&format!("content-{number}")),
        predecessor_digest: None,
        citations: vec![Citation {
            source_id: id(&format!("source:{number}")),
            source_digest: digest(&format!("source-{number}")),
        }],
        state: RecordState::Live,
    }
}

fn canonical_digest(value: &str) -> ContractDigestV1 {
    ContractDigestV1::from_digest(digest(value))
        .unwrap_or_else(|error| panic!("valid canonical digest: {error}"))
}

fn canonical_context(candidate_count: u16) -> CanonicalRecallShadowContextV1 {
    CanonicalRecallShadowContextV1 {
        event_snapshot_digest: canonical_digest("event-snapshot"),
        engram_snapshot_digest: canonical_digest("engram-snapshot"),
        active_nodes: Vec::new(),
        activation_paths: Vec::new(),
        contradictions: Vec::new(),
        coverage_ppm: 900_000,
        confidence_ppm: 800_000,
        ood_ppm: 100_000,
        resource_receipt: CanonicalRecallResourceReceiptV1 {
            candidate_event_count: candidate_count,
            node_count: 0,
            synapse_count: 0,
            active_node_count: 0,
            settling_steps: 0,
        },
    }
}

fn candidate(
    record: MemoryRecord,
    channel: RetrievalChannelV1,
    rank: u32,
) -> RetrievalChannelCandidateV1 {
    RetrievalChannelCandidateV1 {
        generation_vector_digest: cue().snapshot_key.vector_digest,
        support_digest: digest(&format!("support-{}-{channel:?}", record.record_id)),
        contradiction_group_digest: None,
        normalized_score: FixedQ32::ONE,
        ood: probability(1_u64 << 28),
        record,
        channel,
        channel_rank: rank,
    }
}

#[test]
fn channel_completion_order_cannot_change_union_or_recall() {
    let cue = cue();
    let policy = policy();
    let first = record(1);
    let second = record(2);
    let candidates = vec![
        candidate(first.clone(), RetrievalChannelV1::Lexical, 1),
        candidate(first, RetrievalChannelV1::Entity, 1),
        candidate(second.clone(), RetrievalChannelV1::Lexical, 2),
        candidate(second, RetrievalChannelV1::Entity, 2),
    ];
    let mut reversed = candidates.clone();
    reversed.reverse();

    let left = build_candidate_union(&cue, &policy, candidates.clone())
        .unwrap_or_else(|error| panic!("valid union: {error}"));
    let right = build_candidate_union(&cue, &policy, reversed.clone())
        .unwrap_or_else(|error| panic!("valid union: {error}"));
    assert_eq!(left, right);

    let left =
        recall(&cue, &policy, candidates).unwrap_or_else(|error| panic!("valid recall: {error}"));
    let right =
        recall(&cue, &policy, reversed).unwrap_or_else(|error| panic!("valid recall: {error}"));
    assert_eq!(left, right);
    assert_eq!(left.disposition, RecallDispositionV1::Recalled);
    assert_eq!(left.selections.len(), 2);
}

#[test]
fn high_risk_contradiction_forces_abstention() {
    let cue = cue();
    let policy = policy();
    let group = digest("contradiction-group");
    let mut first = candidate(record(1), RetrievalChannelV1::Lexical, 1);
    first.contradiction_group_digest = Some(group);
    let mut second = candidate(record(2), RetrievalChannelV1::Entity, 1);
    second.contradiction_group_digest = Some(group);
    let packet = recall(&cue, &policy, vec![first, second])
        .unwrap_or_else(|error| panic!("valid abstention: {error}"));
    assert_eq!(
        packet.disposition,
        RecallDispositionV1::Abstained(RecallAbstentionReasonV1::ContradictoryEvidence)
    );
    assert!(packet.selections.is_empty());
}

#[test]
fn stale_generation_candidate_is_rejected_before_ranking() {
    let cue = cue();
    let policy = policy();
    let mut stale = candidate(record(1), RetrievalChannelV1::Lexical, 1);
    stale.generation_vector_digest = digest("stale-vector");
    assert_eq!(
        recall(&cue, &policy, vec![stale]),
        Err(RecallErrorV1::GenerationVectorMismatch(
            "memory:1".to_string()
        ))
    );
}

#[test]
fn ood_and_insufficient_coverage_abstain_explicitly() {
    let cue = cue();
    let policy = policy();
    let only_one_channel = candidate(record(1), RetrievalChannelV1::Lexical, 1);
    let packet = recall(&cue, &policy, vec![only_one_channel])
        .unwrap_or_else(|error| panic!("coverage abstention: {error}"));
    assert_eq!(
        packet.disposition,
        RecallDispositionV1::Abstained(RecallAbstentionReasonV1::InsufficientChannelCoverage)
    );

    let first = candidate(record(1), RetrievalChannelV1::Lexical, 1);
    let mut second = candidate(record(2), RetrievalChannelV1::Entity, 1);
    second.ood = ProbabilityQ32::ONE;
    let packet = recall(&cue, &policy, vec![first, second])
        .unwrap_or_else(|error| panic!("ood abstention: {error}"));
    assert_eq!(
        packet.disposition,
        RecallDispositionV1::Abstained(RecallAbstentionReasonV1::OutOfDistribution)
    );
}

#[test]
fn tombstones_and_duplicate_channel_candidates_fail_closed() {
    let cue = cue();
    let policy = policy();
    let mut deleted = record(1);
    deleted.state = RecordState::Tombstone;
    assert_eq!(
        recall(
            &cue,
            &policy,
            vec![candidate(deleted, RetrievalChannelV1::Lexical, 1)]
        ),
        Err(RecallErrorV1::TombstoneCandidate("memory:1".to_string()))
    );

    let duplicate = candidate(record(2), RetrievalChannelV1::Lexical, 1);
    assert_eq!(
        recall(&cue, &policy, vec![duplicate.clone(), duplicate]),
        Err(RecallErrorV1::DuplicateChannelCandidate(
            "memory:2".to_string()
        ))
    );
}

#[test]
fn legacy_recall_projects_to_canonical_shadow_without_fabricating_authority() {
    let cue = cue();
    let policy = policy();
    let first = record(1);
    let second = record(2);
    let legacy = recall(
        &cue,
        &policy,
        vec![
            candidate(first.clone(), RetrievalChannelV1::Lexical, 1),
            candidate(first, RetrievalChannelV1::Entity, 1),
            candidate(second.clone(), RetrievalChannelV1::Lexical, 2),
            candidate(second, RetrievalChannelV1::Entity, 2),
        ],
    )
    .unwrap_or_else(|error| panic!("legacy recall: {error}"));

    let canonical = adapt_generation_bound_recall_to_canonical_shadow_v1(
        &legacy,
        canonical_context(2),
    )
    .unwrap_or_else(|error| panic!("canonical shadow projection: {error}"));

    assert_eq!(canonical.cue_digest.digest(), legacy.cue_digest);
    assert_eq!(canonical.selected_events.len(), legacy.selections.len());
    assert!(canonical.abstain.is_none());
    assert!(canonical
        .selected_events
        .windows(2)
        .all(|rows| rows[0] < rows[1]));
}

#[test]
fn legacy_abstention_maps_to_canonical_abstention_without_selected_events() {
    let cue = cue();
    let policy = policy();
    let legacy = recall(
        &cue,
        &policy,
        vec![candidate(record(1), RetrievalChannelV1::Lexical, 1)],
    )
    .unwrap_or_else(|error| panic!("legacy abstention: {error}"));

    let canonical = adapt_generation_bound_recall_to_canonical_shadow_v1(
        &legacy,
        canonical_context(1),
    )
    .unwrap_or_else(|error| panic!("canonical abstention: {error}"));

    assert_eq!(
        canonical.abstain,
        Some(CanonicalRecallAbstainReasonV1::InsufficientCoverage)
    );
    assert!(canonical.selected_events.is_empty());
}

#[test]
fn canonical_shadow_receipt_cannot_undercount_legacy_selection() {
    let cue = cue();
    let policy = policy();
    let first = record(1);
    let second = record(2);
    let legacy = recall(
        &cue,
        &policy,
        vec![
            candidate(first.clone(), RetrievalChannelV1::Lexical, 1),
            candidate(first, RetrievalChannelV1::Entity, 1),
            candidate(second.clone(), RetrievalChannelV1::Lexical, 2),
            candidate(second, RetrievalChannelV1::Entity, 2),
        ],
    )
    .unwrap_or_else(|error| panic!("legacy recall: {error}"));

    assert_eq!(
        adapt_generation_bound_recall_to_canonical_shadow_v1(
            &legacy,
            canonical_context(1),
        ),
        Err(RecallErrorV1::CanonicalAdapter(
            "candidate receipt undercounts legacy selected plus omitted events"
        ))
    );
}

