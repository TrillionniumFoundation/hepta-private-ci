use super::*;

use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn q(numerator: i64, denominator: i64) -> FixedQ32 {
    FixedQ32::from_raw((numerator * (1_i64 << 32)) / denominator)
}

fn cue() -> MemoryCueV1 {
    let snapshot = CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:hnmf"),
        purpose_id: id("purpose:recall"),
        memory_ledger_frontier: 4,
        knowledge_fact_frontier: 3,
        tombstone_frontier: 1,
        source_ledger_frontier: 4,
        knowledge_graph_generation: Generation::new(2).unwrap(),
        compact_checkpoint_generation: Generation::new(1).unwrap(),
        prompt_registry_revision: Revision::new(1).unwrap(),
        retrieval_profile_digest: digest("retrieval"),
        encoder_preprocessor_digest: digest("encoder"),
        authority_epoch: 1,
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tools"),
    })
    .unwrap();
    crate::compile_cue(
        id("cue:hnmf"),
        digest("objective"),
        digest("context"),
        snapshot,
        digest("cue-profile"),
    )
    .unwrap()
}

fn policy(maximum_results: u32) -> RetrievalPolicyV1 {
    RetrievalPolicyV1 {
        policy_id: id("policy:hnmf"),
        channel_weights: vec![crate::RetrievalChannelWeightV1 {
            channel: crate::RetrievalChannelV1::Lexical,
            weight: FixedQ32::ONE,
            maximum_candidates: 16,
        }],
        maximum_results,
        minimum_total_score: FixedQ32::ZERO,
        maximum_ood: ProbabilityQ32::ONE,
        minimum_distinct_channels: 1,
        abstain_on_contradiction: true,
    }
}

fn candidate(
    cue: &MemoryCueV1,
    name: &str,
    score: FixedQ32,
) -> RetrievalChannelCandidateV1 {
    RetrievalChannelCandidateV1 {
        record: MemoryRecord {
            record_id: id(name),
            revision: Revision::new(1).unwrap(),
            kind: MemoryKind::Fact,
            content_digest: digest(name),
            predecessor_digest: None,
            citations: Vec::new(),
            state: RecordState::Live,
        },
        channel: crate::RetrievalChannelV1::Lexical,
        channel_rank: 1,
        normalized_score: score,
        ood: ProbabilityQ32::ZERO,
        support_digest: digest(&format!("support:{name}")),
        contradiction_group_digest: None,
        generation_vector_digest: cue.snapshot_key.vector_digest,
    }
}

#[test]
fn recurrent_association_can_promote_a_non_top_base_candidate() {
    let cue = cue();
    let first = candidate(&cue, "memory:a", q(7, 10));
    let second = candidate(&cue, "memory:b", q(4, 10));
    let engram = EngramSnapshotV1 {
        generation_vector_digest: cue.snapshot_key.vector_digest,
        nodes: vec![
            EngramNodeV1 {
                record_id: id("memory:a"),
                population_id: id("population:a"),
                cue_bias: FixedQ32::ZERO,
                threshold: FixedQ32::ZERO,
            },
            EngramNodeV1 {
                record_id: id("memory:b"),
                population_id: id("population:b"),
                cue_bias: FixedQ32::ZERO,
                threshold: FixedQ32::ZERO,
            },
        ],
        synapses: vec![EngramSynapseV1 {
            from_record_id: id("memory:a"),
            to_record_id: id("memory:b"),
            weight: FixedQ32::ONE,
            inhibitory: false,
        }],
    };
    let receipt = recall_with_engram(
        &cue,
        &policy(2),
        vec![first, second],
        &engram,
        &RecallDynamicsV1 {
            recurrent_steps: 1,
            maximum_active_units_per_population: 2,
            leak: FixedQ32::ZERO,
            inhibition_enabled: true,
        },
    )
    .unwrap();
    assert_eq!(receipt.packet.disposition, RecallDispositionV1::Recalled);
    assert_eq!(receipt.packet.selections[0].record_id, id("memory:b"));
    assert!(
        receipt.packet.selections[0].weighted_score
            > receipt.packet.selections[1].weighted_score
    );
    receipt.validate().unwrap();
}

#[test]
fn sparse_population_competition_zeroes_units_beyond_bound() {
    let cue = cue();
    let engram = EngramSnapshotV1 {
        generation_vector_digest: cue.snapshot_key.vector_digest,
        nodes: vec![
            EngramNodeV1 {
                record_id: id("memory:a"),
                population_id: id("population:shared"),
                cue_bias: FixedQ32::ZERO,
                threshold: FixedQ32::ZERO,
            },
            EngramNodeV1 {
                record_id: id("memory:b"),
                population_id: id("population:shared"),
                cue_bias: FixedQ32::ZERO,
                threshold: FixedQ32::ZERO,
            },
        ],
        synapses: Vec::new(),
    };
    let receipt = recall_with_engram(
        &cue,
        &policy(2),
        vec![
            candidate(&cue, "memory:a", q(8, 10)),
            candidate(&cue, "memory:b", q(7, 10)),
        ],
        &engram,
        &RecallDynamicsV1 {
            recurrent_steps: 1,
            maximum_active_units_per_population: 1,
            leak: FixedQ32::ZERO,
            inhibition_enabled: true,
        },
    )
    .unwrap();
    assert_eq!(receipt.packet.selections.len(), 1);
    assert_eq!(receipt.packet.selections[0].record_id, id("memory:a"));
    assert_eq!(
        receipt
            .final_activations
            .iter()
            .find(|row| row.record_id == id("memory:b"))
            .unwrap()
            .final_activation,
        FixedQ32::ZERO
    );
}

#[test]
fn stale_engram_generation_and_oversized_dynamics_fail_closed() {
    let cue = cue();
    let mut engram = EngramSnapshotV1 {
        generation_vector_digest: digest("stale"),
        nodes: vec![EngramNodeV1 {
            record_id: id("memory:a"),
            population_id: id("population:a"),
            cue_bias: FixedQ32::ZERO,
            threshold: FixedQ32::ZERO,
        }],
        synapses: Vec::new(),
    };
    let candidate = candidate(&cue, "memory:a", FixedQ32::ONE);
    assert_eq!(
        recall_with_engram(
            &cue,
            &policy(1),
            vec![candidate.clone()],
            &engram,
            &RecallDynamicsV1 {
                recurrent_steps: 1,
                maximum_active_units_per_population: 1,
                leak: FixedQ32::ZERO,
            },
        ),
        Err(HnmfRecallErrorV1::GenerationVectorMismatch)
    );
    engram.generation_vector_digest = cue.snapshot_key.vector_digest;
    assert_eq!(
        recall_with_engram(
            &cue,
            &policy(1),
            vec![candidate],
            &engram,
            &RecallDynamicsV1 {
                recurrent_steps: MAX_RECURRENT_STEPS + 1,
                maximum_active_units_per_population: 1,
                leak: FixedQ32::ZERO,
            },
        ),
        Err(HnmfRecallErrorV1::InvalidRecurrentSteps)
    );
}


#[test]
fn no_recurrence_and_no_inhibition_are_explicit_ablation_profiles() {
    let cue = cue();
    let candidates = vec![
        candidate(&cue, "memory:a", q(6, 10)),
        candidate(&cue, "memory:b", q(4, 10)),
    ];
    let engram = EngramSnapshotV1 {
        generation_vector_digest: cue.snapshot_key.vector_digest,
        nodes: vec![
            EngramNodeV1 {
                record_id: id("memory:a"),
                population_id: id("population:a"),
                cue_bias: FixedQ32::ZERO,
                threshold: FixedQ32::ZERO,
            },
            EngramNodeV1 {
                record_id: id("memory:b"),
                population_id: id("population:b"),
                cue_bias: FixedQ32::ZERO,
                threshold: FixedQ32::ZERO,
            },
        ],
        synapses: vec![EngramSynapseV1 {
            from_record_id: id("memory:a"),
            to_record_id: id("memory:b"),
            weight: FixedQ32::ONE,
            inhibitory: false,
        }],
    };
    let no_recurrence = recall_with_engram(
        &cue,
        &policy(2),
        candidates.clone(),
        &engram,
        &RecallDynamicsV1 {
            recurrent_steps: 0,
            maximum_active_units_per_population: 2,
            leak: FixedQ32::ZERO,
            inhibition_enabled: true,
        },
    )
    .unwrap();
    assert_eq!(no_recurrence.packet.selections[0].record_id, id("memory:a"));

    let mut inhibitory = engram;
    inhibitory.synapses = vec![EngramSynapseV1 {
        from_record_id: id("memory:a"),
        to_record_id: id("memory:b"),
        weight: FixedQ32::ONE,
        inhibitory: true,
    }];
    let inhibited = recall_with_engram(
        &cue,
        &policy(2),
        candidates.clone(),
        &inhibitory,
        &RecallDynamicsV1 {
            recurrent_steps: 1,
            maximum_active_units_per_population: 2,
            leak: FixedQ32::ZERO,
            inhibition_enabled: true,
        },
    )
    .unwrap();
    let no_inhibition = recall_with_engram(
        &cue,
        &policy(2),
        candidates,
        &inhibitory,
        &RecallDynamicsV1 {
            recurrent_steps: 1,
            maximum_active_units_per_population: 2,
            leak: FixedQ32::ZERO,
            inhibition_enabled: false,
        },
    )
    .unwrap();
    let activation = |receipt: &HnmfRecallReceiptV1, name: &str| {
        receipt
            .final_activations
            .iter()
            .find(|row| row.record_id == id(name))
            .unwrap()
            .final_activation
    };
    assert!(activation(&no_inhibition, "memory:b") > activation(&inhibited, "memory:b"));
}

#[test]
fn candidate_engram_expansion_is_bounded_local_and_canonical() {
    let cue = cue();
    let policy = policy(2);
    let candidates = vec![candidate(&cue, "memory:a", q(6, 10))];
    let union = build_candidate_union(&cue, &policy, candidates).unwrap();
    let source = EngramSnapshotV1 {
        generation_vector_digest: cue.snapshot_key.vector_digest,
        nodes: ["memory:d", "memory:c", "memory:a", "memory:b"]
            .into_iter()
            .map(|name| EngramNodeV1 {
                record_id: id(name),
                population_id: id("population:shared"),
                cue_bias: FixedQ32::ZERO,
                threshold: FixedQ32::ZERO,
            })
            .collect(),
        synapses: vec![
            EngramSynapseV1 {
                from_record_id: id("memory:a"),
                to_record_id: id("memory:b"),
                weight: FixedQ32::ONE,
                inhibitory: false,
            },
            EngramSynapseV1 {
                from_record_id: id("memory:b"),
                to_record_id: id("memory:c"),
                weight: FixedQ32::ONE,
                inhibitory: false,
            },
        ],
    };
    let one_hop = expand_candidate_engram(&union, &source, 1).unwrap();
    assert_eq!(
        one_hop
            .nodes
            .iter()
            .map(|node| node.record_id.as_str())
            .collect::<Vec<_>>(),
        vec!["memory:a", "memory:b"]
    );
    let two_hop = expand_candidate_engram(&union, &source, 2).unwrap();
    assert_eq!(
        two_hop
            .nodes
            .iter()
            .map(|node| node.record_id.as_str())
            .collect::<Vec<_>>(),
        vec!["memory:a", "memory:b", "memory:c"]
    );
    assert!(two_hop.nodes.iter().all(|node| node.record_id != id("memory:d")));
    assert_eq!(two_hop, expand_candidate_engram(&union, &source, 2).unwrap());
}
