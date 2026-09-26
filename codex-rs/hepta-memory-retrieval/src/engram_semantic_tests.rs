use super::*;

use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::Generation;

use crate::RetrievalChannelV1;
use crate::RetrievalChannelWeightV1;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn revision(value: u64) -> Revision {
    Revision::new(value).expect("revision")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

fn snapshot_key() -> CognitiveSnapshotKeyV1 {
    CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:engram-semantics"),
        purpose_id: id("purpose:recall"),
        memory_ledger_frontier: 12,
        knowledge_fact_frontier: 9,
        tombstone_frontier: 4,
        source_ledger_frontier: 13,
        knowledge_graph_generation: generation(3),
        compact_checkpoint_generation: generation(2),
        prompt_registry_revision: revision(4),
        retrieval_profile_digest: digest("retrieval-profile"),
        encoder_preprocessor_digest: digest("encoder-profile"),
        authority_epoch: 6,
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
    })
    .expect("snapshot key")
}

fn cue() -> MemoryCueV1 {
    MemoryCueV1 {
        cue_id: id("cue:engram-semantics"),
        objective_digest: digest("objective"),
        approved_context_digest: digest("approved-context"),
        request_digest: digest("request"),
        snapshot_key: snapshot_key(),
        cue_profile_digest: digest("cue-profile"),
    }
}

fn record(number: u64) -> MemoryRecord {
    MemoryRecord {
        record_id: id(&format!("memory:{number}")),
        revision: revision(1),
        kind: MemoryKind::Fact,
        content_digest: digest(&format!("content:{number}")),
        predecessor_digest: None,
        citations: Vec::new(),
        state: RecordState::Live,
    }
}

fn candidate(
    number: u64,
    channel: RetrievalChannelV1,
    score: FixedQ32,
    ood: ProbabilityQ32,
    proposition: Option<Digest32>,
) -> RetrievalChannelCandidateV1 {
    RetrievalChannelCandidateV1 {
        record: record(number),
        channel,
        channel_rank: 1,
        normalized_score: score,
        ood,
        support_digest: digest(&format!("support:{number}:{channel:?}")),
        contradiction_group_digest: proposition,
        generation_vector_digest: cue().snapshot_key.vector_digest,
    }
}

fn retrieval_policy(rows: Vec<(RetrievalChannelV1, FixedQ32)>) -> RetrievalPolicyV1 {
    RetrievalPolicyV1 {
        policy_id: id("policy:engram-semantics"),
        channel_weights: rows
            .into_iter()
            .map(|(channel, weight)| RetrievalChannelWeightV1 {
                channel,
                weight,
                maximum_candidates: 16,
            })
            .collect(),
        maximum_results: 8,
        minimum_total_score: FixedQ32::ZERO,
        maximum_ood: ProbabilityQ32::ONE,
        minimum_distinct_channels: 1,
        abstain_on_contradiction: true,
    }
}

fn support(number: u64) -> EngramSupportV1 {
    EngramSupportV1 {
        record_id: id(&format!("memory:{number}")),
        record_revision: revision(1),
    }
}

fn node(
    name: &str,
    number: u64,
    confidence: ProbabilityQ32,
) -> EngramNodeV1 {
    EngramNodeV1 {
        node_id: id(name),
        population: EngramPopulationV1::SemanticConcept,
        support: vec![support(number)],
        threshold: FixedQ32::ZERO,
        confidence,
        generation_vector_digest: cue().snapshot_key.vector_digest,
    }
}

fn synapse(
    source: &str,
    target: &str,
    relation: SynapseRelationV1,
    weight: FixedQ32,
) -> SynapseV1 {
    SynapseV1 {
        source_node_id: id(source),
        target_node_id: id(target),
        relation,
        weight,
        support_digest: digest(&format!("edge:{source}:{target}:{relation:?}")),
        generation_vector_digest: cue().snapshot_key.vector_digest,
    }
}

#[test]
fn zero_minimum_activation_is_rejected() {
    let mut policy = EngramDynamicsPolicyV1::product_default().expect("policy");
    policy.minimum_activation = FixedQ32::ZERO;
    assert_eq!(
        policy.validate(),
        Err(EngramErrorV1::ScoreOutOfRange("minimum_activation"))
    );
}

#[test]
fn zero_activation_never_creates_active_support() {
    let cue = cue();
    let policy = retrieval_policy(vec![(RetrievalChannelV1::Lexical, FixedQ32::ONE)]);
    let union = build_candidate_union(
        &cue,
        &policy,
        vec![candidate(
            1,
            RetrievalChannelV1::Lexical,
            FixedQ32::ZERO,
            ProbabilityQ32::ZERO,
            None,
        )],
    )
    .expect("union");
    let snapshot = EngramSnapshotV1::new(
        cue.snapshot_key.vector_digest,
        digest("engram:zero-activation"),
        vec![node("node:zero", 1, ProbabilityQ32::ONE)],
        Vec::new(),
    )
    .expect("snapshot");
    let dynamics = EngramDynamicsPolicyV1::product_default().expect("dynamics");
    let receipt = settle_engram(&cue, &union, &snapshot, &dynamics).expect("settle");
    assert!(receipt.active_nodes.is_empty());
    assert!(receipt.selected_support.is_empty());
    assert_eq!(receipt.resources.active_nodes, 0);
    assert_eq!(receipt.confidence, ProbabilityQ32::ZERO);
}

#[test]
fn zero_weight_contradiction_edge_is_semantically_inert() {
    let cue = cue();
    let policy = retrieval_policy(vec![(RetrievalChannelV1::Lexical, FixedQ32::ONE)]);
    let candidates = vec![
        candidate(
            1,
            RetrievalChannelV1::Lexical,
            FixedQ32::ONE,
            ProbabilityQ32::ZERO,
            None,
        ),
        candidate(
            2,
            RetrievalChannelV1::Lexical,
            FixedQ32::from_raw(3_i64 << 30),
            ProbabilityQ32::ZERO,
            None,
        ),
    ];
    let snapshot = EngramSnapshotV1::new(
        cue.snapshot_key.vector_digest,
        digest("engram:zero-weight-contradiction"),
        vec![
            node("node:left", 1, ProbabilityQ32::ONE),
            node("node:right", 2, ProbabilityQ32::ONE),
        ],
        vec![synapse(
            "node:left",
            "node:right",
            SynapseRelationV1::Contradicts,
            FixedQ32::ZERO,
        )],
    )
    .expect("snapshot");
    let mut dynamics = EngramDynamicsPolicyV1::product_default().expect("dynamics");
    dynamics.maximum_settling_steps = 1;
    dynamics.maximum_graph_hops = 0;
    dynamics.leak = FixedQ32::ZERO;
    dynamics.lateral_inhibition = FixedQ32::ZERO;
    let packet = recall_with_engram(&cue, &policy, candidates, &snapshot, &dynamics)
        .expect("recall");
    assert_eq!(packet.disposition, RecallDispositionV1::Recalled);
    assert_eq!(packet.selections.len(), 2);
    let receipt = packet.engram.expect("engram");
    assert!(receipt.contradictions.is_empty());
    assert!(receipt.activation_paths.is_empty());
    assert_eq!(receipt.resources.traversed_synapses, 0);
}

#[test]
fn confidence_is_activation_weighted() {
    let cue = cue();
    let policy = retrieval_policy(vec![(RetrievalChannelV1::Lexical, FixedQ32::ONE)]);
    let union = build_candidate_union(
        &cue,
        &policy,
        vec![
            candidate(
                1,
                RetrievalChannelV1::Lexical,
                FixedQ32::ONE,
                ProbabilityQ32::ZERO,
                None,
            ),
            candidate(
                2,
                RetrievalChannelV1::Lexical,
                FixedQ32::from_raw(1_i64 << 30),
                ProbabilityQ32::ZERO,
                None,
            ),
        ],
    )
    .expect("union");
    let snapshot = EngramSnapshotV1::new(
        cue.snapshot_key.vector_digest,
        digest("engram:weighted-confidence"),
        vec![
            node("node:strong", 1, ProbabilityQ32::ONE),
            node("node:weak", 2, ProbabilityQ32::ZERO),
        ],
        Vec::new(),
    )
    .expect("snapshot");
    let mut dynamics = EngramDynamicsPolicyV1::product_default().expect("dynamics");
    dynamics.maximum_settling_steps = 1;
    dynamics.maximum_graph_hops = 0;
    dynamics.leak = FixedQ32::ZERO;
    dynamics.lateral_inhibition = FixedQ32::ZERO;
    let receipt = settle_engram(&cue, &union, &snapshot, &dynamics).expect("settle");
    assert_eq!(receipt.active_nodes.len(), 2);
    let expected_raw = (u128::from(ProbabilityQ32::ONE.raw()) * 4 / 5) as u64;
    let expected = ProbabilityQ32::from_raw(expected_raw).expect("weighted probability");
    assert_eq!(receipt.confidence, expected);
    assert_ne!(
        receipt.confidence,
        ProbabilityQ32::from_raw(ProbabilityQ32::ONE.raw() / 2).expect("simple average")
    );
}

#[test]
fn rejected_ood_and_opposing_candidate_never_enters_hnmf_receipt() {
    let cue = cue();
    let proposition = digest("proposition:hnmf-admission");
    let mut policy = retrieval_policy(vec![
        (RetrievalChannelV1::Lexical, FixedQ32::ONE),
        (
            RetrievalChannelV1::ContradictionSupport,
            FixedQ32::ONE,
        ),
    ]);
    policy.minimum_total_score = FixedQ32::from_raw(1_i64 << 31);
    policy.maximum_ood = ProbabilityQ32::from_raw(1_u64 << 30).expect("probability");
    let candidates = vec![
        candidate(
            1,
            RetrievalChannelV1::Lexical,
            FixedQ32::ONE,
            ProbabilityQ32::ZERO,
            Some(proposition),
        ),
        candidate(
            2,
            RetrievalChannelV1::ContradictionSupport,
            FixedQ32::from_raw(1),
            ProbabilityQ32::ONE,
            Some(proposition),
        ),
    ];
    let snapshot = EngramSnapshotV1::new(
        cue.snapshot_key.vector_digest,
        digest("engram:admission"),
        vec![
            node("node:admitted", 1, ProbabilityQ32::ONE),
            node("node:rejected", 2, ProbabilityQ32::ONE),
        ],
        Vec::new(),
    )
    .expect("snapshot");
    let mut dynamics = EngramDynamicsPolicyV1::product_default().expect("dynamics");
    dynamics.maximum_settling_steps = 1;
    dynamics.maximum_graph_hops = 0;
    dynamics.leak = FixedQ32::ZERO;
    dynamics.lateral_inhibition = FixedQ32::ZERO;
    let packet = recall_with_engram(&cue, &policy, candidates, &snapshot, &dynamics)
        .expect("recall");
    assert_eq!(packet.disposition, RecallDispositionV1::Recalled);
    assert_eq!(packet.selections.len(), 1);
    assert_eq!(packet.selections[0].record_id, id("memory:1"));
    assert_eq!(packet.omitted_count, 0);
    let receipt = packet.engram.expect("engram");
    assert_eq!(receipt.resources.candidate_records, 1);
    assert_eq!(receipt.selected_support, vec![support(1)]);
    assert!(receipt.contradictions.is_empty());
    assert!(
        receipt
            .active_nodes
            .iter()
            .all(|node| node.node_id != id("node:rejected"))
    );
}
