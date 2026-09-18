//! Source-candidate performance/structural qualification fixture.
//!
//! This executable reports observations for the CI host that ran it. The values
//! are not target-host SLOs, longitudinal efficacy, or independent acceptance.

#![allow(clippy::expect_used, clippy::print_stdout, clippy::unwrap_used)]

use std::collections::BTreeSet;
use std::hint::black_box;
use std::time::Instant;

use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_memory_retrieval::EngramNodeV1;
use codex_hepta_memory_retrieval::EngramSnapshotV1;
use codex_hepta_memory_retrieval::EngramSynapseV1;
use codex_hepta_memory_retrieval::MAX_ENGRAM_NODES;
use codex_hepta_memory_retrieval::MAX_ENGRAM_SYNAPSES;
use codex_hepta_memory_retrieval::MAX_GENERATION_BOUND_CANDIDATES;
use codex_hepta_memory_retrieval::MAX_GENERATION_BOUND_RESULTS;
use codex_hepta_memory_retrieval::MemoryCueV1;
use codex_hepta_memory_retrieval::RecallDynamicsV1;
use codex_hepta_memory_retrieval::RetrievalChannelCandidateV1;
use codex_hepta_memory_retrieval::RetrievalChannelV1;
use codex_hepta_memory_retrieval::RetrievalChannelWeightV1;
use codex_hepta_memory_retrieval::RetrievalLatencySummaryV1;
use codex_hepta_memory_retrieval::RetrievalPolicyV1;
use codex_hepta_memory_retrieval::compile_cue;
use codex_hepta_memory_retrieval::expand_candidate_engram;
use codex_hepta_memory_retrieval::recall_with_engram;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

fn id(value: impl AsRef<str>) -> StableId {
    StableId::new(value.as_ref()).expect("qualification id")
}

fn digest(value: impl AsRef<[u8]>) -> Digest32 {
    Digest32::of_bytes(value.as_ref())
}

fn cue() -> MemoryCueV1 {
    let snapshot = CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:retrieval-qualification"),
        purpose_id: id("purpose:retrieval-qualification"),
        memory_ledger_frontier: 10_000,
        knowledge_fact_frontier: 10_000,
        tombstone_frontier: 100,
        source_ledger_frontier: 10_000,
        knowledge_graph_generation: Generation::new(7).expect("generation"),
        compact_checkpoint_generation: Generation::new(5).expect("generation"),
        prompt_registry_revision: Revision::new(11).expect("revision"),
        retrieval_profile_digest: digest(b"qualified-retrieval-profile"),
        encoder_preprocessor_digest: digest(b"qualified-encoder-profile"),
        authority_epoch: 9,
        model_digest: digest(b"qualified-model"),
        tokenizer_digest: digest(b"qualified-tokenizer"),
        template_digest: digest(b"qualified-template"),
        tool_schema_digest: digest(b"qualified-tools"),
    })
    .expect("snapshot");
    compile_cue(
        id("cue:retrieval-qualification"),
        digest(b"objective"),
        digest(b"approved-context"),
        snapshot,
        digest(b"cue-profile"),
    )
    .expect("cue")
}

fn record(index: usize) -> MemoryRecord {
    MemoryRecord {
        record_id: id(format!("memory:{index:04}")),
        revision: Revision::new(1).expect("revision"),
        kind: MemoryKind::Fact,
        content_digest: digest(format!("content:{index}")),
        predecessor_digest: None,
        citations: Vec::new(),
        state: RecordState::Live,
    }
}

fn candidate(cue: &MemoryCueV1, index: usize) -> RetrievalChannelCandidateV1 {
    RetrievalChannelCandidateV1 {
        record: record(index),
        channel: RetrievalChannelV1::Lexical,
        channel_rank: u32::try_from(index + 1).expect("candidate rank"),
        normalized_score: FixedQ32::ONE,
        ood: ProbabilityQ32::ZERO,
        support_digest: digest(format!("support:{index}")),
        contradiction_group_digest: None,
        generation_vector_digest: cue.snapshot_key.vector_digest,
    }
}

fn fixture() -> (
    MemoryCueV1,
    RetrievalPolicyV1,
    Vec<RetrievalChannelCandidateV1>,
    EngramSnapshotV1,
    RecallDynamicsV1,
) {
    let cue = cue();
    let candidates = (0..MAX_GENERATION_BOUND_CANDIDATES)
        .map(|index| candidate(&cue, index))
        .collect::<Vec<_>>();
    let policy = RetrievalPolicyV1 {
        policy_id: id("policy:retrieval-qualification"),
        channel_weights: vec![RetrievalChannelWeightV1 {
            channel: RetrievalChannelV1::Lexical,
            weight: FixedQ32::ONE,
            maximum_candidates: u32::try_from(MAX_GENERATION_BOUND_CANDIDATES)
                .expect("candidate ceiling"),
        }],
        maximum_results: u32::try_from(MAX_GENERATION_BOUND_RESULTS).expect("result ceiling"),
        minimum_total_score: FixedQ32::ZERO,
        maximum_ood: ProbabilityQ32::ONE,
        minimum_distinct_channels: 1,
        abstain_on_contradiction: false,
    };

    let nodes = (0..MAX_ENGRAM_NODES)
        .map(|index| EngramNodeV1 {
            record_id: id(format!("memory:{index:04}")),
            population_id: id(format!("population:{:02}", index % 64)),
            cue_bias: FixedQ32::ZERO,
            threshold: FixedQ32::ZERO,
        })
        .collect::<Vec<_>>();

    let mut edge_keys = BTreeSet::new();
    // Reach every non-candidate node in one hop from the exact legal set.
    for index in MAX_GENERATION_BOUND_CANDIDATES..MAX_ENGRAM_NODES {
        edge_keys.insert((index % MAX_GENERATION_BOUND_CANDIDATES, index));
    }
    'outer: for source in 0..MAX_ENGRAM_NODES {
        for offset in 1..=16 {
            let destination = (source + offset) % MAX_ENGRAM_NODES;
            if source != destination {
                edge_keys.insert((source, destination));
            }
            if edge_keys.len() == MAX_ENGRAM_SYNAPSES {
                break 'outer;
            }
        }
    }
    assert_eq!(edge_keys.len(), MAX_ENGRAM_SYNAPSES);
    let weight = FixedQ32::from_raw(1_i64 << 20);
    let synapses = edge_keys
        .into_iter()
        .map(|(source, destination)| EngramSynapseV1 {
            from_record_id: id(format!("memory:{source:04}")),
            to_record_id: id(format!("memory:{destination:04}")),
            weight,
            inhibitory: destination % 17 == 0,
        })
        .collect::<Vec<_>>();

    let engram = EngramSnapshotV1 {
        generation_vector_digest: cue.snapshot_key.vector_digest,
        nodes,
        synapses,
    };
    let dynamics = RecallDynamicsV1 {
        recurrent_steps: 4,
        maximum_active_units_per_population: 64,
        leak: FixedQ32::from_raw(1_i64 << 30),
        inhibition_enabled: true,
    };
    (cue, policy, candidates, engram, dynamics)
}

fn peak_rss_kib() -> u64 {
    std::fs::read_to_string("/proc/self/status")
        .ok()
        .and_then(|status| {
            status.lines().find_map(|line| {
                line.strip_prefix("VmHWM:")
                    .and_then(|tail| tail.split_whitespace().next())
                    .and_then(|value| value.parse::<u64>().ok())
            })
        })
        .unwrap_or(0)
}

fn cpu_ticks() -> u64 {
    std::fs::read_to_string("/proc/self/stat")
        .ok()
        .and_then(|stat| {
            let fields = stat.split_whitespace().collect::<Vec<_>>();
            Some(
                fields.get(13)?.parse::<u64>().ok()?
                    + fields.get(14)?.parse::<u64>().ok()?,
            )
        })
        .unwrap_or(0)
}

fn main() {
    let sample_count = std::env::var("HEPTA_RETRIEVAL_QUAL_SAMPLES")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(40)
        .clamp(20, 1_000);
    let (cue, policy, candidates, engram, dynamics) = fixture();

    let union = codex_hepta_memory_retrieval::build_candidate_union(
        &cue,
        &policy,
        candidates.clone(),
    )
    .expect("union");
    let expanded = expand_candidate_engram(&union, &engram, dynamics.recurrent_steps)
        .expect("expanded engram");
    assert_eq!(expanded.nodes.len(), MAX_ENGRAM_NODES);
    assert_eq!(expanded.synapses.len(), MAX_ENGRAM_SYNAPSES);

    let baseline = recall_with_engram(
        &cue,
        &policy,
        candidates.clone(),
        &engram,
        &dynamics,
    )
    .expect("baseline recall");
    baseline.validate().expect("baseline receipt");

    let no_recurrence = RecallDynamicsV1 {
        recurrent_steps: 0,
        maximum_active_units_per_population: 64,
        leak: dynamics.leak,
        inhibition_enabled: true,
    };
    let no_inhibition = RecallDynamicsV1 {
        recurrent_steps: 4,
        maximum_active_units_per_population: 64,
        leak: dynamics.leak,
        inhibition_enabled: false,
    };
    let ablation_recurrence = recall_with_engram(
        &cue,
        &policy,
        candidates.clone(),
        &engram,
        &no_recurrence,
    )
    .expect("no recurrence");
    let ablation_inhibition = recall_with_engram(
        &cue,
        &policy,
        candidates.clone(),
        &engram,
        &no_inhibition,
    )
    .expect("no inhibition");

    let cpu_before = cpu_ticks();
    let mut samples = Vec::with_capacity(sample_count);
    let mut deterministic = true;
    for _ in 0..sample_count {
        let started = Instant::now();
        let receipt = recall_with_engram(
            &cue,
            &policy,
            candidates.clone(),
            &engram,
            &dynamics,
        )
        .expect("measured recall");
        samples.push(u64::try_from(started.elapsed().as_nanos()).unwrap_or(u64::MAX));
        deterministic &= receipt == baseline;
        black_box(receipt.receipt_digest);
    }
    let cpu_after = cpu_ticks();
    let latency = RetrievalLatencySummaryV1::from_samples(&samples).expect("latency summary");
    let synthetic_oracle_passed = deterministic
        && baseline.packet.selections.len() <= MAX_GENERATION_BOUND_RESULTS
        && ablation_recurrence.receipt_digest != baseline.receipt_digest
        && ablation_inhibition.receipt_digest != baseline.receipt_digest;

    println!(
        "{{\"schema\":\"hepta.memory-retrieval.source-qualification.v1\",\"sampleCount\":{},\"p50Nanos\":{},\"p95Nanos\":{},\"p99Nanos\":{},\"maximumNanos\":{},\"sampleDigest\":\"{}\",\"candidateCount\":{},\"expandedNodeCount\":{},\"expandedSynapseCount\":{},\"returnedCount\":{},\"recurrentSteps\":{},\"activeUnitsPerPopulation\":{},\"peakRssKiB\":{},\"cpuTicks\":{},\"syntheticOraclePassed\":{},\"targetHostQualified\":false}}",
        latency.sample_count,
        latency.p50_nanos,
        latency.p95_nanos,
        latency.p99_nanos,
        latency.maximum_nanos,
        latency.sample_digest,
        candidates.len(),
        expanded.nodes.len(),
        expanded.synapses.len(),
        baseline.packet.selections.len(),
        dynamics.recurrent_steps,
        dynamics.maximum_active_units_per_population,
        peak_rss_kib(),
        cpu_after.saturating_sub(cpu_before),
        synthetic_oracle_passed,
    );
}
