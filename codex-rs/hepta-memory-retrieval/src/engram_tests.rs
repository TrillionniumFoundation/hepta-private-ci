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

fn snapshot_key() -> CognitiveSnapshotKeyV1 {
    CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:engram"),
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
    .expect("snapshot key")
}

fn cue() -> MemoryCueV1 {
    MemoryCueV1 {
        cue_id: id("cue:engram"),
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

fn candidate(number: u64, score_raw: i64) -> RetrievalChannelCandidateV1 {
    RetrievalChannelCandidateV1 {
        record: record(number),
        channel: RetrievalChannelV1::Lexical,
        channel_rank: u32::try_from(number).unwrap_or(u32::MAX),
        normalized_score: FixedQ32::from_raw(score_raw),
        ood: ProbabilityQ32::ZERO,
        support_digest: digest(&format!("support:{number}")),
        contradiction_group_digest: None,
        generation_vector_digest: cue().snapshot_key.vector_digest,
    }
}

fn retrieval_policy(maximum_results: u32) -> RetrievalPolicyV1 {
    RetrievalPolicyV1 {
        policy_id: id("policy:retrieval"),
        channel_weights: vec![RetrievalChannelWeightV1 {
            channel: RetrievalChannelV1::Lexical,
            weight: FixedQ32::ONE,
            maximum_candidates: 512,
        }],
        maximum_results,
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
    population: EngramPopulationV1,
    support: Vec<EngramSupportV1>,
    threshold: FixedQ32,
) -> EngramNodeV1 {
    EngramNodeV1 {
        node_id: id(name),
        population,
        support,
        threshold,
        confidence: ProbabilityQ32::ONE,
        generation_vector_digest: cue().snapshot_key.vector_digest,
    }
}

fn synapse(source: &str, target: &str, relation: SynapseRelationV1, weight: FixedQ32) -> SynapseV1 {
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
fn recurrent_association_changes_final_selection_order() {
    let cue = cue();
    let retrieval_policy = retrieval_policy(2);
    let high = candidate(1, 3_i64 << 30);
    let low = candidate(2, 1_i64 << 28);
    let plain = crate::recall(&cue, &retrieval_policy, vec![high.clone(), low.clone()])
        .expect("plain recall");
    assert_eq!(plain.selections[0].record_id, id("memory:1"));

    let snapshot = EngramSnapshotV1::new(
        cue.snapshot_key.vector_digest,
        digest("engram-generation"),
        vec![
            node(
                "node:1",
                EngramPopulationV1::SemanticConcept,
                vec![support(1)],
                FixedQ32::from_raw(11_i64 << 28),
            ),
            node(
                "node:2",
                EngramPopulationV1::EpisodicBinding,
                vec![support(2)],
                FixedQ32::ZERO,
            ),
        ],
        vec![synapse(
            "node:1",
            "node:2",
            SynapseRelationV1::Associative,
            FixedQ32::ONE,
        )],
    )
    .expect("engram snapshot");
    let mut dynamics = EngramDynamicsPolicyV1::product_default().expect("policy");
    dynamics.leak = FixedQ32::ZERO;
    dynamics.lateral_inhibition = FixedQ32::ZERO;

    let packet = recall_with_engram(
        &cue,
        &retrieval_policy,
        vec![high, low],
        &snapshot,
        &dynamics,
    )
    .expect("engram recall");
    assert_eq!(packet.disposition, RecallDispositionV1::Recalled);
    assert_eq!(packet.selections.len(), 2);
    assert_eq!(packet.selections[0].record_id, id("memory:2"));
    let engram = packet.engram.as_ref().expect("engram receipt");
    assert_eq!(engram.settling_steps, dynamics.maximum_settling_steps);
    assert!(!engram.activation_paths.is_empty());
    assert!(engram.resources.traversed_synapses > 0);
}

#[test]
fn ret04_ablation_baselines_are_independent_and_resource_bounded() {
    let cue = cue();
    let retrieval_policy = retrieval_policy(2);
    let candidates = vec![
        candidate(1, FixedQ32::ONE.raw()),
        candidate(2, FixedQ32::ONE.raw()),
    ];
    let nodes = vec![
        node(
            "node:1",
            EngramPopulationV1::SemanticConcept,
            vec![support(1)],
            FixedQ32::ZERO,
        ),
        node(
            "node:2",
            EngramPopulationV1::SemanticConcept,
            vec![support(2)],
            FixedQ32::ZERO,
        ),
    ];

    let no_intervention =
        crate::recall(&cue, &retrieval_policy, candidates.clone()).expect("plain recall");
    assert_eq!(no_intervention.engram, None);

    let no_recurrence_snapshot = EngramSnapshotV1::new(
        cue.snapshot_key.vector_digest,
        digest("engram-no-recurrence"),
        nodes.clone(),
        Vec::new(),
    )
    .expect("no recurrence snapshot");
    let mut no_recurrence = EngramDynamicsPolicyV1::product_default().expect("policy");
    no_recurrence.policy_id = id("policy:hnmf-no-recurrence");
    no_recurrence.maximum_settling_steps = 1;
    no_recurrence.maximum_graph_hops = 0;
    no_recurrence.leak = FixedQ32::ZERO;
    no_recurrence.lateral_inhibition = FixedQ32::ZERO;
    let no_recurrence_packet = recall_with_engram(
        &cue,
        &retrieval_policy,
        candidates.clone(),
        &no_recurrence_snapshot,
        &no_recurrence,
    )
    .expect("no recurrence recall");
    let no_recurrence_receipt = no_recurrence_packet.engram.as_ref().expect("engram");
    assert_eq!(no_recurrence_receipt.resources.traversed_synapses, 0);
    assert_eq!(no_recurrence_receipt.resources.settling_steps, 1);

    let inhibition_snapshot = EngramSnapshotV1::new(
        cue.snapshot_key.vector_digest,
        digest("engram-inhibition-ablation"),
        nodes,
        Vec::new(),
    )
    .expect("inhibition snapshot");
    let mut with_inhibition = EngramDynamicsPolicyV1::product_default().expect("policy");
    with_inhibition.policy_id = id("policy:hnmf-with-inhibition");
    with_inhibition.maximum_settling_steps = 1;
    with_inhibition.maximum_graph_hops = 0;
    with_inhibition.leak = FixedQ32::ZERO;
    let mut without_inhibition = with_inhibition.clone();
    without_inhibition.policy_id = id("policy:hnmf-no-inhibition");
    without_inhibition.lateral_inhibition = FixedQ32::ZERO;

    let inhibited = recall_with_engram(
        &cue,
        &retrieval_policy,
        candidates.clone(),
        &inhibition_snapshot,
        &with_inhibition,
    )
    .expect("inhibited recall");
    let uninhibited = recall_with_engram(
        &cue,
        &retrieval_policy,
        candidates,
        &inhibition_snapshot,
        &without_inhibition,
    )
    .expect("uninhibited recall");
    let inhibited_receipt = inhibited.engram.as_ref().expect("inhibited engram");
    let uninhibited_receipt = uninhibited.engram.as_ref().expect("uninhibited engram");
    assert_ne!(
        inhibited_receipt.dynamics_policy_digest,
        uninhibited_receipt.dynamics_policy_digest
    );
    assert_ne!(
        inhibited_receipt.receipt_digest,
        uninhibited_receipt.receipt_digest
    );
    assert!(
        inhibited_receipt.active_nodes[1].activation
            < uninhibited_receipt.active_nodes[1].activation
    );
}

#[test]
fn population_competition_never_exceeds_declared_active_bound() {
    let cue = cue();
    let candidates = (1..=80)
        .map(|number| candidate(number, FixedQ32::ONE.raw()))
        .collect::<Vec<_>>();
    let nodes = (1..=80)
        .map(|number| {
            node(
                &format!("node:{number:03}"),
                EngramPopulationV1::SemanticConcept,
                vec![support(number)],
                FixedQ32::ZERO,
            )
        })
        .collect::<Vec<_>>();
    let snapshot = EngramSnapshotV1::new(
        cue.snapshot_key.vector_digest,
        digest("engram-generation"),
        nodes,
        Vec::new(),
    )
    .expect("snapshot");
    let mut dynamics = EngramDynamicsPolicyV1::product_default().expect("policy");
    dynamics.maximum_active_per_population = 8;
    dynamics.maximum_active_nodes = 8;
    dynamics.lateral_inhibition = FixedQ32::ZERO;

    let union = build_candidate_union(&cue, &retrieval_policy(16), candidates).expect("union");
    let receipt = settle_engram(&cue, &union, &snapshot, &dynamics).expect("settle");
    assert_eq!(receipt.active_nodes.len(), 8);
    assert_eq!(receipt.resources.active_nodes, 8);
    assert!(receipt.resources.expanded_nodes >= 8);
}

#[test]
fn active_contradiction_forces_abstention() {
    let cue = cue();
    let candidates = vec![
        candidate(1, FixedQ32::ONE.raw()),
        candidate(2, FixedQ32::ONE.raw()),
    ];
    let snapshot = EngramSnapshotV1::new(
        cue.snapshot_key.vector_digest,
        digest("engram-generation"),
        vec![
            node(
                "node:left",
                EngramPopulationV1::SemanticConcept,
                vec![support(1)],
                FixedQ32::ZERO,
            ),
            node(
                "node:right",
                EngramPopulationV1::SemanticConcept,
                vec![support(2)],
                FixedQ32::ZERO,
            ),
        ],
        vec![synapse(
            "node:left",
            "node:right",
            SynapseRelationV1::Contradicts,
            FixedQ32::ONE,
        )],
    )
    .expect("snapshot");
    let mut dynamics = EngramDynamicsPolicyV1::product_default().expect("policy");
    dynamics.lateral_inhibition = FixedQ32::ZERO;
    let packet = recall_with_engram(&cue, &retrieval_policy(2), candidates, &snapshot, &dynamics)
        .expect("recall");
    assert_eq!(
        packet.disposition,
        RecallDispositionV1::Abstained(RecallAbstentionReasonV1::ContradictoryEvidence)
    );
    assert!(packet.selections.is_empty());
    assert!(
        !packet
            .engram
            .as_ref()
            .expect("engram")
            .contradictions
            .is_empty()
    );
}

#[test]
fn engram_snapshot_and_receipt_tampering_fail_closed() {
    let cue = cue();
    let mut snapshot = EngramSnapshotV1::new(
        cue.snapshot_key.vector_digest,
        digest("engram-generation"),
        vec![node(
            "node:1",
            EngramPopulationV1::SemanticConcept,
            vec![support(1)],
            FixedQ32::ZERO,
        )],
        Vec::new(),
    )
    .expect("snapshot");
    snapshot.nodes[0].threshold = FixedQ32::ONE;
    assert_eq!(
        snapshot.validate(),
        Err(EngramErrorV1::DigestMismatch("engram_snapshot"))
    );

    let snapshot = EngramSnapshotV1::new(
        cue.snapshot_key.vector_digest,
        digest("engram-generation"),
        vec![node(
            "node:1",
            EngramPopulationV1::SemanticConcept,
            vec![support(1)],
            FixedQ32::ZERO,
        )],
        Vec::new(),
    )
    .expect("snapshot");
    let union = build_candidate_union(
        &cue,
        &retrieval_policy(1),
        vec![candidate(1, FixedQ32::ONE.raw())],
    )
    .expect("union");
    let policy = EngramDynamicsPolicyV1::product_default().expect("policy");
    let mut receipt = settle_engram(&cue, &union, &snapshot, &policy).expect("receipt");
    receipt.coverage = ProbabilityQ32::ZERO;
    assert_eq!(
        receipt.validate(),
        Err(EngramErrorV1::DigestMismatch("engram_recall"))
    );
}

#[test]
fn recomputed_structural_receipt_forgery_fails_closed() {
    let cue = cue();
    let snapshot = EngramSnapshotV1::new(
        cue.snapshot_key.vector_digest,
        digest("engram-generation"),
        vec![node(
            "node:1",
            EngramPopulationV1::SemanticConcept,
            vec![support(1)],
            FixedQ32::ZERO,
        )],
        Vec::new(),
    )
    .expect("snapshot");
    let union = build_candidate_union(
        &cue,
        &retrieval_policy(1),
        vec![candidate(1, FixedQ32::ONE.raw())],
    )
    .expect("union");
    let policy = EngramDynamicsPolicyV1::product_default().expect("policy");

    let mut missing_support = settle_engram(&cue, &union, &snapshot, &policy).expect("receipt");
    missing_support.active_nodes[0].support.clear();
    missing_support.receipt_digest = missing_support.compute_receipt_digest();
    assert!(matches!(
        missing_support.validate(),
        Err(EngramErrorV1::EmptySupport(_))
    ));

    let mut mismatched_resources =
        settle_engram(&cue, &union, &snapshot, &policy).expect("receipt");
    mismatched_resources.resources.active_nodes = mismatched_resources
        .resources
        .active_nodes
        .saturating_add(1);
    mismatched_resources.resources.receipt_digest = mismatched_resources.resources.compute_digest();
    mismatched_resources.receipt_digest = mismatched_resources.compute_receipt_digest();
    assert_eq!(
        mismatched_resources.validate(),
        Err(EngramErrorV1::NonCanonical("engram_resources"))
    );

    let mut wrong_coverage = settle_engram(&cue, &union, &snapshot, &policy).expect("receipt");
    wrong_coverage.coverage = ProbabilityQ32::ZERO;
    wrong_coverage.receipt_digest = wrong_coverage.compute_receipt_digest();
    assert_eq!(
        wrong_coverage.validate(),
        Err(EngramErrorV1::NonCanonical("engram_coverage"))
    );
}

#[test]
fn engram_product_hard_limits_are_enforced() {
    let mut policy = EngramDynamicsPolicyV1::product_default().expect("default");
    policy.maximum_settling_steps = 5;
    assert_eq!(
        policy.validate(),
        Err(EngramErrorV1::SettlingStepLimitExceeded)
    );
    let mut policy = EngramDynamicsPolicyV1::product_default().expect("default");
    policy.maximum_active_per_population = 65;
    assert_eq!(
        policy.validate(),
        Err(EngramErrorV1::ActivePopulationLimitExceeded)
    );
}

#[test]
#[ignore = "target-host qualification probe; run explicitly with --ignored --nocapture"]
fn target_host_hnmf_reports_latency_percentiles_at_candidate_ceiling() {
    fn percentile(values: &[u128], numerator: usize, denominator: usize) -> u128 {
        assert!(!values.is_empty());
        let rank = values
            .len()
            .saturating_mul(numerator)
            .saturating_add(denominator.saturating_sub(1))
            / denominator;
        values[rank.saturating_sub(1).min(values.len() - 1)]
    }

    let cue = cue();
    let candidates = (1..=512_u64)
        .map(|number| candidate(number, FixedQ32::ONE.raw()))
        .collect::<Vec<_>>();
    let nodes = (1..=512_u64)
        .map(|number| {
            node(
                &format!("qualification-node:{number:04}"),
                EngramPopulationV1::SemanticConcept,
                vec![support(number)],
                FixedQ32::ZERO,
            )
        })
        .collect::<Vec<_>>();
    let synapses = (1..512_u64)
        .map(|number| {
            synapse(
                &format!("qualification-node:{number:04}"),
                &format!("qualification-node:{:04}", number + 1),
                SynapseRelationV1::Associative,
                FixedQ32::from_raw(1_i64 << 28),
            )
        })
        .collect::<Vec<_>>();
    let snapshot = EngramSnapshotV1::new(
        cue.snapshot_key.vector_digest,
        digest("qualification-engram-generation"),
        nodes,
        synapses,
    )
    .expect("qualification snapshot");
    let policy = retrieval_policy(16);
    let dynamics = EngramDynamicsPolicyV1::product_default().expect("dynamics");

    let mut micros = Vec::with_capacity(100);
    let mut last_resources = None;
    for _ in 0..100 {
        let started = std::time::Instant::now();
        let packet = recall_with_engram(&cue, &policy, candidates.clone(), &snapshot, &dynamics)
            .expect("HNMF recall");
        micros.push(started.elapsed().as_micros());
        assert!(packet.selections.len() <= 16);
        last_resources = packet.engram.map(|receipt| receipt.resources);
    }
    micros.sort_unstable();
    let resources = last_resources.expect("resource receipt");
    eprintln!(
        "{{\"schema\":\"hepta.memory-retrieval.target-host.v1\",\"phase\":\"hnmf\",\"candidate_events\":512,\"iterations\":100,\"p50_us\":{},\"p95_us\":{},\"p99_us\":{},\"expanded_nodes\":{},\"traversed_synapses\":{},\"active_nodes\":{},\"settling_steps\":{}}}",
        percentile(&micros, 50, 100),
        percentile(&micros, 95, 100),
        percentile(&micros, 99, 100),
        resources.expanded_nodes,
        resources.traversed_synapses,
        resources.active_nodes,
        resources.settling_steps,
    );
}


#[test]
#[ignore = "target-host structural-ceiling probe; run explicitly with --ignored --nocapture"]
fn target_host_hnmf_validates_full_structural_ceiling() {
    let cue = cue();
    let nodes = (1..=4096_u64)
        .map(|number| {
            node(
                &format!("ceiling-node:{number:04}"),
                EngramPopulationV1::SemanticConcept,
                vec![support(((number - 1) % 512) + 1)],
                FixedQ32::ZERO,
            )
        })
        .collect::<Vec<_>>();
    let mut synapses = Vec::with_capacity(32_768);
    for source in 1..=4096_u64 {
        for offset in 1..=8_u64 {
            let target = ((source - 1 + offset) % 4096) + 1;
            synapses.push(synapse(
                &format!("ceiling-node:{source:04}"),
                &format!("ceiling-node:{target:04}"),
                SynapseRelationV1::Associative,
                FixedQ32::from_raw(1_i64 << 20),
            ));
        }
    }
    assert_eq!(nodes.len(), MAX_ENGRAM_NODES);
    assert_eq!(synapses.len(), MAX_ENGRAM_SYNAPSES);

    let build_started = std::time::Instant::now();
    let snapshot = EngramSnapshotV1::new(
        cue.snapshot_key.vector_digest,
        digest("qualification-full-structural-ceiling"),
        nodes,
        synapses,
    )
    .expect("full structural-ceiling snapshot");
    let build_us = build_started.elapsed().as_micros();

    let validate_started = std::time::Instant::now();
    snapshot.validate().expect("structural ceiling validates");
    let validate_us = validate_started.elapsed().as_micros();

    eprintln!(
        "{{\"schema\":\"hepta.memory-retrieval.target-host.v1\",\"phase\":\"hnmf-structural-ceiling\",\"nodes\":4096,\"synapses\":32768,\"build_us\":{},\"validate_us\":{}}}",
        build_us,
        validate_us,
    );
}
